"""DAIINAS v4.2 — pure, read-only exchange-context reducer.

PROTOTYPE: consumes normalized snapshots/events supplied by a FUTURE adapter.
It does not authenticate, issue requests, connect to WebSockets or place orders.
All actual exchange observations must be provenance-checked by that adapter.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from copy import deepcopy
import json


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Amounts require exact decimal representation')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Invalid amount') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite amount')
    return result


def required_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Missing {name}')
    return value


@dataclass
class ExchangeMirror:
    """One known account scope; external changes always freeze new entries.

    No privileges and no assumption that unknown orders belong to Bitsgap.
    """
    account_id: str
    account_mode: str
    health: str = 'OFFLINE'
    completed_scopes: set = field(default_factory=set)
    balances: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    positions: dict = field(default_factory=dict)
    fills: dict = field(default_factory=dict)
    known_client_oids: set = field(default_factory=set)
    seen_event_ids: set = field(default_factory=set)
    buffered_events: list = field(default_factory=list)
    alert_reasons: list = field(default_factory=list)
    snapshot_ts_ms: int = 0
    last_event_ts_ms: int = 0
    operator_pause: bool = True

    REQUIRED_SCOPES = frozenset({'balances', 'orders', 'positions', 'fills'})
    MODES = frozenset({'CLASSIC_SPOT', 'CLASSIC_FUTURES', 'UTA'})
    SAFE_STATUSES = frozenset({'OFFLINE', 'SYNCING', 'RECONCILED_READONLY',
                               'EXTERNAL_INTERVENTION', 'DEGRADED'})

    def __post_init__(self):
        required_string(self.account_id, 'account_id')
        if self.account_mode not in self.MODES:
            raise ValueError('Account mode must be explicit, never guessed')

    def start_sync(self):
        self.health = 'SYNCING'
        self.completed_scopes.clear()
        self.balances.clear()
        self.orders.clear()
        self.positions.clear()
        self.fills.clear()
        self.buffered_events.clear()
        self.alert_reasons.clear()
        self.snapshot_ts_ms = 0
        self.last_event_ts_ms = 0
        self.operator_pause = True

    def register_client_oid(self, value):
        """Inventory only: does not authorize creating a real order."""
        self.known_client_oids.add(required_string(value, 'clientOid'))

    def _scope_check(self, account_id):
        if account_id != self.account_id:
            self.degrade('account identity conflict')
            raise ValueError('Event/snapshot from unrelated account')

    @staticmethod
    def _timestamp(value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError('Expected positive normalized millisecond timestamp')
        return value

    def ingest_snapshot(self, *, scope, account_id, timestamp_ms, records):
        if self.health != 'SYNCING':
            raise RuntimeError('Complete snapshot is only valid during explicit synchronization')
        if scope not in self.REQUIRED_SCOPES or scope in self.completed_scopes:
            raise ValueError('Unknown or duplicate snapshot scope')
        self._scope_check(account_id)
        ts = self._timestamp(timestamp_ms)
        if not isinstance(records, list):
            raise ValueError('Snapshot records must be complete list')
        target = {}
        for obj in records:
            if not isinstance(obj, dict):
                raise ValueError('Invalid snapshot object')
            key = required_string(obj.get('id'), 'record id')
            if key in target:
                raise ValueError('Duplicate object in snapshot')
            item = dict(obj)
            item['_observed_ms'] = ts
            if scope == 'balances':
                amount(item.get('free'))
                amount(item.get('locked', '0'))
            if scope == 'orders':
                item['ownership'] = self.classify(item)
            target[key] = item
        setattr(self, scope, target)
        self.completed_scopes.add(scope)
        self.snapshot_ts_ms = max(self.snapshot_ts_ms, ts)

    def classify(self, obj):
        """External origin cannot be distinguished as manual vs Bitsgap."""
        coid = obj.get('clientOid')
        return ('DAIINAS' if coid and coid in self.known_client_oids
                else 'UNKNOWN_EXTERNAL')

    def ingest_event(self, event):
        if not isinstance(event, dict):
            raise ValueError('Expected normalized exchange event')
        self._scope_check(event.get('account_id'))
        event_id = required_string(event.get('id'), 'event id')
        self._timestamp(event.get('timestamp_ms'))
        if event_id in self.seen_event_ids:
            return False
        if event.get('scope') not in self.REQUIRED_SCOPES:
            self.degrade('unknown private event scope')
            raise ValueError('Unknown event scope')
        if self.health == 'SYNCING':
            self.buffered_events.append(deepcopy(event))
            self.seen_event_ids.add(event_id)
            return True
        if self.health not in ('RECONCILED_READONLY', 'EXTERNAL_INTERVENTION'):
            raise RuntimeError('Private account not reconciled; event cannot mutate account view')
        self.seen_event_ids.add(event_id)
        self._apply(event)
        return True

    def _apply(self, event):
        scope = event['scope']
        obj = deepcopy(event.get('record'))
        if not isinstance(obj, dict):
            self.degrade('malformed private event')
            raise ValueError('Expected normalized full-state event record')
        rid = required_string(obj.get('id'), 'record id')
        observed = self._timestamp(event['timestamp_ms'])
        target = getattr(self, scope)
        previous = target.get(rid)
        if previous and observed < previous['_observed_ms']:
            return
        if scope == 'balances':
            amount(obj.get('free'))
            amount(obj.get('locked', '0'))
        if scope == 'orders':
            obj['ownership'] = self.classify(obj)
        if event.get('action') == 'DELETE':
            target.pop(rid, None)
        elif event.get('action') == 'UPSERT':
            obj['_observed_ms'] = observed
            target[rid] = obj
        else:
            self.degrade('unrecognized private event action')
            raise ValueError('Unknown event action')
        self.last_event_ts_ms = max(self.last_event_ts_ms, observed)
        if (scope in ('orders', 'positions')
                and (scope != 'orders' or self.classify(obj) != 'DAIINAS')):
            self.external_intervention(f'{scope} updated by unowned/unknown actor: {rid}')
        elif scope == 'balances':
            self.external_intervention(f'balance changed; origin must be reconciled: {rid}')

    def complete_sync(self):
        if self.health != 'SYNCING' or self.completed_scopes != self.REQUIRED_SCOPES:
            raise RuntimeError('Incomplete initial account snapshots')
        self.health = 'RECONCILED_READONLY'
        buffered = sorted(self.buffered_events, key=lambda x: (x['timestamp_ms'], x['id']))
        self.buffered_events.clear()
        for event in buffered:
            self._apply(event)
        if any(obj.get('ownership') == 'UNKNOWN_EXTERNAL'
               for obj in self.orders.values()):
            self.external_intervention('unowned open orders are present')
        return self.status()

    def external_intervention(self, explanation):
        if explanation not in self.alert_reasons:
            self.alert_reasons.append(explanation)
        self.health = 'EXTERNAL_INTERVENTION'
        self.operator_pause = True

    def degrade(self, explanation):
        if explanation not in self.alert_reasons:
            self.alert_reasons.append(explanation)
        self.health = 'DEGRADED'
        self.operator_pause = True

    def resume_readonly(self):
        """No override can grant live-order privileges."""
        if self.health not in ('RECONCILED_READONLY', 'EXTERNAL_INTERVENTION'):
            raise RuntimeError('Reconcile account before resuming observations')
        self.health = 'RECONCILED_READONLY'
        self.operator_pause = False
        return self.status()

    def status(self):
        return {'account_id': self.account_id, 'account_mode': self.account_mode,
                'health': self.health, 'scopes': sorted(self.completed_scopes),
                'orders': len(self.orders), 'positions': len(self.positions),
                'known_client_oids': len(self.known_client_oids),
                'external_or_unknown_orders': sum(
                    x.get('ownership') != 'DAIINAS' for x in self.orders.values()),
                'alert_reasons': list(self.alert_reasons),
                'block_new_entries': True,  # Actual order gateway is NOT implemented.
                'execution_enabled': False, 'operator_pause': self.operator_pause,
                'snapshot_ts_ms': self.snapshot_ts_ms,
                'last_event_ts_ms': self.last_event_ts_ms}

    def preview_order(self, *_args, **_kwargs):
        return {'allowed': False, 'reason': 'EXECUTION_DISABLED_READONLY_PROTO'}

    def place_order(self, *_args, **_kwargs):
        raise PermissionError('LIVE ORDERS DISABLED; no trading transport exists')

    def cancel_order(self, *_args, **_kwargs):
        raise PermissionError('LIVE ORDERS DISABLED; no trading transport exists')

    def transfer(self, *_args, **_kwargs):
        raise PermissionError('Transfers are never permitted by this component')
