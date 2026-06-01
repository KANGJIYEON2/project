import { Rule } from '@/types';
import { ENTERTAINMENT_KEYWORDS, CONDOLENCE_KEYWORDS } from './keywords';

function matchKeyword(text: string, keywords: string[]): boolean {
  const upper = text.toUpperCase();
  return keywords.some(k => upper.includes(k.toUpperCase()));
}

const golfKeywords = ['골프', '컨트리클럽', 'CC', 'G.C', '골프클럽', '골프장'];
const nightlifeKeywords = ['유흥', '룸살롱', '단란주점', '노래방', '가라오케', '클럽', 'CLUB', '호스트'];

export const entertainmentRules: Rule[] = [
  {
    id: 'ENT-001',
    category: 'entertainment',
    name: '골프장·컨트리클럽 키워드',
    description: '골프장 결제는 접대비 분류 검토가 필요합니다.',
    defaultLevel: 'high',
    legalReference: '법인세법 제25조 (접대비)',
    detect: (t) => matchKeyword(t.description, golfKeywords),
    explain: (t) =>
      `"${t.description}"에서 골프장 관련 키워드가 감지되었습니다. 접대비 분류 검토가 필요하며, 한도 초과 시 손금불산입 위험이 있습니다.`,
    getSuggestion: () =>
      '영수증·참석자 명단 확보 / 거래처 관계자 동반 여부 확인 / 접대비 한도 누적 점검',
  },
  {
    id: 'ENT-002',
    category: 'entertainment',
    name: '유흥주점·룸살롱 키워드',
    description: '유흥업소 결제는 접대비 한도 및 매입세액 불공제 검토가 필요합니다.',
    defaultLevel: 'high',
    legalReference: '법인세법 제25조 + 부가가치세법 제39조',
    detect: (t) => matchKeyword(t.description, nightlifeKeywords),
    explain: (t) =>
      `"${t.description}"에서 유흥업소 관련 키워드가 감지되었습니다. 접대비 한도 초과 시 손금불산입, 부가세 매입세액 불공제 대상일 수 있습니다.`,
    getSuggestion: () =>
      '접대비 한도 누적 점검 / 매입세액 불공제 여부 확인 / 업무 관련성 입증 자료 확보',
  },
  {
    id: 'ENT-003',
    category: 'entertainment',
    name: '접대비 한도 초과 의심',
    description: '단일 거래 100만원 초과로 한도 검토가 필요합니다.',
    defaultLevel: 'medium',
    legalReference: '법인세법 제25조 (접대비 한도)',
    detect: (t) =>
      t.amount > 1_000_000 &&
      t.type === 'withdrawal' &&
      matchKeyword(t.description, ENTERTAINMENT_KEYWORDS),
    explain: (t) =>
      `${t.amount.toLocaleString()}원으로 단일 접대비 거래가 100만원을 초과합니다. 중소기업 한도(소득금액 × 0.3% + 연 1,200만원) 검토가 필요합니다.`,
    getSuggestion: () =>
      '연간 접대비 누적액 확인 / 한도 초과 여부 계산 / 세무사와 한도 검토',
  },
  {
    id: 'ENT-004',
    category: 'entertainment',
    name: '경조사비 한도 초과',
    description: '경조사비 1회 20만원 초과 시 일반 접대비로 재분류될 수 있습니다.',
    defaultLevel: 'medium',
    legalReference: '법인세법 시행령 제42조 (경조사비)',
    detect: (t) =>
      t.amount > 200_000 &&
      t.type === 'withdrawal' &&
      matchKeyword(t.description, CONDOLENCE_KEYWORDS),
    explain: (t) =>
      `경조사비 ${t.amount.toLocaleString()}원으로 1회 20만원을 초과합니다. 초과분은 일반 접대비로 재분류될 수 있습니다.`,
    getSuggestion: () =>
      '경조사 관련 증빙(청첩장, 부고 등) 보관 / 접대비 한도 누적 점검',
  },
];
