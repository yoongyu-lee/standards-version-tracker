# 표준 버전 조사 및 변경 사항 정리 지침 (CSV 실시간 참조 기반)

## 0. 결과 전달 방식 변경(핵심 규칙)
- 이메일 본문에 전체 결과를 모두 적는 방식은 사용하지 않는다(불가능/비효율로 판단).
- 최종 산출물은 "CSV 갱신 커밋"으로 제출한다.
- 이메일은 알림용이며, 결과 확인/반영은 GitHub 저장소의 main 브랜치에서 한다.

## 1. 기준 데이터 (CSV) - Source of Truth
- 조사 대상 및 기존 기준값은 아래 CSV 파일을 항상 실시간으로 읽어 참조한다.
- CSV 파일은 본 작업의 유일한 기준(Source of Truth)이다.
- CSV 파일 경로:
  [https://github.com/yoongyu-lee/standards-version-tracker/blob/main/standards.csv](https://github.com/yoongyu-lee/standards-version-tracker/blob/main/standards.csv)

## 2. 조사 대상 처리 순서 규칙
- 조사 대상 표준은 CSV 파일에 정의된 행 순서 그대로 처리한다.
- CSV에 없는 표준은 임의로 추가하지 않는다.
- CSV의 행(row) 1개 = 표준 1개로 간주한다.

## 3. 조사 항목
CSV에 정의된 각 표준에 대해 아래를 조사한다.
- Stable Version의 최신 상태
- Draft Version의 최신 상태

### 추가 탐색 규칙
- Draft Version Link가 CSV에서 비어있거나 N/A라도, 공식 채널에서 최신 Draft 존재 여부를 반드시 탐색한다.
- W3C 계열 표준은 TR(Stable) 링크 외에 Editor's Draft(w3c.github.io 등) 존재 여부를 추가로 탐색한다.

## 4. 변경 여부 판단 기준
CSV 기준값과 비교하여 아래 중 하나라도 변경되면 변경으로 판단한다.
- 버전 번호
- 문서 상태(Stable / Draft)
- 공식 링크(URL)
- 주요 변경 사항(핵심 스펙 변경, 상태 변경 등)

### 특수 규칙
- CSV에 Draft Version 또는 Draft Link가 비어있더라도,
  공식 채널에서 새 Draft 문서(버전/링크)가 발견되면 변경으로 판단한다.
- Draft 상태 표기는 원문 표기를 우선한다(예: W3C Editor's Draft, IETF Internet-Draft 등).

## 5. 최종 산출물(필수) : main 브랜치에 CSV 커밋
- 조사 결과는 이메일 본문에 나열하지 말고, 반드시 CSV 파일에 반영한다.
- 변경 사항이 있으면 standards.csv를 업데이트한 뒤 main 브랜치에 커밋한다.
- 커밋은 "업데이트된 standards.csv"가 실제 결과를 완전히 대표해야 한다.

### 커밋 메시지 형식
**제목:**
```
chore: update standards.csv (stable/draft versions & links)
```

**본문:** 조사한 변경 내역을 구체적으로 나열
```
변경 사항:
- [표준명]: [구체적인 변경 내용]
  - 기존: [이전 버전/링크]
  - 변경: [새 버전/링크]
- [표준명]: [구체적인 변경 내용]
  - 기존: [이전 상태]
  - 변경: [새 상태]
```

**예시:**
```
chore: update standards.csv (stable/draft versions & links)

변경 사항:
- W3C VC Data Model: Editor's Draft v2.1 링크 추가
  - 기존: Draft Version Link 없음
  - 변경: https://w3c.github.io/vc-data-model/ 추가
  
- W3C VC Data Integrity: Editor's Draft v1.1 링크 추가
  - 기존: Stable Link만 존재
  - 변경: Draft Version "v1.1 (Editor's Draft)", Draft Link "https://w3c.github.io/vc-data-integrity/" 추가
  
- W3C DID: v1.1 Working Draft 추가
  - 기존: v1.0 (19 July 2022), Draft 없음
  - 변경: Draft Version "v1.1 (Working Draft - 8 January 2026)", Draft Link "https://www.w3.org/TR/did-1.1/" 추가
  
- SD-JWT VC: 최신 Internet-Draft 버전 업데이트
  - 기존: draft-ietf-oauth-sd-jwt-vc-10
  - 변경: draft-ietf-oauth-sd-jwt-vc-13 (6 November 2025)
```

### CSV 반영 규칙
- 각 표준 행에 대해 Stable Version / Stable Link / Draft Version / Draft Link를 최신 값으로 갱신한다.
- Draft가 존재하지 않으면 Draft Version/Draft Link는 N/A로 유지한다.
- CSV에 기존에 없던 Draft/Stable 링크를 발견한 경우, 해당 링크를 CSV에 추가한다.
- CSV에 이미 최신 값이 동일하면 파일 변경 없이 커밋하지 않는다.

## 6. 이메일 알림 규칙(최소화)
- 이메일은 "커밋 완료 알림"만 포함한다.
- 이메일 본문에는 아래 2줄만 허용한다(그 외 문장 금지).
  1) 커밋 여부: 커밋함 / 변경 없음(커밋 없음)
  2) 커밋 링크: (가능하면) GitHub 커밋 URL 또는 PR URL / 불가하면 저장소 main 브랜치 안내

## 7. 유의사항
- 로컬 사본/과거 값/추정값 사용 금지. 항상 CSV와 공식 채널을 기준으로 갱신한다.
- CSV 행 순서/표준명은 유지한다(임의 재정렬 금지).
- 형식 깨짐(열 누락, 구분자 오류 등) 없이 CSV 구조를 보존한다.
