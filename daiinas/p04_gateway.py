"""Mode/ACK boundary on the EXISTING source journal and v4.7 ledger. MOCK only.

No HTTP, WS, API keys, live transport or second financial/order ledger.
"""
from dataclasses import asdict, dataclass
from copy import deepcopy
from decimal import Decimal
import json
from uuid import uuid4

from .continuous_store import digest

MODES=('OBSERVE','START_PAPER','START_LIVE','PAUSE','STOP','HALT')


@dataclass(frozen=True)
class MockExecutionContract:
    source_kind: str = 'MOCK_EXECUTION_CONTRACT'
    order_types: tuple = ('MARKET_IOC','LIMIT','POST_ONLY_LIMIT')
    protective_tp_sl: bool = True
    reduce_only: bool = True

    def __post_init__(self):
        if (self.source_kind!='MOCK_EXECUTION_CONTRACT' or type(self.protective_tp_sl) is not bool
                or type(self.reduce_only) is not bool or not set(self.order_types)<=set(('MARKET_IOC','LIMIT','POST_ONLY_LIMIT'))):
            raise ValueError('INVALID_MOCK_CONTRACT')


class MockExecutionTransport:
    """ACK simulator only. Quote/native fill models remain in the existing conveyor."""
    def __init__(self,*,outcome='ACKNOWLEDGED'):
        if outcome not in ('ACKNOWLEDGED','UNCERTAIN','REJECTED'):raise ValueError('INVALID_MOCK_OUTCOME')
        self.outcome=outcome;self.calls=[];self.seen={}

    def submit(self,command):
        identity=digest(command);key=command['command_id']
        if key in self.seen:
            if self.seen[key][0]!=identity:raise ValueError('CONFLICTING_MOCK_COMMAND')
            return self.seen[key][1]
        self.calls.append(command)
        result={'command_id':key,'intent_digest':command['intent_digest'],'outcome':self.outcome,
                'source_kind':'MOCK_GATEWAY_ACK'}
        self.seen[key]=(identity,result)
        return result


def _order(ledger,intent):
    return ledger.state.get('venue_orders',{}).get(intent['order_ids']['entry'],{})


def hold(ledger,intent,reason):
    command=_order(ledger,intent).get('gateway_command_id')
    if command:
        ledger.state.setdefault('pending_native_receipts',{}).setdefault('p04:'+command,
            {'digest':digest(command),'reason':reason})


def may_cancel_locally(ledger,intent):
    if not ledger.state.get('p04_gateway'):return True
    if _order(ledger,intent).get('gateway_submission') in ('CLAIMED','ACKNOWLEDGED','UNCERTAIN'):
        hold(ledger,intent,'MOCK_ORDER_CANCEL_NOT_CONFIRMED')
        return False
    return True


def entry_gate(ledger):
    s=ledger.state;g=s.get('p04_gateway')
    if g is None:return None  # Existing PAPER profiles retain their behavior.
    if g['mode']!='START_PAPER':return 'p04_mode_'+g['mode']
    if s['halted'] or s['paused']:return 'p04_operator_or_risk_halt'
    if not ledger.session_armed():return 'p04_session_disarmed'
    if s.get('pending_native_receipts'):return 'p04_native_reconciliation_pending'
    if any(p.get('protection',{}).get('state')!='MODELED_ACKED' for p in s['positions'].values()):
        return 'p04_existing_protection_unverified'
    if s['exit_requests'] or s.get('paper_settlements'):return 'p04_existing_settlement_first'
    contract=g['contract']
    if ledger.portfolio.entry_kind not in contract['order_types'] or not g['order_capability']:
        return 'p04_order_capability_unavailable'
    if not contract['protective_tp_sl'] or not contract['reduce_only']:
        return 'p04_mock_protection_unverified'
    if s['account_capital'].get('account_kind') not in (None,'MOCK'):
        return 'p04_requires_explicit_mock_ledger'
    evidence=g.get('account_evidence')
    if evidence:
        if not 0<=s['now_ms']-evidence['observed_ms']<=15000:return 'p04_account_evidence_stale'
        if evidence['blockers']:return 'p04_account_'+evidence['blockers'][0]
    return None


def can_fill(ledger,intent):
    return (not ledger.state.get('p04_gateway') or
            entry_gate(ledger) is None and _order(ledger,intent).get('gateway_submission')=='ACKNOWLEDGED')


