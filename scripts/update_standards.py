#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
standards.csv를 Source of Truth로 사용해 Stable/Draft 버전과 링크를 자동 갱신한다.

운영 규칙 반영:
- CSV 구조(컬럼/순서/행 순서) 변경 금지
- 수정 가능한 컬럼:
  - Stable Version
  - Stable Version Link
  - Draft Version
  - Draft Version Link
  - 핵심 변경 내용  ✅ (버전 값 변경 시에만 자동 기록)
- 추정/추론 금지: 공식 링크에서 확인 가능한 식별자(버전/날짜/draft-id) 없으면 N/A 유지
- Draft 규칙:
  - Draft Version Link가 N/A면 Draft Version도 반드시 N/A
  - Draft Version은 식별자 필수(버전/날짜/draft-id)
  - (Seed 보호) 버전이 N/A라고 링크를 N/A로 지우지 않음
- 열화 방지:
  - 기존 값이 더 구체적이면(날짜/식별자 포함) 덜 구체적인 값으로 덮어쓰지 않음
- 핵심 변경 내용 컬럼 기록 규칙(A안):
  - 버전 값 변경 시에만 기록한다. (링크만 변경된 경우 기록하지 않음)
  - 형식 고정:
    * Stable: "stable <old> -> <new>"
    * Draft:  "draft <old> -> <new>"
    * 둘 다: "stable ...; draft ..."
  - <old>, <new>는 CSV 문자열 그대로 사용하되 비어있으면 N/A로 표준화
  - 버전 변경이 없으면 ‘핵심 변경 내용’은 기존 값을 유지(덮어쓰지 않음)
- README 변경내역:
  - append-only + 최신이 최상단 (## 변경 내역 바로 아래)

추가: Content snapshot/diff (monitor.py 스타일)
- 매 실행마다 Stable/Draft 링크에 대해 "내용 변경 체크"는 수행한다.
- 단, 파일 변경 정책:
  - 첫 실행(스냅샷 없음): baseline만 저장 (diff 파일 생성/README 기록 안 함)
    * 단, SVT_BASELINE_DIFF=1 이면 baseline에서도 diff 파일 생성(빈 prev 대비)
  - 내용 동일: 아무 파일도 변경하지 않음 (불필요 커밋 방지)
  - 내용 변경: diff 파일 생성 + 스냅샷 갱신 + README 기록

GitHub Actions 대응(중요):
- Actions는 매 실행마다 새 워크스페이스이므로 snapshots가 유지되지 않으면 매번 baseline이 된다.
- 해결:
  1) actions/cache로 snapshots 경로를 캐시하고,
  2) 코드에서는 SVT_SNAPSHOT_DIR / SVT_LOG_ROOT로 그 경로를 지정 가능.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# -------------------------
# Paths / Env overrides
# -------------------------

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CSV_PATH = os.path.join(ROOT, "standards.csv")
README_PATH = os.path.join(ROOT, "README.md")

KST = ZoneInfo("Asia/Seoul")

ALLOWED_UPDATE_COLS = {
    "Stable Version",
    "Stable Version Link",
    "Draft Version",
    "Draft Version Link",
    "핵심 변경 내용",
}

# Content snapshot/diff directories
# - 기본은 repo/logs 아래
# - Actions에서 snapshots를 캐시하려면 SVT_LOG_ROOT 또는 SVT_SNAPSHOT_DIR로 경로를 고정/오버라이드
ENV_LOG_ROOT = os.environ.get("SVT_LOG_ROOT", "").strip()
DEFAULT_LOG_ROOT = os.path.join(ROOT, "logs")
LOG_ROOT = ENV_LOG_ROOT if ENV_LOG_ROOT else DEFAULT_LOG_ROOT

ENV_SNAPSHOT_DIR = os.environ.get("SVT_SNAPSHOT_DIR", "").strip()
ENV_DIFF_DIR = os.environ.get("SVT_DIFF_DIR", "").strip()

SNAPSHOT_DIR = ENV_SNAPSHOT_DIR if ENV_SNAPSHOT_DIR else os.path.join(LOG_ROOT, "snapshots")
DIFF_DIR = ENV_DIFF_DIR if ENV_DIFF_DIR else os.path.join(LOG_ROOT, "diffs")

# baseline에서도 diff를 만들지 여부 (기본: 0 = 기존 동작 유지)
BASELINE_DIFF = os.environ.get("SVT_BASELINE_DIFF", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}


