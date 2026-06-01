# F2A (Feedback to Action) — 병원 리뷰 LLM 자동 분류

> **병원/의원 환자 리뷰(네이버 플레이스 등)를 LLM 으로 자동 분류해 운영 개선 인사이트를 주는 시스템.**
> 리뷰 한 건을 category·severity(P0~P3)·담당팀으로 triage 하되, **PII 마스킹·구조화 출력·비용 추적**을 프로덕션 수준으로 갖췄습니다.

🔗 **라이브**: https://f2a.team-ieum.com (대시보드 7페이지 / 로그인 화면 **"데모 둘러보기"** → 키 없이 읽기 전용 탐색)

---

## 문제 정의
병원은 매일 쌓이는 리뷰를 수작업으로 보지 못해 **의료사고성 컴플레인(P0)·시설 위생 문제 같은 중요한 신호를 놓칩니다.**
F2A 는 리뷰를 인입(CSV/단건/배치) → PII 마스킹 → LLM triage(카테고리/심각도/담당팀) → 대시보드로 흐르게 하고, P0(의료사고·환자안전)은 **키워드 룰로 이중 검증**합니다.

## 한 줄 아키텍처
```
CSV 업로드 / API 단건 / 배치
        │
        ▼
[Ingest] ──PII 마스킹(저장 전)──▶ [DB 저장(마스킹본)] ──▶ [LLM Triage]
                                                              │  category·severity·team
                                                              │  + P0 키워드 이중검증
                                                              ▼
                                        [LLMUsage 비용 1행 적재] ──▶ [대시보드 7페이지]
모델 라우팅: gpt-* → OpenAI / claude-* → Anthropic (동일 인터페이스)
```

## 🎯 핵심 기술 결정 (면접 talking points)

1. **PII 는 LLM/DB 전송 전에 마스킹** — 리뷰 본문을 저장하기 **전에** `mask_pii` 로 마스킹하고, LLM 에는 마스킹본만 전달. 개인정보가 외부 API·DB 어디에도 평문으로 안 남도록 파이프라인을 강제.
2. **구조화 출력 강제** — 자유 텍스트 파싱 금지. OpenAI 는 `response_format=json_object`, Anthropic 은 `tool_use` 로 스키마를 강제 → 파싱 실패/환각 최소화.
3. **P0 는 LLM 단독으로 확정하지 않음** — "의료사고·환자안전"으로 분류되면 **키워드 룰(의료사고/오진/감염/낙상 등)로 이중 검증**, 미충족 시 P1 로 강등. 가장 위험한 분류일수록 사람이 만든 룰로 보강.
4. **Multi-LLM 추상화** — `classify_review(model=...)` 한 함수가 모델 prefix 로 OpenAI/Anthropic 을 라우팅. 모델 A/B 평가(`evals`)와 모델별 비용 비교를 같은 인터페이스로.
5. **비용 가시성** — 매 LLM 호출마다 `LLMUsage` 1행 적재(토큰·비용). 단가 테이블로 "1000건당 $1 이내" KPI 를 측정 가능.

## 📂 코드 하이라이트 (`highlights/`)

| 파일 | 무엇을 보여주나 | 면접 포인트 |
|---|---|---|
| [`triage.py`](./highlights/triage.py) | LLM 분류 + **P0 키워드 이중검증** + 다운그레이드 | "위험 분류를 LLM 에만 맡기지 않는다" |
| [`pii.py`](./highlights/pii.py) | 정규식 기반 PII 마스킹(전화/이메일/이름 등) | 데이터 프라이버시 설계 |
| [`client.py`](./highlights/client.py) | OpenAI 구조화 출력(JSON mode) + 토큰/비용 반환 | LLM 호출 추상화 |
| [`anthropic_client.py`](./highlights/anthropic_client.py) | Claude `tool_use` 로 구조화 출력 | 멀티 프로바이더 동일 계약 |
| [`prompts.py`](./highlights/prompts.py) | 프롬프트 일원화(한 곳에서만 수정) | 프롬프트 버전 관리 |
| [`pricing.py`](./highlights/pricing.py) | 모델별 단가 + prefix 매칭 비용 계산 | 비용 트래킹 |

## 기술 스택
- **Backend**: FastAPI · Python 3.13 · SQLModel + Alembic · PostgreSQL 15
- **LLM**: OpenAI + Anthropic (gpt-4o-mini 기본, claude-haiku-4-5 등) · 구조화 출력
- **인증**: API Key(scope: admin/read/ingest) · 평문 미저장, **sha256 해시만** · **공개 데모는 read 전용 키로 키 없이 열람**
- **Frontend**: Next.js 15 · App Router · Tailwind (대시보드 7페이지)
- **운영**: 앱 내장 스케줄러(감사로그 정리·P0 스파이크 알림) · 평가 인프라(`evals`)

## 🔧 직접 발견·수정한 이슈 (배포 후 코드 리뷰)
- **Alembic 0001 마이그레이션 충돌**: 초기 마이그레이션이 `metadata.create_all()` 로 전체 테이블을 만들고, 이후 마이그레이션이 같은 테이블을 또 생성 → 신규 DB 에서 `DuplicateTable`. (dev 는 `AUTO_CREATE_TABLES=true` 로만 돌려 미검출) → **초기 테이블 include-list 방식**으로 반전해 재발 차단.
- **대소문자 import / Next standalone 바인딩** 등 Linux 운영 환경에서만 드러나는 이슈를 배포 과정에서 잡아 수정.
