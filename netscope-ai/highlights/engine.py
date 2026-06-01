from typing import List
from datetime import datetime, UTC

from src.analysis.rule_engine import (
    RuleEngine,
    default_rules,
    aggregate,
    RuleLog,
)
from src.analysis.gpt_analyzer import GPTAnalyzer
from src.schemas.enums import SeverityLevel, AnalysisStrategy, LogLevel
from src.log.models import Log


class AnalysisEngine:
    def __init__(self):
        self.rule_engine = RuleEngine(default_rules())
        self.gpt = GPTAnalyzer()

    # ======================================================
    # 1️⃣ Project / DB 기반 분석
    # ======================================================
    def analyze(self, logs: List[Log], strategy: AnalysisStrategy):
        return self._analyze_internal(logs, strategy)

    # ======================================================
    # 2️⃣ Test 전용 분석 (DB ❌)
    # ======================================================
    def analyze_test(
        self,
        *,
        messages: List[str],
        strategy: AnalysisStrategy,
    ):
        now = datetime.now(UTC)

        logs = [
            RuleLog(
                source="test",
                message=msg,
                level=self._infer_level(msg),
                timestamp=now,
            )
            for msg in messages
        ]

        return self._analyze_internal(logs, strategy)

    # ======================================================
    # 공통 분석 파이프라인
    # ======================================================
    def _analyze_internal(self, logs, strategy: AnalysisStrategy):
        # 1️⃣ Rule Engine
        matches = self.rule_engine.run(logs)

        rule_result = aggregate(matches)
        result = dict(rule_result)

        # 🔥 signals 표준화 (여기가 핵심)
        signals = [
            {
                "rule_id": m.rule_id,
                "score": m.score,
            }
            for m in matches
        ]

        strategy_used = "rule"
        report_sections: list[dict] = []

        # 2️⃣ GPT 보강
        if strategy == AnalysisStrategy.GPT and self.gpt.is_enabled():
            g = self.gpt.analyze(
                logs=logs,
                rule_summary=result["summary"],
                rule_causes=result["suspected_causes"],
                rule_actions=result["recommended_actions"],
            )

            strategy_used = "gpt"

            bonus = float(g.get("confidence_bonus", 0.0))
            result["confidence"] = min(result["confidence"] + bonus, 1.0)

            result["suspected_causes"] = list(
                dict.fromkeys(
                    result["suspected_causes"]
                    + g.get("suspected_causes", [])
                )
            )

            result["recommended_actions"] = list(
                dict.fromkeys(
                    result["recommended_actions"]
                    + g.get("recommended_actions", [])
                )
            )

            result["summary"] = g.get("summary", result["summary"])
            report_sections = g.get("sections", []) or []

        # 3️⃣ Severity 계산 (confidence + 룰 조합 기반)
        confidence = result["confidence"]
        matched_ids = {s["rule_id"] for s in signals}

        # CRITICAL 자동 승격: 치명적 룰 조합
        critical_combos = [
            {"R020", "R007"},   # 타임아웃→크래시 + OOM
            {"R019", "R022"},   # 에러 버스트 + 다중 source
            {"R024", "R022"},   # 연결실패→재시작 + 다중 source
        ]
        has_critical = any(combo <= matched_ids for combo in critical_combos)

        # HIGH 강제 승격: 고위험 단독 룰
        high_force_rules = {"R013", "R007", "R020"}  # 크래시, OOM, 타임아웃→크래시

        if has_critical or (confidence >= 0.85 and len(matched_ids) >= 5):
            severity = SeverityLevel.CRITICAL
        elif confidence >= 0.75 or (matched_ids & high_force_rules):
            severity = SeverityLevel.HIGH
        elif confidence >= 0.45:
            severity = SeverityLevel.MEDIUM
        else:
            severity = SeverityLevel.LOW

        # 4️⃣ 안정성 보호
        if not result["suspected_causes"]:
            result["suspected_causes"] = ["명확한 패턴 미검출 (추가 로그 필요)"]

        if not result["recommended_actions"]:
            result["recommended_actions"] = ["추가 로그 수집 후 재분석 권장"]

        # ======================================================
        # ✅ 최종 반환 (계약 고정)
        # ======================================================
        return {
            "summary": result["summary"],
            "severity": severity,
            "confidence": result["confidence"],
            "suspected_causes": result["suspected_causes"],
            "recommended_actions": result["recommended_actions"],
            "matched_rules": list({s["rule_id"] for s in signals}),
            "signals": signals,                     # 🔥 이제 항상 있음
            "report_sections": report_sections,     # 🔥 GPT 보고서 본문 (rule-only면 [])
            "strategy_used": strategy_used,
        }

    # --------------------------------------------------
    # Test 로그 레벨 추론
    # --------------------------------------------------
    def _infer_level(self, message: str) -> LogLevel:
        upper = message.upper()
        if "ERROR" in upper:
            return LogLevel.ERROR
        if "WARN" in upper:
            return LogLevel.WARN
        if "DEBUG" in upper:
            return LogLevel.DEBUG
        return LogLevel.INFO
