#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
standards.csv를 Source of Truth로 사용해 Stable/Draft 버전과 링크를 자동 갱신한다.

반영된 동작(요약):
- Draft Version Link가 비어있거나 N/A여도 stable link 기반으로 Draft discovery 시도
  * W3C: TR stable에서 Editor’s Draft 탐색 + (날짜/버전) 식별자 확보 시에만 Draft 반영
  * ISO: stable에서 Next version under development 링크 탐색(기존 유지)
  * IETF: (보수적) stable 링크가 N/A여도 datatracker 공식 검색으로 draft-id를 찾고,
           spec_name과 title 유사도가 임계치 이상일 때만 최신 revision 반영 (추정 금지)
  * OIDF: stable(openid.net/specs) 페이지 내부에 "draft-XX" 명시 링크가 있을 때만 Draft 반영
  * EU: Draft는 기본 N/A 유지, Stable은 latest 기반 최신 버전/링크로 고정(옵션: 아래 EU 블록 참고)
  * HL(예: Hyperledger AnonCreds): Draft 자동 discovery 하지 않음

- Stable Version 자동 채움 개선(문제 해결 포인트)
  * W3C: TR stable에서 vX.Y 또는 날짜(YYYY-MM-DD) 추출
  * IETF: RFC 링크면 "RFC ####"로 Stable Version 채움
  * OIDF: spec URL의 "-1_0.html" 등에서 "1.0" 추출
  * EU: 버전 경로(/X.Y.Z/) 또는 latest 페이지에서 changelog 버전 추출(최신화)

로깅/디프/스냅샷:
- STDOUT + 파일 로그 동시 기록
- snapshots/diffs 생성
- BASELINE_DIFF=1이면 baseline에서도 diff 생성

ENV:
- SVT_DEBUG=1           : DEBUG 레벨 로그
- SVT_LOG_STDOUT_ONLY=1 : 파일 로그 없이 stdout만 (기본은 파일+stdout)
- SVT_LOG_FILE=...      : 로그 파일 경로 강제 지정 (기본: LOG_ROOT/run-YYYYmmdd-HHMMSS.log)
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
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse, quote
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

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

# baseline에서도 diff를 만들지 여부 (기본: 0)
BASELINE_DIFF = os.environ.get("SVT_BASELINE_DIFF", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}

