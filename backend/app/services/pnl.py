from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Transaction


@dataclass
class PnL:
    total_income: float = 0
    total_expenses: float = 0
    net_profit: float = 0
    profit_margin: float = 0
    income_by_category: dict[str, float] = field(default_factory=dict)
    expense_by_category: dict[str, float] = field(default_factory=dict)
    top_transactions: list[dict] = field(default_factory=list)
    deductible_expenses: float = 0
    count: int = 0


def compute_pnl(transactions: list[Transaction]) -> PnL:
    total_income = 0.0
    total_expenses = 0.0
    deductible = 0.0
    income_by: dict[str, float] = {}
    expense_by: dict[str, float] = {}

    for t in transactions:
        cat = t.category or "uncategorized"
        if t.type == "income":
            total_income += abs(t.amount)
            income_by[cat] = income_by.get(cat, 0) + abs(t.amount)
        else:
            absamt = abs(t.amount)
            total_expenses += absamt
            expense_by[cat] = expense_by.get(cat, 0) + absamt
            if t.tax_deductible:
                deductible += absamt

    net = total_income - total_expenses
    margin = round((net / total_income) * 100, 1) if total_income > 0 else 0.0

    top = sorted(transactions, key=lambda t: abs(t.amount), reverse=True)[:10]
    top_transactions = [{"description": t.description, "amount": t.amount, "date": t.date, "category": t.category or "uncategorized"} for t in top]

    return PnL(
        total_income=round(total_income, 2),
        total_expenses=round(total_expenses, 2),
        net_profit=round(net, 2),
        profit_margin=margin,
        income_by_category={k: round(v, 2) for k, v in income_by.items()},
        expense_by_category={k: round(v, 2) for k, v in expense_by.items()},
        top_transactions=top_transactions,
        deductible_expenses=round(deductible, 2),
        count=len(transactions),
    )
