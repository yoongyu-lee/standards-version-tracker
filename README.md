# Digital Identity Standards Version Tracker

디지털 신원 및 검증 가능 자격증명 관련 표준 버전 추적 레포지토리입니다.

This repository tracks the versions and key changes of digital identity and verifiable credentials standards.

## 표준 목록 (Standards List)

### W3C (World Wide Web Consortium)

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **VC Data Model** | v2.0 (2025) | - | 검증 가능 자격증명의 확장 가능한 데이터 모델 정의. Issuer-Holder-Verifier 3자 생태계 기반 | [v2.0](https://www.w3.org/TR/vc-data-model-2.0/) |
| **Verifiable Credential Data Integrity** | - | Working Draft | 데이터 무결성 보장을 위한 암호화 메커니즘 정의 | [WD](https://www.w3.org/TR/vc-data-integrity/) |
| **Decentralized Identifiers (DIDs)** | v1.0 | v1.1 (2026 WD) | v1.1은 실험 버전으로 프로덕션에는 v1.0 사용 권장. 탈중앙화 식별자 체계 | [v1.0](https://www.w3.org/TR/did-core/) \| [v1.1 Draft](https://www.w3.org/TR/did-1.1/) |

### ISO (International Organization for Standardization)

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **ISO/IEC 18013-5** | 2021년 10월 | Committee Draft | mDL(모바일 운전면허증) 구현 인터페이스 사양. 선택적 정보 공개 기능 | [Stable](https://www.iso.org/standard/69084.html) \| [Draft](https://www.iso.org/standard/91081.html) |
| **ISO/IEC TS 23220-6** | 2025년 10월 | - | 모바일 디바이스 신원 관리 빌딩 블록. Secure area 신뢰성 인증 | [Link](https://www.iso.org/standard/86787.html) |

### OIDF (OpenID Foundation)

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **OAuth 2.0 Framework** | RFC 6749 (2012.10) | - | OAuth 2.0 인증 프레임워크. OAuth 1.0 대체 | [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) |
| **OpenID4VCI** | 1.0 (2025.09) | - | OAuth 2.0 기반 VC 발급 API. authorization_details 확장. eIDAS 2.0 준수 | [Spec](https://openid.net/specs/openid-4-verifiable-credential-issuance-1_0.html) |
| **OpenID4VP** | 1.0 (2025.07) | - | OAuth 2.0 확장 VC 제시 프로토콜. DCQL 지원. 선택적 공개 | [Spec](https://openid.net/specs/openid-4-verifiable-presentations-1_0.html) |

### IETF (Internet Engineering Task Force)

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **SD-JWT** | RFC 9901 (2025.11) | - | JWT 클레임 선택적 공개. Salted hash. SHA-256 기본 해시 | [RFC 9901](https://datatracker.ietf.org/doc/rfc9901/) |
| **SD-JWT VC** | - | draft-13 (2025.11) | SD-JWT 기반 VC. application/dc+sd-jwt. W3C VCDM 비종속 | [Draft](https://datatracker.ietf.org/doc/draft-ietf-oauth-sd-jwt-vc/) |

### EU (European Union)

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **EUDI Wallet ARF** | v1.6 (2025.03) | v2.0 (planned) | v1.5: WSCD 상세, 데이터/신뢰 모델 확장. eIDAS 2.0 준수 | [ARF](https://eu-digital-identity-wallet.github.io/eudi-doc-architecture-and-reference-framework/) |

### Hyperledger

| 표준명 | Stable Version | Draft Version | 핵심 변경 내용 | Links |
|--------|----------------|---------------|------|-------|
| **AnonCreds** | v1.0 | v2.0 (in dev) | ZKP 기반 익명 자격증명. Ledger-agnostic. W3C VCDM 호환 | [v1.0](https://hyperledger.github.io/anoncreds-spec/) |

## 주요 표준 간 관계

```
VC Data Model (W3C)
│
├── Data Integrity (W3C) - 암호화 및 무결성 보장
│
├── SD-JWT VC (IETF) - JWT 기반 구현
│   └── SD-JWT (IETF RFC 9901) - 선택적 공개 메커니즘
│
├── AnonCreds (Hyperledger) - ZKP 기반 프라이버시
│
└── ISO/IEC 18013-5 - mDL 구현

DID Core (W3C) - 탈중앙화 식별자

OpenID4VCI (OIDF) - VC 발급 프로토콜
│
└── OAuth 2.0 (IETF RFC 6749) - 기반 프레임워크

OpenID4VP (OIDF) - VC 제시 프로토콜
│
└── OAuth 2.0 (IETF RFC 6749) - 기반 프레임워크

EUDI Wallet ARF (EU) - 유럽 디지털 지갑 아키텍처
├── OpenID4VCI/VP 참조
├── ISO/IEC 18013-5 참조
└── eIDAS 2.0 규정 준수
```

## 데이터 형식

모든 표준 정보는 `standards.csv` 파일에 저장되어 있습니다.

### CSV 필드

- `단체`: 표준 제정 기관 (W3C, ISO, OIDF, IETF, EU, HL)
- `표준명 (항목)`: 표준의 공식 명칭
- `Stable Version`: 안정 버전 (프로덕션 사용 권장)
- `Draft Version`: 초안/개발 중 버전
- `핵심 변경 내용`: 주요 특징 및 변경사항
- `Stable Version Link`: 안정 버전 문서 링크
- `Draft Version Link`: 초안 버전 문서 링크

## 업데이트 내역

### 2026-01-15
- 모든 표준 초기 버전 정보 입력 완료
- W3C VC Data Model v2.0, DID Core v1.0/v1.1 추가
- IETF SD-JWT RFC 9901, SD-JWT VC draft-13 추가
- OpenID4VCI 1.0, OpenID4VP 1.0 Final Spec 추가
- ISO/IEC 18013-5:2021, ISO/IEC TS 23220-6:2025 추가
- EUDI Wallet ARF v1.5/v1.6 추가
- Hyperledger AnonCreds v1.0/v2.0 추가

## 기여 (Contributing)

표준 정보에 오류가 있거나 업데이트가 필요한 경우 Issue나 Pull Request를 생성해 주세요.

## 라이선스 (License)

MIT License

---

**Last Updated**: 2026-01-15 13:30 KST