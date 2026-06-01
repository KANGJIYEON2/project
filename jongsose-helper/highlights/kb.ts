// 서버 사이드 전용 — kb.json은 빌드 타임에 번들된다.
// 클라이언트에 KB 전체를 내려보내지 않는 게 목적.
import 'server-only';
import kbRaw from '@/kb.json';
import type { Chunk, KnowledgeBase, Priority } from './types';

// kb.json은 빌드 스크립트(scripts/semantic-regroup.js)가 의미 단위 청크로 생성한다.
const KB = kbRaw as unknown as KnowledgeBase;

const PRIORITY_WEIGHT: Record<Priority, number> = {
  P0: 2.0,
  P1: 1.0,
  P2: 0.5,
  P3: 0.0,
};

// 한국어 조사/어미 stemming (간단)
const KO_PARTICLES =
  /(으로부터|으로서|에서는|에서도|에서|이라는|이라고|이라서|이라|로부터|로서|이라면|라는|라고|이나|이라|에는|에도|에게서|에게|까지|부터|이랑|마다|마저|조차|이|가|을|를|은|는|의|에|도|와|과|로|랑|만|이여|이야|이며|이고)$/;

// 책자에는 안 쓰이지만 사람이 자주 쓰는 표현 — 검색용 동의어 확장
const SYNONYMS: Record<string, string[]> = {
  추계신고: ['단순경비율', '기준경비율', '단순경비율신고', '기준경비율신고', '경비율', '추계'],
  추계: ['단순경비율', '기준경비율', '경비율'],
  '신고 방법': ['신고 절차', '신고서 작성', '홈택스'],
  '신고 절차': ['신고 방법', '신고서 작성'],
  홈택스: ['전자신고', '신고 서비스'],
  근로: ['근로소득'],
  사업: ['사업소득'],
  연금: ['연금소득'],
  이자: ['이자소득'],
  배당: ['배당소득'],
  // 비교 쿼리("A와 B 차이")에서 양쪽 절이 모두 잡히도록 상호 동의어
  단순경비율: ['기준경비율', '추계'],
  기준경비율: ['단순경비율', '추계'],
  // 의역·일상 표현 매핑
  '장부 없이': ['추계', '단순경비율', '기준경비율', '경비율'],
  '장부 안': ['추계', '경비율'],
  '장부를 안': ['추계', '경비율'],
  월급쟁이: ['근로소득', '근로소득자'],
  월급: ['근로소득'],
  직장인: ['근로소득', '근로소득자'],
  알바: ['일용근로', '근로소득'],
  프리랜서: ['사업소득', '인적용역'],
  자영업: ['사업소득'],
  '예금 이자': ['이자소득', '금융소득'],
  '주식 배당': ['배당소득', '금융소득'],
};

function expandQuery(q: string): string {
  let expanded = q;
  for (const [k, vs] of Object.entries(SYNONYMS)) {
    if (q.includes(k)) expanded += ' ' + vs.join(' ');
  }
  return expanded;
}

