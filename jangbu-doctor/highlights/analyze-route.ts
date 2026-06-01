import { NextRequest, NextResponse } from 'next/server';
import OpenAI from 'openai';
import { buildLawContext } from '@/lib/rag/retriever';

// 간단한 메모리 기반 Rate Limiter (IP당 시간당 30건)
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
const RATE_LIMIT = 30;
const RATE_WINDOW_MS = 60 * 60 * 1000; // 1시간

function checkRateLimit(ip: string): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + RATE_WINDOW_MS });
    return true;
  }
  if (entry.count >= RATE_LIMIT) return false;
  entry.count++;
  return true;
}

const FORBIDDEN_FIELDS = ['account', 'balance', 'accountNumber', 'businessId'];

const FORBIDDEN_PATTERNS = [
  /안전합니다/,
  /보장합니다/,
  /확실합니다/,
  /절세가 가능합니다/,
  /세금이 면제됩니다/,
  /비용처리 가능합니다/,
  /신고하시면 됩니다/,
];

const SYSTEM_PROMPT = `당신은 한국 세법에 정통한 사전 점검 AI입니다.
경리 직원이 통장 거래내역을 보내면, 한국 세법(법인세법, 부가가치세법 등)에 근거하여 위험할 수 있는 거래를 정밀 분석합니다.

[핵심 역할]
당신에게는 실제 법령 원문이 제공됩니다. 반드시 제공된 법령 원문에 근거하여 판단하세요.
법령에 없는 내용을 창작하지 마세요.

[분석 카테고리]
1. 접대비(기업업무추진비) — 법인세법 제25조, 시행령 제41조
   - 한도 계산: 기본 1,200만원 + (수입금액별 적용률)
   - 1건 1만원 초과 시 신용카드등 사용 의무 (시행령 제41조)
   - 경조사비 건당 20만원 한도 (시행령 제42조)
2. 업무무관경비 — 법인세법 제19조의2
   - 업무와 관련 없는 지출은 손금불산입
   - 대표자 개인 사용 = 상여 처분
3. 업무용 승용차 — 법인세법 제27조, 시행령 제50조의2
   - 운행기록부 미작성 시 한도 제한
   - 감가상각, 보험료, 유류비 등 포함
4. 매입세액 불공제 — 부가가치세법 제39조
   - 접대비 관련 지출
   - 비영업용 소형승용차 관련
   - 면세사업 관련 매입
5. 증빙 관련
   - 3만원 초과 간이영수증 = 증빙불비 가산세
   - 적격증빙 수취의무 위반
6. 손금 일반 — 법인세법 제19조
   - 손금의 범위와 요건
   - 자본적 지출 vs 수익적 지출

[엄격한 제약사항]
1. 절대 단정하지 않습니다:
   ❌ "안전합니다" / "보장합니다" / "확실합니다"
   ✅ "검토가 필요합니다" / "가능성이 있습니다"

2. 법령 인용 시 반드시 조항 명시:
   ✅ "법인세법 제25조 제4항에 따르면..."
   ❌ "세법에 의하면..." (모호한 인용)

3. 모르면 "정보 부족으로 판단이 어렵습니다"

4. 응답은 반드시 아래 JSON 형식으로:
{
  "results": [
    {
      "transactionId": "...",
      "risks": [
        {
          "ruleId": "AI-XXX",
          "level": "high|medium|low|safe",
          "reason": "구체적 설명 (어떤 법령의 어떤 조항에 근거하여 왜 위험한지)",
          "category": "entertainment|vehicle|personal|pattern|vat|expense",
          "legalRef": "법인세법 제25조 제4항",
          "suggestion": "구체적인 권장 조치",
          "confidence": 0.XX
        }
      ],
      "overallLevel": "high|medium|low|safe"
    }
  ]
}

[응답 품질 요구사항]
- reason은 구체적으로: 어떤 법조항의 어떤 요건에 해당하는지
- suggestion은 실무적으로: 경리 직원이 바로 실행할 수 있는 수준
- legalRef는 정확하게: "법인세법 제25조" 수준이 아니라 "법인세법 제25조 제4항" 수준으로
- 한국어 자연스럽게, 경리 직원 관점에서 이해 가능하게`;

