"""Spend limits per budget scope, such as one research run or one simulation."""

import threading
from dataclasses import dataclass, field
from decimal import Decimal


class BudgetExceededError(Exception):
    def __init__(self, scope: str, limit: Decimal, spent: Decimal, needed: Decimal) -> None:
        self.scope, self.limit, self.spent, self.needed = scope, limit, spent, needed
        super().__init__(
            f"Budget '{scope}' would be exceeded: limit ${limit:.4f}, "
            f"spent ${spent:.4f}, this call needs up to ${needed:.4f}"
        )


@dataclass
class Budget:
    scope: str
    limit_usd: Decimal
    spent_usd: Decimal = Decimal(0)
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0

    @property
    def remaining_usd(self) -> Decimal:
        return self.limit_usd - self.spent_usd

    def can_afford(self, worst_case_usd: Decimal) -> bool:
        return self.spent_usd + worst_case_usd <= self.limit_usd

    def ensure(self, worst_case_usd: Decimal) -> None:
        if not self.can_afford(worst_case_usd):
            raise BudgetExceededError(self.scope, self.limit_usd, self.spent_usd, worst_case_usd)

    def record(self, cost_usd: Decimal, tokens_in: int, tokens_out: int) -> None:
        self.spent_usd += cost_usd
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.calls += 1


@dataclass
class BudgetRegistry:
    """In-process ledger. Durable history lives in the llm_calls table."""

    default_limit_usd: Decimal
    _budgets: dict[str, Budget] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, scope: str, limit_usd: Decimal | None = None) -> Budget:
        with self._lock:
            budget = self._budgets.get(scope)
            if budget is None:
                budget = Budget(
                    scope, limit_usd if limit_usd is not None else self.default_limit_usd
                )
                self._budgets[scope] = budget
            elif limit_usd is not None:
                budget.limit_usd = limit_usd
            return budget