export function tokenize(q: string): string[] {
  return (q || '')
    .toLowerCase()
    .replace(/[?.,!；;:()\[\]{}"'`~/\\<>=+\-]/g, ' ')
    .split(/\s+/)
    .map((t) => t.replace(KO_PARTICLES, ''))
    .filter((t) => t.length >= 2);
}

// 두 책자가 다루는 주제. 쿼리에 source-specific 키워드가 명시될 때만 그 source에 가산.
const FINANCE_TOPIC_RE = /금융|이자|배당|예금|채권|주식|배당금|이자수익|원천징수|상장|장내|장외|펀드/;
const MANUAL_TOPIC_RE =
  /신고|홈택스|단순경비율|기준경비율|추계|사업소득|근로소득|기타소득|연금소득|경비율|서식|메뉴|입력|작성|로그인|모두채움/;

function sourceAffinity(chunk: Chunk, query: string): number {
  const isFinanceSrc = chunk.source.includes('금융');
  const queryAsksFinance = FINANCE_TOPIC_RE.test(query);
  const queryAsksManual = MANUAL_TOPIC_RE.test(query);

  if (isFinanceSrc) {
    if (queryAsksFinance) return +3.0; // 명시적으로 금융 주제 → 강하게 우선
    if (queryAsksManual && !queryAsksFinance) return -3;
    return 0;
  } else {
    // 매뉴얼
    if (queryAsksFinance && !queryAsksManual) return -2; // 금융만 명시 → 매뉴얼 페널티
    if (queryAsksManual) return +1.0;
    return 0;
  }
}

// 목차/표지 페이지(매뉴얼 p1~3, finance p1~2)는 모든 소득 종류가 압축적으로 등장해
// 점수가 과도하게 잡히기 쉬워서 작은 페널티를 깐다.
// 윈도우 청크는 시작 페이지로 판정한다(예: [1,2,3] → 1).
function tocPenalty(chunk: Chunk): number {
  const first = chunk.pages[0];
  if (chunk.source.includes('매뉴얼') && first <= 3) return -2;
  if (chunk.source.includes('금융') && first <= 2) return -2;
  return 0;
}

function scoreChunk(chunk: Chunk, query: string, tokens: string[]): number {
  let score = 0;
  for (const t of tokens) {
    if (chunk.text.includes(t)) score += 2;
  }
  for (const kw of chunk.keywords || []) {
    if (query.includes(kw)) score += 1.5;
  }
  score += PRIORITY_WEIGHT[chunk.priority] || 0;
  score += sourceAffinity(chunk, query);
  score += tocPenalty(chunk);
  return score;
}

export interface ScoredChunk {
  c: Chunk;
  s: number;
}

export function searchKBDetailed(query: string, k = 4): ScoredChunk[] {
  const expanded = expandQuery(query);
  const tokens = tokenize(expanded);
  if (tokens.length === 0) return [];
  return KB.chunks
    .map((c) => ({ c, s: scoreChunk(c, expanded, tokens) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, k);
}

export function searchKB(query: string, k = 4): Chunk[] {
  return searchKBDetailed(query, k).map((x) => x.c);
}

// ---- Hybrid (embedding + keyword) ----

function cosineSimilarity(a: number[], b: number[]): number {
  let dot = 0;
  let magA = 0;
  let magB = 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    dot += a[i] * b[i];
    magA += a[i] * a[i];
    magB += b[i] * b[i];
  }
  const denom = Math.sqrt(magA) * Math.sqrt(magB);
  return denom === 0 ? 0 : dot / denom;
}

// 2단계 hybrid:
//   Phase 1 — embedding cosine top-N으로 의미 candidate pool 형성
//   Phase 2 — 그 안에서 기존 scoreChunk(keyword+priority+source) + 약한 semantic 가산으로 rerank
// 의역 쿼리는 Phase 1에서 후보로 들어오고, 직접 도메인 쿼리는 Phase 2에서 keyword가 우위.
export interface HybridScoredChunk {
  c: Chunk;
  s: number;
  sim: number;
}

// 청크가 114개 정도라 candidate pool 압축 이득이 적다. 모든 청크에 대해
// 기존 keyword 점수 + semantic 가산을 합산해서 top-k. semantic은 의역/동의어를
// 잡기 위한 보조 신호이고, keyword가 강한 도메인 쿼리는 그쪽이 dominant.
// SEMANTIC_BONUS는 keyword 신호를 흔들지 않게 작게(0~2 정도).
const SEMANTIC_BONUS = 2;

// 인접 페이지(같은 시리즈) 청크 페널티. top-1과 같은 source에서 ±5p 안이면
// 후속 후보 점수에서 차감 → 동일 절 시리즈가 top-k를 독식하지 않게 한다.
// 예: "단순경비율과 기준경비율 차이" 쿼리에서 기준경비율 시리즈 4개 대신
// 단순경비율 절도 한 자리.
const ADJACENT_PENALTY = 6;
const ADJACENT_PAGE_WINDOW = 30;

function isAdjacent(a: Chunk, b: Chunk): boolean {
  if (a.source !== b.source) return false;
  const aMin = Math.min(...a.pages);
  const aMax = Math.max(...a.pages);
  const bMin = Math.min(...b.pages);
  const bMax = Math.max(...b.pages);
  // 페이지 범위가 ADJACENT_PAGE_WINDOW 안에서 인접하거나 겹치면 true
  return aMax + ADJACENT_PAGE_WINDOW >= bMin && bMax + ADJACENT_PAGE_WINDOW >= aMin;
}

export function searchKBHybridDetailed(
  query: string,
  queryEmbed: number[],
  k = 4,
): HybridScoredChunk[] {
  const expanded = expandQuery(query);
  const tokens = tokenize(expanded);

  // 1) 전체 청크 점수
  const all = KB.chunks
    .map((c) => {
      const sim =
        c.embedding && c.embedding.length
          ? cosineSimilarity(queryEmbed, c.embedding)
          : 0;
      const s = scoreChunk(c, expanded, tokens) + sim * SEMANTIC_BONUS;
      return { c, s, sim };
    })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s);

  // 2) MMR 스타일 다양성 reranking — 이미 선택된 청크와 인접하면 페널티 후 재선택
  const picked: HybridScoredChunk[] = [];
  const pool = all.slice(0, 30); // 후보 풀 — 점수 상위 30개에서만 다양성 선택
  while (picked.length < k && pool.length) {
    let bestIdx = -1;
    let bestEff = -Infinity;
    for (let i = 0; i < pool.length; i++) {
      let eff = pool[i].s;
      for (const sel of picked) {
        if (isAdjacent(sel.c, pool[i].c)) eff -= ADJACENT_PENALTY;
      }
      if (eff > bestEff) {
        bestEff = eff;
        bestIdx = i;
      }
    }
    if (bestIdx === -1) break;
    picked.push(pool[bestIdx]);
    pool.splice(bestIdx, 1);
  }
  return picked;
}

export function searchKBHybrid(
  query: string,
  queryEmbed: number[],
  k = 4,
): Chunk[] {
  return searchKBHybridDetailed(query, queryEmbed, k).map((x) => x.c);
}

export function kbMeta() {
  return KB.meta;
}

export function getChunkById(id: string): Chunk | undefined {
  return KB.chunks.find((c) => c.id === id);
}

// 인덱스 페이지용. source별로 그룹화하고 첫 페이지 순으로 정렬.
export function listChunksBySource(): { source: string; chunks: Chunk[] }[] {
  const map = new Map<string, Chunk[]>();
  for (const c of KB.chunks) {
    if (!map.has(c.source)) map.set(c.source, []);
    map.get(c.source)!.push(c);
  }
  return [...map.entries()].map(([source, chunks]) => ({
    source,
    chunks: [...chunks].sort((a, b) => (a.pages[0] || 0) - (b.pages[0] || 0)),
  }));
}

// 같은 source 안에서 이 청크 바로 앞·뒤 청크를 반환. 없으면 undefined.
export function getAdjacentChunks(id: string): {
  prev?: Chunk;
  next?: Chunk;
} {
  const cur = getChunkById(id);
  if (!cur) return {};
  const sameSource = KB.chunks
    .filter((c) => c.source === cur.source)
    .sort((a, b) => (a.pages[0] || 0) - (b.pages[0] || 0));
  const idx = sameSource.findIndex((c) => c.id === id);
  if (idx === -1) return {};
  return {
    prev: idx > 0 ? sameSource[idx - 1] : undefined,
    next: idx < sameSource.length - 1 ? sameSource[idx + 1] : undefined,
  };
}
