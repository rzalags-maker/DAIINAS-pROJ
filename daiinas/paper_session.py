"""Bounded PAPER session reducer inside the existing ledger; no remote control API."""
from .continuous_store import digest


class SessionMixin:
    def session_start(self,*,request_id,actor,duration_ms=None):
        s=self.state;duration=self.portfolio.session_duration_ms if duration_ms is None else duration_ms
        if not isinstance(actor,str) or len(actor)<3 or not isinstance(request_id,str) or not request_id or type(duration) is not int or not 1000<=duration<=18000000:
            self.audit('SESSION_COMMAND_REJECTED',reason='invalid_actor_idempotency_or_duration');return
        identity=digest({'actor':actor,'duration_ms':duration,'action':'START'})
        seen=s.setdefault('session_commands',{})
        if request_id in seen:
            if seen[request_id]!=identity:self.audit('SESSION_COMMAND_REJECTED',reason='conflicting_session_command_id')
            return
        seen[request_id]=identity
        s['session']={'desired':'ARMED_PAPER','started_ms':s['now_ms'],'expires_ms':s['now_ms']+duration,
                      'duration_ms':duration,'actor':actor,'request_id':request_id,'ack_seq':self.seq,
                      'ack':'DURABLY_APPLIED_IN_LEDGER','stop_reason':None,'exchange_connected':False,'remote_control_connected':False}
        self.audit('SESSION_STARTED',request_id=request_id,actor=actor,expires_ms=s['session']['expires_ms'],live_orders_enabled=False)

    def session_stop(self,reason='OWNER_STOP'):
        s=self.state;session=s.get('session')
        if not session:return
        if session['desired']=='DISARMED':return
        session.update(desired='DISARMED',stopped_ms=s['now_ms'],stop_reason=reason,ack_seq=self.seq)
        for key in list(s['pending_entries']):self.cancel(key,'session_stop_cancel_unfilled')
        self.audit('SESSION_STOPPED',reason=reason,status='STOPPED_WITH_EXPOSURE' if s['positions'] or s.get('pending_native_receipts') else 'STOPPED_FLAT',live_orders_enabled=False)

    def session_step(self):
        session=self.state.get('session')
        if session and session['desired']=='ARMED_PAPER' and self.state['now_ms']>=session['expires_ms']:self.session_stop('SESSION_EXPIRED')

    def session_armed(self):
        session=self.state.get('session')
        return bool(session and session['desired']=='ARMED_PAPER' and self.state['now_ms']<session['expires_ms'])

    def session_status(self):
        s=self.state;session=s.get('session')
        if not session:return {'state':'NOT_STARTED','remote_control_connected':False,'exchange_connected':False}
        if session['desired']=='DISARMED':observed='STOPPED_WITH_EXPOSURE' if s['positions'] or s.get('pending_native_receipts') else 'STOPPED_FLAT'
        elif s.get('pending_native_receipts'):observed='PENDING_RECONCILIATION'
        elif s['halted']:observed='RISK_HALT'
        elif s['paused']:observed='PAUSED'
        elif not self.account_limits()['ready_for_paper']:observed='WAITING_ACCOUNT_RECONCILIATION'
        else:observed='MONITORING_PAPER'
        return {**session,'state':observed,'open_positions':len(s['positions']),'pending_entries':len(s['pending_entries']),
                'protection':{key:p.get('protection',{}) for key,p in s['positions'].items()},
                'pending_native_receipts':s.get('pending_native_receipts',{}),'worker_checkpoint_ms':s['now_ms']}
