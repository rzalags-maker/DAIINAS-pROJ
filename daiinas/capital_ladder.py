"""DAIINAS v4 experimental capital-ladder PAPER allocation policy.

Not an order executor, wallet, transfer service, or source of investment return.
All accounting uses deterministic Decimal arithmetic. A hosting ledger must
persist this snapshot ATOMICALLY with actual modeled fees, fills and open risk.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import json


def dec(value):
    """Use decimal strings, integers, or Decimals, never binary money floats."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Money must be an exact decimal string/int/Decimal')
    try:
        amount = Decimal(value)
    except Exception as exc:
        raise ValueError('Invalid decimal amount') from exc
    if not amount.is_finite():
        raise ValueError('Nonfinite amount')
    return amount


@dataclass(frozen=True)
class LadderPolicy:
    activation_total: str = '100'
    activation_reserve: str = '50'
    position_budget: str = '25'
    max_slots: int = 10
    reserve_step: str = '50'
    active_step: str = '50'
    per_trade_planned_risk: str = '0.0025'
    aggregate_planned_risk: str = '0.01'

    def __post_init__(self):
        for field in ('activation_total', 'activation_reserve', 'position_budget',
                      'reserve_step', 'active_step', 'per_trade_planned_risk',
                      'aggregate_planned_risk'):
            if dec(getattr(self, field)) <= 0:
                raise ValueError(f'{field} must be positive')
        if self.max_slots < 2 or self.max_slots > 10:
            raise ValueError('Expected 2..10 available slots')
        if dec(self.activation_total) <= dec(self.activation_reserve):
            raise ValueError('Reserve must be smaller than activation capital')
        if dec(self.activation_total) - dec(self.activation_reserve) < 2 * dec(self.position_budget):
            raise ValueError('Activation must fund the first two slots')
        if dec(self.per_trade_planned_risk) > dec(self.aggregate_planned_risk):
            raise ValueError('Per-position planned risk cannot exceed portfolio cap')


