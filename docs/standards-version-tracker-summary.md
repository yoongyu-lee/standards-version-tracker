# 표준 문서 버전 추적 자동화 가이드

## 목차

- [1. 프로젝트 개요](#1-프로젝트-개요)
- [2. 리포지토리 구조](#2-리포지토리-구조)
- [3. CSV 파일 스키마](#3-csv-파일-스키마)
- [4. 실행 프로세스](#4-실행-프로세스-단계별-상세)
- [5. 환경변수 설정](#5-환경변수-설정)
- [6. 스냅샷 및 변경 감지 메커니즘](#6-스냅샷-및-변경-감지-메커니즘)
- [7. 단체별 버전 추출 및 발견 규칙](#7-단체별-버전-추출-및-발견-규칙)
- [8. 값 검증 및 정규화](#8-값-검증-및-정규화-보수적-병합)
- [9. README 변경 로그 업데이트](#9-readme-변경-로그-업데이트)
- [10. 실행 방법](#10-실행-방법)
- [11. 산출물 위치](#11-산출물-위치)
- [12. 품질 관리 및 오류 처리](#12-품질-관리-및-오류-처리)
- [13. 운영 중 문제 발생 시 확인 순서](#13-운영-중-문제-발생-시-확인-순서)

## 1. 프로젝트 개요

이 프로젝트는 **국제 표준 문서의 버전 변경을 자동으로 추적**하는 도구입니다.

W3C, ISO, IETF, OIDF, EU, Hyperledger(HL) 등 주요 표준화 기구의 문서를 대상으로,
**Stable(안정판)** 과 **Draft(초안)** 의 최신 버전·링크를 주기적으로 확인하여 변경 사항을 기록합니다.

### 프로젝트 필요성

표준 문서는 발행 주체마다 공개 방식과 버전 표기 방식이 달라, 사람이 직접 추적하면 시간이 많이 들고 누락이 생기기 쉽습니다.  
이 프로젝트는 그 수작업을 자동화하여 다음 일을 대신합니다.

- 각 표준 문서의 최신 Stable/Draft 버전과 링크 확인
- 문서 본문 변경 여부 추적
- 변경 이력 누적 및 알림 메일 발송

즉, 이 저장소는 단순 CSV 보관소가 아니라 **"표준 버전 모니터링 파이프라인"** 입니다.

### 입력과 출력

- **입력**: `standards.csv`에 등록된 표준명, 단체, 기존 버전, 공식 링크
- **처리**: 단체별 규칙으로 공식 페이지를 조회하고 버전/링크를 보수적으로 갱신
- **출력**:
  - `standards.csv`: 최신 상태의 표준 메타데이터
  - `README.md`: 날짜별 변경 로그
- `logs/`: 스냅샷 파일, diff 파일, 실행 로그
  - 이메일 알림: 당일 실행 결과 요약

### 핵심 동작 흐름

```
CSV 로드 → 페이지 스냅샷 파일 생성/변경 감지 → 단체별 규칙으로 버전·링크 갱신
→ 값 검증 및 정규화 → CSV·README 업데이트
```

### 핵심 이해 사항

1. `standards.csv`는 사람이 직접 관리하는 입력 파일이면서 동시에 최종 결과가 저장되는 **기준 데이터**입니다.
2. 실제 버전 판단은 `scripts/update_standards.py`가 담당하며, 단체마다 추출 규칙이 다릅니다.
3. 운영 환경에서는 GitHub Actions가 매일 실행되어 변경 여부를 반영하고, 결과를 메일로 전달합니다.

---

## 2. 리포지토리 구조

```
standards/
├── README.md                 ← 변경 이력 로그 (자동 갱신)
├── standards.csv             ← 표준 목록 및 버전 데이터 (Single Source of Truth)
├── standards_init.csv        ← 초기 CSV 백업
├── scripts/
│   ├── update_standards.py   ← 핵심 자동화 스크립트
│   └── requirements.txt      ← Python 패키지 (requests, beautifulsoup4, lxml)
├── .github/workflows/
│   ├── update.yml            ← 버전 체크 + 자동 커밋 워크플로
│   └── notify-readme-changelog.yml  ← 변경 알림 이메일 워크플로
└── logs/                     ← 실행 시 생성되는 산출물
    ├── snapshots/*.txt       ← 페이지 텍스트 스냅샷
    ├── diffs/*.diff          ← 스냅샷 변경 비교 결과
    └── run-*.log             ← 실행 로그
```

### 주요 파일 설명

| 파일 | 역할 |
|------|------|
| `README.md` | 변경 이력 로그. `## 변경 내역` 섹션 아래에 날짜별로 누적 기록됩니다. |
| `standards.csv` | **단일 기준 데이터(Single Source of Truth)**. 추적 대상 표준, 메타데이터, 버전, 링크를 포함합니다. |
| `scripts/update_standards.py` | 핵심 스크립트. CSV를 읽고, 각 행을 처리하여 최신 버전을 갱신합니다. |
| `scripts/requirements.txt` | 필요 패키지: `requests`, `beautifulsoup4`, `lxml` (버전 고정) |

---

## 3. CSV 파일 스키마

### 컬럼 구조

| 컬럼명 | 설명 | 예시 |
|--------|------|------|
| `단체` | 표준화 기구 식별자 | `W3C`, `ISO`, `IETF`, `OIDF`, `EU`, `HL` |
| `표준명 (항목)` | 표준 문서의 이름 | `VC Data Model`, `RFC 9901` |
| `Stable Version` | 안정판 버전 문자열 | `v1.0`, `RFC 9901`, `2.7.3` |
| `Draft Version` | 초안 버전 문자열 | `v2.1 (2025-10-06 Editor's Draft)` |
| `핵심 변경 내용` | 버전 변경 요약 (변경 시에만 기록) | `stable N/A -> v1.0` |
| `Stable Version Link` | 안정판 공식 URL | `https://www.w3.org/TR/vc-data-model-2.0/` |
| `Draft Version Link` | 초안 공식 URL | `https://w3c.github.io/vc-data-model/` |

> [!NOTE]
> 값이 확인 불가능하거나 해당 없는 경우 `N/A`를 사용합니다.

### Stable Version 부재 시 처리 방식

`Stable Version`이 비어 있어도 바로 오류가 나지는 않습니다. 스크립트는 이를 **"아직 확정된 Stable 버전을 모른다"** 는 상태로 간주하고, 아래 순서로 처리합니다.

1. `Stable Version Link`가 있으면 해당 링크를 기준으로 Stable 버전을 자동 추출하려고 시도합니다.
2. 추출에 성공하면 `Stable Version`이 새 값으로 채워집니다.
3. 추출에 실패하면 `Stable Version`은 `N/A`로 유지됩니다.
4. `Stable Version Link` 자체가 `N/A`이면 최종적으로 `Stable Version`도 `N/A`로 정리됩니다.

즉, **Stable Version이 비어 있는 것 자체는 허용되지만, 실제 값으로 갱신되려면 신뢰할 수 있는 Stable 링크 또는 단체별 추출 규칙이 필요합니다.**

### 초기 CSV 세팅 가이드

새로운 표준 문서를 추적 대상에 추가하려면, `standards.csv`에 행을 하나 추가합니다.  
**모든 컬럼을 채울 필요는 없습니다.** 아래 표를 참고하여 최소한의 정보만 입력하면, 나머지는 스크립트가 자동으로 채워줍니다.

| 컬럼 | 필수 여부 | 초기값 가이드 |
|------|-----------|---------------|
| `단체` | ✅ **필수** | 표준화 기구 코드 입력. `W3C`, `ISO`, `IETF`, `OIDF`, `EU`, `HL` 중 선택 |
| `표준명 (항목)` | ✅ **필수** | 표준 문서의 공식 이름 입력. IETF의 경우 `draft-ietf-...` 식별자가 포함되면 Draft 자동 발견에 도움이 됨 |
| `Stable Version` | 선택 | 알고 있으면 입력, 모르면 `N/A` → 스크립트가 링크에서 자동 추출 |
| `Draft Version` | 선택 | 알고 있으면 입력, 모르면 `N/A` → 스크립트가 자동 탐색 |
| `핵심 변경 내용` | 선택 | 비워두면 됨 → 스크립트가 변경 발생 시 자동 기록 |
| `Stable Version Link` | ⚠️ **사실상 필수** | 표준의 공식 URL. 이 링크를 기반으로 버전을 자동 추출하므로, **가능하면 반드시 입력** |
| `Draft Version Link` | 선택 | 알고 있으면 입력, 모르면 `N/A` → 단체에 따라 Stable 페이지에서 자동 발견 가능 |

**실제 초기 CSV 예시** (`standards_init.csv`에서 발췌):

```csv
단체,표준명 (항목),Stable Version,Draft Version,핵심 변경 내용,Stable Version Link,Draft Version Link
W3C,VC Data Model,N/A,N/A,,https://www.w3.org/TR/vc-data-model-2.0/,N/A
IETF,SD-JWT-based Verifiable Credentials (SD-JWT VC),N/A,N/A,,N/A,N/A
HL,AnonCreds Specification,N/A,N/A,,https://anoncreds.github.io/anoncreds-spec/,N/A
```

위 예시처럼 `단체`, `표준명`, `Stable Version Link` 정도만 입력하면,  
스크립트 첫 실행 시 자동으로 버전 정보가 채워집니다.

> [!TIP]
> IETF 표준의 경우, Stable Link(`/doc/rfc####/`)만 있으면 RFC 번호 자동 추출 + Draft 자동 발견까지 수행됩니다.  
> Stable Link조차 없는 경우(위의 SD-JWT VC 예시)에도, 표준명에 `SD-JWT`와 `Verifiable`이 포함되어 있으면 **Deterministic 규칙**으로 Draft를 자동 발견합니다.
>
> **Deterministic 규칙이란?**  
> 일부 IETF 표준은 "이 표준의 Draft 이름은 항상 이것이다"라는 규칙이 코드에 미리 정의되어 있습니다.  
> 예를 들어, 표준명에 `SD-JWT`와 `Verifiable`이 모두 포함되면 → Draft 이름을 `draft-ietf-oauth-sd-jwt-vc`로 확정하고 datatracker에서 최신 리비전(`-13` 등)을 직접 조회합니다.  
> 웹 검색이나 유사도 매칭 없이 **확정된 이름으로 바로 조회**하므로 "Deterministic(결정적)"이라 부릅니다.


---

## 4. 실행 프로세스 (단계별 상세)

### 4.1 로그 환경 준비
- 표준 출력(stdout) 및 파일 로그를 동시에 설정합니다.
- `logs/snapshots`, `logs/diffs` 디렉터리가 없으면 자동 생성합니다.

### 4.2 CSV 로드 및 검증
- `standards.csv`를 읽어들이고, 업데이트 대상 컬럼(`Stable Version`, `Draft Version`, 링크, `핵심 변경 내용`)의 존재 여부를 확인합니다.

### 4.2-1 Stable Version 갱신 절차

Stable Version은 단순히 "웹에서 값을 읽어 와서 덮어쓰는" 방식이 아닙니다. 아래 4단계를 거쳐 **보수적으로** 갱신됩니다.

1. **기존 값 확인**  
   현재 CSV에 들어 있는 `Stable Version`, `Stable Version Link`를 읽습니다.
2. **단체별 규칙으로 후보값 추출**  
   예를 들어 W3C는 TR 페이지의 제목/본문에서 `v2.0` 또는 날짜를 찾고, IETF는 RFC URL에서 `RFC 9901`을 추출합니다.
3. **검증 및 품질 비교**  
   새 후보값이 `N/A`이면 기존값을 유지하고, 둘 다 값이 있으면 더 구체적인 문자열을 선택합니다.
4. **최종 반영**  
   최종값이 기존 CSV와 다를 때만 `standards.csv`, `README.md`, `핵심 변경 내용`에 반영됩니다.

핵심은 다음과 같습니다.

- 새로 찾은 값이 더 좋아야만 갱신됩니다.
- `N/A`가 기존의 좋은 값을 덮어쓰지 않습니다.
- Stable 링크가 없으면 Stable Version도 최종적으로 유지 또는 `N/A` 처리됩니다.

### 4.3 행(row) 단위 처리

각 행에 대해 아래 5단계를 순차적으로 수행합니다:

| 단계 | 설명 |
|------|------|
| **(A) 스냅샷 파일 생성 및 변경 감지** | CSV에 기록된 Stable/Draft 링크의 페이지를 가져와 텍스트 스냅샷 파일 저장, 이전과 비교하여 diff 파일 생성 |
| **(B) 버전·링크 후보 산출** | `단체` 값에 따라 고유 규칙을 적용하여 새 버전/링크 후보를 탐색 |
| **(C) 신규 링크 스냅샷 파일 생성** | 실행 중 새로 발견된 링크도 동일 세션 내에서 즉시 스냅샷 파일에 포함 |
| **(D) 검증·정규화** | 후보값과 기존값을 비교하여 "더 구체적인 값"을 선택 (아래 상세 설명 참고) |
| **(E) 행 업데이트** | 변경된 값이 있으면 해당 행을 갱신하고 `핵심 변경 내용` 컬럼에 변경 이력 기록 |

**실제 메인 루프 코드** (`main()` 함수에서 발췌):

```python
for idx, row in enumerate(rows, start=1):
    org = row.get("단체", "").strip()
    name = row.get("표준명 (항목)", "").strip()

    # 변경 전 값을 백업
    before_raw = {k: (row.get(k, "") ...) for k in fieldnames}

    stable_link = row.get("Stable Version Link", "")
    draft_link = row.get("Draft Version Link", "")

    # (A) 현재 CSV 값 기준 스냅샷 파일/diff 파일
    for link in [stable_link, draft_link]:
        u = norm_na(norm_url(link))
        if not is_na(u):
            check_and_record_content_change(u)

    # (B) 단체별 규칙으로 업데이트 후보 계산
    upd_raw = compute_update_for_row(org, name, stable_link, draft_link)

    # (C) 새로 발견된 링크도 스냅샷 파일 추가
    # ... (discovered_stable, discovered_draft 스냅샷 파일) ...

    # (D) 검증/정규화 — 기존값과 후보값 비교
    upd = validate_and_finalize(before_raw, upd_raw, org)

    # 새 값 반영
    row["Stable Version"] = norm_na(upd.stable_version)
    row["Draft Version"] = norm_na(upd.draft_version)
    # ... (링크도 동일) ...

    # (E) 핵심 변경 내용 기록
    if "핵심 변경 내용" in fieldnames:
        core = compute_core_change(before_raw, row)
        if core is not None:
            row["핵심 변경 내용"] = core
```

#### (D) "더 구체적인 값"이란?

스크립트가 웹에서 새로운 버전 후보를 찾았을 때, 기존 CSV 값과 비교하여 **어느 쪽이 더 정확하고 상세한 정보인지**를 판단합니다.  
이때 각 값에 **"구체성 점수"**를 매기고, 점수가 높은 쪽을 최종 값으로 선택합니다.

> [!IMPORTANT]
> 현재 구현은 기본적으로 **구체성 점수**를 사용하지만,
> **기존값과 새 후보값이 모두 `YYYY-MM-DD` 형식의 날짜를 포함하는 경우에는 날짜의 선후를 먼저 비교합니다.**
> 즉, 두 값 모두 날짜가 있으면 더 최신 날짜를 우선 선택하고,
> 날짜가 같거나 한쪽만 날짜가 있으면 기존의 구체성 점수 규칙으로 판단합니다.

**실제 점수 계산 함수** (`specificity_score`):

```python
def specificity_score(s: str) -> int:
    s = norm_na(s)
    if is_na(s):
        return 0           # "N/A"이면 0점
    score = 0
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):
        score += 50         # 날짜 패턴 → +50점
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s, re.IGNORECASE):
        score += 50         # draft-...-NN 패턴 → +50점
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s, re.IGNORECASE):
        score += 10         # vX.Y 버전 패턴 → +10점
    score += min(len(s), 200) // 20  # 문자열 길이 → 최대 +10점
    return score
```

**실제 비교·선택 함수** (`choose_value_no_degrade`):

```python
def choose_value_no_degrade(current: str, candidate: str) -> str:
    cur = norm_na(current)
    cand = norm_na(candidate)
    if is_na(cand):           # 새 후보가 N/A면 → 기존값 유지 (품질 저하 방지)
        return cur
    if is_na(cur):            # 기존값이 N/A면 → 새 후보 채택
        return cand

    cur_date = extract_iso_date(cur)
    cand_date = extract_iso_date(cand)
    if cur_date and cand_date and cur_date != cand_date:
        return cand if cand_date > cur_date else cur

    # 둘 다 값이 있으면 → 점수가 높은 쪽 선택
    return cand if specificity_score(cand) >= specificity_score(cur) else cur
```

**점수 산정 기준 요약:**

| 값에 포함된 패턴 | 부여 점수 | 예시 |
|-----------------|----------|------|
| `YYYY-MM-DD` 날짜 | +50점 | `2025-10-06` |
| `draft-...-NN` Draft ID | +50점 | `draft-ietf-oauth-sd-jwt-vc-13` |
| `vX.Y` 또는 `vX.Y.Z` 버전 | +10점 | `v1.0`, `v2.1.3` |
| 문자열 길이 | +α점 | 길수록 약간 높음 (최대 +10) |
| `N/A` | 0점 | — |

**구체적인 비교 예시:**

| 기존값 (CSV) | 새 후보값 (웹에서 탐색) | 점수 비교 | 결과 |
|-------------|----------------------|-----------|------|
| `N/A` | `v2.0` | 0점 vs 10점 | ✅ 새 후보 채택 |
| `v1.0 (2025-10-06 Editor's Draft)` | `v1.0 (2025-09-01 Editor's Draft)` | 날짜 우선 비교 | ❌ 기존값 유지 |
| `v1.0 (2025-10-06 Editor's Draft)` | `v1.0 (2025-11-01 Editor's Draft)` | 날짜 우선 비교 | ✅ 새 후보 채택 |
| `v1.0` | `v1.0 (2025-10-06 Editor's Draft)` | 10점 vs 60점+ | ✅ 새 후보 채택 (더 상세) |
| `v2.0` | `N/A` | 10점 vs 0점 | ❌ 기존값 유지 (품질 저하 방지) |
| `RFC 9901` | `RFC 9901` | 동일 | 변경 없음 |

> 핵심: **이미 좋은 값이 있는데 `N/A`로 덮어쓰는 일은 절대 없습니다.**  
> 자세한 검증 규칙은 [8장. 값 검증 및 정규화](#8-값-검증-및-정규화-보수적-병합)를 참고하세요.

#### 구체성 판단 예시: `v1.0 (2025-10-06 Editor's Draft)`

기존 값이 아래와 같다고 가정합니다.

```text
v1.0 (2025-10-06 Editor's Draft)
```

이 값은 이미 날짜와 버전이 함께 들어 있으므로, 현재 로직에서는 비교 우선순위가 다음과 같습니다.

1. 두 값 모두 날짜가 있으면 날짜를 먼저 비교
2. 그 외에는 구체성 점수 비교

| 새 후보값 | 현재 로직의 판단 | 설명 |
|----------|------------------|------|
| `v1.1 (2025-11-01 Editor's Draft)` | 후보 채택 가능 | 버전과 날짜를 모두 포함하고 날짜도 더 최신 |
| `v1.0 (2025-11-01 Editor's Draft)` | 후보 채택 가능 | 같은 형식이며 날짜가 더 최신 |
| `v1.0 (2025-09-01 Editor's Draft)` | 기존값 유지 | 두 값 모두 날짜가 있으므로 더 오래된 날짜는 채택되지 않음 |
| `v1.1` | 기존값 유지 가능성 높음 | 버전만 있고 날짜가 없어 구체성 점수가 더 낮을 수 있음 |
| `N/A` | 기존값 유지 | 품질 저하 방지 정책 적용 |

핵심은, 현재 로직에서 `v1.0 (2025-10-06 Editor's Draft)`보다 확실히 유리하게 평가되는 값은
대체로 `v1.1 (2025-11-01 Editor's Draft)`처럼 **버전과 날짜를 함께 포함한 형태**입니다.
반면 `v1.1`처럼 버전만 있는 값은 실제로 더 최신일 수 있어도, 현재 점수 체계에서는 불리할 수 있습니다.


### 4.4 결과 저장
- 변경 사항이 있으면 `standards.csv`를 저장하고, `README.md`의 `## 변경 내역` 섹션에 날짜별로 기록합니다.
- CSV 저장은 `csv.DictWriter`로 직접 쓰기, README/스냅샷 파일/diff 파일은 **임시 파일→원자적 교체** 방식으로 저장 안정성을 보장합니다.

### 4.5 Stable Version 갱신 예시

#### 예시 1: Stable Version이 비어 있고 Stable Link가 있는 경우

```csv
W3C,VC Data Model,N/A,N/A,,https://www.w3.org/TR/vc-data-model-2.0/,N/A
```

실행 후:

- 스크립트가 W3C TR 페이지를 조회
- 페이지 제목 또는 본문에서 Stable 버전 식별자 추출
- 예: `v2.0` 확인 시 `Stable Version = v2.0` 으로 갱신

#### 예시 2: Stable Version이 이미 있고 새 후보가 더 나쁜 경우

- 기존 CSV 값: `v2.0`
- 새 후보값: `N/A`

결과:

- 기존 `v2.0` 유지
- README에 변경 없음

#### 예시 3: Stable Link가 없어서 갱신할 근거가 없는 경우

- `Stable Version = N/A`
- `Stable Version Link = N/A`

결과:

- 자동 갱신 불가
- `Stable Version`은 계속 `N/A`
- 사람이 공식 Stable 링크를 CSV에 보강해 주는 것이 가장 확실한 해결책

#### 예시 4: 두 값 모두 날짜를 포함하는 경우

- 기존 값: `v1.0 (2025-10-06 Editor's Draft)`
- 새 후보값: `v1.0 (2025-09-01 Editor's Draft)`

현재 로직의 특징:

- 두 값 모두 날짜를 포함하므로 먼저 날짜를 비교합니다.
- `2025-09-01`은 `2025-10-06`보다 오래된 날짜이므로 새 후보는 채택되지 않습니다.
- 결과적으로 기존 값이 유지됩니다.

즉, 현재 구현은 **날짜가 둘 다 있을 때는 날짜 우선**, 그 외에는 **구체성 기반 선택** 로직입니다.

---

## 5. 환경변수 설정

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `SVT_DEBUG` | `0` | `1`로 설정하면 DEBUG 레벨 로그 출력 |
| `SVT_LOG_STDOUT_ONLY` | `0` | `1`로 설정하면 파일 로그를 생성하지 않고 콘솔에만 출력 |
| `SVT_LOG_FILE` | 자동 생성 | 로그 파일 경로 직접 지정 |
| `SVT_LOG_ROOT` | `logs/` | 로그 루트 디렉터리 경로 재정의 |
| `SVT_SNAPSHOT_DIR` | `logs/snapshots/` | 스냅샷 저장 경로 재정의 |
| `SVT_DIFF_DIR` | `logs/diffs/` | diff 저장 경로 재정의 |
| `SVT_BASELINE_DIFF` | `0` | `1`로 설정하면 최초 기준 스냅샷(baseline)에서도 diff 파일 생성 |

> [!TIP]
> 환경변수 값은 `1`, `true`, `TRUE`, `yes`, `YES` 모두 참(true)으로 인식됩니다.

---

## 6. 스냅샷 및 변경 감지 메커니즘

> 용어 정리
> - **스냅샷 파일**: 특정 URL의 본문 텍스트를 저장한 기준 파일
> - **diff 파일**: 이전 스냅샷 파일과 현재 스냅샷 파일의 차이만 기록한 파일
> - **기준 스냅샷(baseline)**: 해당 URL에 대해 처음 저장되는 스냅샷 파일

1. 링크의 HTML 콘텐츠를 가져와 **본문(`<body>`) 텍스트를 줄 단위**로 정리 후 스냅샷 파일로 저장
2. 이전 스냅샷 파일과 비교하여 변경이 있으면 `logs/diffs/*.diff` 형식의 diff 파일을 생성
3. 실행 중 새로 발견된 Stable/Draft 링크도 동일 세션 내에서 즉시 스냅샷 파일에 포함
4. 최초 실행(기준 스냅샷, baseline) 시에는 기본적으로 diff 파일을 생성하지 않으나, `SVT_BASELINE_DIFF=1`이면 생성

**실제 스냅샷 파일/변경 감지 함수** (`check_and_record_content_change`):

```python
def check_and_record_content_change(url: str) -> Tuple[str, Optional[str]]:
    safe = url_to_safe_filename(url)
    snapshot_path = os.path.join(SNAPSHOT_DIR, f"{safe}.txt")

    prev = load_snapshot_lines(snapshot_path)     # 이전 스냅샷 파일 로드
    cur = fetch_page_lines_for_diff(url)          # 현재 페이지 텍스트 가져오기

    if prev == cur:                               # 변경 없음
        return "unchanged", None

    if not prev:                                  # 최초 실행 (기준 스냅샷, baseline)
        save_snapshot_lines(snapshot_path, cur)
        if BASELINE_DIFF:
            diff_rel = _write_diff_file(url, [], cur)
            return "baseline", diff_rel
        return "baseline", None

    # 변경 발생 → diff 파일 생성 + 새 스냅샷 파일 저장
    diff_rel = _write_diff_file(url, prev, cur)
    save_snapshot_lines(snapshot_path, cur)
    return "changed", diff_rel
```

> 스냅샷 파일은 `logs/snapshots/`에 URL을 안전한 파일명으로 변환하여 저장되며,
> diff 파일은 `logs/diffs/`에 `{URL}_{타임스탬프}.diff` 형식으로 생성됩니다.

---

## 7. 단체별 버전 추출 및 발견 규칙

스크립트는 `단체` 컬럼 값에 따라 서로 다른 규칙으로 Stable/Draft 버전과 링크를 탐색합니다.
각 단체의 공식 사이트는 페이지 구조가 다르기 때문에, 단체마다 "어디서 어떤 정보를 읽어올지"를 별도로 정의합니다.

> [!IMPORTANT]
> **핵심 원칙**: "확실한 정보만 사용하고, 품질이 낮은 값으로 덮어쓰지 않는다"

---

### 7.1 W3C

#### Stable Version 추출

스크립트는 W3C TR(Technical Report) 페이지의 HTML을 다운로드한 뒤, 페이지 제목에서 버전 정보를 자동으로 찾아냅니다.

**실제 코드** (`parse_w3c_stable`):

```python
def parse_w3c_stable(url: str) -> Tuple[Optional[str], Optional[str]]:
    html, final_url = http_get(url, return_final_url=True)
    soup = soup_from_html(html)

    # 1순위: <h1> 또는 <title>에서 vX.Y(.Z) 패턴 검색
    h1 = soup.find("h1")
    title = (h1.get_text(" ", strip=True) if h1 else "") or \
            (soup.title.get_text(" ", strip=True) if soup.title else "")
    m = re.search(r"\bv?\d+\.\d+(?:\.\d+)?\b", title, re.IGNORECASE)
    if m:
        v = m.group(0)
        if not v.lower().startswith("v"):
            v = "v" + v
        return v, final_url  # 예: "v2.0"

    # 2순위: 본문에서 YYYY-MM-DD 날짜 검색 (발행일)
    text = soup.get_text("\n", strip=True)
    m2 = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m2:
        return f"{m2.group(1)} (W3C TR)", final_url  # 예: "2025-10-06 (W3C TR)"

    return None, final_url
```

**구체적인 동작:**

1. 페이지의 **`<h1>` 태그**(큰 제목)에서 `vX.Y` 또는 `vX.Y.Z` 형식의 버전 번호를 검색합니다.

   예를 들어, `https://www.w3.org/TR/vc-data-model-2.0/` 페이지의 `<h1>`이 아래와 같다면:
   ```html
   <h1>Verifiable Credentials Data Model v2.0</h1>
   ```
   → 여기서 **`v2.0`** 을 추출하여 Stable Version으로 기록합니다.

2. `<h1>`에 버전 번호가 없으면, **`<title>` 태그**에서도 같은 방식으로 찾습니다.

3. 위에서 모두 찾지 못하면, 페이지 본문 텍스트 전체에서 **`YYYY-MM-DD` 형식의 날짜** (예: `2025-10-06`)를 찾아, `2025-10-06 (W3C TR)` 형식으로 기록합니다. 이때 날짜는 문서의 발행일을 나타냅니다.

#### Draft 발견

Draft란 아직 공식 표준이 되기 전의 작업 문서(**Editor's Draft**)를 말합니다.

**실제 코드** (`discover_w3c_draft_from_stable`):

```python
def discover_w3c_draft_from_stable(stable_url: str):
    html, final_url = http_get(stable_url, return_final_url=True)
    soup = soup_from_html(html)

    # "Editor's Draft" 텍스트가 있는 <a> 태그에서 href를 추출
    ed_href = None
    for a in soup.find_all("a", href=True):
        txt = (a.get_text(" ", strip=True) or "").strip()
        if re.search(r"Editor(?:'|'|)s Draft", txt, re.IGNORECASE):
            ed_href = a["href"].strip()
            break

    # 못 찾으면 w3c.github.io 링크로 fallback
    if not ed_href:
        # ... (본문에서 "Editor's Draft" 텍스트 확인 후 github.io 링크 탐색) ...

    if not ed_href:
        return None, None

    draft_link = norm_url(urljoin(final_url, ed_href))
    dv = parse_w3c_draft_version(draft_link)  # Draft 페이지에서 날짜/버전 추출
    if not dv or not has_identifier(dv):       # 식별자가 없으면 무효
        return None, None

    return dv, draft_link
```

- **Draft 링크가 CSV에 비어 있는 경우**: 스크립트가 Stable 페이지(W3C TR)를 분석하여 "Editor's Draft"라고 쓰인 링크를 자동으로 찾습니다.

  예를 들어 TR 페이지에 아래와 같은 링크가 있다면:
  ```
  Editor's Draft: https://w3c.github.io/vc-data-model/
  ```
  → 이 URL을 Draft Link로 자동 설정합니다.

- **Draft 링크가 이미 있는 경우**: 해당 Draft 페이지에 접속하여 날짜/버전 정보를 추출합니다.
- **식별자(버전 또는 날짜)를 찾지 못하면**: Draft를 기록하지 않습니다 (잘못된 정보를 넣지 않기 위해).

#### Draft 페이지에서 날짜/버전을 찾는 우선순위

Editor's Draft 페이지에 접속한 후, 아래 순서대로 날짜/버전 정보를 탐색합니다.

**실제 코드** (`parse_w3c_draft_version` — 핵심 부분 발췌):

```python
def parse_w3c_draft_version(draft_url: str) -> Optional[str]:
    html, headers = http_get(draft_url, return_headers=True)
    soup = soup_from_html(html)

    # 1순위: h1/title에서 vX.Y(.Z) 버전 추출
    h1txt = soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""
    ver = extract_first(r"\bv([0-9]+(\.[0-9]+){1,2})\b", h1txt, re.IGNORECASE)

    # 2순위: <meta> 태그에서 dcterms.modified 등의 날짜
    dt = None
    meta_keys = {"dcterms.modified", "dcterms.issued", "dc.date", ...}
    for m in soup.find_all("meta"):
        key = (m.get("name") or m.get("property") or "").strip().lower()
        if key in meta_keys:
            dt = extract_first(r"\b(\d{4}-\d{2}-\d{2})\b", m.get("content", ""))
            if dt: break

    # 3순위: <time> 태그의 datetime 속성
    # 4순위: 본문에서 "Last updated", "Modified" 근처의 날짜
    # 5순위: HTTP Last-Modified 헤더
    # ... (순차적으로 시도) ...

    # 최종 조합
    if ver and dt: return f"v{ver} ({dt} Editor's Draft)"
    if dt:         return f"{dt} (Editor's Draft)"
    if ver:        return f"v{ver} (Editor's Draft)"
    return None
```

| 순서 | 어디를 보는가 | 무엇을 찾는가 | 예시 |
|------|-------------|--------------|------|
| 1순위 | 페이지 제목 (`<h1>`, `<title>`) | `v1.1`, `v2.0` 같은 버전 번호 | `<h1>VC Data Model v2.1</h1>` → `v2.1` |
| 2순위 | HTML `<meta>` 태그 | `dcterms.modified` 등의 날짜 | `<meta name="dcterms.modified" content="2025-10-06">` → `2025-10-06` |
| 3순위 | HTML `<time>` 태그 | `datetime` 속성의 날짜 | `<time datetime="2025-10-06">` → `2025-10-06` |
| 4순위 | 본문 텍스트 | "Last updated", "Modified" 근처의 날짜 | `Last updated: 2025-10-06` → `2025-10-06` |
| 5순위 | HTTP 응답 헤더 | `Last-Modified` 헤더 | `Last-Modified: Mon, 06 Oct 2025 ...` → `2025-10-06` |

**최종 기록 형식:**
- 버전 + 날짜 모두 확인됨 → `v2.1 (2025-10-06 Editor's Draft)`
- 날짜만 확인됨 → `2025-10-06 (Editor's Draft)`
- 버전만 확인됨 → `v2.1 (Editor's Draft)`

---

### 7.2 ISO

#### Stable Version 추출

ISO 공식 사이트(예: `https://www.iso.org/standard/69084.html`)에 접속하여, 페이지 내 **"Publication date"** 텍스트 옆에 있는 날짜를 찾습니다.

예를 들어 페이지에 아래와 같이 표시되어 있다면:
```
Publication date: 2021-09
```
→ Stable Version을 `ISO/IEC 18013-5:2021 (ISO Publication: 2021-09)` 형식으로 기록합니다.

#### Draft 발견

ISO 페이지에는 종종 "다음 개정판 작업 중" 같은 항목으로 차기 문서 링크(`/standard/NNNNN.html`)가 걸려 있습니다. 스크립트는 이 링크를 Draft 후보로 활용합니다.

Draft 페이지에서는 `ISO/IEC DIS ...` 형식의 문서 번호와 투표 단계 날짜(`40.20` 단계)를 추출합니다.

> [!NOTE]
> ISO의 Draft Link는 다른 단체와 달리 **"최신 발견값 우선"** 정책을 적용합니다.
> 즉, 새로 발견된 Draft 링크가 있으면 기존 값을 덮어씁니다. 다른 단체는 기존 링크를 보수적으로 유지합니다.

---

### 7.3 IETF

#### Stable Version 추출

**실제 코드** (`parse_ietf_stable_from_rfc_url`):

```python
def parse_ietf_stable_from_rfc_url(url: str) -> Optional[str]:
    u = (url or "").lower()
    m = re.search(r"/rfc(\d+)(?:/|$)", u)         # "/rfc9901/" 패턴
    if m:
        return f"RFC {m.group(1)}"                  # → "RFC 9901"
    m2 = re.search(r"/doc/rfc(\d+)(?:/|$)", u)     # "/doc/rfc9901/" 패턴
    if m2:
        return f"RFC {m2.group(1)}"
    return None
```

IETF의 공식 표준은 **RFC(Request for Comments)** 문서입니다.  
URL 경로에 `/rfc####` 또는 `/doc/rfc####` 패턴이 있으면 자동으로 `RFC ####` 형식으로 변환합니다.

예: `https://datatracker.ietf.org/doc/rfc9901/` → Stable Version = **`RFC 9901`**

#### Draft 발견

IETF는 Draft를 찾을 때 **여러 단계**를 거치며, **확실한 경우에만** 결과를 채택합니다.

**실제 라우팅 코드** (`compute_update_for_row` — IETF 부분 발췌):

```python
if org == "IETF":
    # (1) Stable RFC 처리
    if not is_na(stable_link_n):
        sv = parse_ietf_stable_from_rfc_url(final_stable or stable_link_n)

    # (2) Draft discovery — 3단계
    if is_na(draft_link_n):
        # 2-A: Deterministic 특례 (SD-JWT VC 등)
        dv, dl = discover_ietf_draft_deterministic(spec_name)
        if not (dv and dl):
            # 2-B: 표준명에서 draft-id 추출
            base = _ietf_extract_draft_id_from_text(spec_name)
            if base:
                dv, dl = _ietf_datatracker_fetch_latest_revision(base)
            else:
                # 2-C: Datatracker 공식 검색 (최후 수단)
                dv, dl = discover_ietf_draft_from_name(spec_name)
```

##### 1단계: 특정 표준 전용 규칙 (Deterministic 특례)

```python
def discover_ietf_draft_deterministic(spec_name: str):
    name = (spec_name or "").lower()
    # "SD-JWT"와 "verifiable"이 모두 포함되면 → 확정된 Draft ID로 직접 조회
    if "sd-jwt" in name and "verifiable" in name:
        base = "draft-ietf-oauth-sd-jwt-vc"
    else:
        return None, None
    return _ietf_datatracker_fetch_latest_revision(base)
```

예시: CSV의 표준명이 `SD-JWT-based Verifiable Credentials (SD-JWT VC)`인 경우  
→ IETF datatracker에서 `draft-ietf-oauth-sd-jwt-vc`를 직접 조회하여 최신 리비전(`-13` 등)을 확인합니다.

##### 2단계: 표준명에서 Draft ID 추출

```python
def _ietf_extract_draft_id_from_text(text: str) -> Optional[str]:
    # "draft-ietf-oauth-v2-1-12" → base name "draft-ietf-oauth-v2-1" 추출
    m = re.search(r"\b(draft-[a-z0-9-]+-\d{1,2})\b", text, re.IGNORECASE)
    if m:
        full = m.group(1)
        base = re.sub(r"-\d{1,2}$", "", full)  # 끝의 리비전 번호 제거
        return base.lower()
    # ...
```

표준명이나 기존 Draft 링크에 `draft-ietf-oauth-v2-1-12` 같은 패턴이 포함되어 있으면,
여기서 base name(`draft-ietf-oauth-v2-1`)을 추출한 뒤 datatracker에서 최신 리비전을 조회합니다.

##### 3단계: Datatracker 공식 검색 (최후 수단)

위 방법이 모두 실패하면, 표준명을 키워드로 IETF datatracker를 검색합니다.

```python
# 토큰 유사도 매칭에 사용되는 불용어(stop words) 목록
stop = {"the", "and", "for", "with", "from", "based",
        "json", "token", "tokens", "verifiable", "credential", "credentials"}

# 매칭 점수 계산
def _ietf_match_score(spec_name: str, title: str) -> int:
    s_toks = _ietf_norm_tokens(spec_name)   # 표준명 토큰화
    t_toks = set(_ietf_norm_tokens(title))  # 문서 제목 토큰화
    hits = sum(1 for tok in set(s_toks) if tok in t_toks)
    return hits

# 임계치: 2개 이상 매칭되어야만 채택
if not best_base or best_score < 2:
    return None, None  # 애매하면 N/A 유지
```

검색 결과에서 `draft-ietf-...` 후보를 수집한 뒤, 각 후보의 **문서 제목**과 CSV의 **표준명**을 비교합니다.

> [!IMPORTANT]
> 매칭이 애매하면 절대 채우지 않습니다 (N/A 유지).  
> 이로 인해 잘못된 Draft가 연결되는 것을 방지합니다.

---

### 7.4 OIDF (OpenID Foundation)

#### Stable Version 추출

OIDF의 표준 문서는 URL에 버전 정보가 포함되어 있습니다.

예를 들어:
- `https://openid.net/specs/openid-4-verifiable-credential-issuance-1_0.html`
  - 파일명의 `-1_0.html` 부분에서 → Stable Version = **`1.0`** 추출

#### Draft 발견

스크립트는 Stable 문서(`openid.net/specs/...`) 페이지의 HTML을 분석하여,
**문서 안에 직접 걸려 있는 `draft-XX` 형태의 링크**만을 Draft로 채택합니다.

예를 들어, Stable 문서 본문에 아래와 같은 링크가 있다면:
```html
<a href="https://openid.net/specs/openid-4-vci-draft-15.html">draft-15</a>
```
→ Draft Version = `draft-15 (OIDF Draft)`, Draft Link = 해당 URL

여러 `draft-XX` 링크가 있을 경우 **번호가 가장 큰 것**(=최신)을 선택합니다.

> [!NOTE]
> OIDF는 다른 단체와 달리, `draft-XX` 형식 자체를 유효한 버전 식별자로 인정합니다.
> 다른 단체에서는 `v1.0`이나 `YYYY-MM-DD` 같은 더 구체적인 식별자가 필요합니다.

---

### 7.5 EU (EUDI ARF)

#### Stable Version 추출

EU의 EUDI ARF 문서는 `.../latest/...` 형태의 URL이 항상 최신 버전을 가리킵니다.

스크립트의 동작:
1. 현재 CSV에 기록된 Stable Link에서 **`.../latest/...` URL을 구성**하여 접속
2. 접속한 페이지에서 `Change Log v2.7.3` 같은 텍스트를 찾아 **최신 버전 번호**를 확보
3. 버전 번호를 사용하여 **고정 URL**(예: `/2.7.3/architecture-and-reference-framework-main/`)을 만들어 Stable Link를 갱신

이렇게 하면 Stable Link가 항상 특정 버전을 가리키게 되어, 나중에 새 버전이 나와도 이전 기록이 유지됩니다.

#### Draft
- **Draft는 기본적으로 `N/A`** 를 유지합니다. (Draft 자동 발견 기능 없음)

---

### 7.6 HL (Hyperledger — AnonCreds)

#### Stable
- Stable 링크는 **최종 URL로 정규화만** 수행합니다 (리다이렉트를 따라가서 최종 URL을 기록).
- Stable Version은 자동으로 채우지 않습니다.

#### Draft 자동 발견

AnonCreds의 경우 Stable 링크(예: `https://anoncreds.github.io/anoncreds-spec/`)가 GitHub Pages에 호스팅된 스펙 문서를 가리킵니다.  
스크립트는 이 페이지를 **Draft 상태의 문서로 간주**하고, 페이지 내에서 버전 식별자를 아래 우선순위로 탐색합니다:

##### 1순위: 명시적 Status 텍스트
페이지에 `Specification Status: v1.0 Draft` 같은 텍스트가 있으면 → **`v1.0 Draft`** 로 기록

##### 2순위: 명시적 버전 토큰
`AnonCreds v1.0` 또는 `Version v1.0` 같은 텍스트가 있으면 → **`v1.0 Draft`** 로 기록

##### 3순위: GitHub 최신 커밋 날짜
위에서 버전을 찾지 못하면, 페이지 안에 있는 **GitHub 저장소 링크**(`github.com/.../anoncreds-spec`)를 찾아서 해당 저장소의 **최신 커밋 날짜**를 조회합니다.  
(`main` 브랜치 → `master` 브랜치 → 기본 브랜치 순으로 시도)

최신 커밋이 `2025-03-15`이면 → **`2025-03-15 Draft`** 로 기록

> [!CAUTION]
> 본문에 나타나는 임의의 날짜(예: 예시 JSON 안의 `"collected_on": "2023-07-15"`)는 Draft 식별자로 사용하지 않습니다.
> 오직 GitHub 커밋 날짜 또는 명시적 버전 표기만 사용합니다.

---

### 7.7 기타 단체

- Draft 자동 발견 기능을 제공하지 않습니다.
- Stable 링크의 최종 URL 정리(리다이렉트를 따라가서 실제 URL 확보)만 수행합니다.

---

## 8. 값 검증 및 정규화 (보수적 병합)

버전/링크 후보를 찾은 뒤, 기존 CSV 값과 비교하여 최종 값을 결정합니다.
**잘못된 값이 들어가는 것을 방지**하기 위해 보수적인 규칙을 적용합니다.

**실제 검증 함수** (`validate_and_finalize`):

```python
def validate_and_finalize(existing, upd, org) -> RowUpdate:
    # 기존 CSV 값 로드
    cur_stable_v = norm_na(existing.get("Stable Version"))
    cur_draft_v  = norm_na(existing.get("Draft Version"))
    cur_stable_l = norm_na(existing.get("Stable Version Link"))
    cur_draft_l  = norm_na(existing.get("Draft Version Link"))

    # 후보값 결정 (새 값이 없으면 기존값 사용)
    cand_stable_v = norm_na(upd.stable_version) if upd.stable_version else cur_stable_v
    cand_draft_v  = norm_na(upd.draft_version)  if upd.draft_version  else cur_draft_v

    # 링크: seed-protected (N/A로 덮어쓰지 않음)
    new_stable_l = choose_link_seed_protected(cur_stable_l, cand_stable_l)
    # ISO만 예외: 최신 발견값 우선
    if org == "ISO":
        new_draft_l = cand_draft_l if not is_na(cand_draft_l) else cur_draft_l
    else:
        new_draft_l = choose_link_seed_protected(cur_draft_l, cand_draft_l)

    # 버전: 구체성 점수로 비교 (품질 저하 방지)
    new_stable_v = choose_value_no_degrade(cur_stable_v, cand_stable_v)
    new_draft_v  = choose_value_no_degrade(cur_draft_v,  cand_draft_v)

    # 링크가 N/A면 버전도 N/A
    if is_na(new_stable_l): new_stable_v = "N/A"
    if is_na(new_draft_l):  new_draft_v  = "N/A"

    # 식별자 없는 Draft 무효 처리 (OIDF의 draft-XX는 예외 허용)
    # ...
```

### 버전 문자열 선택 원칙

새 후보값과 기존값 중 **"구체성 점수"가 더 높은 쪽**을 최종 값으로 선택합니다.
(구체성 점수 함수는 [4.3절](#43-행row-단위-처리)의 `specificity_score` 코드 참고)

예시: 기존값이 `v1.0`(10점), 새 후보가 `v1.0 (2025-10-06 Editor's Draft)`(60점+) → 새 후보가 채택됨

**핵심 규칙**: 새 후보가 `N/A`이면 기존값을 유지합니다. (정보가 "사라지는" 것을 방지)

### 링크 선택 원칙

```python
def choose_link_seed_protected(current: str, candidate: str) -> str:
    cur = norm_na(current)
    cand = norm_na(candidate)
    if is_na(cand):     # 새 후보가 N/A면 → 기존 링크 유지
        return cur
    return cand         # 새 후보가 있으면 → 새 후보 채택
```

- 새 후보가 `N/A`이면 기존 링크를 유지합니다 (**seed-protected** 방식).
- **예외**: ISO Draft Link만 "최신 발견값 우선" 정책을 적용합니다.

### Draft 무효 처리 기준

```python
def has_identifier(s: str) -> bool:
    if re.search(r"\bv?\d+\.\d+(\.\d+)?\b", s):          return True  # v1.0, 2.1.3
    if re.search(r"\b\d{4}-\d{2}-\d{2}\b", s):            return True  # 2025-10-06
    if re.search(r"\bdraft-[a-z0-9-]+-\d{1,2}\b", s):     return True  # draft-ietf-...-13
    if re.search(r"\bISO/IEC\s+DIS\b", s):                return True  # ISO/IEC DIS ...
    return False
```

- Draft 링크가 있더라도 버전 문자열에 **식별자가 전혀 없으면** (예: 단순한 페이지 이름만 있는 경우) Draft 자체를 무효(`N/A`)로 처리합니다.
- Stable 링크가 `N/A`이면 Stable Version도 `N/A`로 처리합니다.
- OIDF는 예외적으로 `draft-XX` 형식도 유효한 식별자로 인정합니다.

---

## 9. README 변경 로그 업데이트

변경 로그는 2종류로 구분됩니다:

| 구분 | 형식 | 조건 |
|------|------|------|
| **Version updates** | `- [단체] 표준명: 컬럼명: 이전값 → 새값` | 버전/링크 값이 변경된 경우 |
| **Content diffs** | `<details>` 태그 내 접기 형태 | 문서 본문 변경 시 |

**변경 감지 코드** (`main()` 함수에서 diffs 수집 부분):

```python
diffs: List[str] = []
for col in ["Stable Version", "Stable Version Link",
            "Draft Version", "Draft Version Link"]:
    b = (before_raw.get(col, "") or "").strip()   # 변경 전
    a = (row.get(col, "") or "").strip()           # 변경 후
    if b != a:
        diffs.append(f"{col}: {b or '(empty)'} → {a}")

if diffs:
    diffs_for_readme.append((org, name, diffs))  # README용으로 수집
```

**README 기록 코드** (`update_readme_changelog` — 핵심 부분 발췌):

```python
def update_readme_changelog(diffs_by_row, content_changes_by_row):
    today = datetime.now(KST).strftime("%Y-%m-%d")

    # Version updates 섹션
    version_lines = []
    for org, name, diffs in diffs_by_row:
        joined = "; ".join(diffs)
        version_lines.append(f"- [{org}] {name}: {joined}")

    # Content diffs 섹션 (<details> 접기 형태)
    content_lines = []
    for org, name, notes in content_changes_by_row:
        joined = "; ".join(notes)
        content_lines.append(f"- [{org}] {name}: {joined}")

    # "## 변경 내역" 섹션 바로 아래에 삽입 (최신이 위)
    block = f"### {today}\n...{version_lines}...{content_lines}..."
    # readme[:after_heading_pos] + block + readme[after_heading_pos:]
```

변경 내용은 `## 변경 내역` 섹션의 바로 아래에 **최신 항목이 위**에 오는 방식으로 누적됩니다.

> **CSV `핵심 변경 내용`과의 차이**: CSV는 `Stable Version`, `Draft Version` 2개 컬럼만 비교하지만, README는 링크 컬럼 2개를 포함한 **4개 컬럼 모두** 비교하여 기록합니다.

---

## 10. 실행 방법

### 로컬 환경 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/update_standards.py
```

### GitHub Actions 자동화 (운영 중)

이 프로젝트에는 2개의 GitHub Actions 워크플로가 설정되어 있습니다:

#### `update.yml` — 버전 체크 및 자동 커밋
- **트리거**: 매일 09:10 KST (cron: `10 0 * * *`) 또는 수동 실행(`workflow_dispatch`)
- **동작**:
  1. Python 3.11 환경에서 `update_standards.py` 실행 (`SVT_BASELINE_DIFF=1`)
  2. 이전 스냅샷 파일은 **GitHub Actions 캐시**에서 복원/저장 (키: `svt-snapshots-*`)
  3. `logs/` 전체를 **GitHub Actions 아티팩트**로 업로드 (14일 보관)
  4. `standards.csv`와 `README.md`에 변경이 있으면 자동 커밋 및 push (`standards-bot` 계정)

#### `notify-readme-changelog.yml` — 변경 알림 이메일
- **트리거**: `update.yml` 워크플로가 성공적으로 완료된 후 자동 실행
- **동작**:
  1. `README.md`에서 오늘 날짜의 변경 블록을 추출
  2. 해당 블록 안의 `Version updates` 항목만 검사
  3. 오늘 이미 이메일을 보냈는지 git log로 확인 (중복 발송 방지)
  4. 실제 버전 변경 항목이 있을 때만 이메일을 발송 (SMTP 설정은 GitHub Secrets 사용)
  5. 발송 완료 후 빈 커밋으로 기록 (`chore: email sent on YYYY-MM-DD`)

> [!NOTE]
> 현재 구현 기준으로는 `Content diffs`만 있고 `Version updates`가 없는 경우에는 메일을 보내지 않습니다.
> 즉, 이 워크플로는 **버전 변경 알림 전용**으로 동작합니다.
> README에는 `Content diffs`가 기록될 수 있지만, 이메일은 **버전/링크 값이 실제로 바뀐 경우에만** 발송됩니다.
> 이는 본문 미세 변경으로 인한 알림 노이즈를 줄이고, 실제 버전 변경 신호에만 집중하기 위한 정책입니다.

### GitHub Actions 캐시

GitHub의 `Actions > Caches`에 보이는 `svt-snapshots-...` 항목은 **이전 실행에서 만든 스냅샷 파일을 다음 실행에서도 재사용하기 위한 GitHub Actions 캐시**입니다.

예시:

```text
svt-snapshots-yoongyu-lee/standards-version-tracker-main-24062817573
```

이 키는 대략 아래 정보를 포함합니다.

- `svt-snapshots`: 스냅샷 캐시라는 의미의 접두사
- `yoongyu-lee/standards-version-tracker`: 저장소 이름
- `main`: 브랜치 이름
- `24062817573`: GitHub Actions 실행의 `run_id`

사용 방식은 다음과 같습니다.

1. `Update standards versions` 실행 시작 시, 가장 최근 스냅샷 파일 캐시를 restore 합니다.
2. 스크립트가 현재 페이지를 읽고 기존 스냅샷 파일과 비교하여 diff 여부를 판단합니다.
3. 실행 종료 시, 이번 실행에서 갱신된 `logs/snapshots/`를 새 캐시로 저장합니다.

즉, 이 캐시는 **"지난번 문서 상태"** 를 다음 실행이 기억하게 해 주는 장치입니다.  
이 캐시가 없으면 본문 diff 비교는 사실상 매번 기준 스냅샷(baseline)처럼 동작하게 됩니다.

### GitHub Actions 아티팩트

GitHub의 워크플로 실행 화면에서 보이는 `Artifacts`의 `svt-logs-24017660143` 같은 항목은 **해당 실행(run)에서 생성된 `logs/` 디렉터리 전체를 압축 보관한 GitHub Actions 아티팩트**입니다.

예시:

```text
svt-logs-24017660143
```

여기서 `24017660143`은 해당 실행의 `run_id`입니다. 이 GitHub Actions 아티팩트 안에는 보통 아래 파일들이 들어 있습니다.

- `logs/run-*.log`: 실행 로그
- `logs/snapshots/*.txt`: 해당 실행 시점의 스냅샷 파일
- `logs/diffs/*.diff`: 본문 변경 diff 파일

사용 목적은 다음과 같습니다.

- 워크플로 실패나 이상 동작 시 근거 자료 확인
- 어떤 URL에서 diff가 발생했는지 추적
- 로컬 환경 없이도 실행 결과를 다운로드해 분석

차이는 명확합니다.

- **GitHub Actions 캐시**: 다음 실행이 재사용하기 위한 내부 상태 저장소
- **GitHub Actions 아티팩트**: 사람이 내려받아 확인하기 위한 실행 결과물

이 프로젝트에서는 둘 다 `logs/snapshots` 또는 `logs/`와 관련이 있지만, 목적은 서로 다릅니다.

---

## 11. 산출물 위치

| 산출물 | 경로 | 비고 |
|--------|------|------|
| 실행 로그 | `logs/run-YYYYmmdd-HHMMSS.log` | 파일 로그 비활성화 가능 |
| 스냅샷 파일 | `logs/snapshots/*.txt` | 링크별 텍스트 스냅샷 파일 |
| Diff 파일 | `logs/diffs/*.diff` | 변경 발생 시에만 생성 |
| 변경 이력 | `README.md`의 `## 변경 내역` 섹션 | 자동 갱신 |

---

## 12. 품질 관리 및 오류 처리

| 항목 | 동작 |
|------|------|
| **HTTP 요청** | 최대 3회까지 리다이렉트 추적. HTML 내부 리다이렉트(meta refresh, JS redirect, canonical link)도 감지 |
| **오류 격리** | 네트워크 오류·파싱 실패 시 해당 행에 대해서만 경고 로그를 남기고 **다음 행 처리를 계속 진행** |
| **저장 안정성** | README, 스냅샷 파일, diff 파일은 임시 파일(`.tmp`)을 먼저 생성 후 `os.replace()`로 원자적 교체 |
| **파서 폴백** | BeautifulSoup 파싱 시 `lxml` 실패 → `html.parser`로 자동 폴백 |
| **URL 정규화** | fragment(`#...`) 제거, `urljoin`을 통한 상대 경로 해석 |

---

## 13. 운영 중 문제 발생 시 확인 순서

문제가 생기면 아래 순서로 확인하는 것이 가장 빠릅니다.

1. **GitHub Actions 실행 결과 확인**
   - `update.yml` 또는 `notify-readme-changelog.yml`가 실패했는지 먼저 봅니다.
2. **GitHub Actions 아티팩트 / 로그 확인**
   - `logs/run-*.log`, `logs/diffs/*.diff`, `logs/snapshots/*.txt`를 확인합니다.
3. **`standards.csv` 값 확인**
   - 링크가 비어 있는지, `단체` 값이 지원 규칙과 맞는지 확인합니다.
4. **README 변경 로그 확인**
   - 실제 값 변경이 있었는지, 단순 본문 diff만 있었는지 확인합니다.
5. **필요 시 로컬 재현**
   - `python scripts/update_standards.py`로 동일 현상을 재현합니다.

운영상 가장 흔한 원인은 아래 3가지입니다.

- 원문 사이트의 HTML 구조 변경
- `standards.csv`의 링크 누락 또는 잘못된 링크
- 단체별 파싱 규칙이 새 페이지 구조를 아직 반영하지 못한 경우
