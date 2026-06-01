# EHS Compliance Chatbot — 산업안전 위험관리 SaaS

> **현장 안전(EHS: Environment·Health·Safety)을 디지털화한 멀티테넌트 SaaS.**
> 관리자용 웹 + 현장 작업자용 모바일 PWA 의 듀얼 트랙 구조 위에, RAG 법령 챗봇과 AI 에이전트 4종을 얹었습니다.

🔗 **라이브**: https://safety-ai.team-ieum.com (회원가입 → admin 권한으로 전체 기능 / 작업자 PWA: `/worker`)

---

## 문제 정의
중소 제조 현장은 사고 기록·위험성 평가·교육이 **종이/엑셀**에 흩어져 있고, 외국인 작업자 비중이 높아 안전수칙 전달도 어렵습니다.
이 서비스는 사고 등록 → AI 근본원인/체크리스트/법적근거 분석 → 대시보드/월간 PDF 리포트, 그리고 **음성 신고·익명 제보·다국어 안전가이드·TBM·위험성평가·게이미피케이션**까지 한 플랫폼에서 처리합니다.

## 한 줄 아키텍처
```
[Admin 웹 React]  ┐
                  ├─→  FastAPI (JWT/argon2, 4-Role)  ─→  PostgreSQL
[작업자 PWA React]┘            │
                              ├─ AI Agents: Incident / Law / News / Voice(Whisper)
                              ├─ RAG: FAISS(법령 784 + 룰 13,802) + OpenAI 임베딩
                              └─ 멀티테넌트: 모든 쿼리가 company_id 로 격리
```

## 🎯 핵심 기술 결정 (면접 talking points)

1. **듀얼 트랙 단일 백엔드** — Admin(데스크탑 관리)과 Worker(모바일 현장)를 분리된 React 앱으로, 하나의 FastAPI + 50여 개 엔드포인트가 공유. 역할별 UX 를 나누되 도메인 로직은 단일화.
2. **멀티테넌트 + 4-Role RBAC** — superadmin/admin/field_manager/worker. `get_current_user` + `require_role` 의존성으로 라우트를 가드하고, **모든 데이터 쿼리가 `company_id` 로 필터** → 회사 간 데이터 격리.
3. **AI 에이전트 아키텍처** — `BaseAgent`(`_chat`/`_chat_json` 공유) 를 상속한 4개 전문 에이전트(사고분석/법령/뉴스/음성). 시작 시 OpenAI 클라이언트를 공유 초기화하고 각자 특화 시스템 프롬프트 보유.
4. **RAG 법령 챗봇** — FAISS 벡터DB(법령·룰)에 OpenAI 임베딩으로 의미 검색. 기존 법령 챗봇 위에 EHS 도메인을 확장한 구조.
5. **현장 친화 기능** — Whisper 음성 신고(STT→GPT 구조화→자동 등록), 익명 제보(개인식별정보 미저장), 한국어→5개국어 안전가이드 + QR.

## 📂 코드 하이라이트 (`highlights/`)

| 파일 | 무엇을 보여주나 | 면접 포인트 |
|---|---|---|
| [`base.py`](./highlights/base.py) | `BaseAgent` — 공유 OpenAI 클라이언트, `_chat`/`_chat_json` | 에이전트 공통 추상화 |
| [`incident_agent.py`](./highlights/incident_agent.py) | 사고 → 근본원인·예방 체크리스트·재발방지 생성 | 도메인 특화 LLM 에이전트 |
| [`rag_service.py`](./highlights/rag_service.py) | FAISS 로드 + OpenAI 임베딩 + 의미 검색 | RAG 파이프라인 구현 |
| [`dependencies.py`](./highlights/dependencies.py) | `get_current_user` + `require_role` 의존성 | JWT 인증 + RBAC |
| [`tbm.py`](./highlights/tbm.py) | TBM(작업 전 안전미팅) CRUD + AI 안건 생성 + **테넌트 격리** | 멀티테넌트 쿼리 패턴 (수정 사례 ↓) |

## 기술 스택
- **Backend**: FastAPI(Python 3.11) · SQLAlchemy 2.0 · Alembic · JWT + bcrypt/argon2
- **AI/RAG**: FAISS · OpenAI(text-embedding-3-small, gpt-4o-mini, whisper-1)
- **Frontend**: React 19 · TypeScript · Vite · Tailwind 4 · Zustand · Recharts
- **기타**: pdfplumber/pytesseract(PDF·OCR) · reportlab(리포트 생성) · qrcode

## 🔧 직접 발견·수정한 이슈 (배포 후 멀티에이전트 코드 리뷰)
- **멀티테넌트 cross-tenant 누수 5건**: TBM 조회/참석, 포인트 적립, 퀴즈 응답, 가이드 번역, 사고 담당자 배정 핸들러가 `company_id` 검증 없이 임의 ID 를 수락 → 타사 데이터 접근/유료 GPT 호출 가능. 각 핸들러에 회사 소속 검증을 추가해 차단. *(→ [`tbm.py`](./highlights/tbm.py) 의 `_assert_site_in_company`)*
- **약한 JWT 시크릿**: 11자 시크릿을 32바이트 랜덤으로 교체 + `validate_jwt_secret` 이 32자 미만을 거부하도록 강화.
- **헬스체크 오탐**: nginx 가 IPv4(`listen 80`)만 듣는데 헬스체크가 `localhost`(IPv6 `::1` 우선) 로 접속 → 컨테이너가 `unhealthy` 로 오표시. `127.0.0.1` 로 수정.
