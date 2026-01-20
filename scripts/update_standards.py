#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
standards.csv를 Source of Truth로 사용해 Stable/Draft 버전과 링크를 자동 갱신한다.

v1 정책(안전모드):
- CSV에 이미 존재하는 링크(Stable Version Link / Draft Version Link)만 사용해 파싱한다.
- 링크 디스커버리(검색해서 링크 찾기)는 하지 않는다.
- 4개 컬럼만 수정 가능:
  - Stable Version
  - Stable Version Link
  - Draft Version
  - Draft Version Link
- Draft 규칙 강제:
  - Draft Version Link가 N/A/빈값이면 Draft Version도 반드시 N/A
  - Draft Version은 식별자(버전/날짜/draft-id) 중 최소 1개 포함해야 함
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

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
}

# ---------- Utilities ----------

def norm_na(v: Optional[str]) -> str:
    """Normalize N/A-ish values to 'N/A'."""
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

def http_get(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "standards-version-tracker-bot/1.0 (+https://github.com/yoongyu-lee/standards-version-tracker)"
    }
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text

def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")

def extract_first(regex: str, text: str, flags=0) -> Optional[str]:
    m = re.search(regex, text, flags)
    return m.group(1) if m else None

def has_identifier(s: str) -> bool:
    """Draft Version 필수 조건: 버전/날짜/draft-id 중 최소 1개 포함."""
    if not s:
        return False
    # version like v1.2 or 1.2 (we accept both)
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        return True
    # date like 2026-01-20
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        return True
    # IETF draft id
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        return True
    # RFC number (some drafts may reference RFC, but we mainly use for stable)
    return False

def safe_write_text(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

# ---------- Data model ----------

@dataclass
class RowUpdate:
    stable_version: Optional[str] = None
    stable_link: Optional[str] = None
    draft_version: Optional[str] = None
    draft_link: Optional[str] = None

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "Stable Version": self.stable_version,
            "Stable Version Link": self.stable_link,
            "Draft Version": self.draft_version,
            "Draft Version Link": self.draft_link,
        }

# ---------- Parsers (v1: link must already exist) ----------

def parse_w3c_tr_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    W3C TR Stable:
    - URL path often contains version: ...-2.0/
    - Title contains status: Recommendation / Working Draft / Candidate Recommendation etc.
    Output example: v2.0 (Recommendation)
    """
    html = http_get(url)
    soup = soup_from_html(html)
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()

    # status mapping
    status = None
    status_map = {
        "W3C Recommendation": "Recommendation",
        "W3C Proposed Recommendation": "Proposed Recommendation",
        "W3C Candidate Recommendation": "Candidate Recommendation",
        "W3C Working Draft": "Working Draft",
        "W3C Candidate Recommendation Draft": "Candidate Recommendation Draft",
        "W3C First Public Working Draft": "First Public Working Draft",
        "W3C Editor’s Draft": "Editor's Draft",
        "W3C Editors’ Draft": "Editor's Draft",
        "W3C Note": "Note",
    }
    for k, v in status_map.items():
        if k in title:
            status = v
            break

    # try get version from URL first
    ver = extract_first(r"-([0-9]+\.[0-9]+(\.[0-9]+)?)\/?$", url)
    if not ver:
        # try from title/h1 text
        h1 = soup.find("h1")
        h1txt = h1.get_text(" ", strip=True) if h1 else ""
        ver = extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", h1txt, re.IGNORECASE) or \
              extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", title, re.IGNORECASE)

    if ver and status:
        return f"v{ver} ({status})", url
    if ver:
        # status unknown -> keep version only with generic label (but stable should have status; be conservative)
        return None, None
    return None, None

def parse_w3c_ed_draft(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    W3C Editor's Draft (w3c.github.io 등)에서 Draft Version을 '안전하게' 추출.

    목표(오탐 방지):
    - 날짜는 "버전 날짜"로 신뢰 가능한 위치에서만 뽑는다.
      (meta dcterms.modified / article time / respec This version / Last updated 라인 등)
    - 페이지 전체 텍스트에서 '첫 날짜' 같은 위험한 fallback은 사용하지 않는다.
      (copyright, 예시 날짜 등 오탐 방지)

    반환 포맷:
      - vX.Y (YYYY-MM-DD Editor's Draft)  # 둘 다 있으면 최선
      - YYYY-MM-DD (Editor's Draft)       # 날짜만 확보
      - vX.Y (Editor's Draft)             # 버전만 확보(날짜 못 찾으면)
    식별자(버전/날짜) 둘 다 못 찾으면:
      - (None, None)
    """
    html = http_get(url)
    soup = soup_from_html(html)

    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    h1 = soup.find("h1")
    h1txt = h1.get_text(" ", strip=True) if h1 else ""

    # 1) 버전 후보: title/h1에서 vX.Y(.Z)
    ver = (
        extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", h1txt, re.IGNORECASE)
        or extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", title, re.IGNORECASE)
    )

    # 2) 날짜 후보: "신뢰 가능한 위치"에서만 추출
    dt: Optional[str] = None

    # 2-1) meta: dcterms.modified / dcterms.issued / dc.date / last-modified 등
    meta_keys = {
        "dcterms.modified",
        "dcterms.issued",
        "dc.date",
        "dc.modified",
        "last-modified",
    }
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

    # 2-2) <time datetime="YYYY-MM-DD..."> 또는 <time>YYYY-MM-DD</time>
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

    # 2-3) ReSpec/바이크쉐드 계열: "This version:" / "Last updated:" 근처 텍스트에서 날짜 추출
    # (전체 텍스트에서 임의의 날짜를 잡지 않도록 라인 기반으로 제한)
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

    # 3) 반환: 가장 정보가 풍부한 형태 우선
    if ver and dt:
        return f"v{ver} ({dt} Editor's Draft)", url
    if dt:
        return f"{dt} (Editor's Draft)", url
    if ver:
        return f"v{ver} (Editor's Draft)", url

    return None, None

