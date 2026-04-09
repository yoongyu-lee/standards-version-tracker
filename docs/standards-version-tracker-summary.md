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

1. CSV를 읽습니다.
2. 문서 URL의 본문을 읽어 스냅샷 파일을 저장합니다.
3. 이전 스냅샷 파일과 비교해 diff 파일을 생성합니다.
4. 단체별 규칙으로 Stable/Draft 버전과 링크를 탐색합니다.
5. 기존 값과 새 후보를 비교해 더 적절한 값을 선택합니다.
6. 결과를 `standards.csv`와 `README.md`에 반영합니다.

### 핵심 이해 사항

1. `standards.csv`는 사람이 직접 관리하는 입력 파일이면서 동시에 최종 결과가 저장되는 **기준 데이터**입니다.
2. 실제 버전 판단은 `scripts/update_standards.py`가 담당하며, 단체마다 추출 규칙이 다릅니다.
3. 운영 환경에서는 GitHub Actions가 매일 실행되어 변경 여부를 반영하고, 결과를 메일로 전달합니다.

---

## 2. 리포지토리 구조

```text
standards/
├── README.md
├── standards.csv
├── standards_init.csv
├── scripts/
│   ├── update_standards.py
│   └── requirements.txt
├── .github/workflows/
│   ├── update.yml
│   └── notify-readme-changelog.yml
└── logs/
    ├── snapshots/*.txt
    ├── diffs/*.diff
    └── run-*.log
```

### 주요 파일 설명

| 파일 | 역할 |
|------|------|
| `README.md` | 변경 이력 로그 |
| `standards.csv` | 운영 기준 데이터 |
| `standards_init.csv` | 초기 기준 CSV |
| `scripts/update_standards.py` | 핵심 자동화 스크립트 |
| `scripts/requirements.txt` | 필요 Python 패키지 |
| `.github/workflows/update.yml` | 자동 점검 및 커밋 |
| `.github/workflows/notify-readme-changelog.yml` | 버전 변경 메일 발송 |

---

## 3. CSV 파일 스키마

### 컬럼 구조

| 컬럼명 | 설명 | 예시 |
|--------|------|------|
| `단체` | 표준화 기구 식별자 | `W3C`, `ISO`, `IETF`, `OIDF`, `EU`, `HL` |
| `표준명 (항목)` | 표준 문서 이름 | `VC Data Model`, `RFC 9901` |
| `Stable Version` | 안정판 버전 문자열 | `v1.0`, `RFC 9901`, `2.7.3` |
| `Draft Version` | 초안 버전 문자열 | `v2.1 (2025-10-06 Editor's Draft)` |
| `핵심 변경 내용` | 버전 변경 요약 | `stable N/A -> v1.0` |
| `Stable Version Link` | 안정판 공식 URL | `https://www.w3.org/TR/vc-data-model-2.0/` |
| `Draft Version Link` | 초안 공식 URL | `https://w3c.github.io/vc-data-model/` |

참고: 값이 확인 불가능하거나 해당 없는 경우 `N/A`를 사용합니다.

### Stable Version 부재 시 처리 방식

`Stable Version`이 비어 있어도 바로 오류가 나지는 않습니다. 아래 순서로 처리됩니다.

1. `Stable Version Link`가 있으면 해당 링크를 기준으로 Stable 버전을 자동 추출하려고 시도합니다.
2. 추출에 성공하면 `Stable Version`이 새 값으로 채워집니다.
3. 추출에 실패하면 `Stable Version`은 `N/A`로 유지됩니다.
4. `Stable Version Link` 자체가 `N/A`이면 최종적으로 `Stable Version`도 `N/A`가 됩니다.

즉, `Stable Version`은 초기에는 비어 있어도 되지만, 실제 값으로 갱신되려면 신뢰할 수 있는 Stable 링크 또는 단체별 추출 규칙이 필요합니다.

### 초기 CSV 세팅 가이드

새로운 표준 문서를 추적 대상에 추가하려면 `standards.csv`에 행을 하나 추가하면 됩니다.

| 컬럼 | 필수 여부 | 초기값 가이드 |
|------|-----------|---------------|
| `단체` | ✅ 필수 | `W3C`, `ISO`, `IETF`, `OIDF`, `EU`, `HL` 중 선택 |
| `표준명 (항목)` | ✅ 필수 | 표준 문서의 공식 이름 |
| `Stable Version` | 선택 | 모르면 `N/A` |
| `Draft Version` | 선택 | 모르면 `N/A` |
| `핵심 변경 내용` | 선택 | 비워두면 됨 |
| `Stable Version Link` | ⚠️ 사실상 필수 | 가능하면 반드시 입력 |
| `Draft Version Link` | 선택 | 모르면 `N/A` |

