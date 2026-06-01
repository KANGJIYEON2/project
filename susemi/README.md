# susemi (수세미) — 연말정산 "왜?" 분석 엔진

> **"환급액 숫자"가 아니라 "왜 그렇게 나오는가"를 설명하는 연말정산 서비스.**
> 자체 세금 산식으로 계산하고, 각 단계를 법령 조항까지 trace 하며, 회사 신고분과 cross-check 합니다.

🔗 **라이브**: https://susemi.team-ieum.com (로그인 없이 `/wizard` 4단계 바로 체험)

---

## 문제 정의
시중 계산기는 "환급 OO원"만 보여줄 뿐, **왜 그 금액인지·어디서 더 줄일 수 있는지**를 설명하지 않습니다.
susemi 는 세액을 ① 정수 산식으로 직접 계산하고 ② 각 단계에 법령 anchor 를 붙이며 ③ 회사 신고분과 비교하고 ④ 5년 시뮬·절세 추천까지 제공합니다.

## 한 줄 아키텍처
```
[Next.js 16 위저드/Admin]  →  POST /api/v1/*  →  [FastAPI · Pydantic v2]
   /wizard 4단계                                    ├─ analyze    (룰 평가 + LLM "Why" 해설 + provenance 부착)
   /admin/rules·rag·ripple                          ├─ verify     (자체 산식 vs 회사 신고 cross-check)
   IndexedDB (분석 영속)                            ├─ simulate   (5년 What-if)
                                                     ├─ recommend  (greedy 5 lever 절세 추천)
                                                     └─ admin/rules(LLM 법령→Rule JSON 컴파일 + 검수 큐)
                                                      │
                                       tax_calculator(정수 풀산식) · rules_engine(eval 0줄)
                                       rule_compiler(LLM→룰) · legal_api(법령 RAG)
```

## 🎯 핵심 기술 결정 (면접 talking points)

1. **정수(원 단위) 세금 산식** — 부동소수점 누적오차를 피하려 전 과정을 정수로 계산. 모든 단계가 `CalcStep(name, legal_anchor, formula, inputs, output)` 로 남아 **계산 근거를 그대로 추적**.
2. **`eval()` 0줄 룰 엔진** — 룰을 JSON 으로 정의하고 Pydantic **discriminated union**(`ThresholdEvaluator`/`AllOfFlagsEvaluator`)으로 평가. 동적 코드 실행 없이 확장 가능 → 보안성 확보.
3. **LLM 법령 → Rule JSON 컴파일러** — 법령 본문을 LLM 으로 룰로 변환하되, **메타(rule_id/anchor)는 코드가 강제 덮어쓰기**하고 화이트리스트 밖 필드 참조 시 confidence 디스카운트. LLM 을 "초안 생성기"로만 쓰고 신뢰는 코드가 담보.
4. **출처 없는 인용 금지** — LLM "Why" 해설은 시스템이 제공한 `[rule_id]` anchor 만 인용 가능. `legal_anchor` 가 truth source → **hallucination 차단**.

## 📂 코드 하이라이트 (`highlights/`)

| 파일 | 무엇을 보여주나 | 면접 포인트 |
|---|---|---|
| [`tax_calculator.py`](./highlights/tax_calculator.py) | 한국 소득세 풀 파이프라인(총급여→공제→과표→누진세율→세액공제→결정세액), 단계별 `CalcStep` | "정확성이 최우선인 도메인을 어떻게 검증가능하게 설계했나" |
| [`rules_engine.py`](./highlights/rules_engine.py) | JSON 룰 로드/평가, `EVAL_CONTEXT_FIELDS` 화이트리스트, discriminated union | "`eval()` 없이 안전하게 동적 규칙을" |
| [`rule_compiler.py`](./highlights/rule_compiler.py) | 법령 본문 → LLM → Rule JSON, 메타 강제, 검증/재시도 | "LLM 출력을 어떻게 신뢰가능하게 가두나" |
| [`rule_schema.py`](./highlights/rule_schema.py) | `Rule` + Evaluator/ValueExpr discriminated union 스키마 | 타입 안전한 규칙 모델링 |
| [`analyze.py`](./highlights/analyze.py) | 룰 평가 → LLM Why → `_attach_provenance` 후처리 | 결과에 구조화된 "근거" 부착 |

## 기술 스택
- **Backend**: FastAPI 0.121 · Pydantic v2 · httpx(async) · openai 2.x · PyMuPDF(PDF 파싱)
- **Frontend**: Next.js 16 · React 19 · Tailwind v4 · IndexedDB(분석 영속)
- **데이터**: 세율표/공제표/룰 = 외부 JSON, 법령 = open.law.go.kr API + 디스크 캐시 + RAG 임베딩
- **테스트**: pytest 237 케이스 + 골든셋 5건(세액 검증)

## 🔧 직접 발견·수정한 이슈 (배포 후 코드 리뷰)
- **`/analyze` 비과세 이중차감 버그**: `/analyze` 가 `총급여 - 비과세` 로 과세표준을 계산했으나 총급여는 이미 비과세 제외값 → `/verify·/simulate·/recommend` 와 **세액이 불일치**(사용자에게 과소 세액 노출). 4개 경로의 입력 변환을 일관화하여 수정. *(같은 입력에 화면마다 다른 세금이 나오면 안 된다는 걸 cross-check 으로 잡은 사례)*
