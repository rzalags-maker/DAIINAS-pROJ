"""Account-scoped, pure snapshot reconciliation. No authentication or order transport.

Classic linear USDT Futures only. UTA is deliberately blocked until its collateral
semantics can be verified. The caller journals normalized snapshots atomically
with the existing portfolio checkpoint; MOCK never means authenticated KuCoin.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from .capital_ladder import CapitalLadder, dec
from .continuous_store import digest

ZERO = Decimal(0)
VERSION = 'v4.6-unified-win-gated-account-v2'


def exact(value):
    value = dec(value)
    try:
        if value != value.quantize(Decimal('1e-18')):raise ValueError('Account amount exceeds ledger precision')
    except InvalidOperation as exc:raise ValueError('Account amount exceeds ledger precision') from exc
    return value


@dataclass(frozen=True)
class FuturesAccountSnapshot:
    exchange: str
    account_id: str
    account_mode: str
    settlement_currency: str
    snapshot_id: str
    timestamp_ms: int
    complete: bool
    transport_validated: bool
    signature_validated: bool
    source_kind: str
    settled_cash: str
    equity: str
    free_margin: str
    position_margin: str
    order_margin: str
    unrealized_pnl: str
    liabilities: str
    restricted_collateral: str
    margin_mode: str
    leverage: str
    orders: list
    positions: list
    cash_events: list
    source_digest: str

    def payload(self):
        return asdict(self)

    def validate(self, *, now_ms, max_age_ms=15000):
        obj = self.payload()
        if self.source_digest != digest({k:v for k,v in obj.items() if k != 'source_digest'}):
            raise ValueError('Snapshot provenance digest mismatch')
        if (self.exchange != 'KUCOIN' or self.account_mode != 'CLASSIC_FUTURES'
                or self.settlement_currency != 'USDT'):
            raise ValueError('Unsupported Futures account scope; UTA requires verified normalization')
        if any(not isinstance(v,str) or not v.strip() for v in (self.account_id,self.snapshot_id)):
            raise ValueError('Missing account/snapshot identity')
        if (type(self.timestamp_ms) is not int or type(now_ms) is not int or self.timestamp_ms<0
                or type(max_age_ms) is not int or max_age_ms<=0 or not 0 <= now_ms-self.timestamp_ms <= max_age_ms):
            raise ValueError('Stale/future account snapshot')
        if any(type(v) is not bool or not v for v in
               (self.complete,self.transport_validated,self.signature_validated)):
            raise ValueError('Incomplete or unvalidated account snapshot')
        # There is intentionally no authenticated adapter in this release.
        if self.source_kind != 'MOCK':
            raise ValueError('NOT_CONNECTED: authenticated transport is not implemented')
        keys=('settled_cash','equity','free_margin','position_margin','order_margin',
              'unrealized_pnl','liabilities','restricted_collateral','leverage')
        values={k:exact(getattr(self,k)) for k in keys}
        if any(values[k]<0 for k in keys if k not in ('equity','unrealized_pnl')):
            raise ValueError('Negative account obligation/cash')
        if values['equity'] != values['settled_cash']+values['unrealized_pnl']-values['liabilities']:
            raise ValueError('Equity/cash/unrealized/liability discrepancy')
        # free_margin is already NET of these disjoint obligations. Never deduct
        # them again from the free-margin leg of the admission minimum.
        encumbered=sum((values[k] for k in ('position_margin','order_margin','restricted_collateral')),ZERO)
        if values['free_margin'] > max(ZERO,values['equity']-encumbered):
            raise ValueError('Free margin exceeds net unencumbered equity')
        if self.margin_mode != 'ISOLATED' or not 1 <= values['leverage'] <= 2:
            raise ValueError('Unconfirmed ISOLATED 1–2x pilot constraints')
        for name in ('orders','positions','cash_events'):
            records=getattr(self,name)
            if not isinstance(records,list) or any(not isinstance(x,dict) for x in records):
                raise ValueError('Missing complete account scope: '+name)
            ids=[x.get('id') for x in records]
            if any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)):
                raise ValueError('Missing/duplicate account record ID')
        for name,margin in (('orders','order_margin'),('positions','position_margin')):
            total=ZERO
            for record in getattr(self,name):
                if set(record)!={'id','symbol','margin','planned_loss','margin_mode','leverage','position_side','campaign_id','protected'}:
                    raise ValueError('Incomplete exposure/risk record')
                if (not isinstance(record['symbol'],str) or not record['symbol']
                    or record['margin_mode']!='ISOLATED' or not 1<=exact(record['leverage'])<=2):
                    raise ValueError('Unsupported account exposure')
                if (record['position_side'] not in ('LONG','SHORT') or type(record['protected']) is not bool
                    or record['campaign_id'] is not None and (not isinstance(record['campaign_id'],str) or not record['campaign_id'])):
                    raise ValueError('Incomplete side/campaign/protection semantics')
                if exact(record['margin'])<0 or exact(record['planned_loss'])<0:
                    raise ValueError('Negative exposure/risk')
                total+=exact(record['margin'])
            if total!=values[margin]:raise ValueError('Exposure margin totals do not reconcile')
        return self


class FuturesSnapshotAdapter(Protocol):
    """Future read-only adapter must normalize complete paginated scopes atomically.

    Never supplies an order/transfer method. Real transport remains unimplemented.
    """
    def snapshot(self) -> FuturesAccountSnapshot | None: ...


class NotConnectedAdapter:
    def snapshot(self):
        return None


class MockFuturesAdapter:
    """Finite deterministic test stream; not market/account evidence."""
    def __init__(self,snapshots):self.snapshots=iter(snapshots)
    def snapshot(self):return next(self.snapshots,None)


def mock_snapshot(*, cash, timestamp_ms, snapshot_id, account_id='MOCK-FUTURES',
                  free_margin=None, unrealized_pnl='0', liabilities='0',
                  restricted_collateral='0', orders=None, positions=None, cash_events=None,
                  **changes):
    """Test fixture constructor. Does not accept wallet balances or real attestation."""
    orders=[] if orders is None else orders;positions=[] if positions is None else positions
    pm=sum((exact(x['margin']) for x in positions),ZERO)
    om=sum((exact(x['margin']) for x in orders),ZERO)
    eq=exact(cash)+exact(unrealized_pnl)-exact(liabilities)
    obj=dict(exchange='KUCOIN',account_id=account_id,account_mode='CLASSIC_FUTURES',
             settlement_currency='USDT',snapshot_id=snapshot_id,timestamp_ms=timestamp_ms,
             complete=True,transport_validated=True,signature_validated=True,source_kind='MOCK',
             settled_cash=str(cash),equity=str(eq),free_margin=str(max(ZERO,eq-pm-om-exact(restricted_collateral)) if free_margin is None else free_margin),
             position_margin=str(pm),order_margin=str(om),unrealized_pnl=str(unrealized_pnl),
             liabilities=str(liabilities),restricted_collateral=str(restricted_collateral),
             margin_mode='ISOLATED',leverage='2',orders=orders,positions=positions,
             cash_events=[] if cash_events is None else cash_events)
    obj.update(changes)
    return FuturesAccountSnapshot(**obj,source_digest=digest(obj))


def initial_account_state(opening,account_id):
    return dict(version=VERSION,account_id=account_id,ladder=CapitalLadder(opening).export_state(),
                cash=str(opening),unallocated='0',events={},snapshots={},snapshot=None,
                status='NOT_CONNECTED',reason='No complete account snapshot',peak=None,
                max_drawdown='0',halted=False,earned_early_ports=1,closed_campaigns={},
                pending_campaigns={},early_active_ceiling=str(CapitalLadder(opening).active))


def reconcile(state, snapshot, *, now_ms, owned_ids=()):
    """Return replacement state + immutable audit records; no partial mutation.

    Snapshot cash changes must be fully explained by exact-once settled events.
    An unexplained difference is never relabeled as P&L or new funding.
    """
    import copy
    out=copy.deepcopy(state);s=snapshot.validate(now_ms=now_ms)
    if s.account_id!=out['account_id']:raise ValueError('Account identity changed; never re-seed')
    old=out['snapshot'];snapshots=out['snapshots'];sid=s.snapshot_id
    if sid in snapshots:
        if snapshots[sid]!=s.source_digest:raise ValueError('Conflicting snapshot replay')
        # A duplicate cannot renew freshness or clear a disconnect/degraded latch.
        return out,[]
    if old and s.timestamp_ms<=old['timestamp_ms']:raise ValueError('Nonmonotonic account snapshot')
    ladder=CapitalLadder.restore(out['ladder']);cash=exact(out['cash']);unallocated=exact(out['unallocated']);audit=[]
    finalized_net=ZERO
    for event in sorted(s.cash_events,key=lambda x:(x.get('timestamp_ms',-1),x['id'])):
        eid=event['id'];sha=digest(event)
        if eid in out['events']:
            if out['events'][eid]!=sha:raise ValueError('Conflicting cash event replay')
            continue
        if (event.get('account_id')!=s.account_id or type(event.get('timestamp_ms')) is not int
            or not (old['timestamp_ms'] if old else -1)<event['timestamp_ms']<=s.timestamp_ms):
            raise ValueError('Out-of-scope or nonchronological settled cash event')
        kind=event.get('type');net=exact(event.get('net'))
        if kind=='REALIZED_NET_TRADE':
            if set(event)!={'id','account_id','timestamp_ms','type','net','gross','fees','funding','campaign_id','campaign_complete'}:
                raise ValueError('Missing finalized net trade cost attribution')
            if exact(event['fees'])<0 or net!=exact(event['gross'])-exact(event['fees'])+exact(event['funding']):
                raise ValueError('Realized trade costs do not reconcile')
            cid=event['campaign_id']
            if not isinstance(cid,str) or not cid or type(event['campaign_complete']) is not bool:
                raise ValueError('Explicit campaign identity/completeness required')
            if cid in out['closed_campaigns']:raise ValueError('Campaign already finalized; cannot book twice')
            combined=exact(out['pending_campaigns'].get(cid,'0'))+net
            if event['campaign_complete']:
                if any(x['campaign_id']==cid for x in s.positions+s.orders):raise ValueError('Campaign still has open exposure/orders')
                before_stage=ladder.stage
                ladder.realized_result(combined);finalized_net+=combined
                out['pending_campaigns'].pop(cid,None);out['closed_campaigns'][cid]=str(combined)
                if before_stage=='BOOTSTRAP' and combined>0:
                    out['earned_early_ports']=min(10,out['earned_early_ports']+1)
                    audit.append(dict(event_type='EARLY_WIN_PORT',campaign_id=cid,earned_early_ports=out['earned_early_ports']))
                if before_stage=='BOOTSTRAP' and ladder.stage!='BOOTSTRAP':
                    audit.append(dict(event_type='ACTIVATE_LADDER',campaign_id=cid,active=str(ladder.active),reserve=str(ladder.reserve)))
            else:out['pending_campaigns'][cid]=str(combined)
        elif kind=='CASH_COST':
            if set(event)!={'id','account_id','timestamp_ms','type','net','category'} or event['category'] not in ('FEE','FUNDING'):
                raise ValueError('Unclassified cash settlement')
            ladder.realized_result(net);finalized_net+=net
        elif kind=='EXTERNAL_FLOW':
            if set(event)!={'id','account_id','timestamp_ms','type','net'}:raise ValueError('Invalid external flow')
            # Withdrawals cannot silently consume protected/allocated funds.
            if unallocated+net<0:raise ValueError('External withdrawal exceeds unallocated funds; operator reconciliation required')
            unallocated+=net
        else:raise ValueError('Unknown cash event; external allocation policy NOT_APPROVED')
        cash+=net;out['events'][eid]=sha;audit.append(dict(event_type=kind,**event))
    pending_net=sum((exact(x) for x in out['pending_campaigns'].values()),ZERO)
    if cash!=exact(s.settled_cash) or cash!=ladder.total+unallocated+pending_net:
        raise ValueError('Unexplained settled cash discrepancy')
    active=max(ZERO,ladder.active+min(ZERO,exact(s.unrealized_pnl))+min(ZERO,pending_net)-exact(s.liabilities))
    if ladder.stage=='BOOTSTRAP':
        ceiling=active if finalized_net>0 else min(exact(out['early_active_ceiling']),active)
        out['early_active_ceiling']=str(ceiling)
        active=min(active,ceiling)
    # External flows and reserve reclassification cannot hide trading drawdown.
    previous_active=CapitalLadder.restore(out['ladder']).active
    trading=finalized_net
    peak=max(active,exact(out['peak'])+ladder.active-previous_active-trading if out['peak'] is not None else active)
    dd=max(ZERO,(peak-active)/peak) if peak>0 else ZERO
    out['peak']=str(peak);out['max_drawdown']=str(max(dec(out['max_drawdown']),dd))
    out['halted']=out['halted'] or dd>=Decimal('.06')
    ladder.mark_to_market(str(min(ZERO,active-ladder.active)),len(s.positions)+len(s.orders))
    unknown=[x['id'] for x in s.orders+s.positions if x['id'] not in owned_ids]
    unprotected=any(not x['protected'] for x in s.positions)
    status='EXTERNAL_INTERVENTION' if unknown else 'UNPROTECTED_EXPOSURE' if unprotected else 'RECONCILED_MOCK'
    out.pop('observed_unreconciled',None)
    out.update(ladder=ladder.export_state(),cash=str(cash),unallocated=str(unallocated),
               snapshot=s.payload(),status=status,reason='Unknown account exposure: '+','.join(unknown) if unknown else 'Missing confirmed protection' if unprotected else None)
    snapshots[sid]=s.source_digest
    audit.append(dict(event_type='ACCOUNT_RECONCILED',snapshot_id=sid,source_digest=s.source_digest,status=status))
    return out,audit


def capital_status(state, *, now_ms, local_margin=ZERO, local_risk=ZERO, local_fees=ZERO, local_count=0):
    """Current account admission limits; paper commitments are incremental to account.

    Exchange-held margin is deducted from ACTIVE, but already-net exchange free
    margin is not reduced twice. The local paper ledger never books itself as a
    real exchange fill, so its independent commitments must also be reserved.
    """
    snap=state['snapshot'];ladder=CapitalLadder.restore(state['ladder'])
    reason=state['reason'];status=state['status']
    if snap and not 0<=now_ms-snap['timestamp_ms']<=15000:
        status='STALE';reason='Account snapshot expired'
    ready=bool(snap) and status=='RECONCILED_MOCK' and not state['halted']
    pending_net=sum((exact(x) for x in state['pending_campaigns'].values()),ZERO)
    u=exact(snap['unrealized_pnl']) if snap else ZERO
    liability=exact(snap['liabilities']) if snap else ZERO
    active=max(ZERO,ladder.active+min(ZERO,u)+min(ZERO,pending_net)-liability)
    if ladder.stage=='BOOTSTRAP':active=min(active,exact(state['early_active_ceiling']))
    locked=sum((exact(snap[k]) for k in ('position_margin','order_margin','restricted_collateral')),ZERO) if snap else ZERO
    free=exact(snap['free_margin']) if snap else ZERO
    external_risk=sum((exact(x['planned_loss']) for x in snap['positions']+snap['orders']),ZERO) if snap else ZERO
    peak=exact(state['peak']) if state['peak'] is not None else active
    dd=max(ZERO,(peak-active)/peak) if peak>0 else ZERO
    risk=max(ZERO,active*Decimal('.01')-external_risk-local_risk)
    marginal=max(ZERO,min(active-locked-local_margin-local_fees,free-local_margin-local_fees)) if ready else ZERO
    return dict(account_policy_version=state['version'],opening_funding=str(ladder.starting_total),current_futures_equity=snap['equity'] if snap else None,
                current_settled_cash=snap['settled_cash'] if snap else None,actual_free_margin=snap['free_margin'] if snap else None,
                active_budget=str(active),reserve=str(ladder.reserve),pending=str(ladder.pending),locked=str(locked),
                unallocated_external=state['unallocated'],risk_budget=str(risk if ready else ZERO),
                per_leg_risk_budget=str(active*Decimal('.0025')*(Decimal('.5') if dd>=Decimal('.03') else 1)),
                marginal_margin=str(marginal),allowed_slots=(state['earned_early_ports'] if ladder.stage=='BOOTSTRAP' else ladder.slot_ceiling),deficit=str(ladder.deficit),
                allocation_stage=ladder.stage,earned_early_ports=state['earned_early_ports'],
                funded_slot_ceiling=ladder.slot_ceiling if ladder.stage!='BOOTSTRAP' else None,
                risk_allowed_slot_ceiling=None,open_and_pending_slots=local_count+(len(snap['positions'])+len(snap['orders']) if snap else 0),capacity_basis='Per-instrument minimum lot/full-cost risk checked at entry',
                closed_campaign_ids=sorted(state['closed_campaigns']),unsettled_campaign_net=str(pending_net),
                connector_status=status,reason=reason,orders_enabled=False,ready_for_paper=ready,
                source_kind='MOCK' if snap else None,authenticated_account_connected=False,
                observed_unreconciled=state.get('observed_unreconciled'),
                account_drawdown=str(dd),halted=state['halted'],snapshot_id=snap['snapshot_id'] if snap else None)