def command_for(ledger,intent):
    return {'source_kind':'MOCK_GATEWAY_INTENT','command_id':'p04:'+digest([
        ledger.state['initial_funding']['event_id'],intent['id'],'entry']),
        'intent_digest':digest(intent),'preview':_order(ledger,intent)['preview']}


def _handle_control(ledger,packet):
    """Called only inside the existing immutable journal / checkpoint transaction."""
    s=ledger.state;action=packet.get('action');g=s.get('p04_gateway')
    if action=='p04-initialize':
        if not ledger.v47() or not ledger.portfolio.paper_settlement:raise ValueError('P04_REQUIRES_V47_MOCK_SETTLEMENT')
        contract=asdict(MockExecutionContract(**packet['contract']))
        if g is None:
            s['p04_gateway']={'mode':'OBSERVE','contract':contract,'order_capability':packet['order_capability'],
                'capability_registry':packet['registry'],'account_evidence':None,'last_result':'OBSERVE_ONLY','last_ack_seq':ledger.seq}
        elif g['contract']!=contract or g['order_capability']!=packet['order_capability']:
            raise ValueError('P04_CONTRACT_CHANGE_REQUIRES_SEPARATE_REVIEW')
        ledger.audit('P04_INITIALIZED',live_orders_enabled=False);return
    if g is None:raise ValueError('P04_NOT_INITIALIZED')
    if action=='p04-account-evidence':
        from .bitsgap_account_acceptance import AccountAcceptance
        evidence=AccountAcceptance(**packet['evidence'])
        report=evidence.report(now_ms=s['now_ms'])
        previous=g.get('account_evidence')
        if previous and (evidence.generation<previous['generation'] or evidence.observed_ms<previous['observed_ms']):
            report['paper_observation_blockers']=['ACCOUNT_GENERATION_OR_TIME_REGRESSION']
        g['account_evidence']={'observed_ms':max(evidence.observed_ms,previous['observed_ms'] if previous else 0),
            'generation':max(evidence.generation,previous['generation'] if previous else 0),
            'blockers':report['paper_observation_blockers']}
        if evidence.connection!='CONNECTED':
            g.update(mode='OBSERVE',last_result='ACCOUNT_CONNECTION_LOSS_DISARMED',last_ack_seq=ledger.seq)
            ledger.session_stop('P04_ACCOUNT_DISCONNECTED')
        ledger.audit('P04_ACCOUNT_EVIDENCE',blockers=report['paper_observation_blockers']);return
    if action=='p04-mode':
        mode=packet['mode']
        if mode not in MODES:raise ValueError('INVALID_P04_MODE')
        actor=packet.get('actor');request=packet.get('request_id')
        if not isinstance(actor,str) or len(actor)<3 or not isinstance(request,str) or not request:raise ValueError('OWNER_COMMAND_ID_REQUIRED')
        commands=s.setdefault('session_commands',{});key='p04:'+request;identity=digest([mode,actor,packet.get('duration_ms',0)])
        if key in commands:
            if commands[key]!=identity:raise ValueError('CONFLICTING_P04_COMMAND_ID')
            return
        commands[key]=identity
        if mode=='START_LIVE':
            g['last_result']='START_LIVE_BLOCKED_NO_LIVE_TRANSPORT'
            ledger.audit('P04_LIVE_BLOCKED',orders_enabled=False);return
        g.update(mode=mode,last_ack_seq=ledger.seq,last_result='DURABLY_APPLIED_IN_EXISTING_LEDGER')
        if mode=='START_PAPER':ledger.session_start(request_id='p04-session:'+request,actor=actor,duration_ms=packet.get('duration_ms',0))
        elif mode=='PAUSE':s['paused']=True
        elif mode=='HALT':s['halted']=True;ledger.session_stop('P04_HALT')
        else:ledger.session_stop('P04_'+mode)
        ledger.audit('P04_MODE_ACK',mode=mode,stop_state=ledger.session_status()['state'],orders_enabled=False);return
    if action=='p04-submit-claim':
        key=packet['position_key'];intent=s['pending_entries'].get(key)
        if intent is None:return
        order=_order(ledger,intent)
        if order.get('gateway_submission'):return
        reason=entry_gate(ledger)
        # Reuse all existing risk/free-margin/lot/leverage gates, excluding only
        # this intent's existing reservation while rechecking its original size.
        del s['pending_entries'][key]
        try:plan,rejection=ledger.plan(intent['symbol'],intent['direction'],s['quotes'][intent['symbol']])
        finally:s['pending_entries'][key]=intent
        if (reason or not plan or plan['leverage']!=intent['leverage']
                or Decimal(plan['quantity_contracts'])<Decimal(intent['quantity_contracts'])):
            ledger.audit('P04_SUBMIT_BLOCKED',reason=reason or rejection or 'REVALIDATED_SIZE_CHANGED');return
        command=command_for(ledger,intent)
        order.update(gateway_submission='CLAIMED',gateway_command_id=command['command_id'],
                     gateway_intent_digest=command['intent_digest'])
        hold(ledger,intent,'SUBMISSION_OUTCOME_UNCERTAIN')
        ledger.audit('P04_SUBMISSION_CLAIMED',command_id=command['command_id'],fill_confirmed=False);return
    if action=='p04-cancel-confirmed':
        proof=packet['proof']
        if (not isinstance(proof,dict) or set(proof)!={'source_kind','command_id','intent_digest','complete','filled_quantity','remaining_quantity'}
                or proof['source_kind']!='MOCK_CANCEL_RECONCILIATION' or proof['complete'] is not True
                or proof['filled_quantity']!='0' or proof['remaining_quantity']!='0'):
            raise ValueError('CANCEL_WITHOUT_AUTHORITATIVE_NO_FILL_PROOF')
        pair=next(((key,intent) for key,intent in s['pending_entries'].items()
                   if _order(ledger,intent).get('gateway_command_id')==proof['command_id']),None)
        if pair is None:return
        key,intent=pair;order=_order(ledger,intent)
        if order.get('gateway_intent_digest')!=proof['intent_digest']:raise ValueError('FOREIGN_CANCEL_PROOF')
        order['gateway_submission']='CANCELED'
        s.get('pending_native_receipts',{}).pop('p04:'+proof['command_id'],None)
        ledger.cancel(key,'MOCK_CONFIRMED_NO_FILL_CANCELLATION')
        ledger.audit('P04_CANCEL_RECONCILED',orders_enabled=False);return
    if action=='p04-submit-ack':
        ack=packet['ack']
        if (not isinstance(ack,dict) or set(ack)!={'source_kind','command_id','intent_digest','outcome'}
                or ack['source_kind']!='MOCK_GATEWAY_ACK' or ack['outcome'] not in ('ACKNOWLEDGED','UNCERTAIN','REJECTED')):
            raise ValueError('INVALID_MOCK_ACK')
        pair=next(((key,intent) for key,intent in s['pending_entries'].items()
                   if _order(ledger,intent).get('gateway_command_id')==ack['command_id']),None)
        if pair is None:return
        key,intent=pair;order=_order(ledger,intent)
        if order['gateway_intent_digest']!=ack['intent_digest']:raise ValueError('FOREIGN_OR_CHANGED_ACK')
        old=order['gateway_submission']
        if old in ('ACKNOWLEDGED','REJECTED'):
            if old!=ack['outcome']:raise ValueError('CONFLICTING_FINAL_MOCK_ACK')
            return
        order['gateway_submission']=ack['outcome']
        if ack['outcome']!='UNCERTAIN':s.get('pending_native_receipts',{}).pop('p04:'+ack['command_id'],None)
        if ack['outcome']=='ACKNOWLEDGED' and (g['mode']!='START_PAPER' or not ledger.session_armed() or s['paused'] or s['halted']):
            hold(ledger,intent,'ACK_AFTER_DISARM_REQUIRES_CANCEL_OR_FILL_RECONCILIATION')
        if ack['outcome']=='REJECTED':ledger.cancel(key,'MOCK_REJECTED_NO_FILL')
        ledger.audit('P04_ACK',outcome=ack['outcome'],fill_confirmed=False);return
    raise ValueError('UNKNOWN_P04_CONTROL')


