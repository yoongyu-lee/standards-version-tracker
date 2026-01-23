#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
standards.csv를 Source of Truth로 사용해 Stable/Draft 버전과 링크를 자동 갱신한다.

+ (추가) GitHub Actions에서 "파일이 안 생기는" 원인 분석을 위해
  - STDOUT + 파일 로그 동시 기록
  - 실행 환경/경로/권한/디렉토리 생성/스냅샷 쓰기/디프 쓰기/requests 호출/예외(traceback) 전부 로깅
  - 종료 직전에 logs 디렉토리 트리/파일 목록을 요약 출력

ENV (로깅/디버깅):
- SVT_DEBUG=1           : DEBUG 레벨 로그
- SVT_LOG_STDOUT_ONLY=1 : 파일 로그 없이 stdout만 (기본은 파일+stdout)
- SVT_LOG_FILE=...      : 로그 파일 경로 강제 지정 (기본: LOG_ROOT/run-YYYYmmdd-HHMMSS.log)

기존 ENV:
- SVT_LOG_ROOT, SVT_SNAPSHOT_DIR, SVT_DIFF_DIR
- SVT_BASELINE_DIFF
"""

from __future__ import annotations

import csv
import os
import re
import sys
import traceback
import logging
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
ENV_LOG_ROOT = os.environ.get("SVT_LOG_ROOT", "").strip()
DEFAULT_LOG_ROOT = os.path.join(ROOT, "logs")
LOG_ROOT = ENV_LOG_ROOT if ENV_LOG_ROOT else DEFAULT_LOG_ROOT

ENV_SNAPSHOT_DIR = os.environ.get("SVT_SNAPSHOT_DIR", "").strip()
ENV_DIFF_DIR = os.environ.get("SVT_DIFF_DIR", "").strip()

SNAPSHOT_DIR = ENV_SNAPSHOT_DIR if ENV_SNAPSHOT_DIR else os.path.join(LOG_ROOT, "snapshots")
DIFF_DIR = ENV_DIFF_DIR if ENV_DIFF_DIR else os.path.join(LOG_ROOT, "diffs")

# baseline에서도 diff를 만들지 여부 (기본: 0 = 기존 동작 유지)
BASELINE_DIFF = os.environ.get("SVT_BASELINE_DIFF", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}

# Logging env
DEBUG_MODE = os.environ.get("SVT_DEBUG", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
LOG_STDOUT_ONLY = os.environ.get("SVT_LOG_STDOUT_ONLY", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
ENV_LOG_FILE = os.environ.get("SVT_LOG_FILE", "").strip()

logger = logging.getLogger("svt")


def _now_kst_ts() -> str:
    return datetime.now(KST).strftime("%Y%m%d-%H%M%S")


def setup_logging() -> str:
    """
    stdout + 파일 로깅 동시 설정.
    returns: log_file_path (stdout only면 빈 문자열)
    """
    # 핸들러 중복 방지
    if logger.handlers:
        return ""

    logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG if DEBUG_MODE else logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_file_path = ""
    if not LOG_STDOUT_ONLY:
        try:
            os.makedirs(LOG_ROOT, exist_ok=True)
            if ENV_LOG_FILE:
                log_file_path = ENV_LOG_FILE
            else:
                log_file_path = os.path.join(LOG_ROOT, f"run-{_now_kst_ts()}.log")

            fh = logging.FileHandler(log_file_path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            # 파일 로그가 실패해도 stdout 로그로는 남기기
            logger.error("Failed to init file logging:\n%s", traceback.format_exc())
            log_file_path = ""

    logger.info("[BOOT] logger initialized. debug=%s stdout_only=%s log_file=%s",
                DEBUG_MODE, LOG_STDOUT_ONLY, (log_file_path or "(none)"))
    return log_file_path


def ensure_dirs() -> None:
    """
    스냅샷/디프 디렉토리 생성 + 권한/에러 로깅
    """
    try:
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        os.makedirs(DIFF_DIR, exist_ok=True)
        logger.debug("[FS] ensure_dirs OK snapshot_dir=%s diff_dir=%s", SNAPSHOT_DIR, DIFF_DIR)
    except Exception:
        logger.error("[FS] ensure_dirs FAILED snapshot_dir=%s diff_dir=%s\n%s",
                     SNAPSHOT_DIR, DIFF_DIR, traceback.format_exc())
        raise


def _list_dir_tree(root: str, max_lines: int = 300) -> List[str]:
    """
    디버깅용: 디렉토리 트리를 간단히 나열.
    너무 길어지지 않도록 라인 제한.
    """
    lines: List[str] = []
    try:
        if not os.path.exists(root):
            return [f"(missing) {root}"]
        for cur, dirs, files in os.walk(root):
            rel = os.path.relpath(cur, root)
            lines.append(f"[DIR] {root}/{rel}".replace("\\", "/"))
            dirs.sort()
            files.sort()
            for f in files:
                p = os.path.join(cur, f)
                try:
                    st = os.stat(p)
                    lines.append(f"  - {f} ({st.st_size} bytes)")
                except Exception:
                    lines.append(f"  - {f} (stat failed)")
            if len(lines) >= max_lines:
                lines.append(f"... truncated (max_lines={max_lines})")
                break
    except Exception:
        return [f"(walk failed) {root}", traceback.format_exc()]
    return lines


def url_to_safe_filename(url: str) -> str:
    parsed = urlparse(url)
    clean_path = re.sub(r"[^a-zA-Z0-9]", "_", (parsed.netloc or "") + (parsed.path or ""))
    if not clean_path:
        clean_path = re.sub(r"[^a-zA-Z0-9]", "_", url)
    return clean_path[:200]


def soup_from_html(html: str) -> BeautifulSoup:
    # lxml 미설치/파서 문제도 여기서 터질 수 있으니 로깅
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        logger.error("[PARSE] BeautifulSoup(lxml) failed. Falling back to html.parser.\n%s",
                     traceback.format_exc())
        return BeautifulSoup(html, "html.parser")


def extract_first(regex: str, text: str, flags=0) -> Optional[str]:
    m = re.search(regex, text, flags)
    return m.group(1) if m else None


def http_get(
    url: str,
    timeout: int = 25,
    return_headers: bool = False,
    return_final_url: bool = False,
):
    """
    - HTTP redirect는 requests가 처리(allow_redirects=True)
    - HTML 기반 redirect(meta refresh/JS/link)도 최대 2 hop까지 수동 추적
    + (추가) 각 hop마다 status/최종URL/헤더 일부/본문 길이 로깅
    """
    headers = {
        "User-Agent": "standards-version-tracker-bot/1.0 (+https://github.com/yoongyu-lee/standards-version-tracker)"
    }

    final_url = url
    last_headers = None
    text = None

    for hop in range(1, 4):  # 최대 2번 추가 추적(총 3번 fetch)
        try:
            logger.debug("[HTTP] GET hop=%d url=%s timeout=%s", hop, final_url, timeout)
            r = requests.get(final_url, headers=headers, timeout=timeout, allow_redirects=True)
            logger.debug("[HTTP] RESP hop=%d status=%s final=%s len=%s ct=%s",
                         hop, r.status_code, r.url, len(r.text or ""), r.headers.get("Content-Type"))
            r.raise_for_status()
            text = r.text
            last_headers = r.headers
            final_url = r.url
        except Exception:
            logger.error("[HTTP] FAILED hop=%d url=%s\n%s", hop, final_url, traceback.format_exc())
            raise

        target = _extract_html_redirect_target(final_url, text)
        if target and target != final_url:
            logger.debug("[HTTP] HTML redirect detected: %s -> %s", final_url, target)
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


def fetch_page_lines_for_diff(url: str) -> List[str]:
    """
    HTML <body> 텍스트를 줄 단위로 추출해 비교 가능한 형태로 정규화
    + (추가) 라인 수 로깅
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

    logger.debug("[DIFF] fetched lines url=%s lines=%d", url, len(lines))
    return lines


