from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Model pricing
# ---------------------------------------------------------------------------
# Indicative prices in USD per 1,000,000 tokens. These are PLACEHOLDER defaults
# and almost certainly differ from your Azure contract. Override them with the
# MODEL_PRICING_JSON environment variable (set it in .env), for example:
#
#   MODEL_PRICING_JSON={"gpt-5.4-nano":{"input":0.10,"output":0.40},
#                       "gpt-5.4-mini":{"input":0.25,"output":2.00},
#                       "gpt-5.4":{"input":1.25,"output":10.00},
#                       "text-embedding-3-large":{"input":0.13,"output":0.0}}
#
# A deployment is matched to a price by the LONGEST key that is a
# case-insensitive substring of the deployment name (so "gpt-5.4-nano" matches
# the nano entry before the shorter "gpt-5.4" entry).
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4-nano": {"input": 0.10, "output": 0.40},
    "gpt-5.4-mini": {"input": 0.25, "output": 2.00},
    "gpt-5.4": {"input": 1.25, "output": 10.00},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}

_FALLBACK_PRICE = {"input": 0.0, "output": 0.0}


def load_pricing() -> dict[str, dict[str, float]]:
    """Return the pricing table, overlaying MODEL_PRICING_JSON onto the defaults."""
    pricing = {k: dict(v) for k, v in DEFAULT_PRICING.items()}
    raw = os.environ.get("MODEL_PRICING_JSON", "").strip()
    if raw:
        try:
            override = json.loads(raw)
            for model, prices in override.items():
                entry = pricing.get(model, {"input": 0.0, "output": 0.0})
                entry.update({k: float(v) for k, v in prices.items()})
                pricing[model] = entry
        except Exception:
            # Malformed override must never crash a run; keep the defaults.
            pass
    return pricing


def price_for(deployment: str, pricing: dict[str, dict[str, float]] | None = None) -> dict[str, float]:
    """Match a deployment name to a price entry by longest substring key."""
    pricing = pricing or load_pricing()
    name = (deployment or "").lower()
    best_key = ""
    for key in pricing:
        if key.lower() in name and len(key) > len(best_key):
            best_key = key
    return pricing.get(best_key, _FALLBACK_PRICE)


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------
@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageTracker:
    """Thread-safe accumulator of token usage per deployment name.

    Pairwise LLM calls run in parallel, so record() must be safe to call from
    multiple worker threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_model: dict[str, ModelUsage] = {}

    def record(self, model: str, *, input_tokens: int, output_tokens: int = 0, calls: int = 1) -> None:
        if not model:
            model = "unknown"
        with self._lock:
            usage = self._by_model.setdefault(model, ModelUsage())
            usage.calls += calls
            usage.input_tokens += int(input_tokens or 0)
            usage.output_tokens += int(output_tokens or 0)

    def snapshot(self) -> dict[str, ModelUsage]:
        with self._lock:
            return {m: ModelUsage(u.calls, u.input_tokens, u.output_tokens) for m, u in self._by_model.items()}

    def is_empty(self) -> bool:
        with self._lock:
            return not self._by_model


# ---------------------------------------------------------------------------
# Cost estimation and reporting
# ---------------------------------------------------------------------------
def estimate_cost(tracker: UsageTracker, pricing: dict[str, dict[str, float]] | None = None) -> tuple[list[dict], float]:
    """Return a per-model cost breakdown and the grand total in USD."""
    pricing = pricing or load_pricing()
    rows: list[dict] = []
    total = 0.0
    for model, usage in sorted(tracker.snapshot().items()):
        price = price_for(model, pricing)
        cost = usage.input_tokens / 1_000_000 * price["input"] + usage.output_tokens / 1_000_000 * price["output"]
        total += cost
        rows.append({
            "model": model,
            "calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "input_price_per_1m": price["input"],
            "output_price_per_1m": price["output"],
            "cost_usd": round(cost, 4),
        })
    return rows, round(total, 4)


def format_cost_report(rows: list[dict], total: float) -> str:
    """Render the cost breakdown as an aligned plain-text table."""
    if not rows:
        return "=== Run cost ===\nNo LLM usage recorded (dry run or fully cached run)."
    header = f"{'Model':<26} {'Calls':>7} {'In tokens':>12} {'Out tokens':>12} {'Cost (USD)':>12}"
    lines = ["=== Run cost (estimated) ===", header, "-" * len(header)]
    tot_calls = sum(r["calls"] for r in rows)
    tot_in = sum(r["input_tokens"] for r in rows)
    tot_out = sum(r["output_tokens"] for r in rows)
    for r in rows:
        lines.append(f"{r['model']:<26} {r['calls']:>7} {r['input_tokens']:>12,} {r['output_tokens']:>12,} {r['cost_usd']:>12.4f}")
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<26} {tot_calls:>7} {tot_in:>12,} {tot_out:>12,} {total:>12.4f}")
    lines.append("Prices are indicative — set MODEL_PRICING_JSON in .env for your real Azure rates.")
    return "\n".join(lines)