# Logging env
DEBUG_MODE = os.environ.get("SVT_DEBUG", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
LOG_STDOUT_ONLY = os.environ.get("SVT_LOG_STDOUT_ONLY", "0").strip() in {"1", "true", "TRUE", "yes", "YES"}
ENV_LOG_FILE = os.environ.get("SVT_LOG_FILE", "").strip()

logger = logging.getLogger("svt")


def _now_kst_ts() -> str:
    return datetime.now(KST).strftime("%Y%m%d-%H%M%S")


def setup_logging() -> str:
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
            log_file_path = ENV_LOG_FILE or os.path.join(LOG_ROOT, f"run-{_now_kst_ts()}.log")

            fh = logging.FileHandler(log_file_path, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except Exception:
            logger.error("Failed to init file logging:\n%s", traceback.format_exc())
            log_file_path = ""

    logger.info("[BOOT] logger initialized. debug=%s stdout_only=%s log_file=%s",
                DEBUG_MODE, LOG_STDOUT_ONLY, (log_file_path or "(none)"))
    return log_file_path


def ensure_dirs() -> None:
    try:
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        os.makedirs(DIFF_DIR, exist_ok=True)
        logger.debug("[FS] ensure_dirs OK snapshot_dir=%s diff_dir=%s", SNAPSHOT_DIR, DIFF_DIR)
    except Exception:
        logger.error("[FS] ensure_dirs FAILED snapshot_dir=%s diff_dir=%s\n%s",
                     SNAPSHOT_DIR, DIFF_DIR, traceback.format_exc())
        raise


def _list_dir_tree(root: str, max_lines: int = 300) -> List[str]:
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


def extract_first(regex: str, text: str, flags=0) -> Optional[str]:
    m = re.search(regex, text, flags)
    return m.group(1) if m else None


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


def norm_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    p = urlparse(u)
    p2 = p._replace(fragment="")
    return urlunparse(p2)


def url_to_safe_filename(url: str) -> str:
    parsed = urlparse(url)
    clean_path = re.sub(r"[^a-zA-Z0-9]", "_", (parsed.netloc or "") + (parsed.path or ""))
    if not clean_path:
        clean_path = re.sub(r"[^a-zA-Z0-9]", "_", url)
    return clean_path[:200]


def soup_from_html(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        logger.error("[PARSE] BeautifulSoup(lxml) failed. Falling back to html.parser.\n%s",
                     traceback.format_exc())
        return BeautifulSoup(html, "html.parser")


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


def http_get(
    url: str,
    timeout: int = 25,
    return_headers: bool = False,
    return_final_url: bool = False,
):
    headers = {
        "User-Agent": "standards-version-tracker-bot/1.0 (+https://github.com/yoongyu-lee/standards-version-tracker)"
    }

    final_url = norm_url(url)
    last_headers = None
    text = None

    for hop in range(1, 4):
        try:
            logger.debug("[HTTP] GET hop=%d url=%s timeout=%s", hop, final_url, timeout)
            r = requests.get(final_url, headers=headers, timeout=timeout, allow_redirects=True)
            logger.debug("[HTTP] RESP hop=%d status=%s final=%s len=%s ct=%s",
                         hop, r.status_code, r.url, len(r.text or ""), r.headers.get("Content-Type"))
            r.raise_for_status()
            text = r.text
            last_headers = r.headers
            final_url = norm_url(r.url)
        except Exception:
            logger.error("[HTTP] FAILED hop=%d url=%s\n%s", hop, final_url, traceback.format_exc())
            raise

        target = _extract_html_redirect_target(final_url, text)
        if target:
            t = norm_url(target)
            if t and t != final_url:
                logger.debug("[HTTP] HTML redirect detected: %s -> %s", final_url, t)
                final_url = t
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


# -------------------------
# Diff snapshot logic
# -------------------------

def fetch_page_lines_for_diff(url: str) -> List[str]:
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
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f.readlines()]
    logger.debug("[FS] snapshot loaded path=%s lines=%d", path, len(lines))
    return lines


def save_snapshot_lines(path: str, lines: List[str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    os.replace(tmp, path)
    logger.debug("[FS] snapshot saved path=%s lines=%d", path, len(lines))


def make_unified_diff(prev_lines: List[str], cur_lines: List[str]) -> str:
    import difflib
    diff = difflib.unified_diff(prev_lines, cur_lines, lineterm="")
    return "\n".join(diff).strip()


def safe_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)
    logger.debug("[FS] file saved path=%s bytes=%d", path, len(content.encode("utf-8", "ignore")))


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
    ensure_dirs()

    safe = url_to_safe_filename(url)
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"{safe}.txt")

    prev = load_snapshot_lines(snapshot_path)
    cur = fetch_page_lines_for_diff(url)

    if prev == cur:
        logger.debug("[DIFF] unchanged url=%s snapshot=%s", url, snapshot_path)
        return "unchanged", None

    if not prev:
        logger.info("[DIFF] baseline url=%s snapshot=%s (BASELINE_DIFF=%s)", url, snapshot_path, BASELINE_DIFF)
        save_snapshot_lines(snapshot_path, cur)
        if BASELINE_DIFF:
            diff_rel = _write_diff_file(url, [], cur)
            return "baseline", diff_rel
        return "baseline", None

    logger.info("[DIFF] changed url=%s snapshot=%s prev_lines=%d cur_lines=%d",
                url, snapshot_path, len(prev), len(cur))
    diff_rel = _write_diff_file(url, prev, cur)
    save_snapshot_lines(snapshot_path, cur)
    return "changed", diff_rel


# -------------------------
# Version parsing utils
# -------------------------

def has_identifier(s: str) -> bool:
    if not s:
        return False
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        return True
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        return True
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        return True
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


# -------------------------
# Data model
# -------------------------

@dataclass
class RowUpdate:
    stable_version: Optional[str] = None
    stable_link: Optional[str] = None
    draft_version: Optional[str] = None
    draft_link: Optional[str] = None


# -------------------------
# Parsers / Discovery
# -------------------------

def parse_hl_anoncreds_draft(draft_url: str) -> Optional[str]:
    """
    Hyperledger AnonCreds spec 페이지(gh-pages)에서 버전 식별자를 찾아 Draft Version을 만든다.
    - 규칙: Draft Version에는 식별자(버전/날짜 등)가 반드시 포함되어야 함.
    - 안전 개선: 본문 임의의 YYYY-MM-DD(예: 예시 JSON의 collected_on 등)는 더 이상 사용하지 않음.
      GitHub repo 최신 커밋 날짜 또는 명시적 버전 토큰만 허용.
    """
    try:
        html = http_get(draft_url)
    except Exception:
        return None

    soup = soup_from_html(html)

    # 0) 우선순위: "Specification Status: vX.Y Draft" 형태
    text_one_line = soup.get_text(" ", strip=True)
    m_status = re.search(
        r"\bSpecification\s+Status\b\s*:\s*v?(\d+\.\d+(?:\.\d+)?)\s*(?:Draft)?",
        text_one_line,
        re.IGNORECASE,
    )
    if m_status:
        v = m_status.group(1)
        return f"v{v} Draft"

    # 1) v1.0 / 1.0 / 1.0.0 등 명시 버전 토큰 (제목/본문)
    m_named = re.search(r"\bAnonCreds\s+v?(\d+\.\d+(?:\.\d+)?)\b", html, re.IGNORECASE)
    if m_named:
        return f"v{m_named.group(1)} Draft"

    m_ver = re.search(r"\bVersion\s+v?(\d+\.\d+(?:\.\d+)?)\b", html, re.IGNORECASE)
    if m_ver:
        return f"v{m_ver.group(1)} Draft"

    # 2) 안전한 날짜 근거: 페이지 내 GitHub repo(anoncreds/anoncreds-spec) 링크를 찾아
    #    최신 커밋 날짜를 Draft 식별자로 사용
    repo_url = None
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if "github.com" in href and re.search(r"/anoncreds(?:-|\.)?/anoncreds-spec", href, re.IGNORECASE):
            repo_url = href
            break

    if repo_url:
        dt = parse_github_latest_commit_date(repo_url.rstrip("/"))
        if dt:
            return f"{dt} Draft"

    return None


def parse_github_latest_commit_date(repo_url: str) -> Optional[str]:
    """
    GitHub repo의 최신 커밋 날짜를 YYYY-MM-DD로 추출.
    - API 없이 commits 페이지의 datetime 속성 파싱
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

        m1 = re.search(r'<relative-time[^>]+datetime="(\d{4}-\d{2}-\d{2})T', html, re.IGNORECASE)
        if m1:
            return m1.group(1)
        m2 = re.search(r'datetime="(\d{4}-\d{2}-\d{2})T', html, re.IGNORECASE)
        if m2:
            return m2.group(1)

    return None


def parse_iso_stable(url: str, spec_name: str) -> Tuple[Optional[str], Optional[str]]:
    html, final_url = http_get(url, return_final_url=True)
    soup = soup_from_html(html)
    text = soup.get_text("\n", strip=True)

    pub = (
        extract_first(r"Publication date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        or extract_first(r"Publication date\s*:?\s*([0-9]{4}-[0-9]{2})", text)
    )
    if pub:
        return f"{spec_name} (ISO Publication: {pub})", final_url

    pub2 = extract_first(r"\bPublished\s*:?\s*([0-9]{4}-[0-9]{2})\b", text)
    if pub2:
        return f"{spec_name} (ISO Publication: {pub2})", final_url

    return None, final_url


def discover_iso_next_draft_from_stable(stable_url: str) -> Optional[str]:
    try:
        html, final_url = http_get(stable_url, return_final_url=True)
    except Exception:
        return None

    soup = soup_from_html(html)
    anchors = soup.find_all("a", href=True)

    candidates: List[str] = []
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        u = norm_url(urljoin(final_url, href))
        if "iso.org/standard/" in u and re.search(r"/standard/\d+\.html$", u):
            candidates.append(u)

    return candidates[0] if candidates else None


def parse_iso_draft(url: str) -> Tuple[Optional[str], Optional[str]]:
    html, final_url = http_get(url, return_final_url=True)
    soup = soup_from_html(html)
    text = soup.get_text("\n", strip=True)

    ref = extract_first(r"\b(ISO(?:/IEC)?\s+DIS\s+[0-9-]+)\b", text)
    if ref:
        ref = re.sub(r"\s+", " ", ref.strip())

    d_4020 = extract_first(r"\b40\.20\s+(\d{4}-\d{2}-\d{2})\b", text)
    if d_4020:
        if ref:
            return f"{ref} (DIS ballot initiated: {d_4020})", final_url
        return f"DIS ballot initiated: {d_4020} (ISO Draft)", final_url

    d_any = extract_first(r"\b(20|19)\d{2}-\d{2}-\d{2}\b", text)
    if d_any:
        if ref:
            return f"{ref} ({d_any} ISO Draft)", final_url
        return f"{d_any} (ISO Draft)", final_url

    if ref:
        return f"{ref} (ISO Draft)", final_url

    return None, final_url


def parse_w3c_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    W3C TR stable에서 Stable Version 추출:
    - 우선순위: h1/title에서 vX.Y(.Z)
    - fallback: 페이지 내 YYYY-MM-DD (식별자 충족 목적)
    """
    html, final_url = http_get(url, return_final_url=True)
    soup = soup_from_html(html)

    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else "") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    m = re.search(r"\bv?\d+\.\d+(?:\.\d+)?\b", title, re.IGNORECASE)
    if m:
        v = m.group(0)
        if not v.lower().startswith("v"):
            v = "v" + v
        return v, final_url

    text = soup.get_text("\n", strip=True)
    m2 = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m2:
        return f"{m2.group(1)} (W3C TR)", final_url

    return None, final_url


def parse_w3c_draft_version(draft_url: str) -> Optional[str]:
    """
    W3C Editor’s Draft(또는 WD) 페이지에서 날짜/버전 식별자를 찾아
    'YYYY-MM-DD Editor's Draft' 같은 형태로 반환.
    """
    # 강화: 메타 태그, <time>, 본문 문구, HTTP Last-Modified 헤더까지 폭넓게 탐지
    try:
        html, headers = http_get(draft_url, return_headers=True)
    except Exception:
        return None

    soup = soup_from_html(html)

    # 1) 버전 탐지: h1/title에서 vX.Y(.Z) 우선, 없으면 제한적 semver(X.Y[.Z])
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

    # 2) 날짜 탐지 우선순위:
    #   - meta[name|property in {dcterms.modified,dcterms.issued,dc.date,dc.modified,last-modified}]
    #   - <time datetime="YYYY-MM-DD"> 또는 내용 텍스트 내 YYYY-MM-DD
    #   - 본문 라인 중 "This version|Last updated|Updated|Modified" 근처의 YYYY-MM-DD
    #   - HTTP Last-Modified 헤더 파싱
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

    # 3) 출력 조합(식별자 필수는 상위 validate 단계에서 확인)
    if ver and dt:
        return f"v{ver} ({dt} Editor's Draft)"
    if dt:
        return f"{dt} (Editor's Draft)"
    if ver:
        return f"v{ver} (Editor's Draft)"
    return None


def discover_w3c_draft_from_stable(stable_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    W3C TR stable 페이지에서 Editor’s Draft 링크를 찾고,
    Draft Version(식별자 포함)까지 확보되면 (draft_version, draft_link) 반환.
    """
    try:
        html, final_url = http_get(stable_url, return_final_url=True)
    except Exception:
        return None, None

    soup = soup_from_html(html)

    ed_href = None
    for a in soup.find_all("a", href=True):
        txt = (a.get_text(" ", strip=True) or "").strip()
        if re.search(r"Editor(?:’|'|)s Draft", txt, re.IGNORECASE):
            ed_href = a["href"].strip()
            break

    if not ed_href:
        text = soup.get_text("\n", strip=True)
        if re.search(r"Editor(?:’|'|)s Draft", text, re.IGNORECASE):
            for a in soup.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if "w3c.github.io" in href:
                    ed_href = href
                    break

    if not ed_href:
        return None, None

    draft_link = norm_url(urljoin(final_url, ed_href))

    dv = parse_w3c_draft_version(draft_link)
    if not dv or not has_identifier(dv):
        return None, None

    return dv, draft_link


def parse_ietf_stable_from_rfc_url(url: str) -> Optional[str]:
    u = (url or "").lower()
    m = re.search(r"/rfc(\d+)(?:/|$)", u)
    if m:
        return f"RFC {m.group(1)}"
    m2 = re.search(r"/doc/rfc(\d+)(?:/|$)", u)
    if m2:
        return f"RFC {m2.group(1)}"
    return None


def _ietf_extract_draft_id_from_text(text: str) -> Optional[str]:
    """
    spec_name 등에 draft-ietf-...-NN 형태가 있으면 base name 반환.
      - 입력: draft-ietf-oauth-v2-1-12 -> base: draft-ietf-oauth-v2-1
      - 입력: draft-ietf-oauth-v2-1    -> base: draft-ietf-oauth-v2-1
    """
    if not text:
        return None
    m = re.search(r"\b(draft-[a-z0-9-]+-\d{1,2})\b", text, re.IGNORECASE)
    if m:
        full = m.group(1)
        base = re.sub(r"-\d{1,2}$", "", full)
        return base.lower()

    m2 = re.search(r"\b(draft-[a-z0-9-]+)\b", text, re.IGNORECASE)
    if m2:
        return m2.group(1).lower()

    return None


def _ietf_datatracker_fetch_latest_revision(base_draft_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    base_draft_name에 대해 datatracker 문서 HTML에서 가장 큰 revision(-NN)을 선택해 반환.
    """
    if not base_draft_name:
        return None, None

    doc_url = f"https://datatracker.ietf.org/doc/{quote(base_draft_name)}/"
    try:
        html, final_url = http_get(doc_url, return_final_url=True)
    except Exception:
        return None, None

    matches = re.findall(rf"\b({re.escape(base_draft_name)}-\d{{1,2}})\b", html, re.IGNORECASE)
    if not matches:
        return None, final_url

    best = None
    best_n = -1
    for m in matches:
        mm = re.search(r"-(\d{1,2})$", m)
        if not mm:
            continue
        n = int(mm.group(1))
        if n > best_n:
            best_n = n
            best = m.lower()

    if not best:
        return None, final_url

    draft_id = best
    draft_link = f"https://datatracker.ietf.org/doc/html/{quote(draft_id)}"
    draft_version = f"{draft_id} Internet-Draft"
    return draft_version, draft_link


def _ietf_norm_tokens(s: str) -> List[str]:
    """
    IETF datatracker search 결과를 spec_name에 매칭하기 위한 보수적 토큰화.
    - 알파넘만 남기고 소문자
    - 길이 3 미만 토큰 제거(노이즈 감소)
    """
    if not s:
        return []
    s = re.sub(r"[\u2018\u2019\u201C\u201D]", "'", s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if len(t) >= 3]
    # 너무 흔한 단어 제거(보수적으로 최소만)
    stop = {"the", "and", "for", "with", "from", "based", "json", "token", "tokens", "verifiable", "credential", "credentials"}
    return [t for t in toks if t not in stop]


def _ietf_title_from_doc_page(doc_url: str) -> str:
    """
    datatracker doc 페이지에서 title/h1 등을 뽑아 매칭에 사용.
    실패해도 빈 문자열 반환.
    """
    try:
        html = http_get(doc_url)
    except Exception:
        return ""
    soup = soup_from_html(html)
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            return t
    if soup.title:
        t = soup.title.get_text(" ", strip=True)
        if t:
            return t
    # fallback: 상단 텍스트 일부
    txt = soup.get_text("\n", strip=True)
    return (txt.splitlines()[0] if txt else "")[:200]


def _ietf_match_score(spec_name: str, title: str) -> int:
    """
    매우 보수적인 매칭 점수:
    - spec_name 토큰이 title에 몇 개나 등장하는지
    - 0이면 불일치 취급
    """
    s_toks = _ietf_norm_tokens(spec_name)
    t_toks = set(_ietf_norm_tokens(title))
    if not s_toks or not t_toks:
        return 0
    hits = sum(1 for tok in set(s_toks) if tok in t_toks)
    return hits

def discover_ietf_draft_deterministic(spec_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    SD-JWT VC 전용 deterministic discovery (OAuth WG 규칙 기반)
    """
    name = (spec_name or "").lower()

    if "sd-jwt" in name and "verifiable" in name:
        base = "draft-ietf-oauth-sd-jwt-vc"
    else:
        return None, None

    return _ietf_datatracker_fetch_latest_revision(base)

def discover_ietf_draft_from_name(spec_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Stable/Draft 링크가 N/A인 IETF 행을 위한 보수적 discovery:
    1) datatracker 공식 검색(doc search)에서 draft-ietf-* 후보를 수집
    2) 후보 doc 페이지 제목(title/h1)이 spec_name과 유사(토큰 hit >= 2)할 때만 채택
    3) 채택된 base name에 대해 최신 revision(-NN)으로 확정하여 (draft_version, draft_link) 반환

    원칙:
    - 매칭이 애매하면 절대 채우지 않음(N/A 유지)
    """
    q = (spec_name or "").strip()
    if not q:
        return None, None

    search_url = "https://datatracker.ietf.org/doc/search/?name=" + quote(q)
    try:
        html, final_url = http_get(search_url, return_final_url=True)
    except Exception:
        return None, None

    # 검색 결과에서 draft-ietf-... base 후보 추출
    # - /doc/draft-ietf-foo/ 형태 또는 draft-ietf-foo-12 형태가 섞일 수 있어 둘 다 처리
    candidates: List[str] = []

    # (1) 링크 기반
    soup = soup_from_html(html)
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        u = norm_url(urljoin(final_url, href))
        m = re.search(r"datatracker\.ietf\.org/doc/(draft-ietf-[a-z0-9-]+)/?$", u, re.IGNORECASE)
        if m:
            candidates.append(m.group(1).lower())

    # (2) 텍스트 기반(혹시 링크 구조가 바뀌는 경우)
    m2 = re.findall(r"\b(draft-ietf-[a-z0-9-]+)-\d{1,2}\b", html, re.IGNORECASE)
    candidates.extend([x.lower() for x in m2])

    # 중복 제거
    uniq: List[str] = []
    seen = set()
    for c in candidates:
        c = c.strip().lower()
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(c)

    if not uniq:
        return None, None

    # 후보를 제목 매칭으로 필터링 (보수적으로 hit >= 2)
    best_base = None
    best_score = 0
    for base in uniq[:20]:  # 너무 많은 후보는 제한
        doc_url = f"https://datatracker.ietf.org/doc/{quote(base)}/"
        title = _ietf_title_from_doc_page(doc_url)
        score = _ietf_match_score(spec_name, title)
        logger.debug("[IETF] search-cand base=%s score=%s title=%s", base, score, title[:120])
        if score > best_score:
            best_score = score
            best_base = base

    # 임계치(보수): 2개 이상 토큰이 title과 매칭될 때만 채택
    if not best_base or best_score < 2:
        logger.info("[IETF] search no-confident-match spec_name=%s best_score=%s", spec_name, best_score)
        return None, None

    dv, dl = _ietf_datatracker_fetch_latest_revision(best_base)
    if dv and dl:
        return dv, dl
    return None, None


def parse_oidf_stable_from_spec_url(url: str) -> Optional[str]:
    """
    OIDF stable spec URL에서 "-1_0.html" 같은 버전을 "1.0" 형태로 추출
    """
    u = (url or "")
    m = re.search(r"-(\d+)_(\d+)(?:[^/]*?)\.html?$", u)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


def discover_oidf_draft_from_stable(stable_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    OIDF는 추정 금지:
    - stable(openid.net/specs/...) 문서에서 명시적으로 드러난 draft 링크 중
      파일명에 draft-XX(식별자)가 있는 경우만 채택한다.
    """
    try:
        html, final_url = http_get(stable_url, return_final_url=True)
    except Exception:
        return None, None

    if "openid.net" not in (urlparse(final_url).netloc or ""):
        return None, None

    soup = soup_from_html(html)
    candidates: List[str] = []

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        u = norm_url(urljoin(final_url, href))
        if "openid.net/specs/" in u and re.search(r"draft-\d{1,3}", u, re.IGNORECASE):
            candidates.append(u)

    if not candidates:
        m = re.findall(
            r"https?://[^\"'\s>]+openid\.net/specs/[^\"'\s>]+draft-\d{1,3}[^\"'\s>]*",
            html,
            re.IGNORECASE,
        )
        candidates.extend([norm_url(x) for x in m])

    best = None
    best_n = -1
    for u in candidates:
        mm = re.search(r"draft-(\d{1,3})", u, re.IGNORECASE)
        if not mm:
            continue
        n = int(mm.group(1))
        if n > best_n:
            best_n = n
            best = u

    if not best:
        return None, None

    dv = f"draft-{best_n} (OIDF Draft)"
    return dv, best


def parse_eu_stable_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    p = urlparse(url)
    path = p.path or ""
    m = re.search(r"/(\d+\.\d+\.\d+)/", path)
    if m:
        return m.group(1)
    return None


def normalize_final_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        _, final_url = http_get(url, return_final_url=True)
        return None, final_url
    except Exception:
        return None, None


def discover_eudi_arf_latest_stable(current_stable_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    EU(EUDI ARF) Stable 링크가 구버전이어도, eudi.dev/latest/... 를 통해 최신 버전을 찾아
    버전 고정 URL로 확정한다.

    반환: (stable_version, stable_link)
    """
    if not current_stable_url:
        return None, None

    cur = norm_url(current_stable_url)
    p = urlparse(cur)
    if "eudi.dev" not in (p.netloc or "") and "github.io" not in (p.netloc or ""):
        # eudi.dev or eu-digital-identity-wallet.github.io 모두 가능
        return None, None

    # latest URL 강제
    path = p.path or ""
    path2 = re.sub(r"^/(\d+\.\d+\.\d+)/", "/latest/", path)
    if not path2.startswith("/latest/"):
        path2 = "/latest/architecture-and-reference-framework-main/"

    latest_url = urlunparse(p._replace(path=path2, params="", query="", fragment=""))

    try:
        html, latest_final = http_get(latest_url, return_final_url=True)
    except Exception:
        # latest 실패 -> 기존 링크 final_url 정규화 + URL에서 버전 파싱
        try:
            _, final_url = http_get(cur, return_final_url=True)
            return parse_eu_stable_from_url(final_url) or parse_eu_stable_from_url(cur), final_url
        except Exception:
            return None, None

    # 페이지에서 changelog 버전 파싱 ("Change Log v2.7.3")
    m = re.search(r"\bChange\s+Log\s+v(\d+\.\d+\.\d+)\b", html, re.IGNORECASE)
    ver = m.group(1) if m else None
    if not ver:
        ver = parse_eu_stable_from_url(latest_final) or parse_eu_stable_from_url(cur)

    if not ver:
        # 버전 확보 실패 -> 링크만 최신으로
        return None, latest_final

    # 버전 고정 URL 구성 (latest_final path를 버전 경로로 치환)
    latest_parsed = urlparse(latest_final)
    fixed_path = re.sub(r"^/latest/", f"/{ver}/", (latest_parsed.path or "/latest/architecture-and-reference-framework-main/"))
    fixed_url = urlunparse(latest_parsed._replace(path=fixed_path, params="", query="", fragment=""))

    try:
        _, fixed_final = http_get(fixed_url, return_final_url=True)
        return ver, fixed_final
    except Exception:
        return ver, latest_final


# -------------------------
# Routing
# -------------------------

def compute_update_for_row(org: str, spec_name: str, stable_link: str, draft_link: str) -> RowUpdate:
    org = (org or "").strip()
    spec_name = (spec_name or "").strip()

    stable_link_n = norm_na(norm_url(stable_link))
    draft_link_n = norm_na(norm_url(draft_link))

    upd = RowUpdate()

    # ---- HL(AnonCreds): Stable은 없고 Draft만 존재하는 케이스 처리 ----
    if org == "HL" and not is_na(stable_link_n):
        try:
            # stable 링크는 final_url로 정규화
            _, final_stable = normalize_final_url(stable_link_n)
            final_stable = final_stable or stable_link_n

            # AnonCreds spec 페이지면, 해당 페이지를 Draft로 간주하고 식별자 확보 시에만 반영
            if re.search(r"\banoncreds\b", spec_name, re.IGNORECASE) or re.search(
                r"(anoncreds\.github\.io/anoncreds-spec|hyperledger\.github\.io/anoncreds-spec)",
                final_stable,
                re.IGNORECASE,
            ):
                dv = parse_hl_anoncreds_draft(final_stable)
                if dv and has_identifier(dv):
                    upd.draft_version = dv
                    upd.draft_link = final_stable

            # stable link는 기존 정책대로 "정규화만" (stable version은 채우지 않음)
            upd.stable_link = final_stable

        except Exception:
            logger.warning("[ROW] HL(AnonCreds) parse failed org=%s name=%s\n%s",
                           org, spec_name, traceback.format_exc())
        return upd

    # ---- ISO: stable에서 next draft 링크를 항상 최신화 ----
    if org == "ISO" and not is_na(stable_link_n) and "iso.org/standard/" in stable_link_n:
        try:
            sv, sl = parse_iso_stable(stable_link_n, spec_name)
            if sl:
                upd.stable_link = sl
            if sv:
                upd.stable_version = sv

            latest_draft_link = discover_iso_next_draft_from_stable(sl or stable_link_n)
            if latest_draft_link:
                upd.draft_link = latest_draft_link
                dv, dl2 = parse_iso_draft(latest_draft_link)
                if dl2:
                    upd.draft_link = dl2
                if dv:
                    upd.draft_version = dv
            else:
                if not is_na(draft_link_n):
                    dv, dl2 = parse_iso_draft(draft_link_n)
                    if dl2:
                        upd.draft_link = dl2
                    if dv:
                        upd.draft_version = dv

        except Exception:
            logger.warning("[ROW] ISO parse failed org=%s name=%s\n%s",
                           org, spec_name, traceback.format_exc())

        return upd

    # ---- W3C: stable version 채움 + draft_link 비어도 stable(TR)에서 Editor’s Draft 탐색 ----
    if org == "W3C" and not is_na(stable_link_n):
        try:
            sv, sl = parse_w3c_stable(stable_link_n)
            if sl:
                upd.stable_link = sl
            if sv:
                upd.stable_version = sv

            if is_na(draft_link_n):
                dv, dl = discover_w3c_draft_from_stable(sl or stable_link_n)
                if dl and dv:
                    upd.draft_link = dl
                    upd.draft_version = dv
            else:
                dv = parse_w3c_draft_version(draft_link_n)
                if dv and has_identifier(dv):
                    upd.draft_version = dv
        except Exception:
            logger.warning("[ROW] W3C discovery failed org=%s name=%s\n%s",
                           org, spec_name, traceback.format_exc())
        return upd

    # ---- IETF: stable RFC version 채움 + draft discovery ----
    if org == "IETF":
        try:
            # (1) Stable RFC 처리
            if not is_na(stable_link_n):
                _, final_stable = normalize_final_url(stable_link_n)
                if final_stable:
                    upd.stable_link = final_stable

                sv = parse_ietf_stable_from_rfc_url(final_stable or stable_link_n)
                if sv:
                    upd.stable_version = sv

            # (2) Draft discovery
            if is_na(draft_link_n):
                # 2-A: SD-JWT VC deterministic 특례 (OAuth WG)
                dv, dl = discover_ietf_draft_deterministic(spec_name)
                if dv and dl:
                    upd.draft_version = dv
                    upd.draft_link = dl
                else:
                    # 2-B: 기존 보수적 검색 fallback
                    base = _ietf_extract_draft_id_from_text(spec_name)
                    if base:
                        dv, dl = _ietf_datatracker_fetch_latest_revision(base)
                        if dv and dl:
                            upd.draft_version = dv
                            upd.draft_link = dl
                    else:
                        dv, dl = discover_ietf_draft_from_name(spec_name)
                        if dv and dl:
                            upd.draft_version = dv
                            upd.draft_link = dl

        except Exception:
            logger.warning("[ROW] IETF discovery failed org=%s name=%s\n%s",
                        org, spec_name, traceback.format_exc())
        return upd


    # ---- OIDF: stable version 채움 + stable 페이지에 명시된 draft 링크가 있을 때만 ----
    if org == "OIDF" and not is_na(stable_link_n):
        try:
            _, final_stable = normalize_final_url(stable_link_n)
            if final_stable:
                upd.stable_link = final_stable

            sv = parse_oidf_stable_from_spec_url(final_stable or stable_link_n)
            if sv:
                upd.stable_version = sv

            if is_na(draft_link_n):
                dv, dl = discover_oidf_draft_from_stable(final_stable or stable_link_n)
                if dv and dl:
                    upd.draft_version = dv
                    upd.draft_link = dl
        except Exception:
            logger.warning("[ROW] OIDF discovery failed org=%s name=%s\n%s",
                           org, spec_name, traceback.format_exc())
        return upd

    # ---- EU: Draft는 기본 N/A 유지, Stable은 latest 기반으로 최신 버전/링크로 고정 ----
    if org == "EU" and not is_na(stable_link_n):
        try:
            ver, link = discover_eudi_arf_latest_stable(stable_link_n)
            if link:
                upd.stable_link = link
            if ver:
                upd.stable_version = ver
        except Exception:
            logger.warning("[ROW] EU latest discovery failed org=%s name=%s\n%s",
                           org, spec_name, traceback.format_exc())
        return upd

    # ---- HL 및 기타: draft discovery 하지 않음. stable 링크 final_url 정규화 정도만(옵션) ----
    if not is_na(stable_link_n):
        try:
            _, final_stable = normalize_final_url(stable_link_n)
            if final_stable:
                upd.stable_link = final_stable
        except Exception:
            pass

    return upd


# -------------------------
# Validator / Finalizer
# -------------------------

def validate_and_finalize(existing: Dict[str, str], upd: RowUpdate, org: str) -> RowUpdate:
    cur_stable_v = norm_na(existing.get("Stable Version"))
    cur_stable_l = norm_na(existing.get("Stable Version Link"))
    cur_draft_v = norm_na(existing.get("Draft Version"))
    cur_draft_l = norm_na(existing.get("Draft Version Link"))

    cand_stable_v = norm_na(upd.stable_version) if upd.stable_version is not None else cur_stable_v
    cand_stable_l = norm_na(upd.stable_link) if upd.stable_link is not None else cur_stable_l
    cand_draft_v = norm_na(upd.draft_version) if upd.draft_version is not None else cur_draft_v
    cand_draft_l = norm_na(upd.draft_link) if upd.draft_link is not None else cur_draft_l

    new_stable_l = choose_link_seed_protected(cur_stable_l, cand_stable_l)

    # ISO의 Draft Link는 seed-protect가 아니라 "최신 discovery 우선"
    if org == "ISO":
        new_draft_l = cand_draft_l if not is_na(cand_draft_l) else cur_draft_l
    else:
        new_draft_l = choose_link_seed_protected(cur_draft_l, cand_draft_l)

    new_stable_v = choose_value_no_degrade(cur_stable_v, cand_stable_v)
    new_draft_v = choose_value_no_degrade(cur_draft_v, cand_draft_v)

    if is_na(new_stable_l):
        new_stable_v = "N/A"

    if is_na(new_draft_l):
        new_draft_v = "N/A"
    else:
        # draft 링크가 있어도 식별자 없으면 Draft 자체 인정하지 않음 → 둘 다 N/A
        # (OIDF draft-XX는 has_identifier로 잡히지 않으니 OIDF는 별도 허용)
        if org == "OIDF":
            ok = bool(re.search(r"\bdraft-\d{1,3}\b", new_draft_v, re.IGNORECASE)) or has_identifier(new_draft_v)
            if not ok:
                new_draft_v = "N/A"
                new_draft_l = "N/A"
        else:
            if is_na(new_draft_v) or not has_identifier(new_draft_v):
                new_draft_v = "N/A"
                new_draft_l = "N/A"

    return RowUpdate(
        stable_version=new_stable_v,
        stable_link=new_stable_l,
        draft_version=new_draft_v,
        draft_link=new_draft_l,
    )


# -------------------------
# CSV / README
# -------------------------

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


# -------------------------
# Main
# -------------------------

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

    logger.info("[RUN] rows=%d", len(rows))

    for idx, row in enumerate(rows, start=1):
        org = row.get("단체", "").strip()
        name = row.get("표준명 (항목)", "").strip()

        before_raw = {k: (row.get(k, "") if row.get(k, "") is not None else "") for k in fieldnames}

        stable_link = row.get("Stable Version Link", "")
        draft_link = row.get("Draft Version Link", "")

        # (A) 현재 CSV 값 기준 snapshot/diff
        for link in [stable_link, draft_link]:
            u = norm_na(norm_url(link))
            if not is_na(u):
                try:
                    check_and_record_content_change(u)
                except Exception:
                    logger.warning("[WARN] content snapshot failed url=%s\n%s", u, traceback.format_exc())

        # (B) 업데이트 계산
        upd_raw = compute_update_for_row(org, name, stable_link, draft_link)

        # (C) 같은 run에서 새로 발견된 stable/draft 링크 snapshot 추가(유용)
        try:
            discovered_stable = norm_na(norm_url(upd_raw.stable_link or ""))
            if not is_na(discovered_stable):
                check_and_record_content_change(discovered_stable)
        except Exception:
            logger.warning("[WARN] discovered stable snapshot failed url=%s\n%s",
                           (upd_raw.stable_link or ""), traceback.format_exc())

        try:
            discovered_draft = norm_na(norm_url(upd_raw.draft_link or ""))
            if not is_na(discovered_draft):
                check_and_record_content_change(discovered_draft)
        except Exception:
            logger.warning("[WARN] discovered draft snapshot failed url=%s\n%s",
                           (upd_raw.draft_link or ""), traceback.format_exc())

        # (D) validate/finalize
        upd = validate_and_finalize(before_raw, upd_raw, org)

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

        if diffs:
            changed_any = True
            csv_changed_any = True
            diffs_for_readme.append((org, name, diffs))

    if changed_any:
        if csv_changed_any:
            write_csv_rows(CSV_PATH, fieldnames, rows)
            logger.info("[OK] standards.csv updated rows_changed=%d", len(diffs_for_readme))
        update_readme_changelog(diffs_for_readme, content_changes_for_readme)
    else:
        logger.info("[OK] No changes detected.")

    logger.info("[TREE] LOG_ROOT listing:\n%s", "\n".join(_list_dir_tree(LOG_ROOT, max_lines=250)))
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