def parse_ietf_draft_from_link(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    IETF draft link:
    - We only accept Internet-Draft id 'draft-...-NN'
    - Version string example: draft-ietf-foo-bar-13 (Internet-Draft)
    """
    draft_id = extract_first(r"\b(draft-[a-z0-9-]+-\d{1,2})\b", url, re.IGNORECASE)
    if not draft_id:
        return None, None
    return f"{draft_id} (Internet-Draft)", url

def parse_rfc_from_link_or_page(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    RFC stable:
    - If URL contains rfcXXXX -> RFC XXXX
    - Else parse page for 'RFC XXXX'
    """
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

def parse_semver_from_url(url: str) -> Optional[str]:
    """
    Extract semver-like X.Y.Z from URL path (EU eudi.dev typically).
    """
    return extract_first(r"/(\d+\.\d+\.\d+)(/|$)", url)

def parse_hl_anoncreds(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Hyperledger AnonCreds spec page:
    - Try to find vX.Y in title/h1
    """
    html = http_get(url)
    soup = soup_from_html(html)
    title = (soup.title.get_text(" ", strip=True) if soup.title else "").strip()
    h1 = soup.find("h1")
    h1txt = h1.get_text(" ", strip=True) if h1 else ""
    ver = extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", h1txt, re.IGNORECASE) or \
          extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", title, re.IGNORECASE)
    if ver:
        return f"v{ver}", url
    return None, None

# ---------- Routing ----------

def compute_update_for_row(org: str, spec_name: str, stable_link: str, draft_link: str) -> RowUpdate:
    org = (org or "").strip()
    stable_link_n = norm_na(stable_link)
    draft_link_n = norm_na(draft_link)

    upd = RowUpdate()

    # Stable parsing if stable link exists
    if not is_na(stable_link_n):
        try:
            if org == "W3C" and "w3.org/TR/" in stable_link_n:
                v, l = parse_w3c_tr_stable(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "IETF":
                # could be rfc-editor or datatracker; parse RFC number if possible
                v, l = parse_rfc_from_link_or_page(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            elif org == "EU":
                ver = parse_semver_from_url(stable_link_n)
                if ver:
                    upd.stable_version, upd.stable_link = f"v{ver}", stable_link_n

            elif org == "HL":
                v, l = parse_hl_anoncreds(stable_link_n)
                if v and l:
                    upd.stable_version, upd.stable_link = v, l

            else:
                # ISO / OIDF / etc: v1에서는 구조가 제각각이라 무리한 파싱 금지
                pass

        except Exception:
            # 네 원칙(추정 금지): 실패 시 아무것도 업데이트하지 않음
            pass

    # Draft parsing if draft link exists; otherwise must be N/A (validator will enforce)
    if not is_na(draft_link_n):
        try:
            if org == "W3C":
                if "w3c.github.io" in draft_link_n:
                    v, l = parse_w3c_ed_draft(draft_link_n)
                    if v and l:
                        upd.draft_version, upd.draft_link = v, l
                elif "w3.org/TR/" in draft_link_n:
                    # TR Draft (WD/CRD etc): try reuse stable parser to get v+status, but label as Draft with identifier
                    v, l = parse_w3c_tr_stable(draft_link_n)
                    if v and l:
                        # v already has status (e.g., Working Draft). As Draft Version we keep it as-is.
                        upd.draft_version, upd.draft_link = v, l

            elif org == "IETF":
                v, l = parse_ietf_draft_from_link(draft_link_n)
                if v and l:
                    upd.draft_version, upd.draft_link = v, l

            else:
                # ISO/OIDF/EU/HL 등은 v1에서 Draft 파싱은 보수적으로(링크 있어도 식별자 못 뽑으면 업데이트 금지)
                # 다만 URL에 버전이 명확히 있으면 처리 가능
                if org == "EU":
                    ver = parse_semver_from_url(draft_link_n)
                    if ver:
                        upd.draft_version, upd.draft_link = f"v{ver} (Draft)", draft_link_n

        except Exception:
            pass

    return upd

# ---------- Validator (enforce your rules) ----------

def validate_and_finalize(existing: Dict[str, str], upd: RowUpdate) -> RowUpdate:
    """
    Enforce strict rules + prevent "degradation" (i.e., do not overwrite a more specific
    existing value with a less specific newly-parsed value).

    Rules enforced:
    - Only finalize values for the 4 allowed columns.
    - Stable:
      - If Stable Link is N/A => Stable Version must be N/A
      - If Stable Version is N/A => Stable Link must be N/A
    - Draft (hard rules):
      - If Draft Link is N/A => Draft Version must be N/A
      - If Draft Link is present, Draft Version must exist and contain an identifier
        (version/date/draft-id). Otherwise set BOTH Draft fields to N/A.
    - Degradation prevention:
      - If an existing value is more specific (e.g., includes a YYYY-MM-DD date or
        draft-...-NN), do NOT replace it with a simpler new value.
      - Links are only replaced if the new link is non-N/A or the existing link is N/A.
    """

    cur_stable_v = norm_na(existing.get("Stable Version"))
    cur_stable_l = norm_na(existing.get("Stable Version Link"))
    cur_draft_v = norm_na(existing.get("Draft Version"))
    cur_draft_l = norm_na(existing.get("Draft Version Link"))

    cand_stable_v = norm_na(upd.stable_version) if upd.stable_version is not None else cur_stable_v
    cand_stable_l = norm_na(upd.stable_link) if upd.stable_link is not None else cur_stable_l
    cand_draft_v = norm_na(upd.draft_version) if upd.draft_version is not None else cur_draft_v
    cand_draft_l = norm_na(upd.draft_link) if upd.draft_link is not None else cur_draft_l

    def specificity_score(s: str) -> int:
        s = norm_na(s)
        if is_na(s):
            return 0
        score = 0
        # Strong identifiers
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
            score += 50
        if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
            score += 50
        # Version token
        if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
            score += 10
        # Non-trivial qualifiers (month names, localized date words)
        if re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", s, re.IGNORECASE):
            score += 5
        if re.search(r"(년|월|일)", s):
            score += 5
        # Slight preference for richer strings (cap so it doesn't dominate)
        score += min(len(s), 200) // 20
        return score

    def choose_value(cur: str, cand: str) -> str:
        """
        Choose candidate only if it is at least as specific as current,
        otherwise keep current (prevents degradation).
        """
        cur_n = norm_na(cur)
        cand_n = norm_na(cand)
        if is_na(cand_n):
            return cur_n
        if is_na(cur_n):
            return cand_n
        return cand_n if specificity_score(cand_n) >= specificity_score(cur_n) else cur_n

    def choose_link(cur: str, cand: str) -> str:
        """
        Replace link only when candidate is non-N/A OR current is N/A.
        Prevents wiping a real link with N/A.
        """
        cur_n = norm_na(cur)
        cand_n = norm_na(cand)
        if is_na(cand_n):
            return cur_n  # never overwrite with N/A
        return cand_n if (not is_na(cand_n) or is_na(cur_n)) else cur_n

    # 1) Apply degradation-safe selection
    new_stable_v = choose_value(cur_stable_v, cand_stable_v)
    new_stable_l = choose_link(cur_stable_l, cand_stable_l)

    new_draft_v = choose_value(cur_draft_v, cand_draft_v)
    new_draft_l = choose_link(cur_draft_l, cand_draft_l)

    # 2) Stable consistency (soft, but enforced)
    if is_na(new_stable_l):
        new_stable_v = "N/A"
    if is_na(new_stable_v):
        new_stable_l = "N/A"

    # 3) Draft hard rules (strict)
    if is_na(new_draft_l):
        new_draft_v = "N/A"
    else:
        # link exists -> version must be valid identifier-bearing string
        if is_na(new_draft_v) or not has_identifier(new_draft_v):
            new_draft_v = "N/A"
            new_draft_l = "N/A"

    return RowUpdate(
        stable_version=new_stable_v,
        stable_link=new_stable_l,
        draft_version=new_draft_v,
        draft_link=new_draft_l,
    )

# ---------- CSV / README Update ----------

def load_csv_rows(path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = []
        for r in reader:
            # keep all original columns; normalize None -> ""
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
        return fieldnames, rows

def write_csv_rows(path: str, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    # Preserve column order exactly as existing file
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

def diff_summary(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    diffs = []
    for col in ["Stable Version", "Stable Version Link", "Draft Version", "Draft Version Link"]:
        b = norm_na(before.get(col))
        a = norm_na(after.get(col))
        if b != a:
            diffs.append(f"{col}: {b} → {a}")
    return diffs

def update_readme_changelog(diffs_by_row: List[Tuple[str, str, List[str]]]) -> None:
    """
    README '## 변경 내역' 바로 아래에 최신 항목을 추가한다.
    형식:
    ### YYYY-MM-DD
    - [단체] 표준명: Stable... / Draft...
    """
    if not diffs_by_row:
        return

    if not os.path.exists(README_PATH):
        return

    readme = open(README_PATH, "r", encoding="utf-8").read()

    heading = "## 변경 내역"
    idx = readme.find(heading)
    if idx == -1:
        # heading 없으면 아무 것도 하지 않음(규칙상 기존 포맷 임의 변경 금지)
        return

    today = datetime.now(KST).strftime("%Y-%m-%d")

    lines = [f"### {today}"]
    for org, name, diffs in diffs_by_row:
        # 간결하게: 버전만 보여주고 싶으면 여기서 요약을 바꿀 수 있음
        joined = "; ".join(diffs)
        lines.append(f"- [{org}] {name}: {joined}")

    block = "\n".join(lines) + "\n\n"

    # Insert right after the heading line (append-only + newest on top)
    # Find end of the heading line
    after_heading_pos = readme.find("\n", idx)
    if after_heading_pos == -1:
        return
    after_heading_pos += 1

    new_readme = readme[:after_heading_pos] + "\n" + block + readme[after_heading_pos:]
    safe_write_text(README_PATH, new_readme)

def main() -> int:
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] standards.csv not found at {CSV_PATH}", file=sys.stderr)
        return 2

    fieldnames, rows = load_csv_rows(CSV_PATH)

    # Validate structure: do not change columns
    missing = [c for c in ALLOWED_UPDATE_COLS if c not in fieldnames]
    if missing:
        print(f"[ERROR] CSV missing expected columns: {missing}", file=sys.stderr)
        return 2

    diffs_for_readme: List[Tuple[str, str, List[str]]] = []
    changed_any = False

    for i, row in enumerate(rows):
        org = row.get("단체", "").strip()
        name = row.get("표준명 (항목)", "").strip()

        before = {k: row.get(k, "") for k in fieldnames}

        stable_link = row.get("Stable Version Link", "")
        draft_link = row.get("Draft Version Link", "")

        upd_raw = compute_update_for_row(org, name, stable_link, draft_link)
        upd = validate_and_finalize(before, upd_raw)

        after = before.copy()
        after["Stable Version"] = upd.stable_version or "N/A"
        after["Stable Version Link"] = upd.stable_link or "N/A"
        after["Draft Version"] = upd.draft_version or "N/A"
        after["Draft Version Link"] = upd.draft_link or "N/A"

        diffs = diff_summary(before, after)
        if diffs:
            changed_any = True
            diffs_for_readme.append((org, name, diffs))
            # apply only allowed columns
            row["Stable Version"] = after["Stable Version"]
            row["Stable Version Link"] = after["Stable Version Link"]
            row["Draft Version"] = after["Draft Version"]
            row["Draft Version Link"] = after["Draft Version Link"]

    if changed_any:
        write_csv_rows(CSV_PATH, fieldnames, rows)
        update_readme_changelog(diffs_for_readme)
        print(f"[OK] Updated standards.csv and README.md with {len(diffs_for_readme)} changed rows.")
    else:
        print("[OK] No changes detected.")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())

def is_more_specific(new: str, old: str) -> bool:
    """
    새 값이 기존 값보다 '덜 구체적'이면 False.
    구체성 기준(간단 규칙):
    - 날짜(YYYY-MM-DD) 포함 > 미포함
    - draft-...-NN 포함 > 미포함
    - 길이가 긴 쪽이 대체로 더 구체(완전한 기준은 아니지만 diff-noise 방지에 유용)
    """
    new = norm_na(new)
    old = norm_na(old)
    if is_na(new):
        return False
    if is_na(old):
        return True

    def score(s: str) -> int:
        sc = 0
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s): sc += 3
        if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.I): sc += 3
        if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.I): sc += 1
        sc += min(len(s), 200) // 20  # 길이 보너스(과도하지 않게)
        return sc

    return score(new) >= score(old)