### 초기 입력 예시

```csv
단체,표준명 (항목),Stable Version,Draft Version,핵심 변경 내용,Stable Version Link,Draft Version Link
W3C,VC Data Model,N/A,N/A,,https://www.w3.org/TR/vc-data-model-2.0/,N/A
IETF,SD-JWT-based Verifiable Credentials (SD-JWT VC),N/A,N/A,,N/A,N/A
HL,AnonCreds Specification,N/A,N/A,,https://anoncreds.github.io/anoncreds-spec/,N/A
```

위처럼 `단체`, `표준명`, `Stable Version Link` 정도만 입력해도 첫 실행 시 자동으로 값이 채워질 수 있습니다.

참고: IETF는 일부 항목에서 Stable 링크가 없어도 Draft를 찾을 수 있습니다. 예를 들어 표준명에 `SD-JWT`와 `Verifiable`이 함께 포함되면, 결정된 규칙에 따라 Draft를 직접 찾습니다.

---

## 4. 실행 프로세스 (단계별 상세)

### 4.1 로그 환경 준비

- 표준 출력과 파일 로그를 함께 사용합니다.
- `logs/snapshots`, `logs/diffs` 디렉터리가 없으면 자동 생성합니다.

### 4.2 CSV 로드 및 검증

- `standards.csv`를 읽습니다.
- 필요한 컬럼이 모두 있는지 확인합니다.

### 4.3 Stable Version 갱신 절차

Stable Version은 아래 4단계로 갱신됩니다.

1. 기존 `Stable Version`과 `Stable Version Link`를 확인합니다.
2. 단체별 규칙으로 새 후보값을 찾습니다.
3. 기존값과 새 후보를 비교해 더 적절한 값을 선택합니다.
4. 최종값이 바뀌었을 때만 CSV와 README에 반영합니다.

핵심 원칙은 다음과 같습니다.

- 새 후보가 `N/A`이면 기존값을 유지합니다.
- 새 값이 더 좋아야만 갱신됩니다.
- Stable 링크가 없으면 Stable Version도 최종적으로 유지 또는 `N/A` 처리됩니다.

### 4.4 행(row) 단위 처리

각 행은 아래 순서로 처리됩니다.

| 단계 | 설명 |
|------|------|
| **(A) 스냅샷 파일 생성 및 변경 감지** | 현재 문서 본문을 저장하고 이전 스냅샷 파일과 비교 |
| **(B) 버전·링크 후보 산출** | 단체별 규칙으로 새 후보 탐색 |
| **(C) 신규 링크 스냅샷 파일 생성** | 새로 발견한 링크도 같은 실행에서 스냅샷 저장 |
| **(D) 검증·정규화** | 기존값과 후보값 비교 |
| **(E) 행 업데이트** | 최종값 반영 및 `핵심 변경 내용` 갱신 |

### 4.5 값 비교 원칙

버전 선택은 보수적으로 이뤄집니다.

- 새 후보가 `N/A`이면 기존값을 유지합니다.
- 기존값과 후보값이 모두 날짜를 포함하면 더 최신 날짜를 우선합니다.
- 그 외에는 더 구체적인 값을 우선합니다.

#### 예시

| 기존값 | 새 후보값 | 결과 |
|------|-----------|------|
| `N/A` | `v2.0` | 새 후보 채택 |
| `v1.0 (2025-10-06 Editor's Draft)` | `v1.0 (2025-09-01 Editor's Draft)` | 기존값 유지 |
| `v1.0 (2025-10-06 Editor's Draft)` | `v1.0 (2025-11-01 Editor's Draft)` | 새 후보 채택 |
| `v2.0` | `N/A` | 기존값 유지 |

### 4.6 Stable Version 갱신 예시

#### 예시 1: Stable Version이 비어 있고 Stable Link가 있는 경우

- `Stable Version = N/A`
- `Stable Version Link = https://www.w3.org/TR/vc-data-model-2.0/`

결과:

- 스크립트가 페이지를 조회합니다.
- 버전 식별자를 찾으면 `Stable Version`을 채웁니다.

#### 예시 2: Stable Link가 없는 경우

