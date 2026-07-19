from __future__ import annotations

# Approximate Gemini 1.5 Pro pricing (SKILL.md §17). Logged with every agent
# action so the /agents dashboard can show cumulative AI spend.
_INPUT_PER_1M = 3.50
_OUTPUT_PER_1M = 10.50


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens / 1_000_000) * _INPUT_PER_1M + (output_tokens / 1_000_000) * _OUTPUT_PER_1M
    return round(cost, 6)


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))
