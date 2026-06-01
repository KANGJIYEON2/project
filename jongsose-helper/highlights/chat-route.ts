import { NextResponse } from 'next/server';
import OpenAI from 'openai';
import { searchKB, searchKBHybrid } from '@/app/lib/kb';
import type { ChatRequestBody, Chunk } from '@/app/lib/types';

export const runtime = 'nodejs'; // kb.json import + 큰 body 처리 위해 Node 런타임
export const dynamic = 'force-dynamic';

const DEFAULT_MODEL = process.env.OPENAI_MODEL || 'gpt-4o-mini';
const EMBED_MODEL = process.env.EMBED_MODEL || 'text-embedding-3-small';

// 청크의 페이지 묶음을 사람이 읽기 좋은 라벨로. [4,5,6] → "4-6", [4] → "4".
function pagesLabel(pages: number[]): string {
  if (pages.length === 0) return '?';
  if (pages.length === 1) return String(pages[0]);
  return `${pages[0]}-${pages[pages.length - 1]}`;
}

/** o1/o3/o4 계열은 temperature·system role을 지원하지 않는다. */
function isReasoningModel(model: string): boolean {
  return /^(o1|o3|o4)/.test(model);
}

// 시스템 프롬프트가 길어 모델이 후반부 가이드를 흘릴 때를 대비해, 사용자 쿼리에서
// 의도가 명확한 케이스만 system 메시지 맨 끝에 강한 한 줄 가드를 박는다.
function urgentGuardForQuery(query: string): string | null {
  const q = query || '';
  if (/신고\s*기한|납부\s*기한|언제\s*까지|언제\s*신고|마감일|기한.*(알려|언제|뭐|뭔)/.test(q)) {
    return '[!] 이 질문은 **신고기한 질문**입니다. 첫 문장에 "종합소득세 신고·납부 기한은 매년 5월 1일~5월 31일입니다"라고 단정해서 답하세요. 신고 절차 나열, "근거에 명시되어 있지 않다"는 회피, 화면 캡처의 날짜를 근거로 인용하는 것 모두 금지. 성실신고확인 대상자(6/30)·개인지방소득세도 짧게 덧붙이세요.';
  }
  return null;
}

