from __future__ import annotations

from ..config import settings

# Per-1M-token USD list prices, logged with every agent action so the /agents
# dashboard can show cumulative AI spend.
#
# These were hardcoded to Gemini 1.5 Pro while every call actually went to the
# OpenAI-compatible gateway, so the dashboard has always been an estimate. Now
# that the backend is selectable the rate has to follow the model, or moving to
# Gemini Flash would look ~10x more expensive than it is.
#
# Prefix match on the model id, longest first. Unknown models fall back to
# _DEFAULT, which stays deliberately pessimistic — overstating spend is the safer
# error for a number the owner uses to make decisions.
_RATES: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (3.50, 10.50),
    "gemini-1.5-flash": (0.075, 0.30),
    "azure.gpt-4.1": (2.00, 8.00),
    "azure.gpt-4o-mini": (0.15, 0.60),
    "azure.gpt-4o": (2.50, 10.00),
}
_DEFAULT = (3.50, 10.50)


def rates_for(model: str | None) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a model id."""
    name = (model or "").strip().lower()
    if not name:
        return _DEFAULT
    for prefix in sorted(_RATES, key=len, reverse=True):
        if name.startswith(prefix):
            return _RATES[prefix]
    return _DEFAULT


def estimate_cost_usd(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """Estimated USD for one call.

    `model` is optional so the ~30 existing call sites keep working; when it is
    omitted the currently active model is used, which is right for every caller
    that logs a call it just made.
    """
    if model is None:
        model = settings.MODEL_NAME
    in_rate, out_rate = rates_for(model)
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return round(cost, 6)


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
