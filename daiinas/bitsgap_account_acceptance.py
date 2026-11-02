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



class SessionEvidence:
    """Retains only redacted cohorts captured while the writer is connected.

    A new connection generation invalidates the previous candidate immediately.
    We never obtain coherence by evaluating a disconnected service as current.
    """
    def __init__(self):
        self.generation = None
        self.latest = None
        self.sample_count = 0
        self.first_ms = None
        self.last_ms = None

    def capture(self, sample):
        if self.generation != sample['generation']:
            self.generation = sample['generation']
            self.latest = None
        if not sample['connected'] or not sample['resynced']:
            return
        self.sample_count += 1
        now = sample['captured_ms']
        self.first_ms = now if self.first_ms is None else self.first_ms
        self.last_ms = now
        self.latest = {k: sample[k] for k in ('captured_ms','topics','oldest_receipt_ms',
                                            'position_mode','connection','sources')}

    def report(self, service, *, catalog, now_ms):
        result = blocked_report('NO_CURRENT_SESSION_EVIDENCE')
        result.update(catalog_declaration=catalog, authenticated_market_scope='KUCOIN_FUTURES_USDT',
                      observation_samples=self.sample_count,
                      first_sample_ms=self.first_ms, last_sample_ms=self.last_ms,
                      connection_after_stop='CONNECTED' if service.connected else 'DISCONNECTED')
        diagnostics = service.transport_diagnostics
        # Do not forward remote errors, raw exceptions or arbitrary diagnostics.
        failure = diagnostics.get('ws_last_failure', 'NONE')
        result['transport'] = {
            'rest_catalog_auth': 'PASS',
            'websocket_auth': 'PASS' if diagnostics.get('ws_auth_succeeded_in_last_session') else 'UNVERIFIED',
            'snapshot_batches': diagnostics.get('ws_snapshot_batches_sent', 0),
            'snapshot_responses': diagnostics.get('ws_snapshot_responses', 0),
            'disconnects': diagnostics.get('ws_disconnects', 0),
            'stop': 'BOUNDED_STOP' if failure == 'NONE' else 'TRANSPORT_INTERRUPTED',
        }
        if failure != 'NONE':
            from .bitsgap_futures_observe import safe_diagnostic_category
            specific = {'WS_AUTH_UNVERIFIED':'WS_AUTH_REJECTED',
                'WS_TERMINAL_AUTH_FAILURE':'WS_AUTH_REJECTED',
                'WS_FOREIGN_EXCHANGE_SCOPE':'ACCOUNT_SCOPE_MISMATCH',
                'WS_BAD_FRAME':'WS_SCHEMA_UNVERIFIED',
                'WS_UNVERIFIED_TOPIC_FRAME':'WS_SCHEMA_UNVERIFIED',
                'WS_DISCONNECTED_OR_TRANSPORT_ERROR':'WS_TRANSPORT_INTERRUPTED'}
            result['transport']['failure_reason'] = specific.get(failure, safe_diagnostic_category(failure))
        if self.latest is None or self.generation != service.generation:
            if failure != 'NONE':
                result['reasons'].append(result['transport']['failure_reason'])
            return result
        cohort = self.latest
        result['session_evidence'] = cohort
        reasons = []
        balance = cohort['topics']['balance']
        if (cohort['oldest_receipt_ms']['balance'] is None or
                not 0 <= now_ms - cohort['oldest_receipt_ms']['balance'] <= service.max_age_ms or
                not 0 <= now_ms - cohort['captured_ms'] <= service.max_age_ms):
            reasons.append('ACCOUNT_EVIDENCE_STALE')
        if cohort['connection'] != 'CONNECTED':
            reasons.append('ACCOUNT_NOT_CONNECTED_DURING_SAMPLE')
        if balance['state'] != 'VALIDATED':
            reasons.append('BALANCE_' + balance['state'])
            reasons.append(balance['reason'])
        if not diagnostics.get('ws_auth_succeeded_in_last_session'):
            reasons.append('WS_AUTH_UNVERIFIED')
        coherent = not reasons
        for name in ('orders','positions'):
            topic = cohort['topics'][name]
            oldest = cohort['oldest_receipt_ms'][name]
            if oldest is not None and not 0 <= now_ms - oldest <= service.max_age_ms:
                reasons.append(name.upper() + '_STALE')
            if topic['state'] not in ('VERIFIED_EMPTY','VERIFIED_ACTIVE'):
                reasons.append(name.upper() + '_' + topic['state'])
                reasons.append('EXPOSURE_UNVERIFIED')
                if topic['state'] == 'PROVIDER_NO_DATA':
                    reasons.append('NULL_IS_NOT_ZERO')
        mode_topic = ('positions_settings' if cohort['topics']['positions_settings']['state'] == 'VALIDATED'
                      else 'positions')
        mode_time = cohort['oldest_receipt_ms'][mode_topic]
        if (cohort['position_mode'] != 'ONE_WAY' or mode_time is None
                or not 0 <= now_ms - mode_time <= service.max_age_ms):
            reasons.append('ONE_WAY_UNVERIFIED')
        if failure != 'NONE':
            reasons.append('TRANSPORT_INTERRUPTED')
        result['wallet_coherence'] = 'PASS' if coherent else 'UNVERIFIED'
        result['status'] = ('PASS' if not reasons else 'PARTIAL') if coherent else 'BLOCKED'
        result['reasons'] = sorted(set(reasons))
        return result


