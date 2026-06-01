# Netscope-AI — 설명가능 로그 진단 (Explainable Log Diagnostics)

> **"이 로그가 위험하다"가 아니라 "왜 그렇게 판단했는가"를 룰 ID·근거·점수로 보여주는** 로그 진단 플랫폼.
> 결정론적 룰 엔진(R001~R024)을 baseline 으로 두고, 패턴 학습(L0~L4)·실시간 SSE·GPT 보고서를 얹었습니다.

🔗 **라이브**: https://netscope-ai.team-ieum.com (`alice@demo.io` · PW `Demo1234!` — 테넌트별 데이터 분리)

---

## 문제 정의
로그 알림 도구는 보통 "에러 N건"만 띄울 뿐, **왜 위험한지·무엇을 봐야 하는지** 설명하지 않아 신뢰하기 어렵습니다.
Netscope 는 모든 판단을 **룰 ID + 근거 + confidence 점수**로 노출하고, 새로 들어오는 로그에서 **패턴을 스스로 학습**하며, ingest 즉시 화면을 **실시간 갱신**합니다.

## 한 줄 아키텍처
```
Agent/로그 ──/ingest──▶ [Parser] ─▶ [Rule Engine R001~R024] ─▶ severity/confidence
                            │                │  (+ GPT 구조화 보고서, 룰을 뒤집지 않음)
                            │                ▼
                            │          [AnalysisResult 저장] ──▶ broker.publish
                            ▼                                         │
                    [Drain 패턴 마이닝 L0~L4]                 [SSE /events/stream]
                    (변수 마스킹→템플릿→카탈로그→가중치 학습)        │ tenant 필터
                                                                      ▼
                                                   [Next.js 16 Fleet 대시보드 · 실시간 갱신]
모든 보호 라우트: 쿠키 JWT → tenant_id 로 쿼리 필터 (멀티테넌트 격리)
```

## 🎯 핵심 기술 결정 (면접 talking points)

1. **설명가능성(XAI)이 제품의 핵심** — 24개 룰(키워드/에러버스트/타임아웃 연쇄/스파이크 등) + 13개 interaction_bonus 조합으로 severity 를 산출하고, **어떤 룰이 왜 걸렸는지**를 칩+근거로 노출. confidence 산식이 결정론적이라 재현 가능.
2. **온라인 패턴 학습 L0~L4** — Drain 알고리즘으로 로그 변수를 마스킹(IP/UUID/숫자 등)해 템플릿을 추출하고, 카탈로그에 적재 → 분석 시 매칭 → 사용자 피드백(confirm/dismiss)으로 **가중치를 온라인 학습**. 단, **안전 가드**(score_seed ≤ 0.30, |adjust| ≤ 0.10, 테넌트 격리)로 폭주 방지.
3. **LLM 은 룰을 뒤집지 않는다** — GPT 보고서는 "rule-engine analysis is the baseline. Do NOT contradict rules" 를 시스템 프롬프트로 강제 → 결정성/재현성 유지하면서 자연어 설명만 보강.
4. **실시간 SSE 푸시** — ingest → 완전 분석 저장 → `broker.publish` → `/events/stream`(쿠키 인증, **tenant 별 필터**) → 프론트 EventSource 자동 갱신. 폴링 없이 라이브 피드.
5. **레이어 경계 엄수** — 분석 엔진(`engine.py`)은 **ORM 을 모른다**(frozen dataclass 만 받음). 쓰기/도메인 로직은 domain 레이어로 위임 → 테스트 용이성.

## 📂 코드 하이라이트 (`highlights/`)

| 파일 | 무엇을 보여주나 | 면접 포인트 |
|---|---|---|
| [`rule_engine.py`](./highlights/rule_engine.py) | R001~R024 룰 + interaction_bonus + severity 매핑 | "결정론적 설명가능 진단을 어떻게 설계했나" |
| [`engine.py`](./highlights/engine.py) | 오케스트레이션(Rule→GPT→severity→DTO), **ORM 미의존** | 레이어 경계/테스트 가능성 |
| [`drain.py`](./highlights/drain.py) | Drain 트리 — 온라인 로그 템플릿 마이닝 | 패턴 학습 알고리즘 구현 |
| [`weight_learner.py`](./highlights/weight_learner.py) | 피드백 기반 가중치 학습 + **안전 가드** | "학습 시스템의 폭주를 어떻게 막나" |
| [`broker.py`](./highlights/broker.py) | in-memory 이벤트 broker(publish/since) | 실시간 pub/sub |
| [`events.py`](./highlights/events.py) | `GET /events/stream` SSE (쿠키 인증, tenant 필터) | 서버 푸시 + 멀티테넌트 |
| [`gpt_analyzer.py`](./highlights/gpt_analyzer.py) | GPT 구조화 보고서(summary + report_sections) | LLM 을 baseline 보조로 |

## 기술 스택
- **Backend**: FastAPI · SQLAlchemy · PostgreSQL 16 · 쿠키 JWT(rotation + reuse 탐지, argon2)
- **학습/분석**: Drain 패턴 마이닝 · 룰 엔진 v3.0 · OpenAI(gpt-4o-mini) 구조화 보고서
- **실시간**: SSE(`/events/stream`) + in-memory broker
- **Frontend**: Next.js 16 · React 19 · ECharts(Fleet 대시보드) · Tailwind 4 · zustand
- **테스트**: pytest 43 (health/rule engine/parser/learning)

## 🔧 직접 발견·수정한 이슈 (배포 후 코드 리뷰 + 라이브 테스트)
- **멀티테넌트 패턴 PK 충돌 (HIGH)**: 패턴 `id` 가 콘텐츠 해시라 **테넌트 간 동일** → `id` 단독 PK 면 다른 테넌트가 같은 로그 템플릿을 적재할 때 PK 충돌로 **ingest 트랜잭션이 깨져 분석 저장까지 연쇄 실패**. → PK 를 복합 `(id, tenant_id)` 로 변경.
- **배치 내 중복 INSERT (라이브 테스트로 추가 발견)**: 한 배치에 같은 템플릿이 여러 번이면 첫 INSERT 가 flush 전이라 두 번째 조회가 못 찾고 또 INSERT → 충돌. → 배치 내 pending 캐시로 합산. 실제로 동일 템플릿을 두 테넌트로 ingest 해 **둘 다 정상 저장됨**을 확인(테스트 43개 통과).
- *교훈*: 정적 리뷰로 1건(PK), 라이브 종단 테스트로 1건(배치 중복)을 잡음 — "실제로 띄워서 쳐봐야 보이는 결함"의 사례.
