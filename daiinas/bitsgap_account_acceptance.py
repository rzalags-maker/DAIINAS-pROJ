"""Redacted P03.1 account evidence. Never converts a wallet into ledger funding."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AccountAcceptance:
    observed_ms: int
    generation: int
    account_scope_matches: bool
    balance: str
    orders: str
    positions: str
    position_mode: str
    connection: str
    terminal_parity: str = 'PENDING_OWNER_VERIFICATION'
    equity: str = 'UNVERIFIED'
    free_margin: str = 'UNVERIFIED'
    protection: str = 'UNVERIFIED'

    def __post_init__(self):
        states=('VALIDATED','VERIFIED_EMPTY','VERIFIED_ACTIVE','PROVIDER_NO_DATA','UNVERIFIED','STALE','CONFLICT')
        if (type(self.observed_ms) is not int or self.observed_ms<0 or type(self.generation) is not int or self.generation<0
                or type(self.account_scope_matches) is not bool or any(x not in states for x in (self.balance,self.orders,self.positions))
                or self.position_mode not in ('ONE_WAY','HEDGE','UNVERIFIED') or self.connection not in ('CONNECTED','DISCONNECTED','STALE')
                or self.terminal_parity!='PENDING_OWNER_VERIFICATION'
                or (self.equity,self.free_margin,self.protection)!=('UNVERIFIED',)*3):
            raise ValueError('INVALID_REDACTED_ACCOUNT_EVIDENCE')

    @classmethod
    def from_state(cls,state,*,expected_market_id,expected_scope_ref):
        s=state.status()
        receipts=[r.received_ms for r in state.records.values() if r.generation==state.generation]
        return cls(min(receipts,default=state.clock()),state.generation,
            state.market_id==expected_market_id and state.scope_ref==expected_scope_ref,
            s['topics']['balance']['state'],s['topics']['orders']['state'],
            s['topics']['positions']['state'],s['observed_position_mode'],s['connection'])

    def report(self,*,now_ms,max_age_ms=15000):
        reasons=[]
        if not self.account_scope_matches:reasons.append('ACCOUNT_SCOPE_MISMATCH')
        if type(now_ms) is not int or not 0<=now_ms-self.observed_ms<=max_age_ms:reasons.append('ACCOUNT_EVIDENCE_STALE')
        if self.connection!='CONNECTED':reasons.append('ACCOUNT_DISCONNECTED')
        if self.balance!='VALIDATED':reasons.append('BALANCE_'+self.balance)
        for name,state in (('ORDERS',self.orders),('POSITIONS',self.positions)):
            if state not in ('VERIFIED_EMPTY','VERIFIED_ACTIVE'):reasons.append(name+'_'+state)
        if self.position_mode!='ONE_WAY':reasons.append('ONE_WAY_UNVERIFIED')
        return {'fields':asdict(self),'paper_observation_blockers':reasons,
            'financial_blockers':['EQUITY_UNVERIFIED','FREE_MARGIN_UNVERIFIED','COLLATERAL_AND_COSTS_UNVERIFIED',
                                  'FULL_EXPOSURE_COMPLETENESS_UNVERIFIED','PERSISTENT_TP_SL_UNVERIFIED'],
            'new_entry':'NO_TRADE_ACCOUNT_NOT_RECONCILED','eligible_capital':None,'orders_enabled':False}


def main(argv=None):
    import argparse,json
    from pathlib import Path
    from .bitsgap_account_state import PrivateStore
    from .bitsgap_account_visibility import load_state
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-file',required=True,type=Path)
    p.add_argument('--scope-ref',required=True)
    p.add_argument('--expected-market-id',required=True,type=int)
    args=p.parse_args(argv)
    store=None
    try:
        store=PrivateStore(args.state_file,readonly=True)
        state=load_state(store,args.scope_ref)
        evidence=AccountAcceptance.from_state(state,expected_market_id=args.expected_market_id,expected_scope_ref=args.scope_ref)
        print(json.dumps(evidence.report(now_ms=state.clock()),sort_keys=True))
        return 2  # Financial admission remains blocked.
    except Exception:
        print(json.dumps({'status':'ACCOUNT_ACCEPTANCE_UNVERIFIED','orders_enabled':False}))
        return 2
    finally:
        if store is not None:store.close()


if __name__=='__main__':raise SystemExit(main())