def load_snapshot_lines(path: str) -> List[str]:
    if not os.path.exists(path):
        logger.debug("[FS] snapshot missing path=%s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
        logger.debug("[FS] snapshot loaded path=%s lines=%d", path, len(lines))
        return lines
    except Exception:
        logger.error("[FS] snapshot read FAILED path=%s\n%s", path, traceback.format_exc())
        raise


def save_snapshot_lines(path: str, lines: List[str]) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp, path)
        logger.debug("[FS] snapshot saved path=%s lines=%d", path, len(lines))
    except Exception:
        logger.error("[FS] snapshot write FAILED path=%s tmp=%s\n%s", path, tmp, traceback.format_exc())
        raise


def make_unified_diff(prev_lines: List[str], cur_lines: List[str]) -> str:
    import difflib
    diff = difflib.unified_diff(prev_lines, cur_lines, lineterm="")
    return "\n".join(diff).strip()


def safe_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
        logger.debug("[FS] file saved path=%s bytes=%d", path, len(content.encode("utf-8", "ignore")))
    except Exception:
        logger.error("[FS] file write FAILED path=%s tmp=%s\n%s", path, tmp, traceback.format_exc())
        raise


def _write_diff_file(url: str, prev: List[str], cur: List[str]) -> Optional[str]:
    diff_text = make_unified_diff(prev, cur)

    ts = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    safe = url_to_safe_filename(url)
    diff_filename = f"{safe}__{ts}.diff"
    diff_path = os.path.join(DIFF_DIR, diff_filename)

    if diff_text:
        safe_write_text(diff_path, diff_text + "\n")
        rel = os.path.relpath(diff_path, ROOT)
        logger.info("[DIFF] created url=%s diff=%s", url, rel)
        return rel

    logger.debug("[DIFF] empty diff url=%s (no file created)", url)
    return None


