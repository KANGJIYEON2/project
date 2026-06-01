# 프로젝트 포트폴리오 — 4개 풀스택 AI 서비스 (기획 → 배포 단독 개발)

> FastAPI · Next.js/React · PostgreSQL · OpenAI/Anthropic · Docker + Caddy 로
> **4개 서비스를 기획부터 EC2 운영 배포까지 단독으로** 구축했습니다.
> 각 폴더의 `README.md` + `highlights/` 에 **면접에서 바로 설명할 핵심 코드만** 추려 담았습니다.

---

## 🗂 한눈에 보기

| 프로젝트 | 한 줄 정의 | 핵심 기술 포인트 | 라이브 데모 |
|---|---|---|---|
| **[susemi](./susemi)** | 연말정산 "왜?" 분석 — 자체 세금 산식 + 법령 trace | 정수 소득세 풀산식 · `eval()` 0줄 룰엔진 · LLM 법령→룰 컴파일 · 출처 추적 | [susemi.team-ieum.com](https://susemi.team-ieum.com) |
| **[ehs-compliance-chatbot](./ehs-compliance-chatbot)** | 산업안전(EHS) 위험관리 SaaS — Admin웹 + 작업자 PWA | 멀티테넌트 4-Role · AI 에이전트 4종 · FAISS RAG · Whisper 음성신고 | [safety-ai.team-ieum.com](https://safety-ai.team-ieum.com) |
| **[F2A](./F2A)** | 병원 리뷰 LLM 자동 분류 (category/severity/team) | 구조화 LLM 출력 · PII 마스킹 · Multi-LLM(OpenAI/Claude) · 비용 트래킹 | [f2a.team-ieum.com](https://f2a.team-ieum.com) |
| **[netscope-ai](./netscope-ai)** | 설명가능 로그 진단 — "왜 그렇게 판단했는가" | 룰엔진 R001~R024 · 패턴 학습 L0~L4 · 실시간 SSE · 멀티테넌트 | [netscope-ai.team-ieum.com](https://netscope-ai.team-ieum.com) |

### 데모 계정
| 프로젝트 | 접속 방법 |
|---|---|
| susemi | 로그인 없이 `/wizard` 4단계 바로 체험 |
| ehs | 회원가입(회사 등록) → admin 권한으로 전체 기능 |
| F2A | 대시보드 진입에 API Key 필요 — **데모 시 별도 제공** |
| netscope | `alice@demo.io` / `bob@demo.io` / `carol@demo.io` · PW `Demo1234!` (테넌트별 데이터 분리) |

---

## 🧭 면접관용 빠른 네비게이션 — "이것만 보세요"

각 프로젝트에서 **가장 보여주고 싶은 코드 1~2개**를 골랐습니다.

| 보고 싶은 역량 | 어디를 보면 되나 |
|---|---|
| **정확성이 생명인 도메인 로직** | [`susemi/highlights/tax_calculator.py`](./susemi/highlights/tax_calculator.py) — 정수 한국 소득세 풀 파이프라인 + 단계별 `CalcStep` trace |
| **보안을 고려한 설계** | [`susemi/highlights/rules_engine.py`](./susemi/highlights/rules_engine.py) — `eval()` 없이 Pydantic discriminated-union 으로 룰 평가 |
| **LLM 을 신뢰가능하게 쓰는 법** | [`F2A/highlights/triage.py`](./F2A/highlights/triage.py) — 구조화 출력 + P0 키워드 이중검증, [`F2A/highlights/pii.py`](./F2A/highlights/pii.py) — LLM 전송 전 PII 마스킹 |
| **멀티 LLM 추상화** | [`F2A/highlights/client.py`](./F2A/highlights/client.py) + [`anthropic_client.py`](./F2A/highlights/anthropic_client.py) — OpenAI/Claude 동일 인터페이스 |
| **설명가능 AI(XAI)** | [`netscope-ai/highlights/rule_engine.py`](./netscope-ai/highlights/rule_engine.py) — 룰 ID + 근거 + 점수, [`drain.py`](./netscope-ai/highlights/drain.py) — 온라인 패턴 학습 |
| **실시간 시스템** | [`netscope-ai/highlights/events.py`](./netscope-ai/highlights/events.py) + [`broker.py`](./netscope-ai/highlights/broker.py) — SSE 서버 푸시 |
| **AI 에이전트 아키텍처** | [`ehs.../highlights/base.py`](./ehs-compliance-chatbot/highlights/base.py) + [`incident_agent.py`](./ehs-compliance-chatbot/highlights/incident_agent.py) |
| **멀티테넌트 격리 / RBAC** | [`ehs.../highlights/dependencies.py`](./ehs-compliance-chatbot/highlights/dependencies.py) + [`tbm.py`](./ehs-compliance-chatbot/highlights/tbm.py) |

---

## 🛠 공통 엔지니어링 역량 (4개 프로젝트 전반)

- **LLM 을 프로덕션에서 신뢰가능하게**: 자유 텍스트 파싱 금지 → 항상 JSON 스키마/tool_use 구조화 출력, 룰엔진을 baseline 으로 두고 LLM 은 보조, hallucination 방지(출처/룰ID 만 인용), 토큰·비용 로깅.
- **보안 우선 설계**: `eval()` 미사용, path traversal 화이트리스트, PII 마스킹, JWT/argon2, API Key sha256 해시, 멀티테넌트 cross-tenant 차단.
- **운영 배포**: 4개 서비스를 단일 **Caddy 리버스 프록시**(자동 HTTPS) 뒤에 Docker Compose 로 배포, 공유 네트워크 + 서브도메인 라우팅, EC2 단일 호스트 운영.
- **테스트/검증 습관**: pytest(예: netscope 43, susemi 237), 골든셋, 라우터 통합 테스트, 배포 후 라이브 종단 검증.
- **엔지니어링 성숙도**: 배포 후 코드 리뷰로 **직접 결함을 찾아 수정**한 사례를 각 프로젝트 README 에 정리 (예: netscope 멀티테넌트 PK 충돌, ehs cross-tenant 누수, susemi 세액 이중차감).

---

## 📦 폴더 구조

```
project/
├── README.md                    ← (이 파일) 4개 프로젝트 총정리 · 네비게이션
├── susemi/
│   ├── README.md                ← 프로젝트 요약 · 아키텍처 · 코드 하이라이트 표
│   └── highlights/              ← 대표 소스 코드 발췌 (실제 운영 코드)
├── ehs-compliance-chatbot/
│   ├── README.md
│   └── highlights/
├── F2A/
│   ├── README.md
│   └── highlights/
└── netscope-ai/
    ├── README.md
    └── highlights/
```

> `highlights/` 의 파일은 각 서비스의 실제 운영 코드에서 **면접에서 설명할 핵심만** 발췌한 것입니다.
> 전체 코드·커밋 히스토리는 각 서비스의 개별 레포에 있습니다.
