from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Literal


OptionType = Literal["call", "put"]
Direction = Literal["up", "down"]
Behavior = Literal["in", "out"]
Monitoring = Literal["continuous", "daily_close", "weekly", "monthly", "maturity_only"]


@dataclass(frozen=True)
class BarrierContract:
    option_type: OptionType
    direction: Direction
    behavior: Behavior
    spot: float
    strike: float
    barrier: float
    valuation_date: date
    expiration_date: date
    rate: float
    dividend_yield: float
    volatility: float
    quantity: float = 1.0
    multiplier: float = 1.0
    rebate: float = 0.0
    rebate_timing: str = "expiry"
    monitoring: Monitoring = "continuous"
    barrier_status: str = "not_triggered"
    paths: int = 50_000
    seed: int = 42
    calculate_greeks: bool = False

    @property
    def years(self) -> float:
        return (self.expiration_date - self.valuation_date).days / 365.0

    def changed(self, **changes):
        return replace(self, **changes)

    def as_dict(self):
        values = asdict(self)
        values["valuation_date"] = self.valuation_date.isoformat()
        values["expiration_date"] = self.expiration_date.isoformat()
        return values


@dataclass(frozen=True)
class MarketLeg:
    strike: float
    quantity_ratio: float = 1.0