def check_and_record_content_change(url: str) -> Tuple[str, Optional[str]]:
    """
    반환:
      - ("baseline", None): 이전 스냅샷이 없어 베이스라인만 생성 (기본: diff 생성/README 기록 안 함)
      - ("baseline", diff_relpath): (옵션) SVT_BASELINE_DIFF=1이면 baseline에서도 diff 생성
      - ("unchanged", None): 이전 스냅샷과 동일 (파일 변경 없음)
      - ("changed", diff_relpath): 실제 변경 감지 → diff 생성 + 스냅샷 갱신
    """
    ensure_dirs()

    safe = url_to_safe_filename(url)
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"{safe}.txt")

    prev = load_snapshot_lines(snapshot_path)
    cur = fetch_page_lines_for_diff(url)

    if prev == cur:
        logger.debug("[DIFF] unchanged url=%s snapshot=%s", url, snapshot_path)
        return "unchanged", None

    if not prev:
        # baseline
        logger.info("[DIFF] baseline url=%s snapshot=%s (BASELINE_DIFF=%s)", url, snapshot_path, BASELINE_DIFF)
        save_snapshot_lines(snapshot_path, cur)
        if BASELINE_DIFF:
            diff_rel = _write_diff_file(url, [], cur)
            return "baseline", diff_rel
        return "baseline", None

    # changed
    logger.info("[DIFF] changed url=%s snapshot=%s prev_lines=%d cur_lines=%d",
                url, snapshot_path, len(prev), len(cur))
    diff_rel = _write_diff_file(url, prev, cur)
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


