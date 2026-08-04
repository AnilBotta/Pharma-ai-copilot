"""Token pricing for cost estimation.

Prices change and are not something this code can discover at runtime, so the
table below is **operator-maintained configuration, not fact**. Two rules follow
from that:

* A model absent from the table yields ``None`` rather than a guessed cost. The
  UI shows "cost unavailable" instead of a confident wrong number. Inventing a
  plausible figure would be the same class of error as inventing a citation.
* Prices can be overridden per deployment through ``OPENAI_PRICING_JSON``
  without a code change.

Figures are USD per million tokens and must be checked against
https://openai.com/api/pricing before being relied on for budgeting.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    """USD per million tokens."""

    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None


#: Verify against current OpenAI pricing before trusting cost figures.
#: Keys are matched by longest prefix, so dated snapshots such as
#: "gpt-5-mini-2025-08-07" resolve to the "gpt-5-mini" entry.
DEFAULT_PRICING: dict[str, ModelPricing] = {
    "gpt-5-nano": ModelPricing(Decimal("0.05"), Decimal("0.40"), Decimal("0.005")),
    "gpt-5-mini": ModelPricing(Decimal("0.25"), Decimal("2.00"), Decimal("0.025")),
    "gpt-5": ModelPricing(Decimal("1.25"), Decimal("10.00"), Decimal("0.125")),
    "gpt-4.1-nano": ModelPricing(Decimal("0.10"), Decimal("0.40"), Decimal("0.025")),
    "gpt-4.1-mini": ModelPricing(Decimal("0.40"), Decimal("1.60"), Decimal("0.10")),
    "gpt-4.1": ModelPricing(Decimal("2.00"), Decimal("8.00"), Decimal("0.50")),
    "gpt-4o-mini": ModelPricing(Decimal("0.15"), Decimal("0.60"), Decimal("0.075")),
    "gpt-4o": ModelPricing(Decimal("2.50"), Decimal("10.00"), Decimal("1.25")),
    "text-embedding-3-small": ModelPricing(Decimal("0.02"), Decimal("0")),
    "text-embedding-3-large": ModelPricing(Decimal("0.13"), Decimal("0")),
}


def _load_overrides() -> dict[str, ModelPricing]:
    raw = os.environ.get("OPENAI_PRICING_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return {
            model: ModelPricing(
                Decimal(str(values["input_per_million"])),
                Decimal(str(values["output_per_million"])),
                (
                    Decimal(str(values["cached_input_per_million"]))
                    if "cached_input_per_million" in values
                    else None
                ),
            )
            for model, values in parsed.items()
        }
    except (ValueError, KeyError, TypeError):
        logger.warning(
            "OPENAI_PRICING_JSON could not be parsed; falling back to built-in "
            "pricing. Costs for overridden models will be estimated from defaults."
        )
        return {}


def get_pricing(model: str) -> ModelPricing | None:
    """Resolve pricing by longest matching prefix, or None if unknown."""
    table = {**DEFAULT_PRICING, **_load_overrides()}
    matches = [key for key in table if model.startswith(key)]
    if not matches:
        return None
    return table[max(matches, key=len)]


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> Decimal | None:
    """Estimated USD cost, or None when the model's pricing is unknown.

    Cached input tokens are billed at a lower rate when the model publishes one,
    so they are subtracted from the full-rate input count rather than
    double-counted.
    """
    pricing = get_pricing(model)
    if pricing is None:
        logger.info("No pricing configured for model %r; cost not estimated.", model)
        return None

    million = Decimal(1_000_000)
    billable_input = max(0, input_tokens - cached_tokens)

    cost = (Decimal(billable_input) / million) * pricing.input_per_million
    cost += (Decimal(output_tokens) / million) * pricing.output_per_million

    if cached_tokens and pricing.cached_input_per_million is not None:
        cost += (Decimal(cached_tokens) / million) * pricing.cached_input_per_million
    elif cached_tokens:
        # No cached rate published: bill at full input rate rather than free,
        # so the estimate errs high instead of understating spend.
        cost += (Decimal(cached_tokens) / million) * pricing.input_per_million

    return cost.quantize(Decimal("0.000001"))
