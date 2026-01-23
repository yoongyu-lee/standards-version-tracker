# 표준 문서 버전 추적 자동화 가이드

## 프로젝트 개요
이 저장소는 **표준 문서의 안정판(Stable)과 초안(Draft)** 버전 및 링크를 자동으로 확인하고, 변경 내용을 기록하는 스크립트를 제공합니다.  
기준 데이터는 `standards.csv`이며, 스크립트 실행 시 각 항목의 최신 상태를 확인하여 **CSV 파일과 변경 로그(`README.md`)에 반영**합니다.

---

## 리포지토리 구조 및 파일 설명

- `README.md`  
  변경 이력을 기록하는 로그 파일입니다. 스크립트 실행 시 최신 변경 내용이 **"## 변경 내역"** 섹션 바로 아래에 **추가 전용(append-only)** 방식으로 누적됩니다.

- `standards.csv`  
  이 프로젝트의 **단일 기준 데이터(Single Source of Truth)** 입니다.  
  추적 대상 표준 목록과 메타데이터(단체, 표준명, Stable/Draft 버전, 링크 등)를 포함하며, 스크립트가 이 파일을 업데이트합니다.

- `scripts/requirements.txt`  
  필요한 Python 패키지 목록입니다. (예: `requests`, `beautifulsoup4`, `lxml`)

- `scripts/update_standards.py`  
  핵심 자동화 스크립트입니다.  
  주요 실행 흐름은 다음과 같습니다:  
  **CSV 로드 → 페이지 스냅샷 생성/변경 감지 → 버전/링크 갱신(단체별 규칙 적용) → 값 검증 및 정규화 → CSV/README 업데이트**  
  실행 시 `logs/` 디렉터리 하위에 `snapshots/`, `diffs/`, 실행 로그 파일이 생성됩니다(환경변수로 경로 변경 가능).


---

## CSV 파일 형식(스키마)

### 필수 컬럼
- `단체`, `표준명 (항목)`, `Stable Version`, `Draft Version`, `핵심 변경 내용`, `Stable Version Link`, `Draft Version Link`

### 컬럼 설명
- **Stable/Draft Version**  
  버전 문자열 또는 식별자입니다. 예: `v1.0`, `YYYY-MM-DD`, `RFC ####` 등  
  확인이 불가능한 경우 `N/A`를 사용합니다.

- **Stable/Draft Version Link**  
  해당 버전을 확인할 수 있는 공식 링크(정규화된 URL)입니다. 링크가 없는 경우 `N/A`

- **핵심 변경 내용**  
  동일 행에서 **버전 값이 변경된 경우에만** 요약 내용을 기록합니다.  
  예시: `stable N/A -> v1.0; draft N/A -> 2025-01-19 Editor's Draft`

---

## 실행 프로세스 개요

1) **로그 환경 준비**  
   - 표준 출력 및 파일 로그를 설정하고, `logs/snapshots`, `logs/diffs` 디렉터리가 없으면 생성합니다.

2) **CSV 로드 및 검증**  
   - `standards.csv`를 읽어들이고 필수 컬럼의 존재 여부를 확인합니다.

3) **행(row) 단위 처리**  
   - (A) CSV에 기록된 Stable/Draft 링크의 **페이지 스냅샷**을 저장하고 **변경 여부(diff)**를 확인  
   - (B) 단체별 규칙에 따라 새로운 버전/링크 후보를 산출  
   - (C) 실행 중 새로 발견된 링크도 동일 실행 세션 내에서 즉시 스냅샷에 포함  
   - (D) 값 검증 및 정규화를 수행한 후 최종 값 확정  
   - (E) 변경된 값이 있는 경우 해당 행을 업데이트

4) **결과 저장**  
   - 변경 사항이 있으면 `standards.csv`를 저장하고, `README.md`의 "## 변경 내역" 섹션에 날짜별로 기록합니다.

5) **생성 산출물**
   - `logs/snapshots/*.txt` : 각 링크의 텍스트 스냅샷
   - `logs/diffs/*.diff` : 이전/현재 스냅샷 비교 결과 (변경 발생 시에만 생성)
   - `logs/run-YYYYmmdd-HHMMSS.log` : 실행 로그 (환경변수로 비활성화 또는 경로 변경 가능)

---

## 환경변수 설정

- `SVT_DEBUG=1` : 디버그 로그 출력 활성화
- `SVT_LOG_STDOUT_ONLY=1` : 파일 로그를 생성하지 않고 콘솔에만 출력
- `SVT_LOG_FILE` : 로그 파일 경로 직접 지정
- `SVT_LOG_ROOT`, `SVT_SNAPSHOT_DIR`, `SVT_DIFF_DIR` : 로그/스냅샷/diff 경로 재정의
- `SVT_BASELINE_DIFF=1` : 최초 스냅샷에서도 diff 파일 생성

---

## 스냅샷 및 변경 감지 메커니즘

- 링크의 HTML 콘텐츠를 가져와 본문 텍스트를 줄 단위로 정리한 후 스냅샷으로 저장합니다.
- 이전 스냅샷과 비교하여 변경 사항이 있으면 `logs/diffs/*.diff` 파일을 생성합니다.
- 실행 중 새로 발견된 Stable/Draft 링크도 동일 실행 세션 내에서 즉시 스냅샷에 포함됩니다.