def handle_control(ledger,packet):
    # Reject malformed/conflicting commands without poisoning the append-only
    # publication journal or preserving a partially applied financial transition.
    before=deepcopy(ledger.state);index=ledger.idx
    ledger.db.execute('SAVEPOINT p04_control')
    try:
        _handle_control(ledger,packet)
    except (ValueError,KeyError,TypeError,ArithmeticError):
        ledger.db.execute('ROLLBACK TO p04_control');ledger.db.execute('RELEASE p04_control')
        ledger.state.clear();ledger.state.update(before);ledger.idx=index
        ledger.audit('P04_COMMAND_REJECTED',reason='INVALID_SCHEMA_SCOPE_OR_CONFLICT',orders_enabled=False)
    else:ledger.db.execute('RELEASE p04_control')


class P04MockWorker:
    """Synchronous MOCK worker using the source's and ledger's existing writers.

    Durable claim BEFORE transport: crash/unknown outcome is reconciled, not retried.
    Constructor boot event durably disarms entries; no transport call on restart.
    """
    def __init__(self,source,ledger,*,registry,contract,transport):
        if type(transport) is not MockExecutionTransport or type(contract) is not MockExecutionContract:
            raise ValueError('ONLY_EXPLICIT_MOCK_TRANSPORT_ALLOWED')
        identity=json.loads(ledger.db.execute("SELECT value FROM v33_meta WHERE key='identity'").fetchone()[0])
        if identity['source_id']!=source.source_id:raise ValueError('FOREIGN_SOURCE_JOURNAL')
        self.source,self.ledger,self.transport=source,ledger,transport
        place=registry.get('order_place')
        available=place.verification in ('DOCUMENTED','LIVE_DISCOVERED') and 'WS' in place.transports
        self.append('initialize:'+digest(asdict(contract)),{'action':'p04-initialize',
            'contract':asdict(contract),'order_capability':available,'registry':registry.safe_status()})
        saved=ledger.state.get('p04_gateway')
        expected=json.loads(json.dumps(asdict(contract)))
        if saved is None or saved['contract']!=expected or saved['order_capability']!=available:
            raise ValueError('P04_CONTRACT_CHANGE_REQUIRES_SEPARATE_REVIEW')
        self.control('OBSERVE',request_id='boot:'+uuid4().hex,actor='mock-worker-boot')

    def append(self,key,payload):
        rows=self.source.append([('CONTROL','p04:'+key,payload)])
        # Process publication backlog first, including claims already durable in
        # source but not checkpointed. No transport is invoked during recovery.
        while True:
            batch=self.source.after(self.ledger.state['cursor'])
            if not batch:break
            self.ledger.apply(batch)
        return rows

    def control(self,mode,*,request_id,actor,duration_ms=0):
        if type(duration_ms) is not int or duration_ms!=0 and duration_ms<1000:raise ValueError('INVALID_SESSION_DURATION')
        if mode not in MODES or not isinstance(request_id,str) or not request_id or not isinstance(actor,str) or len(actor)<3:
            raise ValueError('INVALID_OWNER_COMMAND')
        self.append('mode:'+request_id,{'action':'p04-mode','mode':mode,'request_id':request_id,'actor':actor,'duration_ms':duration_ms})
        return self.status()

    def observe_account(self,evidence):
        self.append('account:'+digest(asdict(evidence)),{'action':'p04-account-evidence','evidence':asdict(evidence)})

    def submit_pending(self):
        if entry_gate(self.ledger):return self.status()
        for key,intent in list(self.ledger.state['pending_entries'].items()):
            if _order(self.ledger,intent).get('gateway_submission'):continue
            self.append('claim:'+intent['id'],{'action':'p04-submit-claim','position_key':key})
            order=_order(self.ledger,intent)
            if order.get('gateway_submission')!='CLAIMED':continue
            if (self.ledger.state['p04_gateway']['mode']!='START_PAPER' or not self.ledger.session_armed()
                    or self.ledger.state['paused'] or self.ledger.state['halted']):return self.status()
            command=command_for(self.ledger,intent)
            try:ack=self.transport.submit(command)
            except Exception:return self.status()  # Claim/hold stays durable.
            self.append('ack:'+digest(ack),{'action':'p04-submit-ack','ack':ack})
        return self.status()

    def reconcile_ack(self,ack):
        self.append('ack:'+digest(ack),{'action':'p04-submit-ack','ack':ack})

    def reconcile_cancel(self,proof):
        self.append('cancel:'+digest(proof),{'action':'p04-cancel-confirmed','proof':proof})

    def status(self):
        s=self.ledger.state;g=s['p04_gateway']
        return {'mode':g['mode'],'result':g['last_result'],'worker_ack_seq':g['last_ack_seq'],
            'stop_state':self.ledger.session_status()['state'],'pending_entries':len(s['pending_entries']),
            'open_positions':len(s['positions']),'unresolved':len(s.get('pending_native_receipts',{})),
            'entry_blocker':entry_gate(self.ledger),'transport':'MOCK_ONLY','orders_enabled':False,
            'live_trading':'DISABLED','model_a_live_admission':'NO_TRADE_ACCOUNT_NOT_RECONCILED'}
