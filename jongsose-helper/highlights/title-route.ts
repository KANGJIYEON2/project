import { NextResponse } from 'next/server';
import OpenAI from 'openai';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MODEL = process.env.OPENAI_MODEL || 'gpt-4o-mini';

function isReasoningModel(model: string): boolean {
  return /^(o1|o3|o4)/.test(model);
}

interface ReqBody {
  userMessage?: string;
  botReply?: string;
}

export async function POST(req: Request) {
  if (!process.env.OPENAI_API_KEY) {
    return NextResponse.json(
      { error: 'OPENAI_API_KEY가 .env.local에 설정되지 않았습니다.' },
      { status: 500 },
    );
  }
  let body: ReqBody;
  try {
    body = (await req.json()) as ReqBody;
  } catch {
    return NextResponse.json({ error: 'JSON 본문이 올바르지 않습니다.' }, { status: 400 });
  }
  const userMsg = (body.userMessage || '').trim();
  const botReply = (body.botReply || '').trim();
  if (!userMsg) return NextResponse.json({ title: '' });

  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  const sys =
    '대화의 주제를 8~14자 한국어로 짧게 요약해 제목으로 만들어주세요. 명사구 형태. 따옴표·마침표·이모지 없이 제목만 한 줄로.';
  const user = `[사용자 질문]\n${userMsg.slice(0, 400)}\n\n[봇 답변 일부]\n${botReply.slice(0, 400)}\n\n제목:`;

  try {
    const res = await client.chat.completions.create({
      model: MODEL,
      messages: [
        { role: 'system', content: sys },
        { role: 'user', content: user },
      ],
      ...(isReasoningModel(MODEL) ? {} : { temperature: 0.3 }),
      max_completion_tokens: 60,
    });
    let title = (res.choices[0]?.message?.content || '').trim();
    // 따옴표/마침표/줄바꿈 정리
    title = title.split(/\n/)[0];
    title = title.replace(/^["'`「『\s]+|["'`」』.。\s]+$/g, '');
    title = title.slice(0, 24);
    return NextResponse.json({ title });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: `OpenAI 호출 실패: ${msg}` }, { status: 502 });
  }
}
