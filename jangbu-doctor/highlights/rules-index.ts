import { Rule, Transaction, AnalysisResult, AnalysisContext, RiskLevel } from '@/types';
import { entertainmentRules } from './entertainment';
import { vehicleRules } from './vehicle';
import { personalRules } from './personal';
import { patternRules } from './pattern';
import { vatRules } from './vat';
import { expenseRules } from './expense';

export const ALL_RULES: Rule[] = [
  ...entertainmentRules,
  ...personalRules,
  ...vatRules,
  ...vehicleRules,
  ...patternRules,
  ...expenseRules,
];

const LEVEL_PRIORITY: Record<RiskLevel, number> = {
  high: 3,
  medium: 2,
  low: 1,
  safe: 0,
};

function getOverallLevel(levels: RiskLevel[]): RiskLevel {
  if (levels.length === 0) return 'safe';
  return levels.reduce((highest, current) =>
    LEVEL_PRIORITY[current] > LEVEL_PRIORITY[highest] ? current : highest
  );
}

export function runRuleEngine(
  transactions: Transaction[],
  context?: Partial<AnalysisContext>
): Record<string, AnalysisResult> {
  const fullContext: AnalysisContext = {
    allTransactions: transactions,
    ...context,
  };

  const results: Record<string, AnalysisResult> = {};

  for (const t of transactions) {
    const risks = ALL_RULES
      .filter((rule) => rule.enabled !== false && rule.detect(t, fullContext))
      .map((rule) => ({
        ruleId: rule.id,
        level: rule.defaultLevel,
        reason: rule.explain(t),
        category: rule.category,
        legalRef: rule.legalReference,
        suggestion: rule.getSuggestion?.(t),
      }));

    results[t.id] = {
      transaction: t,
      risks,
      overallLevel: getOverallLevel(risks.map((r) => r.level)),
      analyzedAt: new Date().toISOString(),
      aiAnalyzed: false,
      addedToPrescription: false,
      dismissed: false,
    };
  }

  return results;
}