export async function POST(request: NextRequest) {
  try {
    // Rate limiting
    const ip = request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() || 'unknown';
    if (!checkRateLimit(ip)) {
      return NextResponse.json(
        { error: 'RATE_LIMIT', message: '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.' },
        { status: 429 }
      );
    }

    const body = await request.json();
    const { transactions, context } = body;

    if (!transactions || !Array.isArray(transactions) || transactions.length === 0) {
      return NextResponse.json(
        { error: 'INVALID_INPUT', message: '거래 내역이 필요합니다.' },
        { status: 400 }
      );
    }

    if (transactions.length > 200) {
      return NextResponse.json(
        { error: 'INVALID_INPUT', message: '한 번에 최대 200건까지 분석 가능합니다.' },
        { status: 400 }
      );
    }

    // 입력 필드 길이 제한
    for (const t of transactions) {
      if (t.description && t.description.length > 200) t.description = t.description.slice(0, 200);
      if (t.note && t.note.length > 100) t.note = t.note.slice(0, 100);
    }

    // 마스킹 검증
    for (const t of transactions) {
      for (const field of FORBIDDEN_FIELDS) {
        if (field in t && t[field] !== undefined) {
          return NextResponse.json(
            { error: 'INVALID_INPUT', message: `금지된 필드가 포함되어 있습니다: ${field}`, violations: [field] },
            { status: 400 }
          );
        }
      }
    }

    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
      return NextResponse.json(
        { error: 'INTERNAL_ERROR', message: 'AI 분석 서비스를 사용할 수 없습니다.' },
        { status: 500 }
      );
    }

    const client = new OpenAI({ apiKey });

    // RAG: 거래 기반으로 관련 법령 원문 검색
    const lawContext = buildLawContext(
      transactions.map((t: { description: string; amount: number; type: string }) => ({
        description: t.description,
        amount: t.amount,
        type: t.type as 'deposit' | 'withdrawal',
      }))
    );

    const userMessage = transactions
      .map((t: { id: string; date: string; description: string; amount: number; type: string; note?: string }, i: number) =>
        `거래 ${i + 1}\n- ID: ${t.id}\n- 날짜: ${t.date}\n- 거래처: ${t.description}\n- 금액: ${t.amount.toLocaleString()}원\n- 구분: ${t.type === 'withdrawal' ? '출금' : '입금'}${t.note ? `\n- 메모: ${t.note}` : ''}`
      )
      .join('\n\n');

    const contextStr = context
      ? `\n\n[회사 정보]\n${context.industry ? `- 업종: ${context.industry}` : ''}${context.cumulativeEntertainment ? `\n- 당해 누적 접대비: ${context.cumulativeEntertainment.toLocaleString()}원` : ''}`
      : '';

    const fullUserMessage = `다음 거래들을 한국 세법에 근거하여 정밀 검토해주세요.
아래 제공된 법령 원문을 참고하여, 각 거래의 세무 위험을 분석해주세요.

${lawContext}

[분석 대상 거래]
${userMessage}${contextStr}`;

    const response = await client.chat.completions.create({
      model: 'gpt-4o',
      temperature: 0.2,
      max_tokens: 4096,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: fullUserMessage },
      ],
    });

    const responseText = response.choices[0]?.message?.content || '';

    // JSON 파싱
    const jsonMatch = responseText.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return NextResponse.json(
        { error: 'INTERNAL_ERROR', message: 'AI 응답을 파싱할 수 없습니다.' },
        { status: 500 }
      );
    }

    const parsed = JSON.parse(jsonMatch[0]);

    // 금지 패턴 필터링 — AI 응답에서 단정적 표현을 안전한 표현으로 교체
    if (parsed.results) {
      for (const result of parsed.results) {
        for (const risk of result.risks || []) {
          if (risk.reason) {
            for (const pattern of FORBIDDEN_PATTERNS) {
              if (pattern.test(risk.reason)) {
                console.warn(`Forbidden pattern filtered: ${pattern}`);
                risk.reason = risk.reason
                  .replace(/안전합니다/g, '위험 패턴이 감지되지 않았습니다')
                  .replace(/보장합니다/g, '검토가 필요합니다')
                  .replace(/확실합니다/g, '가능성이 있습니다')
                  .replace(/절세가 가능합니다/g, '절세 가능 여부 검토가 필요합니다')
                  .replace(/세금이 면제됩니다/g, '면세 해당 여부 검토가 필요합니다')
                  .replace(/비용처리 가능합니다/g, '비용처리 가능 여부 검토가 필요합니다')
                  .replace(/신고하시면 됩니다/g, '신고 방법은 세무사와 상의하세요');
              }
            }
          }
        }
      }
    }

    return NextResponse.json({
      ...parsed,
      metadata: {
        analyzedAt: new Date().toISOString(),
        model: 'gpt-4o',
        tokensUsed: response.usage?.total_tokens || 0,
      },
    });
  } catch (error) {
    console.error('AI analysis error:', error instanceof Error ? error.message : 'Unknown error');
    return NextResponse.json(
      { error: 'INTERNAL_ERROR', message: 'AI 분석 중 오류가 발생했습니다.' },
      { status: 500 }
    );
  }
}