function buildOpenAIMessages(body: ChatRequestBody, retrieved: Chunk[]) {
  const sysLines = [
    '당신은 한국의 종합소득세 신고 도우미입니다. 사용자의 질문에 적극적으로 답하는 것이 우선이며, 검색된 근거를 충분히 활용하세요.',
    '',
    '[기본 원칙 — 거부보다 답변이 먼저]',
    '· 검색된 근거가 한 묶음이라도 있으면, 그 안에서 답을 찾아 정리하세요. 정확히 그 단어로 안 나와도 절차·메뉴·예시·항목명으로 묶어 설명할 수 있으면 그렇게 답하세요.',
    '· *매년 바뀔 수 있는 수치* — **세율·경비율·금액 한도·공제 한도** — 는 근거에 명시된 것만 인용하고, 근거에 없으면 "근거에 수치는 명시돼 있지 않다"고 짧게 덧붙이세요.',
    '· *안정 상수* — **법정 신고기한, 일반적 절차 순서** 같이 매년 같은 사실 — 은 아래 [상수] 섹션의 값을 시스템 내장 상식으로 그대로 답하세요. "근거에 없다"고 회피하지 마세요.',
    '· 개념 설명·절차 흐름·용어 비교는 일반 세무 상식과 [용어 매핑]을 자유롭게 활용하세요.',
    '· 한 청크는 보통 2~10페이지의 한 절(section)이라 표·메뉴 화면 설명이 같이 들어 있습니다. 메뉴 경로(예: "신고도움자료 > 신고서 작성")가 보이면 그걸 그대로 옮기세요.',
    '',
    '[질문 의도별 답변 형태 — 사용자의 질문을 먼저 분류하고 그 형태대로 답하세요]',
    '· "A와 B의 차이는?" / "A vs B" / "뭐가 달라?" → **비교**가 메인. 두 개념을 표나 항목 대조로 먼저 설명. RAG 근거에 명시 비교가 없어도 아래 [용어 매핑]을 그대로 써서 비교를 만드세요. 절차 나열은 금지.',
    '· "X가 뭐야?" / "X 뜻" / "X 의미" → **정의**가 메인. 한두 문장으로 정의 → 적용 대상·예시 → 필요하면 책자의 관련 절차 한 줄.',
    '· "어떻게 신고해?" / "신고 방법" / "절차 알려줘" → **절차**가 메인. 책자의 메뉴 경로·단계를 그대로.',
    '· "기한", "한도", "세율", "경비율" 등 수치 질문 → 종합소득세 표준 신고기한은 아래 [상수] 그대로 답함. 매년 바뀔 수 있는 세율·경비율·한도는 근거에 명시된 것만 인용, 없으면 "근거에 수치 명시 없음"이라고 짧게.',
    '',
    '[금지]',
    '· 검색된 근거가 있는데 "책자에 해당 내용이 없습니다" / "정보를 찾을 수 없습니다" / "추가 정보가 필요합니다"로 회피하는 것. 이런 회피는 검색이 0건이고 일반 세무 상식으로도 도저히 답할 수 없을 때만 허용됩니다.',
    '· 사용자가 정의·비교·차이를 물었는데 절차만 나열하고 끝내는 것. RAG가 절차 청크를 잡았더라도, 질문 의도가 비교/정의면 그 형태로 답한 뒤 절차는 짧게 보조로만.',
    '',
    '[용어 매핑 — 시스템 내장 정의 (검색 근거 없이도 그대로 사용 가능)]',
    '· "추계신고" / "추계": 장부 없이 정부가 정한 경비율로 소득금액을 추정하는 신고 방식. 매뉴얼은 이를 "단순경비율 신고"와 "기준경비율 신고" 두 절차로 나누어 다룹니다.',
    '· "단순경비율": 수입금액이 일정 기준 이하인 영세사업자에게 적용. 정해진 경비율을 수입금액에 곱해 경비를 추산.',
    '· "기준경비율": 단순경비율 대상이 아닌 사업자. 주요경비(매입·인건비·임차료)는 증빙으로, 나머지는 기준경비율로 추산.',
    '· 단순경비율과 기준경비율의 핵심 차이: ① 적용 대상(수입 규모) ② 주요경비 처리 방식(경비율만 적용 vs 증빙+경비율 혼합).',
    '',
    '[상수 — 매년 동일한 법정 사실. 근거에 없어도 그대로 답하라]',
    '· **종합소득세 신고·납부 기한**: 매년 **5월 1일~5월 31일**. 5/31이 토·일·공휴일이면 다음 영업일까지 연장.',
    '· **성실신고확인 대상자**: 신고·납부 기한이 **6월 30일**까지 연장.',
    '· **개인지방소득세**: 종합소득세와 별도로 신고하지만 기한·납세지는 동일(5/31). 홈택스가 아닌 위택스에서 신고.',
    '· 위 사실들은 매년 변하지 않으므로 책자에 명시되어 있지 않더라도 "올해 신고기한은 5월 31일입니다"처럼 단정해서 답하세요. "근거에 명시되어 있지 않다"는 군더더기를 붙이지 마세요.',
    '',
    '[답변 형식]',
    '· 한국어, 간결하게. 필요하면 1~2단계로 정리. 절차 안내일 경우 책자의 메뉴 경로를 그대로 옮기세요.',
    '· 사용한 근거가 있으면 답변 마지막 줄에 [매뉴얼 p36-p38] 처럼 출처를 표기. 여러 묶음이면 [매뉴얼 p36-p38, p43-p45].',
    '· 세무 자문이 아닌 신고 보조이며, 실제 신고 전에는 사람의 확인이 필요하다는 점을 길지 않게 덧붙여도 됩니다.',
    '',
    '이미지가 첨부된 경우(보통 홈택스 신고 서식 캡처): 화면에서 보이는 항목을 읽고 누락·오류·확인할 사항을 책자 근거와 대조해 피드백하세요.',
  ];

  const ctx = retrieved
    .map(
      (c, i) =>
        `### 근거 ${i + 1} — ${c.source} p${pagesLabel(c.pages)} (${c.priority})\n${c.text}`,
    )
    .join('\n\n');
  const ctxBlock = retrieved.length
    ? ctx
    : '(검색 결과 0건. 이번에만 시스템 내장 용어 매핑과 일반 세무 상식으로 답하세요.)';

  const systemContent =
    sysLines.join('\n') + '\n\n[공식 책자 근거]\n' + ctxBlock;
  const guard = urgentGuardForQuery(body.query);

  const sysRole = isReasoningModel(DEFAULT_MODEL) ? 'developer' : 'system';

  const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [
    { role: sysRole as 'system', content: systemContent },
  ];

  for (const m of (body.history || []).slice(-6)) {
    messages.push({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.text,
    });
  }

  const userText = guard
    ? `${guard}\n\n[사용자 질문]\n${body.query}`
    : body.query;

  if (body.image && body.image.dataUrl) {
    messages.push({
      role: 'user',
      content: [
        {
          type: 'text',
          text: body.query || '첨부한 홈택스 서식을 검토해줘.',
        },
        { type: 'image_url', image_url: { url: body.image.dataUrl } },
      ],
    });
  } else {
    messages.push({ role: 'user', content: userText });
  }

  return messages;
}

