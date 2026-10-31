from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
import math
from .models import RiskConfig, Signal


@dataclass(frozen=True)
class ContractRules:
    symbol: str
    min_qty: str
    max_qty: str
    step_size: str
    tick_size: str
    min_notional: str
    contract_size: str = '1'  # Binance USD-M quantity is in base asset units

    def __post_init__(self):
        values = [Decimal(v) for k, v in self.__dict__.items() if k != 'symbol']
        if any(not v.is_finite() or v < 0 for v in values) or any(
                Decimal(v) <= 0 for k,v in self.__dict__.items() if k not in ('symbol','min_notional')):
            raise ValueError('Contract filters must be finite; only an unpublished notional floor may be zero')
        if Decimal(self.min_qty) > Decimal(self.max_qty):
            raise ValueError('Invalid quantity range')

    def quantity(self, amount: float) -> float:
        return float((Decimal(str(amount)) / Decimal(self.step_size)).to_integral_value(
            rounding=ROUND_FLOOR) * Decimal(self.step_size))

    def price(self, value: float, up=False) -> float:
        from decimal import ROUND_CEILING
        return float((Decimal(str(value)) / Decimal(self.tick_size)).to_integral_value(
            rounding=ROUND_CEILING if up else ROUND_FLOOR) * Decimal(self.tick_size))

    def valid(self, quantity: float, price: float) -> bool:
        q = Decimal(str(quantity))
        return (Decimal(self.min_qty) <= q <= Decimal(self.max_qty)
                and q % Decimal(self.step_size) == 0
                and q * Decimal(str(price)) * Decimal(self.contract_size) >= Decimal(self.min_notional))


def fill(price: float, buy: bool, risk: RiskConfig) -> float:
    cost = (risk.spread_bps / 2 + risk.slippage_bps) / 10_000
    return price * (1 + cost if buy else 1 - cost)


def size(equity: float, free_margin: float, entry: float, stop: float,
         rules: ContractRules, risk: RiskConfig) -> float:
    """Never round up to satisfy minimums or increase risk after a loss."""
    unit = float(rules.contract_size)
    # Include adverse stop fill and both fees in the loss budget.
    stop_fill = fill(stop, entry < stop, risk)
    loss = (abs(entry-stop_fill) + risk.fee_rate*(entry+stop_fill)) * unit
    if min(equity, free_margin, entry, stop, loss) <= 0 or not math.isfinite(loss):
        return 0.0
    by_risk = equity * risk.risk_fraction / loss
    by_margin = free_margin / (entry * unit * (1/risk.leverage + risk.fee_rate))
    q = rules.quantity(min(by_risk, by_margin, float(rules.max_qty)))
    return q if rules.valid(q, entry) else 0.0
