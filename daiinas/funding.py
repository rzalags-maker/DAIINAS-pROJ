"""Typed opening provenance and future read-only snapshot contract. No network IO."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from .capital_ladder import dec

PAPER_SCOPE='FUNDED_V4_PAPER_USDT_PERPETUAL'


def paper_funding(amount,*,account_id,source_reference,timestamp_ms):
    """Caller explicitly names a hypothetical seed; never a verified balance."""
    return {'kind':'owner_confirmed_paper_scenario','account_id':account_id,'scope':PAPER_SCOPE,
            'currency':'USDT','amount':str(dec(str(amount))),'timestamp_ms':timestamp_ms,
            'source_reference':source_reference,'source_evidence':'Explicit hypothetical PAPER scenario; no exchange balance verified.'}


def validate_funding(source,amount):
    if not isinstance(source,dict):raise ValueError('Explicit typed opening funding source required; no v4 capital default')
    if source.get('kind')=='verified_readonly_exchange_snapshot':
        raise ValueError('ACTUAL_EXCHANGE_READ_ONLY: NOT_CONNECTED; no authorized private connector exists')
    if source.get('kind')=='mock_futures_snapshot':
        from .account_capital import FuturesAccountSnapshot
        snapshot=FuturesAccountSnapshot(**source['snapshot']).validate(now_ms=source['timestamp_ms'])
        expected=snapshot_funding(snapshot)
        if source!=expected or dec(amount)!=dec(snapshot.settled_cash):raise ValueError('Conflicting snapshot opening funding')
        return dict(source)
    required={'kind','account_id','scope','currency','amount','timestamp_ms','source_reference','source_evidence'}
    if set(source)!=required or source.get('kind')!='owner_confirmed_paper_scenario':raise ValueError('Unknown or incomplete funding source')
    if source['currency']!='USDT' or source['scope']!=PAPER_SCOPE:raise ValueError('Wrong funding currency or account scope')
    if any(not isinstance(source[k],str) or len(source[k].strip())<3 for k in ('account_id','source_reference','source_evidence')):
        raise ValueError('Documented account identity and source evidence required')
    if type(source['timestamp_ms']) is not int or source['timestamp_ms']<0:raise ValueError('Explicit funding timestamp required')
    opening=dec(str(amount))
    if opening<=0 or dec(source['amount'])!=opening:raise ValueError('Conflicting opening funding amount')
    if opening.quantize(Decimal('0.000000000000000001'))!=opening:raise ValueError('Opening amount exceeds ledger precision')
    return dict(source)


@dataclass(frozen=True)
class ReadOnlySnapshot:
    account_id: str
    account_class: str
    settlement_asset: str
    snapshot_id: str
    timestamp_ms: int
    complete: bool
    scope_eligible: bool
    free_cash: str
    settled_cash: str
    frozen: str
    pledged: str
    locked: str
    borrowed: str
    margin_obligations: str
    marked_position_equity: str


class FutureReadOnlyAdapter(Protocol):
    """Design contract only. No implementation, authentication, orders or transfers."""
    def snapshot(self)->ReadOnlySnapshot:...


def validate_readonly_snapshot(snapshot,*,account_id,now_ms,max_age_ms=15000):
    """Offline validation fixture/API boundary; does NOT authorize a connection.

    settled_cash is gross settled cash; encumbrances are disjoint deductions.
    free_cash is an independent conservative cap. Marked equity/other wallets
    never increase eligible opening cash. Future adapters must prove semantics.
    """
    s=snapshot
    if (type(s.complete) is not bool or type(s.scope_eligible) is not bool or
        type(s.timestamp_ms) is not int or s.timestamp_ms<0 or type(max_age_ms) is not int or max_age_ms<=0):
        raise ValueError('Invalid typed snapshot completeness or timestamp')
    if (not s.complete or not s.scope_eligible or s.account_id!=account_id or
        s.account_class!='CLASSIC_FUTURES' or s.settlement_asset!='USDT' or not s.snapshot_id):
        raise ValueError('Incomplete/conflicting/ineligible read-only snapshot')
    if not 0<=now_ms-s.timestamp_ms<=max_age_ms:raise ValueError('Stale or future read-only snapshot')
    values={k:dec(getattr(s,k)) for k in ('free_cash','settled_cash','frozen','pledged','locked','borrowed','margin_obligations')}
    if any(v<0 for v in values.values()):raise ValueError('Negative or invalid cash components')
    if values['free_cash']>values['settled_cash']:raise ValueError('Conflicting free versus settled cash; equity is not funding')
    dec(s.marked_position_equity)
    available=min(values['free_cash'],values['settled_cash']-sum((values[k] for k in ('frozen','pledged','locked','borrowed','margin_obligations')),Decimal(0)))
    if available<=0:raise ValueError('No settled unpledged eligible cash')
    return available


def snapshot_funding(snapshot):
    """Derive cycle-zero provenance from a strict MOCK account, never an input seed.

    Authenticated initialization remains blocked until the approved adapter exists.
    """
    snapshot.validate(now_ms=snapshot.timestamp_ms)
    if dec(snapshot.settled_cash)<=0:raise ValueError('Positive settled opening capital required')
    if dec(snapshot.liabilities)>0:raise ValueError('Opening liabilities need verified owner-equity normalization; startup blocked')
    return dict(kind='mock_futures_snapshot',account_id=snapshot.account_id,
                scope='CLASSIC_FUTURES',currency=snapshot.settlement_currency,
                amount=snapshot.settled_cash,timestamp_ms=snapshot.timestamp_ms,
                opening_equity=snapshot.equity,initial_usable_margin=snapshot.free_margin,
                source_reference=snapshot.snapshot_id,source_digest=snapshot.source_digest,
                source_evidence='MOCK Futures account; not authenticated KuCoin',snapshot=snapshot.payload())
