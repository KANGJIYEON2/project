/**
 * RAG Retriever: 거래 정보를 기반으로 관련 법령 조문을 검색
 * 키워드 매칭 + 태그 기반 검색으로 관련 조문을 찾아 LLM 컨텍스트에 주입
 */

import lawKnowledge from './law-knowledge.json';

interface LawArticle {
  lawName: string;
  mst: string;
  jo: string;
  label: string;
  tags: string[];
  articleNo: string;
  content: string;
  paragraphs: { number: string; content: string; subItems?: { number: string; content: string }[] }[];
  enforcementDate: string;
  fullText?: string;
}

const articles = lawKnowledge as LawArticle[];

// 거래 키워드 → 관련 태그 매핑
const KEYWORD_TAG_MAP: Record<string, string[]> = {
  // 접대비 관련
  '골프': ['접대비', '기업업무추진비', '매입세액불공제'],
  '컨트리클럽': ['접대비', '기업업무추진비'],
  '유흥': ['접대비', '매입세액불공제', '유흥'],
  '룸살롱': ['접대비', '매입세액불공제'],
  '노래방': ['접대비'],
  '한정식': ['접대비'],
  '오마카세': ['접대비'],
  '클럽': ['접대비'],
  '가라오케': ['접대비'],

  // 개인사용 의심
  '백화점': ['업무무관', '개인사용', '비용불인정'],
  '면세점': ['업무무관', '개인사용'],
  '미용실': ['업무무관', '개인사용'],
  '헤어샵': ['업무무관', '개인사용'],
  '네일샵': ['업무무관', '개인사용'],
  '스파': ['업무무관', '개인사용'],
  '의류': ['업무무관', '개인사용'],
  '옷': ['업무무관', '개인사용'],

  // 차량
  '주유': ['차량', '승용차', '운행기록부'],
  '주유소': ['차량', '승용차'],
  '톨게이트': ['차량', '승용차'],
  '하이패스': ['차량', '승용차'],
  '카센터': ['차량', '감가상각'],
  '정비': ['차량'],
  '타이어': ['차량'],

  // 경조사
  '축의금': ['경조사', '접대비'],
  '조의금': ['경조사', '접대비'],
  '화환': ['경조사'],

  // 부가세
  '현금영수증': ['매입세액', '간이영수증'],
  '간이영수증': ['간이영수증', '매입세액불공제'],

  // 기부금
  '기부': ['기부금'],
  '후원': ['기부금'],
  '성금': ['기부금'],

  // 통신비 등
  'SKT': ['비용', '손금'],
  'KT': ['비용', '손금'],
  'LG U+': ['비용', '손금'],
};

// 금액 기반 태그
function getAmountTags(amount: number, type: 'deposit' | 'withdrawal'): string[] {
  const tags: string[] = [];
  if (type === 'withdrawal') {
    if (amount > 1_000_000) tags.push('접대비', '한도');
    if (amount > 5_000_000) tags.push('과다경비');
    if (amount % 1_000_000 === 0 && amount >= 1_000_000) tags.push('가공경비');
  }
  return tags;
}

/**
 * 거래 정보에서 관련 태그를 추출
 */
function extractTags(description: string, amount: number, type: 'deposit' | 'withdrawal'): string[] {
  const tags = new Set<string>();

  // 키워드 매칭
  const upperDesc = description.toUpperCase();
  for (const [keyword, relatedTags] of Object.entries(KEYWORD_TAG_MAP)) {
    if (upperDesc.includes(keyword.toUpperCase())) {
      relatedTags.forEach((t) => tags.add(t));
    }
  }

  // 금액 기반
  getAmountTags(amount, type).forEach((t) => tags.add(t));

  // 기본 태그 (출금이면 비용 관련 항상 포함)
  if (type === 'withdrawal') {
    tags.add('손금');
    tags.add('비용');
  }

  return [...tags];
}

/**
 * 관련 조문 검색 (태그 유사도 기반)
 */
export function retrieveRelevantArticles(
  description: string,
  amount: number,
  type: 'deposit' | 'withdrawal',
  maxResults: number = 8
): LawArticle[] {
  const queryTags = extractTags(description, amount, type);
  if (queryTags.length === 0) return [];

  // 태그 매칭 점수 계산
  const scored = articles.map((article) => {
    let score = 0;
    for (const tag of queryTags) {
      if (article.tags.some((t) => t.includes(tag) || tag.includes(t))) {
        score += 2;
      }
    }

    // 조문 내용에서 키워드 직접 매칭 (보너스)
    const fullText = article.fullText || [
      article.content,
      ...article.paragraphs.map((p) => p.content),
    ].join(' ');

    const descWords = description.split(/\s+/);
    for (const word of descWords) {
      if (word.length >= 2 && fullText.includes(word)) {
        score += 1;
      }
    }

    return { article, score };
  });

  return scored
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, maxResults)
    .map((s) => s.article);
}

/**
 * 거래 목록에 대해 관련 법령을 모아서 LLM 컨텍스트용 텍스트로 변환
 */
export function buildLawContext(
  transactions: { description: string; amount: number; type: 'deposit' | 'withdrawal' }[]
): string {
  const allArticles = new Map<string, LawArticle>();

  for (const t of transactions) {
    const relevant = retrieveRelevantArticles(t.description, t.amount, t.type, 5);
    for (const art of relevant) {
      allArticles.set(`${art.lawName}-${art.jo}`, art);
    }
  }

  if (allArticles.size === 0) return '';

  const parts: string[] = ['[참고 법령 원문]'];

  for (const art of allArticles.values()) {
    parts.push(`\n### ${art.lawName} ${art.label}`);
    parts.push(`(시행일: ${art.enforcementDate})`);

    if (art.content) {
      parts.push(art.content);
    }

    for (const p of art.paragraphs) {
      const paraText = p.content.length > 500 ? p.content.slice(0, 500) + '...' : p.content;
      parts.push(`${p.number} ${paraText}`);

      if (p.subItems) {
        for (const sub of p.subItems.slice(0, 5)) {
          parts.push(`  ${sub.number} ${sub.content}`);
        }
        if (p.subItems.length > 5) {
          parts.push(`  ... 외 ${p.subItems.length - 5}호`);
        }
      }
    }
  }

  return parts.join('\n');
}