def blocked_report(reason):
    return {'status':'BLOCKED', 'reasons':[reason],
            'report_scope':'READ_ONLY_OBSERVATION_PROCEDURE_NOT_TRADE_READINESS',
            'wallet_coherence':'UNVERIFIED',
            'authenticated_market_scope':'UNVERIFIED',
            'transport':{'websocket_auth':'UNVERIFIED','stop':'SETUP_OR_NO_EVIDENCE'},
            'terminal_parity':'PENDING_OWNER_VERIFICATION',
            'equity':'UNVERIFIED', 'free_margin':'UNVERIFIED',
            'full_exposure_completeness':'UNVERIFIED', 'persistent_tp_sl':'UNVERIFIED',
            'financial_admission':'BLOCKED',
            'new_entry':'NO_TRADE_ACCOUNT_NOT_RECONCILED',
            'DAIINAS_ORDER_ROUTING':'DISABLED', 'LIVE_TRADING':'DISABLED',
            'orders_enabled':False}


def _credential(path=None):
    """No discovery of owner files. File access requires an explicit host option."""
    import os, stat
    from .bitsgap_account_state import _ci, AccountStateError
    if path is None:
        key = os.environ.get('BITSGAP_PRIVATE_KEY_PEM')
        if not key:
            raise AccountStateError('CREDENTIAL_NOT_CONFIGURED')
        return key
    if _ci():
        raise AccountStateError('PRIVATE_CREDENTIAL_FILE_DISALLOWED_IN_CI')
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or not 0 < info.st_size <= 16384):
            raise ValueError()
        return os.read(fd, 16385).decode('ascii')
    except Exception:
        raise AccountStateError('PRIVATE_CREDENTIAL_FILE_UNSAFE_OR_UNAVAILABLE') from None
    finally:
        if fd is not None:
            os.close(fd)


async def observe_session(observer, connect, *, seconds):
    """Injection boundary for offline tests; uses the existing observer and registry."""
    import asyncio
    from .bitsgap_account_state import observe_bounded
    from .bitsgap_capabilities import BitsgapCapabilityRegistry
    await asyncio.to_thread(observer.discover)
    registry = await asyncio.to_thread(BitsgapCapabilityRegistry.discover, observer)
    if any(registry.get(t).market_id != observer._futures_em for t in
            ('balance','orders','positions','positions_settings')):
        from .bitsgap_account_state import AccountStateError
        raise AccountStateError('ACCOUNT_SCOPE_MISMATCH')
    catalog = {t: registry.get(t).verification for t in
               ('balance','orders','positions','positions_settings')}
    samples = SessionEvidence()
    service = await observe_bounded(observer, connect, seconds=seconds,
        scope_ref='bounded-acceptance', sample_sink=samples.capture)
    return samples.report(service, catalog=catalog, now_ms=service.clock())