- `Stable Version = N/A`
- `Stable Version Link = N/A`

결과:

- 자동 갱신 근거가 부족합니다.
- `Stable Version`은 계속 `N/A`로 남을 수 있습니다.

---

## 5. 환경변수 설정

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `SVT_DEBUG` | `0` | DEBUG 로그 출력 |
| `SVT_LOG_STDOUT_ONLY` | `0` | 파일 로그 없이 콘솔만 사용 |
| `SVT_LOG_FILE` | 자동 생성 | 로그 파일 경로 직접 지정 |
| `SVT_LOG_ROOT` | `logs/` | 로그 루트 디렉터리 |
| `SVT_SNAPSHOT_DIR` | `logs/snapshots/` | 스냅샷 파일 저장 경로 |
| `SVT_DIFF_DIR` | `logs/diffs/` | diff 파일 저장 경로 |
| `SVT_BASELINE_DIFF` | `0` | 기준 스냅샷에서도 diff 파일 생성 |

---

## 6. 스냅샷 및 변경 감지 메커니즘

> 용어 정리
> - **스냅샷 파일**: 특정 URL의 본문 텍스트를 저장한 기준 파일
> - **diff 파일**: 이전 스냅샷 파일과 현재 스냅샷 파일의 차이만 기록한 파일
> - **기준 스냅샷(baseline)**: 해당 URL에 대해 처음 저장되는 스냅샷 파일

동작 방식은 다음과 같습니다.

1. 링크의 HTML을 가져옵니다.
2. 본문 텍스트를 정리해 스냅샷 파일로 저장합니다.
3. 이전 스냅샷 파일과 비교합니다.
4. 차이가 있으면 `logs/diffs/*.diff` 형식의 diff 파일을 생성합니다.
5. 실행 중 새로 발견된 링크도 같은 실행에서 스냅샷 파일에 포함합니다.

> 스냅샷 파일은 `logs/snapshots/`에 저장되며,
> diff 파일은 `logs/diffs/`에 생성됩니다.

---

## 7. 단체별 버전 추출 및 발견 규칙

스크립트는 `단체` 값에 따라 서로 다른 규칙으로 Stable/Draft 버전과 링크를 탐색합니다.

중요 원칙: **확실한 정보만 사용하고, 품질이 낮은 값으로 기존 값을 덮어쓰지 않습니다.**

### 7.1 W3C

- Stable: TR 페이지에서 버전 번호 또는 날짜를 읽습니다.
  - 여기서 TR은 `Technical Report`의 약자이며, W3C가 표준 문서를 게시하는 공식 문서 페이지를 의미합니다.
  - 예: `https://www.w3.org/TR/vc-data-model-2.0/`
- Draft: Stable 페이지에서 `Editor's Draft` 링크를 찾아 사용합니다.
- Draft 식별자는 제목, 메타데이터, 본문 날짜, HTTP 헤더 등을 바탕으로 찾습니다.

### 7.2 ISO

- Stable: 공식 페이지의 발행일을 기반으로 버전을 구성합니다.
- Draft: 차기 개정판 링크가 있으면 Draft 후보로 사용합니다.
- ISO는 Draft 링크에 대해 최신 발견값 우선 정책을 사용합니다.
- 참고: ISO 문서는 유료 또는 접근 제한이 있는 경우가 있어, 실제 문서 원문 대신 공개적으로 접근 가능한 ISO 소개 페이지(`iso.org/standard/...`)를 링크로 사용하는 경우가 있습니다.
- 따라서 일부 항목에서는 Stable과 Draft가 같은 공개 링크를 사용할 수 있으며, 한 페이지 안에 Stable 정보와 Draft 관련 정보가 함께 있어 두 값이 모두 추출될 수 있습니다.

### 7.3 IETF

- Stable: RFC URL에서 `RFC ####` 형식으로 읽습니다.
- Draft: 결정형 규칙, 표준명 기반 식별, Datatracker 검색 순으로 탐색합니다.
- 애매한 경우에는 Draft를 채우지 않습니다.

### 7.4 OIDF

- Stable: URL 파일명에서 버전을 읽습니다.
- Draft: 문서 안에 명시된 `draft-XX` 링크만 인정합니다.

### 7.5 EU

- Stable: `latest` 페이지에서 최신 버전을 확인한 뒤 고정 URL로 갱신합니다.
- Draft: 기본적으로 `N/A`를 유지합니다.

### 7.6 HL (AnonCreds)

