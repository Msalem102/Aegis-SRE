"""
Aegis SRE - Token Pricing & Task Cost Accounting Engine.
Calculates token consumption, financial cost, and enterprise ROI for autonomous remediation tasks
using official Meta Model API pricing for Muse Spark (muse-spark-1.2).
"""

from typing import Dict, Any, Optional
import os


class CostTracker:
    # Official Meta Model API Pricing for Muse Spark (Standard Private Tier)
    # Rates per 1,000,000 tokens
    DEFAULT_INPUT_PRICE_PER_M = 1.25    # $1.25 / 1M prompt tokens
    DEFAULT_OUTPUT_PRICE_PER_M = 4.25   # $4.25 / 1M completion tokens

    # Average human SRE operational benchmark for comparison
    AVERAGE_SRE_HOURLY_RATE = 120.00    # $120/hr (~$2.00/minute)
    AVERAGE_MANUAL_TRIAGE_MINUTES = 45   # Average MTTR for Sev-1 DB/API outage = $90.00

    def __init__(self, model_name: str = "muse-spark-1.2"):
        self.model_name = model_name
        self.input_price_per_m = float(os.getenv("META_INPUT_PRICE_PER_M", self.DEFAULT_INPUT_PRICE_PER_M))
        self.output_price_per_m = float(os.getenv("META_OUTPUT_PRICE_PER_M", self.DEFAULT_OUTPUT_PRICE_PER_M))

        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.call_records = []

    def record_usage(self, prompt_tokens: int, completion_tokens: int, task_name: str = "llm_call") -> Dict[str, Any]:
        """Records token usage from a model call and calculates its financial cost."""
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens

        input_cost = (prompt_tokens / 1_000_000.0) * self.input_price_per_m
        output_cost = (completion_tokens / 1_000_000.0) * self.output_price_per_m
        total_call_cost = input_cost + output_cost

        record = {
            "task_name": task_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "input_cost_usd": input_cost,
            "output_cost_usd": output_cost,
            "total_cost_usd": total_call_cost
        }
        self.call_records.append(record)
        return record

    def estimate_tokens_from_text(self, text: str) -> int:
        """Approximates token count for offline/mock simulation (~4 chars per token)."""
        return max(1, len(text) // 4)

    def get_task_summary(self) -> Dict[str, Any]:
        """Calculates total incident remediation financial cost and SRE ROI metrics."""
        total_tokens = self.total_prompt_tokens + self.total_completion_tokens
        input_cost = (self.total_prompt_tokens / 1_000_000.0) * self.input_price_per_m
        output_cost = (self.total_completion_tokens / 1_000_000.0) * self.output_price_per_m
        total_cost_usd = input_cost + output_cost

        manual_engineer_cost = (self.AVERAGE_SRE_HOURLY_RATE / 60.0) * self.AVERAGE_MANUAL_TRIAGE_MINUTES
        cost_savings_pct = (
            ((manual_engineer_cost - total_cost_usd) / manual_engineer_cost) * 100.0
            if manual_engineer_cost > 0 else 0.0
        )

        return {
            "model": self.model_name,
            "rates_per_million": {
                "input_tokens_usd": self.input_price_per_m,
                "output_tokens_usd": self.output_price_per_m
            },
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": total_tokens,
            "input_cost_usd": round(input_cost, 6),
            "output_cost_usd": round(output_cost, 6),
            "total_cost_usd": round(total_cost_usd, 6),
            "total_cost_formatted": f"${total_cost_usd:.4f}",
            "roi_comparison": {
                "manual_sre_triage_cost_usd": manual_engineer_cost,
                "aegis_remediation_cost_usd": round(total_cost_usd, 4),
                "operational_cost_reduction_percent": round(cost_savings_pct, 2)
            }
        }
