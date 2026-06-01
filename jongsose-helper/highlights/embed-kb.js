// kb.json의 모든 청크에 OpenAI 임베딩을 부여한다.
// 검색은 키워드 매칭만으로는 동의어/의역에 약한데, 임베딩 cosine similarity를
// 추가해 의미 기반 검색을 만든다. embedding은 청크 텍스트(절 제목 + 본문) 기준.
//
// 비용: text-embedding-3-small $0.02/1M tokens. 114 청크 × ~3000토큰 ≈ $0.007.
// 청크가 한 번 만들어지면 임베딩도 한 번만 다시 생성.

const fs = require('fs');
const path = require('path');
const OpenAI = require('openai');

const ROOT = path.resolve(__dirname, '..');
const KB_PATH = path.join(ROOT, 'kb.json');
const BACKUP_PATH = path.join(ROOT, 'kb.json.bak');

const MODEL = process.env.EMBED_MODEL || 'text-embedding-3-small';
const BATCH_SIZE = 32; // OpenAI는 한 번에 여러 input 받을 수 있다. 한 호출당 32개씩.
const MAX_RETRIES = 5;

function loadEnvLocal() {
  const envPath = path.join(ROOT, '.env.local');
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    let val = m[2];
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (!process.env[m[1]]) process.env[m[1]] = val;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function callWithRetry(fn) {
  let lastErr;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      const status = e?.status;
      const isRetryable = status === 429 || (status >= 500 && status < 600);
      if (!isRetryable) throw e;
      const retryAfterSec = Number(e?.headers?.['retry-after']);
      const waitMs = Number.isFinite(retryAfterSec)
        ? retryAfterSec * 1000 + 500
        : Math.min(60000, 2000 * 2 ** attempt);
      process.stdout.write(`  (${status} → ${Math.round(waitMs / 1000)}s 대기) `);
      await sleep(waitMs);
    }
  }
  throw lastErr;
}

// 임베딩 input은 source·절 제목·키워드를 dominant로 박고 본문은 발췌만.
// 12p짜리 큰 청크에서 본문 노이즈가 임베딩을 흐리는 걸 막는다. 절 제목과 키워드가
// 의미 검색의 메인 시그널이 되도록.
const BODY_SNIPPET_CHARS = 1500;
function embedInputFor(chunk) {
  const parts = [
    `[${chunk.source}]`,
    chunk.title ? `[${chunk.title}]` : null,
    chunk.keywords && chunk.keywords.length
      ? `keywords: ${chunk.keywords.slice(0, 20).join(', ')}`
      : null,
    chunk.text.slice(0, BODY_SNIPPET_CHARS),
  ];
  return parts.filter(Boolean).join('\n\n');
}

(async () => {
  loadEnvLocal();
  if (!process.env.OPENAI_API_KEY) {
    console.error('OPENAI_API_KEY가 .env.local에 없습니다.');
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(KB_PATH, 'utf8'));
  fs.writeFileSync(BACKUP_PATH, JSON.stringify(raw, null, 2));
  console.log(`backup: ${BACKUP_PATH}`);

  const chunks = raw.chunks || [];
  console.log(`embedding ${chunks.length}청크 with ${MODEL}, batch=${BATCH_SIZE}`);

  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  let done = 0;

  for (let i = 0; i < chunks.length; i += BATCH_SIZE) {
    const batch = chunks.slice(i, i + BATCH_SIZE);
    const inputs = batch.map(embedInputFor);
    process.stdout.write(`  batch ${i}-${i + batch.length - 1} ... `);
    const res = await callWithRetry(() =>
      client.embeddings.create({ model: MODEL, input: inputs }),
    );
    if (res.data.length !== batch.length) {
      throw new Error(
        `batch 응답 수 불일치: req=${batch.length}, res=${res.data.length}`,
      );
    }
    for (let j = 0; j < batch.length; j++) {
      batch[j].embedding = res.data[j].embedding;
    }
    done += batch.length;
    console.log(`${done}/${chunks.length}`);
  }

  const meta = {
    ...raw.meta,
    embedModel: MODEL,
    embeddedAt: new Date().toISOString(),
  };

  fs.writeFileSync(KB_PATH, JSON.stringify({ meta, chunks }, null, 2));
  console.log(`\n=== 완료 ===`);
  console.log(`총 ${chunks.length}청크 임베딩 부여 (${MODEL})`);
  const dim = chunks[0]?.embedding?.length || 0;
  console.log(`dim: ${dim}, 청크당 ~${(dim * 4 / 1024).toFixed(1)}KB`);
})().catch((e) => {
  console.error('실패:', e);
  process.exit(1);
});
