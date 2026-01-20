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
  - 버전 값이 변경된 경우에만 기록한다. (링크만 변경된 경우 기록하지 않음)
  - 형식 고정:
    * Stable 버전 변경 시:  "stable <old> -> <new>"
    * Draft 버전 변경 시:   "draft <old> -> <new>"
    * 둘 다 변경 시:         "stable <old> -> <new>; draft <old> -> <new>"
  - <old>, <new>는 CSV의 Stable Version / Draft Version 값(문자열) 그대로 사용하되,
    비어있거나 null 계열이면 "N/A"로 표준화한다.
  - 버전이 변경되지 않았으면 ‘핵심 변경 내용’은 기존 값을 유지한다. (빈 값으로 덮어쓰지 않는다.)
- README 변경내역:
  - append-only + 최신이 최상단 (## 변경 내역 바로 아래)

지원 파서(링크가 있을 때만; 일부 HL은 stable 페이지에서 draft 링크를 발견 가능):
- W3C TR (Stable/Draft): 상태 + 버전
  - ✅ 개선: SOTD/상태 탐지 대소문자/공백 변화에 더 강하게
  - ✅ 개선: 상태를 못 잡아도 버전만 확인되면 "vX.Y (W3C TR)"로 최소 기록
- W3C Editor’s Draft(w3c.github.io): 버전/날짜(안전 추출) + (추가) HTTP Last-Modified fallback
- IETF RFC(Stable)
- IETF Internet-Draft(datatracker 페이지에서 최신 -NN 추출)
- OIDF(openid.net/specs) Stable: 버전 + Status/Published
- ISO(iso.org/standard) Stable: Publication date 보강
- EU(eudi.dev) Stable: URL semver
- HL(AnonCreds) Stable:
  - HTML redirect(meta refresh/JS/link) 추적 후 실제 스펙 페이지 파싱
  - "This version (v1.0)" / "Specification Status: vX.Y"에서 vX.Y 추출
- HL(AnonCreds) Draft(발견형):
  - spec 페이지의 "Latest Draft" 링크가 GitHub repo일 경우,
  - GitHub commits 페이지에서 최신 커밋 날짜(YYYY-MM-DD)를 식별자로 사용

추가 안전장치:
- W3C did-1.1에서 Recommendation 오탐 방지:
  - SOTD 근처를 우선 탐지
  - experimental / DO NOT implement 감지 시 Recommendation이면 무효 처리(업데이트 하지 않음)
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CSV_PATH = os.path.join(ROOT, "standards.csv")
README_PATH = os.path.join(ROOT, "README.md")

KST = ZoneInfo("Asia/Seoul")

ALLOWED_UPDATE_COLS = {
    "Stable Version",
    "Stable Version Link",
    "Draft Version",
    "Draft Version Link",
    "핵심 변경 내용",  # ✅ 추가 (버전 변경 시에만 기록)
}

# =========================
# Utils
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

def safe_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

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
    - 포맷 고정:
      * stable <old> -> <new>
      * draft <old> -> <new>
      * 둘 다: stable ...; draft ...
    - old/new는 CSV 문자열 그대로 사용하되, 비어있으면 N/A로 표준화
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
    # meta refresh: <meta http-equiv="refresh" content="0; url=...">
    m = re.search(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?[^"\']*url\s*=\s*([^"\'>\s;]+)',
        html,
        re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1).strip())

    # JS redirect: window.location = "..."
    m = re.search(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return urljoin(base_url, m.group(1).strip())

    # "Redirecting" 페이지: 첫 번째 유의미한 링크를 target 후보로 사용
    if re.search(r"\bRedirecting\b", html, re.IGNORECASE):
        soup = soup_from_html(html)
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
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
    - HTML 기반 redirect(meta refresh/JS/link)도 1~2 hop까지 수동 추적
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
    ✅ 개선: "Status of This Document" 탐지를 대소문자 무시 + 공백 변화에 강하게
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

    # ✅ 개선: 상태 매칭을 케이스 인센서티브로
    status = None
    window_l = window.lower()
    for k, v in status_map.items():
        if k.lower() in window_l:
            status = v
            break

    # 안전장치: did-1.1 Recommendation 오탐 방지
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

    # ✅ 개선: 상태까지 잡히면 기존 포맷 유지, 상태를 못 잡아도 버전만 잡히면 최소 기록
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
    GitHub repo에서 최신 커밋 날짜를 YYYY-MM-DD로 추출.
    - API 없이 commits 페이지 HTML에서 relative-time datetime 파싱
    - branch가 main/master 다를 수 있어 여러 경로 시도
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
    HL AnonCreds spec 페이지에서
    - stable 버전 후보: "This version (vX.Y)" 또는 "Specification Status: vX.Y ..."
    - latest draft 링크: 본문 링크 중 GitHub repo(anoncreds/anoncreds-spec)를 발견
    - HTML redirect는 http_get()에서 이미 처리됨
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
    Draft Link가 N/A여도 HL spec 페이지에서 Latest Draft repo를 발견하면 Draft로 기록.
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

            else:
                pass

        except Exception:
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

            else:
                pass

        except Exception:
            pass
    else:
        # ✅ Draft 링크가 N/A여도 HL은 stable 페이지에서 Latest Draft 발견 가능
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

def update_readme_changelog(diffs_by_row: List[Tuple[str, str, List[str]]]) -> None:
    if not diffs_by_row:
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
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] standards.csv not found at {CSV_PATH}", file=sys.stderr)
        return 2

    fieldnames, rows = load_csv_rows(CSV_PATH)

    missing = [c for c in ALLOWED_UPDATE_COLS if c not in fieldnames]
    if missing:
        print(f"[ERROR] CSV missing expected columns: {missing}", file=sys.stderr)
        return 2

    changed_any = False
    diffs_for_readme: List[Tuple[str, str, List[str]]] = []

    for row in rows:
        org = row.get("단체", "").strip()
        name = row.get("표준명 (항목)", "").strip()

        before_raw = {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in fieldnames}

        stable_link = row.get("Stable Version Link", "")
        draft_link = row.get("Draft Version Link", "")

        upd_raw = compute_update_for_row(org, name, stable_link, draft_link)
        upd = validate_and_finalize(before_raw, upd_raw)

        # 1) 4개 핵심 컬럼 업데이트
        row["Stable Version"] = norm_na(upd.stable_version)
        row["Stable Version Link"] = norm_na(upd.stable_link)
        row["Draft Version"] = norm_na(upd.draft_version)
        row["Draft Version Link"] = norm_na(upd.draft_link)

        # 2) ✅ 핵심 변경 내용: 버전 변경 시에만 기록, 아니면 기존 값 유지
        if "핵심 변경 내용" in fieldnames:
            core = compute_core_change(before_raw, row)
            if core is not None:
                row["핵심 변경 내용"] = core
            # else: 버전 변경이 없으면 절대 덮어쓰지 않음(기존 값 유지)

        # 3) README diff는 기존대로 4개 컬럼만 (중복 기록 방지)
        diffs: List[str] = []
        for col in ["Stable Version", "Stable Version Link", "Draft Version", "Draft Version Link"]:
            b = (before_raw.get(col, "") or "").strip()
            a = (row.get(col, "") or "").strip()
            if b != a:
                diffs.append(f"{col}: {b or '(empty)'} → {a}")

        # 4) CSV 실제 변경 여부 판단:
        core_changed = False
        if "핵심 변경 내용" in fieldnames:
            b_core = (before_raw.get("핵심 변경 내용", "") or "").strip()
            a_core = (row.get("핵심 변경 내용", "") or "").strip()
            core_changed = (b_core != a_core)

        if diffs or core_changed:
            changed_any = True
            if diffs:
                diffs_for_readme.append((org, name, diffs))
            else:
                # (거의 발생하지 않지만) 핵심 변경 내용만 바뀐 경우 README는 업데이트하지 않음
                pass

    if changed_any:
        write_csv_rows(CSV_PATH, fieldnames, rows)
        update_readme_changelog(diffs_for_readme)
        print(f"[OK] Updated standards.csv and README.md with {len(diffs_for_readme)} changed rows.")
    else:
        print("[OK] No changes detected.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())