export async function POST(req: Request) {
  if (!process.env.OPENAI_API_KEY) {
    return NextResponse.json(
      { error: 'OPENAI_API_KEY가 .env.local에 설정되지 않았습니다.' },
      { status: 500 },
    );
  }

  let body: ChatRequestBody;
  try {
    body = (await req.json()) as ChatRequestBody;
  } catch {
    return NextResponse.json({ error: 'JSON 본문이 올바르지 않습니다.' }, { status: 400 });
  }

  if (!body.query && !body.image) {
    return NextResponse.json(
      { error: 'query 또는 image 중 하나는 필요합니다.' },
      { status: 400 },
    );
  }

  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

  // 신고기한 같은 안정 상수 질문은 RAG로 잡힌 절차 청크에 끌려가지 않도록
  // 검색 자체를 우회한다. 시스템 프롬프트의 [상수] + user message 가드만으로 답하게.
  const intentGuard = body.query ? urgentGuardForQuery(body.query) : null;
  let retrieved: Chunk[] = [];
  if (body.query && !intentGuard) {
    try {
      const embedRes = await client.embeddings.create({
        model: EMBED_MODEL,
        input: body.query,
      });
      const queryEmbed = embedRes.data[0]?.embedding;
      retrieved = queryEmbed
        ? searchKBHybrid(body.query, queryEmbed, 4)
        : searchKB(body.query, 4);
    } catch {
      // embedding 호출 실패 시 keyword-only로 폴백
      retrieved = searchKB(body.query, 4);
    }
  }
  const messages = buildOpenAIMessages(body, retrieved);

  const citations = retrieved.map((c) => ({
    id: c.id,
    source: c.source,
    pages: c.pages,
    title: c.title,
    priority: c.priority,
    excerpt: c.text.slice(0, 140),
    imageUrls: c.imageUrls,
  }));

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const write = (obj: unknown) => {
        controller.enqueue(encoder.encode(JSON.stringify(obj) + '\n'));
      };
      // citations를 먼저 보내서 클라이언트가 답변 시작 전에 출처 카드를 알게.
      write({ type: 'citations', citations });
      try {
        const completion = await client.chat.completions.create({
          model: DEFAULT_MODEL,
          messages,
          ...(isReasoningModel(DEFAULT_MODEL) ? {} : { temperature: 0.2 }),
          max_completion_tokens: 2048,
          stream: true,
        });
        for await (const chunk of completion) {
          const delta = chunk.choices[0]?.delta?.content;
          if (delta) write({ type: 'token', text: delta });
        }
        write({ type: 'done' });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        write({ type: 'error', message: `OpenAI 호출 실패: ${msg}` });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'application/x-ndjson; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no',
    },
  });
}