class CapitalLadder:
    """Allocate realized profits; never draw down the protected reserve.

    ACTIVE is the capital allocated to trading; PENDING is profit frozen
    until a complete scaling step; RESERVE is isolated capital; DEFICIT
    exposes losses beyond the active allocation instead of hiding them.
    Physical reserve segregation remains an external obligation.
    """

    def __init__(self, initial_capital, policy=None):
        self.policy = policy or LadderPolicy()
        first = dec(initial_capital)
        if first <= 0:
            raise ValueError('Starting capital must be positive')
        self.starting_total = first
        self.realized_net = Decimal(0)
        self.active = first
        self.reserve = Decimal(0)
        self.pending = Decimal(0)
        self.deficit = Decimal(0)
        self.stage = 'BOOTSTRAP'
        self.next_step = 'RESERVE'
        self.committed_active = Decimal(0)
        self.slot_ceiling = 1  # One candidate slot even at original 8 USDT.
        self._activate_and_scale()
        self._check()

    @property
    def total(self):
        return self.active + self.reserve + self.pending - self.deficit

    def _potential_slots(self, active):
        if self.stage == 'BOOTSTRAP':
            return 1 if active > 0 else 0
        return min(self.policy.max_slots,
                   int(max(Decimal(0), active) // dec(self.policy.position_budget)))

    def _promote(self):
        self.slot_ceiling = self._potential_slots(self.active)

    def _maximum_ramp_active(self):
        return dec(self.policy.position_budget) * self.policy.max_slots

    def _activate_and_scale(self):
        if self.stage == 'BOOTSTRAP' and self.active >= dec(self.policy.activation_total):
            self.reserve = dec(self.policy.activation_reserve)
            self.active -= self.reserve
            self.stage = 'EXPAND'
        if self.stage == 'EXPAND' and self.active >= self._maximum_ramp_active():
            excess = self.active - self._maximum_ramp_active()
            self.active = self._maximum_ramp_active()
            self.committed_active = self.active
            self.stage = 'SCALE'
            self.next_step = 'RESERVE'
            self._scale(excess)
        self._promote()

    def _scale(self, amount):
        self.pending += amount
        while True:
            step = dec(self.policy.reserve_step if self.next_step == 'RESERVE'
                       else self.policy.active_step)
            if self.pending < step:
                break
            self.pending -= step
            if self.next_step == 'RESERVE':
                self.reserve += step
                self.next_step = 'ACTIVE'
            else:
                self.active += step
                self.committed_active += step
                self.next_step = 'RESERVE'

    def realized_result(self, net_pnl):
        """Only settled net P&L including fees/carry; deposits are not P&L."""
        amount = dec(net_pnl)
        self.realized_net += amount
        if amount < 0:
            loss = -amount
            taken = min(loss, self.active)
            self.active -= taken
            self.deficit += loss - taken
            self.slot_ceiling = min(self.slot_ceiling, self._potential_slots(self.active))
        elif amount > 0:
            cover = min(amount, self.deficit)
            self.deficit -= cover
            amount -= cover
            if self.stage == 'SCALE':
                # Recover the last active rung before any new reserve/active
                # profit distribution, even when scaling PENDING already exists.
                restore = min(amount,
                              max(Decimal(0), self.committed_active - self.active))
                self.active += restore
                amount -= restore
                self._scale(amount)
            else:
                self.active += amount
                self._activate_and_scale()
            # Only REALIZED profits restore a slot removed by adverse marks.
            self._promote()
        self._check()
        return self.snapshot()

    def mark_to_market(self, unrealized_pnl, open_positions=0):
        """Unrealized losses deallocate slots; unrealized gains never add any.

        Never execute or invent a closing trade merely to meet this ceiling.
        """
        mark = dec(unrealized_pnl)
        if (not isinstance(open_positions, int) or isinstance(open_positions, bool)
                or open_positions < 0):
            raise ValueError('Invalid open position count')
        effective = max(Decimal(0), self.active + min(Decimal(0), mark))
        self.slot_ceiling = min(self.slot_ceiling, self._potential_slots(effective))
        max_open = min(self.slot_ceiling, self._potential_slots(effective))
        return {
            'allowed_slots': max_open,
            'open_positions': open_positions,
            'free_slots': max(0, max_open - open_positions),
            'excess_open_to_reduce_safely': max(0, open_positions - max_open),
            'block_new_entries': open_positions >= max_open or max_open == 0,
            'marked_trading_budget': str(effective),
            'reserve_untouched': str(self.reserve),
            'manual_safe_exit_required': open_positions > max_open,
        }

    def new_position_risk_budget(self, existing_planned_risk, open_positions,
                                 unrealized_pnl='0'):
        """Planned risk cap only; real gap loss can exceed this ceiling."""
        existing = dec(existing_planned_risk)
        if existing < 0:
            raise ValueError('Existing planned risk cannot be negative')
        caps = self.mark_to_market(unrealized_pnl, open_positions)
        if caps['block_new_entries']:
            return Decimal(0)
        active = dec(caps['marked_trading_budget'])
        available = active * dec(self.policy.aggregate_planned_risk) - existing
        if available <= 0:
            return Decimal(0)
        # Divide remaining aggregate risk among remaining optional slots.
        per_slot_share = available / caps['free_slots']
        return max(Decimal(0),
                   min(active * dec(self.policy.per_trade_planned_risk),
                       per_slot_share))

    def snapshot(self):
        return {
            'starting_total': str(self.starting_total),
            'realized_net': str(self.realized_net),
            'active': str(self.active),
            'reserve': str(self.reserve),
            'pending': str(self.pending),
            'deficit': str(self.deficit),
            'total': str(self.total),
            'stage': self.stage,
            'next_step': self.next_step,
            'committed_active': str(self.committed_active),
            'slot_ceiling': self.slot_ceiling,
            'per_position_budget': str(dec(self.policy.position_budget)),
            'policy': asdict(self.policy),
            'live_orders_enabled': False,
        }

    def export_state(self):
        return json.dumps(self.snapshot(), sort_keys=True, separators=(',', ':'))

    @classmethod
    def restore(cls, encoded):
        """Deterministic restart for PAPER; caller must persist atomically."""
        state = json.loads(encoded)
        policy = LadderPolicy(**state['policy'])
        result = cls(state['starting_total'], policy=policy)
        for key in ('realized_net', 'active', 'reserve', 'pending',
                    'deficit', 'committed_active'):
            setattr(result, key, dec(state[key]))
        for key in ('stage', 'next_step', 'slot_ceiling'):
            setattr(result, key, state[key])
        if (result.stage not in ('BOOTSTRAP', 'EXPAND', 'SCALE')
                or result.next_step not in ('RESERVE', 'ACTIVE')):
            raise ValueError('Invalid stored ladder stage')
        if (not isinstance(result.slot_ceiling, int)
                or not 0 <= result.slot_ceiling <= result.policy.max_slots):
            raise ValueError('Invalid stored slots')
        result._check()
        if result.snapshot() != state:
            raise ValueError('Snapshot mismatch')
        return result

    def _check(self):
        if min(self.active, self.reserve, self.pending, self.deficit) < 0:
            raise AssertionError('Negative allocation not permitted')
        if self.total != self.starting_total + self.realized_net:
            raise AssertionError('Double-counted or missing financial flows')
        if self.stage == 'BOOTSTRAP' and self.reserve != 0:
            raise AssertionError('Bootstrap cannot have allocated reserve')
        if (self.stage != 'BOOTSTRAP'
                and self.reserve < dec(self.policy.activation_reserve)):
            raise AssertionError('Protected reserve was spent')
        if self.slot_ceiling < 0 or self.slot_ceiling > self._potential_slots(self.active):
            raise AssertionError('Overallocated slots')
        if self.stage == 'SCALE' and self.committed_active < self._maximum_ramp_active():
            raise AssertionError('Invalid scale baseline')