def ensure_dirs() -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    os.makedirs(DIFF_DIR, exist_ok=True)


def url_to_safe_filename(url: str) -> str:
    """
    URL → 파일명(도메인+경로 기반, 안전 문자만)
    """
    parsed = urlparse(url)
    clean_path = re.sub(r"[^a-zA-Z0-9]", "_", (parsed.netloc or "") + (parsed.path or ""))
    if not clean_path:
        clean_path = re.sub(r"[^a-zA-Z0-9]", "_", url)
    return clean_path[:200]


def fetch_page_lines_for_diff(url: str) -> List[str]:
    """
    HTML <body> 텍스트를 줄 단위로 추출해 비교 가능한 형태로 정규화
    """
    html = http_get(url)
    soup = soup_from_html(html)

    body = soup.body
    if body is None:
        text = soup.get_text(separator="\n", strip=True)
    else:
        text = body.get_text(separator="\n", strip=True)

    lines: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        lines.append(s)
    return lines


def load_snapshot_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f.readlines()]


def save_snapshot_lines(path: str, lines: List[str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, path)


def make_unified_diff(prev_lines: List[str], cur_lines: List[str]) -> str:
    import difflib
    diff = difflib.unified_diff(prev_lines, cur_lines, lineterm="")
    return "\n".join(diff).strip()


def safe_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def _write_diff_file(url: str, prev: List[str], cur: List[str]) -> Optional[str]:
    diff_text = make_unified_diff(prev, cur)

    ts = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    safe = url_to_safe_filename(url)
    diff_filename = f"{safe}__{ts}.diff"
    diff_path = os.path.join(DIFF_DIR, diff_filename)

    # diff가 빈 문자열일 수 있으니(이론상 거의 없음) 그래도 파일을 만들지 여부는 정책 선택
    if diff_text:
        safe_write_text(diff_path, diff_text + "\n")
        return os.path.relpath(diff_path, ROOT)

    return None


def check_and_record_content_change(url: str) -> Tuple[str, Optional[str]]:
    """
    반환:
      - ("baseline", None): 이전 스냅샷이 없어 베이스라인만 생성 (기본: diff 생성/README 기록 안 함)
      - ("baseline", diff_relpath): (옵션) SVT_BASELINE_DIFF=1이면 baseline에서도 diff 생성
      - ("unchanged", None): 이전 스냅샷과 동일 (파일 변경 없음)
      - ("changed", diff_relpath): 실제 변경 감지 → diff 생성 + 스냅샷 갱신

    정책:
      - 내용 동일이면 스냅샷 파일도 건드리지 않는다(불필요 커밋 방지)
      - 첫 실행은 기본적으로 스냅샷만 만들고 diff는 만들지 않는다(초기 전체 diff 폭발 방지)
        * 단, SVT_BASELINE_DIFF=1이면 baseline에서도 diff 파일 생성(빈 prev 대비)
    """
    ensure_dirs()

    safe = url_to_safe_filename(url)
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"{safe}.txt")

    prev = load_snapshot_lines(snapshot_path)
    cur = fetch_page_lines_for_diff(url)

    if prev == cur:
        return "unchanged", None

    # baseline (no previous)
    if not prev:
        save_snapshot_lines(snapshot_path, cur)
        if BASELINE_DIFF:
            diff_rel = _write_diff_file(url, [], cur)
            return "baseline", diff_rel
        return "baseline", None

    # changed
    diff_rel = _write_diff_file(url, prev, cur)

    # 변경이 있으므로 스냅샷 갱신
    save_snapshot_lines(snapshot_path, cur)

    return "changed", diff_rel


# =========================
# Utils (general)
# =========================

def norm_na(v: Optional[str]) -> str:
    if v is None:
        return "N/A"
    s = str(v).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return "N/A"
    if s.upper() == "N/A":
        return "N/A"
    return s


def is_na(v: Optional[str]) -> bool:
    return norm_na(v) == "N/A"


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_first(regex: str, text: str, flags=0) -> Optional[str]:
    m = re.search(regex, text, flags)
    return m.group(1) if m else None


def has_identifier(s: str) -> bool:
    if not s:
        return False
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        return True
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        return True
    return False


