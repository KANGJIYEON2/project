import { Rule, Transaction } from '@/types';

export const patternRules: Rule[] = [
  {
    id: 'PAT-001',
    category: 'pattern',
    name: '정확한 라운드 금액',
    description: '정확한 라운드 금액은 가공경비 의심 패턴입니다.',
    defaultLevel: 'medium',
    detect: (t) =>
      t.type === 'withdrawal' &&
      t.amount >= 1_000_000 &&
      t.amount % 1_000_000 === 0,
    explain: (t) =>
      `${t.amount.toLocaleString()}원은 정확한 라운드 금액으로 가공경비 의심 패턴입니다. 실제 거래 증빙 확인이 필요합니다.`,
    getSuggestion: () =>
      '세금계산서·영수증 등 실거래 증빙 확인 / 거래처 실재 여부 확인',
  },
  {
    id: 'PAT-002',
    category: 'pattern',
    name: '반복 동일 금액 입출금',
    description: '동일 거래 반복은 자금 순환 의심 패턴입니다.',
    defaultLevel: 'medium',
    detect: (t, context) => {
      if (!context?.allTransactions) return false;
      const sameDeals = context.allTransactions.filter(
        (other) =>
          other.id !== t.id &&
          other.description === t.description &&
          other.amount === t.amount
      );
      return sameDeals.length >= 2;
    },
    explain: (t) =>
      `"${t.description}" ${t.amount.toLocaleString()}원이 월 3회 이상 반복됩니다. 자금 순환 의심 패턴으로 계약서·세금계산서 확인이 필요합니다.`,
    getSuggestion: () =>
      '계약서·세금계산서 확인 / 정기 임대료·구독료인지 확인 / 거래처 실재성 검증',
  },
  {
    id: 'PAT-003',
    category: 'pattern',
    name: '신규 거래처 + 큰 금액',
    description: '처음 등장하는 거래처에 큰 금액 출금은 실재성 검증이 필요합니다.',
    defaultLevel: 'medium',
    detect: (t, context) => {
      if (!context?.allTransactions) return false;
      if (t.type !== 'withdrawal' || t.amount <= 5_000_000) return false;
      const others = context.allTransactions.filter(
        (other) => other.id !== t.id && other.description === t.description
      );
      return others.length === 0;
    },
    explain: (t) =>
      `"${t.description}"은 처음 등장하는 거래처이며 ${t.amount.toLocaleString()}원 출금입니다. 거래처 실재성 검증이 필요합니다.`,
    getSuggestion: () =>
      '세금계산서·계약서 보유 확인 / 거래처 사업자등록 확인 / 실재 거래 여부 검증',
  },
  {
    id: 'PAT-004',
    category: 'pattern',
    name: '갑작스런 큰 금액 출금',
    description: '평균 출금액의 5배 이상은 대표자 가지급금 가능성이 있습니다.',
    defaultLevel: 'medium',
    detect: (t, context) => {
      if (!context?.allTransactions) return false;
      if (t.type !== 'withdrawal' || t.amount < 1_000_000) return false;
      const withdrawals = context.allTransactions.filter(
        (other) => other.type === 'withdrawal' && other.id !== t.id
      );
      if (withdrawals.length < 3) return false;
      const avg = withdrawals.reduce((s, w) => s + w.amount, 0) / withdrawals.length;
      return t.amount > avg * 5;
    },
    explain: (t) =>
      `${t.amount.toLocaleString()}원 출금은 평균 출금액의 5배를 초과합니다. 대표자 가지급금 가능성이 있으며 용도 명확화가 필요합니다.`,
    getSuggestion: () =>
      '출금 용도 확인 / 대표자 가지급금 여부 점검 / 증빙 서류 확보',
  },
];