def _worker(args):
    import asyncio, ssl
    from .bitsgap_account_state import AccountStateError
    from .bitsgap_readonly import BitsgapError
    from .bitsgap_futures_observe import BitsgapFuturesObserver, safe_diagnostic_category
    try:
        key = _credential(args.credential_file)
        from websockets.asyncio.client import connect
        # Use system trust with the existing platform/session CA configuration.
        context = ssl.create_default_context()
        observer = BitsgapFuturesObserver(key)
        def secure_connect(url):
            return connect(url, ssl=context, open_timeout=5, close_timeout=2,
                           max_size=65536, max_queue=16, ping_interval=20)
        return asyncio.run(observe_session(observer, secure_connect, seconds=args.seconds))
    except AccountStateError as exc:
        allowed = ('ACCOUNT_SCOPE_MISMATCH','CREDENTIAL_NOT_CONFIGURED','PRIVATE_CREDENTIAL_FILE_DISALLOWED_IN_CI',
                   'PRIVATE_CREDENTIAL_FILE_UNSAFE_OR_UNAVAILABLE')
        return blocked_report(str(exc) if str(exc) in allowed else 'ACCOUNT_STATE_UNVERIFIED')
    except BitsgapError as exc:
        return blocked_report(safe_diagnostic_category(exc.category))
    except ImportError:
        return blocked_report('DEPENDENCY_NOT_CONFIGURED')
    except ValueError:
        return blocked_report('CATALOG_OR_LOCAL_SCHEMA_UNVERIFIED')
    except Exception:
        return blocked_report('LOCAL_RUNTIME_UNVERIFIED')


def main(argv=None):
    import argparse,json,subprocess,sys
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observe',action='store_true')
    p.add_argument('--seconds',type=int,default=60)
    p.add_argument('--credential-file',type=Path)
    p.add_argument('--_worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--state-file',type=Path)
    p.add_argument('--scope-ref')
    p.add_argument('--expected-market-id',type=int)
    args=p.parse_args(argv)
    if args.observe:
        if not 1 <= args.seconds <= 3600 or args.state_file or args.scope_ref or args.expected_market_id is not None:
            report=blocked_report('INVALID_OBSERVATION_ARGUMENTS')
        elif args._worker:
            report=_worker(args)
        else:
            # A process deadline also bounds blocked DNS/REST threads and executor
            # teardown. Never forward worker stderr or a partial private traceback.
            command=[sys.executable,'-B','-m',__package__+'.bitsgap_account_acceptance',
                     '--observe','--_worker','--seconds',str(args.seconds)]
            if args.credential_file is not None:
                command += ['--credential-file',str(args.credential_file)]
            try:
                completed=subprocess.run(command,capture_output=True,text=True,
                    timeout=65+args.seconds+20,check=False)
                report=json.loads(completed.stdout)
                if not isinstance(report,dict) or report.get('status') not in ('PASS','PARTIAL','BLOCKED'):
                    raise ValueError()
            except subprocess.TimeoutExpired:
                report=blocked_report('SESSION_DEADLINE_EXCEEDED')
            except KeyboardInterrupt:
                report=blocked_report('SESSION_CANCELLED')
            except Exception:
                report=blocked_report('ACCEPTANCE_WORKER_UNAVAILABLE')
        print(json.dumps(report,sort_keys=True))
        return 2 if report['status']=='BLOCKED' else 0
    if args._worker or args.credential_file or not args.state_file or not args.scope_ref or args.expected_market_id is None:
        p.error('checkpoint reporting requires --state-file, --scope-ref and --expected-market-id; or use --observe')
    from .bitsgap_account_state import PrivateStore
    from .bitsgap_account_visibility import load_state
    store=None
    try:
        store=PrivateStore(args.state_file,readonly=True)
        state=load_state(store,args.scope_ref)
        evidence=AccountAcceptance.from_state(state,expected_market_id=args.expected_market_id,expected_scope_ref=args.scope_ref)
        print(json.dumps(evidence.report(now_ms=state.clock()),sort_keys=True))
        return 2
    except Exception:
        print(json.dumps(blocked_report('CHECKPOINT_UNVERIFIED')))
        return 2
    finally:
        if store is not None:store.close()


if __name__=='__main__':raise SystemExit(main())
