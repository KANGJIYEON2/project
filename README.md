<div align="center">

# 🛠️ 강지연 · 프로덕트 엔지니어 포트폴리오

### 세무·회계 도메인 × AI 프로덕트 — **6개 서비스를 기획부터 배포까지 단독 개발**

<br>

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
<br>
![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Caddy](https://img.shields.io/badge/Caddy-1F88C0?style=for-the-badge&logo=caddy&logoColor=white)

</div>

---

> 각 폴더의 `README.md` + `highlights/` 에 **면접에서 바로 설명할 핵심 코드만** 추려 담았습니다.
> 전체 코드·커밋 히스토리는 각 서비스의 개별 레포에 있습니다.

<br>

## 💼 도메인 특화 — 세무·회계

> **세무·회계 5년 경력**에서 직접 겪은 문제를 프로덕트로 만든 3종.

| 프로젝트 | 한 줄 정의 | 핵심 기술 | 라이브 |
|:---|:---|:---|:---:|
| 🧾 **[susemi](./susemi)** | 연말정산 **"왜?"** 분석 — 자체 세금 산식 + 법령 trace | 정수 소득세 풀산식 · `eval()` 0줄 룰엔진 · LLM 법령→룰 컴파일 | **[🔗](https://susemi.team-ieum.com)** |
| 📚 **[jongsose-helper](./jongsose-helper)** | 종합소득세 신고 **RAG 챗봇** (공식 책자 근거) | 책자 RAG · 동의어 매핑 · Vision 서식검토 · 환각 방지 | **[🔗](https://jongsose-helper.vercel.app)** |
| 🩺 **[jangbu-doctor](./jangbu-doctor)** | 통장 CSV → **세무조사 위험거래** 사전 점검 | 세무 룰 엔진 6종 · 법령 RAG · 통장 마스킹 | **[🔗](https://jangbu-doctor.vercel.app)** |

## 🤖 AI 플랫폼 · 인프라

> RAG · LLM 에이전트 · 멀티테넌트 · 실시간 — 더 넓은 시스템 엔지니어링.

| 프로젝트 | 한 줄 정의 | 핵심 기술 | 라이브 |
|:---|:---|:---|:---:|
| 🦺 **[ehs-compliance-chatbot](./ehs-compliance-chatbot)** | 산업안전(EHS) 위험관리 **SaaS** (Admin웹 + 작업자 PWA) | 멀티테넌트 4-Role · AI 에이전트 4종 · FAISS RAG · Whisper | **[🔗](https://safety-ai.team-ieum.com)** |
| 🏥 **[F2A](./F2A)** | 병원 리뷰 **LLM 자동 분류** (category/severity/team) | 구조화 LLM 출력 · PII 마스킹 · Multi-LLM · 비용 트래킹 | **[🔗](https://f2a.team-ieum.com)** |
| 🔭 **[netscope-ai](./netscope-ai)** | **설명가능** 로그 진단 — "왜 그렇게 판단했는가" | 룰엔진 R001~R024 · 패턴 학습 L0~L4 · 실시간 SSE | **[🔗](https://netscope-ai.team-ieum.com)** |

#### 🔑 데모 접속
| 프로젝트 | 접속 방법 |
|:---|:---|
| susemi · jongsose · jangbu | 로그인 없이 바로 체험 (jongsose 는 1회 체험 게이트) |
| netscope | `alice@demo.io` / `bob@demo.io` / `carol@demo.io` · PW `Demo1234!` (테넌트별 데이터 분리) |
| ehs | 회원가입(회사 등록) → admin 권한으로 전체 기능 |
| F2A | 로그인 화면 **"데모 둘러보기"** 클릭 → 키 없이 읽기 전용 탐색 (관리 기능은 API Key 필요) |

<br>

## 🧭 빠른 네비게이션 — *"이것만 보세요"*

각 프로젝트에서 **가장 보여주고 싶은 코드**를 역량별로 골랐습니다.

| 보고 싶은 역량 | 어디를 보면 되나 |
|:---|:---|
| 🎯 **정확성이 생명인 도메인 로직** | [`susemi/.../tax_calculator.py`](./susemi/highlights/tax_calculator.py) — 정수 한국 소득세 풀 파이프라인 + 단계별 `CalcStep` trace |
| 🧱 **세무 지식을 룰로 코드화** | [`jangbu-doctor/.../rules-index.ts`](./jangbu-doctor/highlights/rules-index.ts) + [`rules-entertainment.ts`](./jangbu-doctor/highlights/rules-entertainment.ts) — 접대비/차량/패턴 위험 룰 |
| 🔒 **보안을 고려한 설계** | [`susemi/.../rules_engine.py`](./susemi/highlights/rules_engine.py) — `eval()` 없이 Pydantic discriminated-union |
| 📚 **RAG · 환각 방지** | [`jongsose-helper/.../chat-route.ts`](./jongsose-helper/highlights/chat-route.ts) + [`kb.ts`](./jongsose-helper/highlights/kb.ts) — 책자 근거 검색, 없으면 "없음" |
| 🤝 **LLM 을 신뢰가능하게** | [`F2A/.../triage.py`](./F2A/highlights/triage.py) — 구조화 출력 + P0 키워드 이중검증, [`pii.py`](./F2A/highlights/pii.py) — 전송 전 PII 마스킹 |
| 🔀 **멀티 LLM 추상화** | [`F2A/.../client.py`](./F2A/highlights/client.py) + [`anthropic_client.py`](./F2A/highlights/anthropic_client.py) — OpenAI/Claude 동일 인터페이스 |
| 💡 **설명가능 AI (XAI)** | [`netscope-ai/.../rule_engine.py`](./netscope-ai/highlights/rule_engine.py) — 룰 ID + 근거 + 점수, [`drain.py`](./netscope-ai/highlights/drain.py) — 온라인 패턴 학습 |
| ⚡ **실시간 시스템** | [`netscope-ai/.../events.py`](./netscope-ai/highlights/events.py) + [`broker.py`](./netscope-ai/highlights/broker.py) — SSE 서버 푸시 |
| 🧩 **AI 에이전트 아키텍처** | [`ehs/.../base.py`](./ehs-compliance-chatbot/highlights/base.py) + [`incident_agent.py`](./ehs-compliance-chatbot/highlights/incident_agent.py) |
| 🛡️ **멀티테넌트 격리 / RBAC** | [`ehs/.../dependencies.py`](./ehs-compliance-chatbot/highlights/dependencies.py) + [`tbm.py`](./ehs-compliance-chatbot/highlights/tbm.py) |

<br>

## 🛠 공통 엔지니어링 역량

<table>
<tr>
<td width="50%" valign="top">

**🤖 LLM 을 프로덕션에서 신뢰가능하게**
- 자유 텍스트 파싱 금지 → 항상 JSON 스키마 / tool_use 구조화 출력
- 룰엔진을 baseline, LLM 은 보조
- 출처/룰ID 만 인용해 hallucination 차단
- 토큰·비용 로깅

**🔐 보안 우선 설계**
- `eval()` 미사용 · path traversal 화이트리스트
- PII 마스킹 · JWT/argon2 · API Key sha256
- 멀티테넌트 cross-tenant 차단

</td>
<td width="50%" valign="top">

**🚀 운영 배포**
- 4개 서비스를 단일 **Caddy 리버스 프록시**(자동 HTTPS) 뒤에 Docker Compose 배포
- 공유 네트워크 + 서브도메인 라우팅 · EC2 단일 호스트
- 2개 서비스는 Vercel 배포

**✅ 검증 습관 · 엔지니어링 성숙도**
- pytest(netscope 43 · susemi 237) · 골든셋 · 라우터 통합 테스트
- 배포 후 **직접 결함을 찾아 수정** (netscope 멀티테넌트 PK 충돌, ehs cross-tenant 누수, susemi 세액 이중차감)

</td>
</tr>
</table>

<br>

## 📦 폴더 구조

```text
project/
├── README.md                      # (이 파일) 6개 프로젝트 총정리 · 네비게이션
│
├── 세무·회계 도메인
│   ├── susemi/
│   ├── jongsose-helper/
│   └── jangbu-doctor/
│
├── AI 플랫폼·인프라
│   ├── ehs-compliance-chatbot/
│   ├── F2A/
│   └── netscope-ai/
│
└── <각 프로젝트 폴더>
    ├── README.md                  # 요약 · 아키텍처 · 코드 하이라이트 표
    └── highlights/                # 대표 코드 발췌 (실제 운영 코드)
```

<br>
<br>

---

<div align="center">

### 강지연 — Product Engineer

**세무·회계 5년 경력 · 도메인 특화 엔지니어**

> ### 💬 *"문제를 프로덕트로 만드는 엔지니어"*

현장에서 겪은 문제를 직접 코드로 풀고, 기획부터 배포·운영까지 끝까지 책임집니다.

</div>