- Stable: 링크 정규화만 수행합니다.
- Draft: 문서 상태 텍스트, 버전 표기, GitHub 커밋 날짜 등을 활용합니다.

### 7.7 기타 단체

- Draft 자동 발견 기능을 제공하지 않습니다.
- Stable 링크의 최종 URL 정리만 수행합니다.

---

## 8. 값 검증 및 정규화 (보수적 병합)

버전/링크 후보를 찾은 뒤, 기존 CSV 값과 비교하여 최종 값을 결정합니다.

### 버전 문자열 선택 원칙

- 새 후보가 `N/A`이면 기존값 유지
- 두 값 모두 날짜를 포함하면 더 최신 날짜 우선
- 그 외에는 더 구체적인 값 우선

### 링크 선택 원칙

- 새 후보가 `N/A`이면 기존 링크 유지
- 새 후보가 있으면 새 링크 채택
- 예외: ISO Draft Link는 최신 발견값 우선

### Draft 무효 처리 기준

- Draft 링크가 있더라도 버전 문자열에 식별자가 없으면 Draft를 무효 처리합니다.
- Stable 링크가 `N/A`이면 Stable Version도 `N/A` 처리합니다.
- OIDF는 `draft-XX` 형식도 유효한 식별자로 인정합니다.

---

## 9. README 변경 로그 업데이트

변경 로그는 두 종류로 구분됩니다.

| 구분 | 형식 | 조건 |
|------|------|------|
| **Version updates** | `- [단체] 표준명: 컬럼명: 이전값 → 새값` | 버전/링크 값이 변경된 경우 |
| **Metadata changes** | `- [단체] 표준명: Draft metadata changed (...)` | 버전 문자열로 승격하지 않는 서버 헤더/보조 메타 정보가 바뀐 경우 |
| **Content diffs** | `<details>` 태그 내 접기 형태 | 문서 본문 변경 시 |

변경 내용은 `README.md`의 `## 변경 내역` 바로 아래에 **최신이 위로** 누적됩니다.

> `핵심 변경 내용`은 CSV 안에서 버전 변화 요약용으로 쓰이고, README는 링크 컬럼까지 포함한 전체 변경 이력을 기록합니다.

### README 예상 출력 예시

아래 예시는 `Version updates`, `Metadata changes`, `Content diffs`를 분리해서 기록하도록 확장했을 때의 예상 형태입니다.

#### 예시 1: 문서 헤더에 명시된 날짜가 바뀌어 Draft Version이 갱신되는 경우

이 경우 본문 문단이 그대로여도, 문서 상단의 `W3C Editor's Draft 09 April 2026` 또는 `<time datetime="2026-04-09">` 같은 명시적 날짜가 바뀌었기 때문에 `Draft Version`을 갱신하는 것이 맞습니다.

```csv
단체,표준명 (항목),Stable Version,Draft Version,핵심 변경 내용,Stable Version Link,Draft Version Link
W3C,Verifiable Credential Data Integrity,v1.0,v1.1 (2026-04-09 Editor's Draft),draft v1.1 (2025-08-14 Editor's Draft) -> v1.1 (2026-04-09 Editor's Draft),https://www.w3.org/TR/vc-data-integrity/,https://w3c.github.io/vc-data-integrity/
```

```md
### 2026-04-09

#### Version updates
- [W3C] Verifiable Credential Data Integrity: Draft Version: v1.1 (2025-08-14 Editor's Draft) → v1.1 (2026-04-09 Editor's Draft)
```

#### 예시 2: 서버 헤더만 바뀌고 문서에 보이는 버전 날짜는 유지되는 경우

이 경우 `Last-Modified` 같은 신호는 바뀌었지만, 문서 안에 사용자에게 보이는 draft 날짜는 그대로이므로 `standards.csv`의 버전 값은 유지하고 `README.md`에만 메타데이터 변경 흔적을 기록합니다.

```csv
단체,표준명 (항목),Stable Version,Draft Version,핵심 변경 내용,Stable Version Link,Draft Version Link
W3C,Verifiable Credential Data Integrity,v1.0,v1.1 (2025-08-14 Editor's Draft),,https://www.w3.org/TR/vc-data-integrity/,https://w3c.github.io/vc-data-integrity/
```

```md
### 2026-04-09

#### Metadata changes
- [W3C] Verifiable Credential Data Integrity: Draft metadata changed (Last-Modified: 2026-04-08 -> 2026-04-09)
```

