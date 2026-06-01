import { Transaction } from '@/types';

const FORBIDDEN_FIELDS = ['account', 'balance', 'accountNumber', 'businessId'];

export function validateMasking(data: Record<string, unknown>[]): string[] {
  const violations: string[] = [];
  for (const item of data) {
    for (const field of FORBIDDEN_FIELDS) {
      if (field in item && item[field] !== undefined) {
        violations.push(field);
      }
    }
  }
  return [...new Set(violations)];
}

/**
 * 거래처명에서 개인정보 패턴 마스킹
 * "홍길동에게 이체" → "***에게 이체"
 */
function maskPersonalInfo(text: string): string {
  // 한국 이름 패턴 (2~4글자 한글 + 에게/님/씨/으로 등)
  let masked = text.replace(/([가-힣]{2,4})(에게|님|씨|으로|한테)/g, '***$2');
  // 전화번호 패턴
  masked = masked.replace(/01[0-9]-?\d{3,4}-?\d{4}/g, '***-****-****');
  // 주민등록번호 패턴
  masked = masked.replace(/\d{6}-?[1-4]\d{6}/g, '******-*******');
  return masked;
}

export function maskTransactionsForAI(
  transactions: Transaction[]
): Pick<Transaction, 'id' | 'date' | 'description' | 'amount' | 'type' | 'note'>[] {
  return transactions.map(({ id, date, description, amount, type, note }) => ({
    id,
    date,
    description: maskPersonalInfo(description),
    amount,
    type,
    ...(note ? { note: maskPersonalInfo(note) } : {}),
  }));
}