def specificity_score(s: str) -> int:
    s = norm_na(s)
    if is_na(s):
        return 0
    score = 0
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        score += 50
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        score += 50
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        score += 10
    if re.search(r"(년|월|일)", s):
        score += 5
    score += min(len(s), 200) // 20
    return score


def choose_value_no_degrade(current: str, candidate: str) -> str:
    cur = norm_na(current)
    cand = norm_na(candidate)
    if is_na(cand):
        return cur
    if is_na(cur):
        return cand
    return cand if specificity_score(cand) >= specificity_score(cur) else cur


def choose_link_seed_protected(current: str, candidate: str) -> str:
    cur = norm_na(current)
    cand = norm_na(candidate)
    if is_na(cand):
        return cur
    return cand


def compute_core_change(before_row: Dict[str, str], after_row: Dict[str, str]) -> Optional[str]:
    """
    '핵심 변경 내용' 자동 기록 규칙(A안):
    - 버전 값(Stable Version / Draft Version)이 변경된 경우에만 기록
    - 링크만 변경된 경우 기록하지 않음(기존 값 유지)
    """
    b_stable = norm_na(before_row.get("Stable Version"))
    a_stable = norm_na(after_row.get("Stable Version"))

    b_draft = norm_na(before_row.get("Draft Version"))
    a_draft = norm_na(after_row.get("Draft Version"))

    parts: List[str] = []
    if b_stable != a_stable:
        parts.append(f"stable {b_stable} -> {a_stable}")
    if b_draft != a_draft:
        parts.append(f"draft {b_draft} -> {a_draft}")

    if not parts:
        return None
    return "; ".join(parts)