---

## 단체별 버전 추출 및 발견 규칙

스크립트는 `단체` 값에 따라 서로 다른 규칙으로 Stable/Draft 버전과 링크를 보완합니다.  
핵심 원칙: **"확실한 정보만 사용하고, 품질이 낮은 값으로 덮어쓰지 않는다"**

### W3C
- **Stable**
  - W3C TR 페이지에서 `vX.Y(.Z)` 또는 `YYYY-MM-DD` 형식을 추출합니다.
- **Draft**
  - Draft 링크가 비어 있으면 TR 페이지에서 **"Editor's Draft" 링크**를 검색합니다.
  - Draft 버전은 **날짜/버전 등의 식별자**가 확인될 때만 기록합니다.
  - Draft 링크가 이미 존재하면 해당 페이지에서 날짜/버전을 추출합니다.

### ISO
- **Stable**
  - ISO 페이지에서 **Publication date(발행일)** 를 찾아 버전 정보를 보완합니다.
- **Draft**
  - Stable 페이지 내에서 차기 문서 링크(`/standard/NNNNN.html`)를 찾아 Draft 후보로 활용합니다.
  - Draft 페이지에서 `ISO/IEC DIS ...` 형식의 식별자와 날짜를 추출합니다.

### IETF
- **Stable**
  - RFC 링크인 경우 `RFC ####` 형식으로 Stable Version을 설정합니다.
- **Draft**
  - **보수적 접근 방식**을 사용합니다.
  - 표준명 또는 기존 Draft 링크에 `draft-...-NN` 형식의 식별자가 있는 경우에만,
    datatracker에서 최신 리비전을 확인하여 반영합니다.

### OIDF
- **Stable**
  - `...-1_0.html` 형식의 URL 패턴에서 `1.0`(또는 팀 규칙에 따라 `v1.0`)을 추출합니다.
- **Draft**
  - Stable 문서에 **명시적으로 기재된 `openid.net/specs/...draft-XX` 링크**가 있는 경우에만 채택합니다.  
    (추정이나 추측으로 생성하지 않습니다)

### EU (EUDI ARF)
- **Draft**는 기본적으로 `N/A`
- **Stable**
  - `.../latest/...` 링크를 통해 최신 버전을 확인합니다.
  - 가능한 경우 `/X.Y.Z/` 형태의 **버전 고정 URL**로 정규화합니다.
  - 페이지 내용에서 `Change Log vX.Y.Z` 형식의 정보도 함께 검색합니다.

### HL 및 기타
- Draft 자동 발견 기능을 제공하지 않습니다.
- Stable 링크의 최종 URL 정리(리다이렉트 반영) 정도만 수행합니다.

---

## 값 검증 및 정규화 (보수적 병합)

- 새로운 후보값(candidate)과 기존값(current)을 비교하여 **더 구체적인 값**을 선택합니다.
- `N/A`로의 "품질 저하"를 방지합니다. (확실한 정보가 없으면 기존값을 유지)
- 링크는 기본적으로 **기존값을 보수적으로 유지(seed-protected)** 합니다.  
  단, **ISO Draft Link**는 "최신 발견값 우선" 정책을 적용합니다.
- Draft 링크가 존재하더라도 버전 문자열에 식별자(버전/날짜/draft-id)가 없으면 Draft를 무효 처리합니다(`N/A`).  
  OIDF는 예외적으로 `draft-XX` 형식도 유효한 식별자로 인정합니다.

---

## README 변경 로그 업데이트

- 각 행에서 변경된 컬럼만 선별하여 다음 형식으로 기록합니다.  
  `- [단체] 표준명: Stable/Draft Version/Link 변경 내용 요약`
- 문서 본문 변경 내역(diff)은 `<details>` 태그를 사용하여 확장 가능한 형태로 준비되어 있습니다(필요 시 활용).

---

## 실행 방법

### 로컬 환경 실행
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/update_standards.py
```

### GitHub Actions 운영 예시
- 스케줄(예: 매일 새벽) 또는 수동 트리거로 `python scripts/update_standards.py` 실행
- 변경 사항이 있으면 자동으로 커밋 및 PR 생성
- 로그/스냅샷/diff는 아티팩트로 업로드 (선택 사항)

> 참고: 현재 저장소에 워크플로 파일이 없다면 `.github/workflows/*.yml` 파일 추가가 필요합니다.

---

## 산출물(아티팩트) 위치

- 실행 로그: `logs/run-YYYYmmdd-HHMMSS.log` (파일 로그 비활성화 가능)
- 스냅샷: `logs/snapshots/*.txt`
- Diff 파일: `logs/diffs/*.diff`
- 변경 이력: `README.md`의 "## 변경 내역" 섹션

---

## 품질 관리 및 오류 처리

- HTTP 요청은 최대 3회까지 리다이렉트를 따라가며, HTML 내부 리다이렉트도 일부 감지합니다.
- 네트워크 오류나 파싱 실패가 발생하더라도 **해당 행에 대해서만 경고 로그를 남기고 다음 행 처리를 계속 진행**합니다.
- 스냅샷/CSV/README 저장 시 임시 파일을 먼저 생성한 후 원자적으로 교체하는 방식으로 저장 안정성을 보장합니다.