#### 예시 3: 메타데이터와 본문은 바뀌었지만 버전 값은 그대로인 경우

이 경우 `standards.csv`는 유지되고, `README.md`에만 메타데이터 변경과 본문 diff가 함께 기록됩니다.

```md
### 2026-04-09

#### Metadata changes
- [W3C] Verifiable Credential Data Integrity: Draft metadata changed (Last-Modified: 2026-04-08 -> 2026-04-09)

<details>
<summary>Content diffs (click to expand)</summary>

- [W3C] Verifiable Credential Data Integrity: Draft: content changed (logs/diffs/....diff)

</details>
```

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

이 프로젝트에는 2개의 GitHub Actions 워크플로가 있습니다.

#### `update.yml` — 버전 체크 및 자동 커밋

1. Python 3.11 환경에서 `update_standards.py`를 실행합니다.
2. 이전 스냅샷 파일은 GitHub Actions 캐시에서 복원합니다.
3. 실행 결과 `logs/`는 GitHub Actions 아티팩트로 업로드합니다.
4. `standards.csv`와 `README.md`에 변경이 있으면 자동 커밋합니다.

#### `notify-readme-changelog.yml` — 변경 알림 이메일

1. `README.md`에서 오늘 날짜의 변경 블록을 읽습니다.
2. `Version updates` 항목이 있는지 확인합니다.
3. 실제 버전 변경이 있을 때만 이메일을 발송합니다.
4. 발송 후 빈 커밋으로 기록을 남깁니다.

참고: `Content diffs`만 있고 `Version updates`가 없는 경우에는 메일을 보내지 않습니다.  
이메일은 **버전 변경 알림 전용**입니다.

### GitHub Actions 캐시

`Actions > Caches`에 보이는 `svt-snapshots-...` 항목은 이전 실행의 스냅샷 파일을 다음 실행에서도 재사용하기 위한 저장소입니다.

예시:

```text
svt-snapshots-yoongyu-lee/standards-version-tracker-main-24062817573
```

이 캐시가 있어야 이번 실행과 지난 실행의 본문 차이를 비교할 수 있습니다.

### GitHub Actions 아티팩트

실행 결과 화면의 `svt-logs-...` 항목은 해당 실행에서 생성된 `logs/` 전체를 압축한 결과물입니다.

예시:

```text
svt-logs-24017660143
```

이 안에는 보통 실행 로그, 스냅샷 파일, diff 파일이 포함됩니다.

참고: GitHub Actions 아티팩트는 **다음 실행에서 재사용하지 않습니다.**
아티팩트는 사람이 실행 결과를 내려받아 확인하는 용도이고,
다음 실행이 실제로 다시 사용하는 것은 GitHub Actions 캐시에 저장된 스냅샷 파일입니다.

---

## 11. 산출물 위치

| 산출물 | 경로 | 비고 |
|--------|------|------|
| 실행 로그 | `logs/run-YYYYmmdd-HHMMSS.log` | 파일 로그 비활성화 가능 |
| 스냅샷 파일 | `logs/snapshots/*.txt` | 링크별 텍스트 기준본 |
| Diff 파일 | `logs/diffs/*.diff` | 변경 발생 시에만 생성 |
| 변경 이력 | `README.md`의 `## 변경 내역` 섹션 | 자동 갱신 |

---

## 12. 품질 관리 및 오류 처리

| 항목 | 동작 |
|------|------|
| HTTP 요청 | 최대 3회까지 리다이렉트 추적 |
| 오류 격리 | 한 행에서 실패해도 다음 행 처리 계속 |
| 저장 안정성 | 임시 파일 후 원자적 교체 |
| 파서 폴백 | `lxml` 실패 시 `html.parser` 사용 |
| URL 정규화 | fragment 제거, 상대 경로 정리 |

---

## 13. 운영 중 문제 발생 시 확인 순서

1. GitHub Actions 실행 결과 확인
2. GitHub Actions 아티팩트와 로그 확인
3. `standards.csv` 값과 링크 확인
4. `README.md`에서 실제 버전 변경인지 확인
5. 필요 시 로컬에서 `python scripts/update_standards.py`로 재현

운영상 흔한 원인은 다음과 같습니다.

- 원문 사이트의 HTML 구조 변경
- `standards.csv`의 링크 누락 또는 잘못된 링크
- 단체별 파싱 규칙이 새 페이지 구조를 아직 반영하지 못한 경우