def _extract_html_redirect_target(base_url: str, html: str) -> Optional[str]:
    """
    HTTP 30x가 아닌, HTML(meta refresh / JS / 링크) 기반 redirect를 추적하기 위한 target 추출.
    """
    # meta refresh
    m = re.search(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?[^"\']*url\s*=\s*([^"\'>\s;]+)',
        html,
        re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1).strip())

    # JS redirect
    m = re.search(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return urljoin(base_url, m.group(1).strip())

    # "Redirecting" 페이지: 첫 번째 유의미한 링크
    if re.search(r"\bRedirecting\b", html, re.IGNORECASE):
        soup = soup_from_html(html)
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href:
                return urljoin(base_url, href)

    # rel=canonical
    soup = soup_from_html(html)
    link = soup.find("link", attrs={"rel": re.compile(r"\bcanonical\b", re.IGNORECASE)})
    if link and link.get("href"):
        return urljoin(base_url, link["href"].strip())

    return None


def http_get(
    url: str,
    timeout: int = 25,
    return_headers: bool = False,
    return_final_url: bool = False,
):
    """
    - HTTP redirect는 requests가 처리(allow_redirects=True)
    - HTML 기반 redirect(meta refresh/JS/link)도 최대 2 hop까지 수동 추적
    """
    headers = {
        "User-Agent": "standards-version-tracker-bot/1.0 (+https://github.com/yoongyu-lee/standards-version-tracker)"
    }

    final_url = url
    last_headers = None
    text = None

    for _ in range(3):  # 최대 2번 추가 추적(총 3번 fetch)
        r = requests.get(final_url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        text = r.text
        last_headers = r.headers
        final_url = r.url

        target = _extract_html_redirect_target(final_url, text)
        if target and target != final_url:
            final_url = target
            continue
        break

    assert text is not None and last_headers is not None

    if return_headers and return_final_url:
        return text, last_headers, final_url
    if return_headers:
        return text, last_headers
    if return_final_url:
        return text, final_url
    return text


# =========================
# Data model
# =========================

@dataclass
class RowUpdate:
    stable_version: Optional[str] = None
    stable_link: Optional[str] = None
    draft_version: Optional[str] = None
    draft_link: Optional[str] = None


# =========================
# Parsers
# =========================

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def parse_w3c_tr_version_from_url(url: str) -> Optional[str]:
    return extract_first(r"/[a-z0-9\-]+-([0-9]+\.[0-9]+(\.[0-9]+)?)\/?$", url, re.IGNORECASE)


def w3c_extract_sotd_window_text(soup: BeautifulSoup) -> str:
    """
    "Status of This Document" 근처를 우선 탐지(대소문자/공백 변화에 강하게)
    """
    body_text = soup.get_text("\n", strip=True)
    lines = body_text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"status\s+of\s+this\s+document", line, re.IGNORECASE):
            start = max(0, i)
            end = min(len(lines), i + 250)
            return "\n".join(lines[start:end])
    return body_text


def parse_w3c_tr_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    html = http_get(url)
    soup = soup_from_html(html)

    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    h1 = soup.find("h1")
    h1txt = h1.get_text(" ", strip=True) if h1 else ""

    status_map = {
        "W3C Recommendation": "Recommendation",
        "W3C Proposed Recommendation": "Proposed Recommendation",
        "W3C Candidate Recommendation": "Candidate Recommendation",
        "W3C Candidate Recommendation Draft": "Candidate Recommendation Draft",
        "W3C Working Draft": "Working Draft",
        "W3C First Public Working Draft": "First Public Working Draft",
        "W3C Note": "Note",
    }

    window = w3c_extract_sotd_window_text(soup)

    status = None
    window_l = window.lower()
    for k, v in status_map.items():
        if k.lower() in window_l:
            status = v
            break

    # did-1.1 Recommendation 오탐 방지(규칙 유지)
    if "did-1.1" in url and re.search(r"\bexperimental\b|DO NOT implement", window, re.IGNORECASE):
        if status == "Recommendation":
            status = None

    ver = parse_w3c_tr_version_from_url(url)
    if not ver:
        ver = (
            extract_first(r"\bv([0-9]+\.[0-9]+(\.[0-9]+)?)\b", h1txt, re.IGNORECASE)
            or extract_first(r"\bv([0-9]+\.[0-9]+(\.[0-9]+)?)\b", title, re.IGNORECASE)
        )
    if not ver:
        ver = (
            extract_first(r"\b([0-9]+\.[0-9]+(\.[0-9]+)?)\b", h1txt)
            or extract_first(r"\b([0-9]+\.[0-9]+(\.[0-9]+)?)\b", title)
        )

    if ver and status:
        return f"v{ver} ({status})", url
    if ver:
        return f"v{ver} (W3C TR)", url
    return None, None


def parse_w3c_ed_draft(url: str) -> Tuple[Optional[str], Optional[str]]:
    html, headers = http_get(url, return_headers=True)
    soup = soup_from_html(html)

    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    h1 = soup.find("h1")
    h1txt = h1.get_text(" ", strip=True) if h1 else ""

    ver = (
        extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", h1txt, re.IGNORECASE)
        or extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", title, re.IGNORECASE)
    )

    # "1.1" 형태도 제한적으로 허용
    if not ver:
        ver = (
            extract_first(r"\b([0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?)\b", h1txt)
            or extract_first(r"\b([0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?)\b", title)
        )

    dt: Optional[str] = None
    meta_keys = {"dcterms.modified", "dcterms.issued", "dc.date", "dc.modified", "last-modified"}
    for m in soup.find_all("meta"):
        name = (m.get("name") or "").strip().lower()
        prop = (m.get("property") or "").strip().lower()
        key = name or prop
        if key in meta_keys:
            content = (m.get("content") or "").strip()
            d = extract_first(r"\b(\d{4}-\d{2}-\d{2})\b", content)
            if d:
                dt = d
                break

    if not dt:
        for t in soup.find_all("time"):
            datetime_attr = (t.get("datetime") or "").strip()
            d = extract_first(r"\b(\d{4}-\d{2}-\d{2})\b", datetime_attr)
            if d:
                dt = d
                break
            txt = t.get_text(" ", strip=True)
            d = extract_first(r"\b(\d{4}-\d{2}-\d{2})\b", txt)
            if d:
                dt = d
                break

    if not dt:
        body_text = soup.get_text("\n", strip=True)
        for line in body_text.splitlines():
            l = line.strip()
            if not l:
                continue
            if re.search(r"\b(This version|Last updated|Updated|Modified)\b", l, re.IGNORECASE):
                d = extract_first(r"\b(\d{4}-\d{2}-\d{2})\b", l)
                if d:
                    dt = d
                    break

    if not dt:
        lm = (headers.get("Last-Modified") or "").strip()
        if lm:
            try:
                dt_obj = parsedate_to_datetime(lm)
                dt = dt_obj.date().isoformat()
            except Exception:
                dt = None

    if ver and dt:
        return f"v{ver} ({dt} Editor's Draft)", url
    if dt:
        return f"{dt} (Editor's Draft)", url
    if ver:
        return f"v{ver} (Editor's Draft)", url
    return None, None


def parse_rfc_from_link_or_page(url: str) -> Tuple[Optional[str], Optional[str]]:
    rfc = extract_first(r"\brfc(\d{3,5})\b", url, re.IGNORECASE)
    if rfc:
        return f"RFC {rfc}", url

    try:
        text = http_get(url)
    except Exception:
        return None, None

    rfc2 = extract_first(r"\bRFC\s+(\d{3,5})\b", text)
    if rfc2:
        return f"RFC {rfc2}", url
    return None, None


def parse_ietf_draft_from_datatracker(url: str) -> Tuple[Optional[str], Optional[str]]:
    html = http_get(url)
    draft_id = extract_first(r"\b(draft-[a-z0-9-]+-\d{1,2})\b", html, re.IGNORECASE)
    if not draft_id:
        return None, None
    return f"{draft_id} (Internet-Draft)", url


def parse_semver_from_url(url: str) -> Optional[str]:
    return extract_first(r"/(\d+\.\d+\.\d+)(/|$)", url)


def parse_oidf_spec_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    html = http_get(url)
    soup = soup_from_html(html)
    text = soup.get_text("\n", strip=True)

    title = (soup.title.get_text(" ", strip=True) if soup.title else "")
    h1 = soup.find(["h1", "h2"])
    htxt = h1.get_text(" ", strip=True) if h1 else ""

    ver = (
        extract_first(r"\b([0-9]+\.[0-9]+)\b", htxt)
        or extract_first(r"\b([0-9]+\.[0-9]+)\b", title)
        or extract_first(r"\b([0-9]+\.[0-9]+)\b", text)
    )
    if not ver:
        return None, None

    status = None
    m = re.search(r"^Status:\s*(.+)$", text, re.MULTILINE)
    if m:
        status = m.group(1).strip()

    pub_iso = None
    m = re.search(r"^Published:\s*([0-9]{1,2})\s+([A-Za-z]+)\s+([0-9]{4})\s*$", text, re.MULTILINE)
    if m:
        dd, mon, yyyy = m.group(1), m.group(2).lower(), m.group(3)
        if mon in MONTHS:
            pub_iso = f"{yyyy}-{MONTHS[mon]}-{int(dd):02d}"

    if status and pub_iso:
        return f"{ver} ({status}, {pub_iso})", url
    if status:
        return f"{ver} ({status})", url
    if pub_iso:
        return f"{ver} ({pub_iso})", url
    return f"{ver}", url


def parse_iso_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    html = http_get(url)
    soup = soup_from_html(html)
    text = soup.get_text("\n", strip=True)

    pub = (
        extract_first(r"Publication date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        or extract_first(r"Publication date\s*:?\s*([0-9]{4}-[0-9]{2})", text)
    )
    if pub:
        return f"ISO Publication: {pub}", url

    pub2 = extract_first(r"\bPublished\s*:?\s*([0-9]{4}-[0-9]{2})\b", text)
    if pub2:
        return f"ISO Publication: {pub2}", url

    return None, None


def parse_github_latest_commit_date(repo_url: str) -> Optional[str]:
    """
    GitHub commits 페이지 HTML에서 최신 커밋 날짜(YYYY-MM-DD) 추출 (API 미사용)
    """
    repo_url = repo_url.rstrip("/")
    candidates = [
        repo_url + "/commits/main/",
        repo_url + "/commits/master/",
        repo_url + "/commits/",
    ]
    for commits_url in candidates:
        try:
            html, _final = http_get(commits_url, return_final_url=True)
        except Exception:
            continue

        dt = extract_first(r'<relative-time[^>]+datetime="(\d{4}-\d{2}-\d{2})T', html, re.IGNORECASE)
        if dt:
            return dt

        dt2 = extract_first(r'datetime="(\d{4}-\d{2}-\d{2})T', html, re.IGNORECASE)
        if dt2:
            return dt2

    return None


def parse_hl_anoncreds_page(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    HL AnonCreds spec 페이지에서:
    - stable 버전 후보: "This version (vX.Y)" 또는 "Specification Status: vX.Y ..."
    - latest draft 링크 후보: GitHub repo(anoncreds/anoncreds-spec) 링크 발견
    """
    html, final_url = http_get(url, return_final_url=True)
    soup = soup_from_html(html)
    text_one_line = soup.get_text(" ", strip=True)

    v_this = extract_first(
        r"\bThis version\b\s*(?:\(|:)?\s*v([0-9]+\.[0-9]+(\.[0-9]+)?)\s*\)?",
        text_one_line,
        re.IGNORECASE,
    )
    v_status = extract_first(
        r"\bSpecification Status\b\s*:\s*v([0-9]+\.[0-9]+(\.[0-9]+)?)\b",
        text_one_line,
        re.IGNORECASE,
    )

    stable_ver = None
    if v_this:
        stable_ver = f"v{v_this}"
    elif v_status:
        stable_ver = f"v{v_status}"

    latest_draft_link = None
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("https://github.com/") and "anoncreds/anoncreds-spec" in href:
            latest_draft_link = href
            break

    return stable_ver, final_url, latest_draft_link


def parse_hl_anoncreds_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    stable_ver, final_url, _latest = parse_hl_anoncreds_page(url)
    if stable_ver:
        return stable_ver, final_url
    return None, None


def discover_hl_anoncreds_draft_from_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Draft 링크가 N/A여도 stable 페이지에서 GitHub repo를 발견하면 Draft로 기록.
    Draft Version은 YYYY-MM-DD (GitHub Draft) 형태로 작성(식별자 규칙 충족).
    """
    _stable_ver, _final_url, latest_draft_link = parse_hl_anoncreds_page(url)
    if not latest_draft_link:
        return None, None

    dt = parse_github_latest_commit_date(latest_draft_link)
    if dt:
        return f"{dt} (GitHub Draft)", latest_draft_link

    return None, None


# =========================
# Routing
# =========================

def compute_update_for_row(org: str, spec_name: str, stable_link: str, draft_link: str) -> RowUpdate:
    org = (org or "").strip()
    spec_name = (spec_name or "").strip()

    stable_link_n = norm_na(stable_link)
    draft_link_n = norm_na(draft_link)

    upd = RowUpdate()

    # --- Stable ---
    if not is_na(stable_link_n):
        try:
            if org == "W3C" and "w3.org/TR/" in stable_link_n:
                v, l = parse_w3c_tr_stable(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "IETF":
                v, l = parse_rfc_from_link_or_page(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "OIDF" and "datatracker.ietf.org/doc/html/rfc" in stable_link_n:
                v, l = parse_rfc_from_link_or_page(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "EU":
                ver = parse_semver_from_url(stable_link_n)
                if ver:
                    upd.stable_version, upd.stable_link = f"v{ver}", stable_link_n

            elif org == "OIDF" and "openid.net/specs/" in stable_link_n:
                v, l = parse_oidf_spec_stable(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "ISO" and "iso.org/standard/" in stable_link_n:
                suffix, l = parse_iso_stable(stable_link_n)
                if suffix and l:
                    upd.stable_version, upd.stable_link = f"{spec_name} ({suffix})", l

            elif org == "HL":
                v, l = parse_hl_anoncreds_stable(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

        except Exception:
            # 운영상: 추정 금지, 실패 시 기존값 유지
            pass

    # --- Draft ---
    if not is_na(draft_link_n):
        try:
            if org == "W3C":
                if "w3c.github.io" in draft_link_n:
                    v, l = parse_w3c_ed_draft(draft_link_n)
                    if v and l:
                        upd.draft_version, upd.draft_link = v, l
                elif "w3.org/TR/" in draft_link_n:
                    v, l = parse_w3c_tr_stable(draft_link_n)
                    if v and l:
                        upd.draft_version, upd.draft_link = v, l

            elif org == "IETF":
                v, l = parse_ietf_draft_from_datatracker(draft_link_n)
                if v and l:
                    upd.draft_version, upd.draft_link = v, l

            elif org == "EU":
                ver = parse_semver_from_url(draft_link_n)
                if ver:
                    upd.draft_version, upd.draft_link = f"v{ver} (Draft)", draft_link_n

        except Exception:
            pass
    else:
        # Draft 링크가 N/A여도 HL은 stable 페이지에서 Latest Draft 발견 가능
        if org == "HL" and not is_na(stable_link_n):
            try:
                dv, dl = discover_hl_anoncreds_draft_from_stable(stable_link_n)
                if dv and dl:
                    upd.draft_version, upd.draft_link = dv, dl
            except Exception:
                pass

    return upd


# =========================
# Validator / Finalizer
# =========================

def validate_and_finalize(existing: Dict[str, str], upd: RowUpdate) -> RowUpdate:
    cur_stable_v = norm_na(existing.get("Stable Version"))
    cur_stable_l = norm_na(existing.get("Stable Version Link"))
    cur_draft_v = norm_na(existing.get("Draft Version"))
    cur_draft_l = norm_na(existing.get("Draft Version Link"))

    cand_stable_v = norm_na(upd.stable_version) if upd.stable_version is not None else cur_stable_v
    cand_stable_l = norm_na(upd.stable_link) if upd.stable_link is not None else cur_stable_l
    cand_draft_v = norm_na(upd.draft_version) if upd.draft_version is not None else cur_draft_v
    cand_draft_l = norm_na(upd.draft_link) if upd.draft_link is not None else cur_draft_l

    # 링크는 seed 보호 (N/A로 덮어쓰기 금지)
    new_stable_l = choose_link_seed_protected(cur_stable_l, cand_stable_l)
    new_draft_l = choose_link_seed_protected(cur_draft_l, cand_draft_l)

    # 값은 열화 방지
    new_stable_v = choose_value_no_degrade(cur_stable_v, cand_stable_v)
    new_draft_v = choose_value_no_degrade(cur_draft_v, cand_draft_v)

    # Stable: 링크가 N/A면 버전도 N/A
    if is_na(new_stable_l):
        new_stable_v = "N/A"

    # Draft: 링크가 N/A면 버전도 N/A
    if is_na(new_draft_l):
        new_draft_v = "N/A"
    else:
        # 링크가 있는데 버전이 식별자 규칙을 만족 못하면 버전만 N/A(링크 유지)
        if is_na(new_draft_v) or not has_identifier(new_draft_v):
            new_draft_v = "N/A"

    # Draft Version을 채우면 Draft Link도 있어야 함
    if not is_na(new_draft_v) and is_na(new_draft_l):
        new_draft_v = "N/A"

    return RowUpdate(
        stable_version=new_stable_v,
        stable_link=new_stable_l,
        draft_version=new_draft_v,
        draft_link=new_draft_l,
    )


# =========================
# CSV / README Update
# =========================

def load_csv_rows(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows: List[Dict[str, str]] = []
        for r in reader:
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
        return fieldnames, rows


def write_csv_rows(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def update_readme_changelog(
    diffs_by_row: List[Tuple[str, str, List[str]]],
    content_changes_by_row: List[Tuple[str, str, List[str]]],
) -> None:
    if not diffs_by_row and not content_changes_by_row:
        return
    if not os.path.exists(README_PATH):
        return

    readme = open(README_PATH, "r", encoding="utf-8").read()
    heading = "## 변경 내역"
    idx = readme.find(heading)
    if idx == -1:
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")
    lines = [f"### {today}"]

    for org, name, diffs in diffs_by_row:
        joined = "; ".join(diffs)
        lines.append(f"- [{org}] {name}: {joined}")

    for org, name, diffs in content_changes_by_row:
        joined = "; ".join(diffs)
        lines.append(f"- [{org}] {name}: {joined}")

    block = "\n".join(lines) + "\n\n"

    after_heading_pos = readme.find("\n", idx)
    if after_heading_pos == -1:
        return
    after_heading_pos += 1

    new_readme = readme[:after_heading_pos] + "\n" + block + readme[after_heading_pos:]
    safe_write_text(README_PATH, new_readme)


# =========================
# Main
# =========================

def main() -> int:
    ensure_dirs()

    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] standards.csv not found at {CSV_PATH}", file=sys.stderr)
        return 2

    fieldnames, rows = load_csv_rows(CSV_PATH)

    missing = [c for c in ALLOWED_UPDATE_COLS if c not in fieldnames]
    if missing:
        print(f"[ERROR] CSV missing expected columns: {missing}", file=sys.stderr)
        return 2

    changed_any = False
    csv_changed_any = False

    diffs_for_readme: List[Tuple[str, str, List[str]]] = []
    content_changes_for_readme: List[Tuple[str, str, List[str]]] = []

    # content diff 상태 집계 (Actions 디버깅용)
    content_status_counts = {"baseline": 0, "unchanged": 0, "changed": 0}
    content_diff_files = 0

    for row in rows:
        org = row.get("단체", "").strip()
        name = row.get("표준명 (항목)", "").strip()

        before_raw = {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in fieldnames}

        stable_link = row.get("Stable Version Link", "")
        draft_link = row.get("Draft Version Link", "")

        # ✅ 항상 내용 변경 체크(단, 파일 변경은 baseline/changed일 때만 발생)
        content_notes: List[str] = []
        logs_changed = False

        stable_url = norm_na(stable_link)
        if not is_na(stable_url):
            try:
                status, diff_rel = check_and_record_content_change(stable_url)
                if status in content_status_counts:
                    content_status_counts[status] += 1

                if status in ("baseline", "changed"):
                    logs_changed = True
                    changed_any = True

                if diff_rel:
                    content_diff_files += 1

                if status == "changed" and diff_rel:
                    content_notes.append(f"내용 변경 감지(버전 동일) – stable diff: {diff_rel}")
                if status == "baseline" and diff_rel:
                    content_notes.append(f"baseline diff 생성 – stable diff: {diff_rel}")

            except Exception as e:
                print("[WARN] stable content snapshot failed:", stable_url, "err=", repr(e))

        draft_url = norm_na(draft_link)
        if not is_na(draft_url):
            try:
                status, diff_rel = check_and_record_content_change(draft_url)
                if status in content_status_counts:
                    content_status_counts[status] += 1

                if status in ("baseline", "changed"):
                    logs_changed = True
                    changed_any = True

                if diff_rel:
                    content_diff_files += 1

                if status == "changed" and diff_rel:
                    content_notes.append(f"내용 변경 감지(버전 동일) – draft diff: {diff_rel}")
                if status == "baseline" and diff_rel:
                    content_notes.append(f"baseline diff 생성 – draft diff: {diff_rel}")

            except Exception as e:
                print("[WARN] draft content snapshot failed:", draft_url, "err=", repr(e))

        if content_notes:
            content_changes_for_readme.append((org, name, content_notes))

        if logs_changed:
            # logs(스냅샷/디프)가 바뀌었을 수도 있음
            changed_any = True

        # --- 기존 버전/링크 자동 갱신 로직 ---
        upd_raw = compute_update_for_row(org, name, stable_link, draft_link)
        upd = validate_and_finalize(before_raw, upd_raw)

        row["Stable Version"] = norm_na(upd.stable_version)
        row["Stable Version Link"] = norm_na(upd.stable_link)
        row["Draft Version"] = norm_na(upd.draft_version)
        row["Draft Version Link"] = norm_na(upd.draft_link)

        # 핵심 변경 내용: 버전 변경 시에만 기록
        if "핵심 변경 내용" in fieldnames:
            core = compute_core_change(before_raw, row)
            if core is not None:
                row["핵심 변경 내용"] = core

        # README diff는 4개 컬럼만
        diffs: List[str] = []
        for col in ["Stable Version", "Stable Version Link", "Draft Version", "Draft Version Link"]:
            b = (before_raw.get(col, "") or "").strip()
            a = (row.get(col, "") or "").strip()
            if b != a:
                diffs.append(f"{col}: {b or '(empty)'} → {a}")

        core_changed = False
        if "핵심 변경 내용" in fieldnames:
            b_core = (before_raw.get("핵심 변경 내용", "") or "").strip()
            a_core = (row.get("핵심 변경 내용", "") or "").strip()
            core_changed = (b_core != a_core)

        if diffs or core_changed:
            changed_any = True
            csv_changed_any = True
            if diffs:
                diffs_for_readme.append((org, name, diffs))

    # 파일 쓰기 / README 업데이트
    if changed_any:
        if csv_changed_any:
            write_csv_rows(CSV_PATH, fieldnames, rows)

        update_readme_changelog(diffs_for_readme, content_changes_for_readme)

        print(
            "[OK] Updated artifacts. "
            f"csv_row_changes={len(diffs_for_readme)}, content_only_changes={len(content_changes_for_readme)}"
        )
    else:
        print("[OK] No changes detected.")

    # 디버깅 로그 (Actions에서 baseline 반복 여부 확인)
    print(
        "[INFO] content_status_counts="
        f"{content_status_counts}, diff_files_created={content_diff_files}, "
        f"snapshot_dir={SNAPSHOT_DIR}, diff_dir={DIFF_DIR}, baseline_diff={BASELINE_DIFF}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())