def has_identifier(s: str) -> bool:
    if not s:
        return False
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        return True
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        return True
    # ✅ ISO DIS 같은 형태도 identifier로 인정
    if re.search(r"\bISO/IEC\s+DIS\b", s):
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
    # ISO DIS 포함이면 추가 가점
    if re.search(r"\bISO/IEC\s+DIS\b", s):
        score += 30
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
    m = re.search(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?[^"\']*url\s*=\s*([^"\'>\s;]+)',
        html,
        re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1).strip())

    m = re.search(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return urljoin(base_url, m.group(1).strip())

    if re.search(r"\bRedirecting\b", html, re.IGNORECASE):
        soup = soup_from_html(html)
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href:
                return urljoin(base_url, href)

    soup = soup_from_html(html)
    link = soup.find("link", attrs={"rel": re.compile(r"\bcanonical\b", re.IGNORECASE)})
    if link and link.get("href"):
        return urljoin(base_url, link["href"].strip())

    return None


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


def parse_iso_draft(url: str, spec_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    ✅ 개선:
    - Life cycle에서 날짜 파싱 실패해도,
      draft 링크가 있는 이상 'DIS'임을 버전으로 기록해야 함 (N/A로 두면 안됨)
    """
    html = http_get(url)
    soup = soup_from_html(html)
    text = soup.get_text("\n", strip=True)

    # 1) Life cycle: 40.20 ... 2026-01-01 ...
    d = extract_first(r"\b40\.20\s+(\d{4}-\d{2}-\d{2})\b", text)
    if d:
        ref = extract_first(r"\b(ISO/IEC\s+DIS\s+[0-9-]+)\b", text)
        if ref:
            ref = re.sub(r"\s+", " ", ref.strip())
            return f"{ref} (DIS ballot initiated: {d})", url
        return f"ISO/IEC DIS {spec_name.split(':')[0].strip()} (DIS ballot initiated: {d})", url

    # 2) 다른 단계라도 날짜가 있으면 잡기
    d2 = extract_first(r"\b(20|19)\d{2}-\d{2}-\d{2}\b", text)
    if d2:
        ref = extract_first(r"\b(ISO/IEC\s+DIS\s+[0-9-]+)\b", text)
        if ref:
            ref = re.sub(r"\s+", " ", ref.strip())
            return f"{ref} ({d2} ISO Draft)", url

    # 3) ✅ fallback: 페이지 텍스트에서 DIS ref 추출
    ref2 = extract_first(r"\b(ISO/IEC\s+DIS\s+[0-9-]+)\b", text)
    if ref2:
        ref2 = re.sub(r"\s+", " ", ref2.strip())
        return f"{ref2} (ISO Draft)", url

    # 4) ✅ last fallback: 최소 DIS 식별자라도 기록
    # (ISO draft 링크 존재 = draft 확정)
    return f"ISO/IEC DIS {spec_name.split(':')[0].strip()} (ISO Draft)", url


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
            logger.warning("[ROW] stable parse failed org=%s name=%s url=%s\n%s",
                           org, spec_name, stable_link_n, traceback.format_exc())

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

            elif org == "ISO" and "iso.org/standard/" in draft_link_n:
                # ✅ ISO Draft Version은 링크가 있는 이상 N/A면 안 됨.
                v, l = parse_iso_draft(draft_link_n, spec_name)
                if v and l:
                    upd.draft_version, upd.draft_link = v, l

        except Exception:
            logger.warning("[ROW] draft parse failed org=%s name=%s url=%s\n%s",
                           org, spec_name, draft_link_n, traceback.format_exc())

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

    new_stable_l = choose_link_seed_protected(cur_stable_l, cand_stable_l)
    new_draft_l = choose_link_seed_protected(cur_draft_l, cand_draft_l)

    new_stable_v = choose_value_no_degrade(cur_stable_v, cand_stable_v)
    new_draft_v = choose_value_no_degrade(cur_draft_v, cand_draft_v)

    if is_na(new_stable_l):
        new_stable_v = "N/A"

    # Draft 규칙:
    # - 링크가 N/A면 버전도 N/A
    # - 링크가 있어도 식별자 없으면 버전은 N/A 유지
    if is_na(new_draft_l):
        new_draft_v = "N/A"
    else:
        if is_na(new_draft_v) or not has_identifier(new_draft_v):
            new_draft_v = "N/A"

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
    """
    README 변경내역을 '버전 변경'과 'content diff'를 분리해서 기록한다.
    - Version updates: 펼쳐진 상태로 (가독성 우선)
    - Content diffs: <details>로 접어서 (README 지저분함 방지)
    """
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

    version_lines: List[str] = []
    for org, name, diffs in diffs_by_row:
        joined = "; ".join(diffs)
        version_lines.append(f"- [{org}] {name}: {joined}")

    content_lines: List[str] = []
    for org, name, notes in content_changes_by_row:
        joined = "; ".join(notes)
        content_lines.append(f"- [{org}] {name}: {joined}")

    lines: List[str] = [f"### {today}"]

    if version_lines:
        lines.append("")
        lines.append("#### Version updates")
        lines.extend(version_lines)

    if content_lines:
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Content diffs (click to expand)</summary>")
        lines.append("")
        lines.extend(content_lines)
        lines.append("")
        lines.append("</details>")

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
    log_file = setup_logging()

    try:
        logger.info("[ENV] cwd=%s", os.getcwd())
        logger.info("[ENV] script_dir=%s", os.path.dirname(__file__))
        logger.info("[ENV] ROOT=%s", ROOT)
        logger.info("[ENV] CSV_PATH=%s exists=%s", CSV_PATH, os.path.exists(CSV_PATH))
        logger.info("[ENV] README_PATH=%s exists=%s", README_PATH, os.path.exists(README_PATH))
        logger.info("[ENV] LOG_ROOT=%s SNAPSHOT_DIR=%s DIFF_DIR=%s BASELINE_DIFF=%s",
                    LOG_ROOT, SNAPSHOT_DIR, DIFF_DIR, BASELINE_DIFF)
        logger.info("[ENV] python=%s", sys.version.replace("\n", " "))
        logger.info("[ENV] requests=%s bs4=%s", getattr(requests, "__version__", "unknown"),
                    getattr(__import__("bs4"), "__version__", "unknown"))
        try:
            import lxml  # noqa
            logger.info("[ENV] lxml=installed")
        except Exception:
            logger.info("[ENV] lxml=NOT installed (will fallback to html.parser)")
    except Exception:
        logger.error("[ENV] dump failed\n%s", traceback.format_exc())

    ensure_dirs()

    if not os.path.exists(CSV_PATH):
        logger.error("[ERROR] standards.csv not found at %s", CSV_PATH)
        return 2

    fieldnames, rows = load_csv_rows(CSV_PATH)

    missing = [c for c in ALLOWED_UPDATE_COLS if c not in fieldnames]
    if missing:
        logger.error("[ERROR] CSV missing expected columns: %s", missing)
        return 2

    changed_any = False
    csv_changed_any = False

    diffs_for_readme: List[Tuple[str, str, List[str]]] = []
    content_changes_for_readme: List[Tuple[str, str, List[str]]] = []

    content_status_counts = {"baseline": 0, "unchanged": 0, "changed": 0}
    content_diff_files = 0

    logger.info("[RUN] rows=%d", len(rows))

    for idx, row in enumerate(rows, start=1):
        org = row.get("단체", "").strip()
        name = row.get("표준명 (항목)", "").strip()

        before_raw = {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in fieldnames}

        stable_link = row.get("Stable Version Link", "")
        draft_link = row.get("Draft Version Link", "")

        logger.debug("[ROW] #%d org=%s name=%s stable_link=%s draft_link=%s",
                     idx, org, name, stable_link, draft_link)

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
                    content_notes.append(f"changed stable: {diff_rel}")
                if status == "baseline" and diff_rel:
                    content_notes.append(f"baseline stable: {diff_rel}")

            except Exception as e:
                logger.warning("[WARN] stable content snapshot failed: %s err=%s\n%s",
                               stable_url, repr(e), traceback.format_exc())

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
                    content_notes.append(f"changed draft: {diff_rel}")
                if status == "baseline" and diff_rel:
                    content_notes.append(f"baseline draft: {diff_rel}")

            except Exception as e:
                logger.warning("[WARN] draft content snapshot failed: %s err=%s\n%s",
                               draft_url, repr(e), traceback.format_exc())

        if content_notes:
            content_changes_for_readme.append((org, name, content_notes))

        if logs_changed:
            changed_any = True

        # --- 버전/링크 자동 갱신 로직 ---
        upd_raw = compute_update_for_row(org, name, stable_link, draft_link)
        upd = validate_and_finalize(before_raw, upd_raw)

        row["Stable Version"] = norm_na(upd.stable_version)
        row["Stable Version Link"] = norm_na(upd.stable_link)
        row["Draft Version"] = norm_na(upd.draft_version)
        row["Draft Version Link"] = norm_na(upd.draft_link)

        if "핵심 변경 내용" in fieldnames:
            core = compute_core_change(before_raw, row)
            if core is not None:
                row["핵심 변경 내용"] = core

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

    if changed_any:
        if csv_changed_any:
            write_csv_rows(CSV_PATH, fieldnames, rows)
            logger.info("[OK] standards.csv updated rows_changed=%d", len(diffs_for_readme))

        update_readme_changelog(diffs_for_readme, content_changes_for_readme)

        logger.info("[OK] Updated artifacts. csv_row_changes=%d content_only_changes=%d",
                    len(diffs_for_readme), len(content_changes_for_readme))
    else:
        logger.info("[OK] No changes detected.")

    logger.info("[INFO] content_status_counts=%s diff_files_created=%d snapshot_dir=%s diff_dir=%s baseline_diff=%s",
                content_status_counts, content_diff_files, SNAPSHOT_DIR, DIFF_DIR, BASELINE_DIFF)

    logger.info("[TREE] LOG_ROOT listing:\n%s", "\n".join(_list_dir_tree(LOG_ROOT, max_lines=250)))
    logger.info("[TREE] SNAPSHOT_DIR listing:\n%s", "\n".join(_list_dir_tree(SNAPSHOT_DIR, max_lines=250)))
    logger.info("[TREE] DIFF_DIR listing:\n%s", "\n".join(_list_dir_tree(DIFF_DIR, max_lines=250)))

    if log_file:
        logger.info("[DONE] log_file=%s", log_file)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            setup_logging()
            logger.critical("[FATAL] uncaught exception\n%s", traceback.format_exc())
        except Exception:
            print("[FATAL] uncaught exception (logger init failed)\n" + traceback.format_exc(), file=sys.stderr)
        raise