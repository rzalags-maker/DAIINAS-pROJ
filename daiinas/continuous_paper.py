"""Durable v3.3 experimental observed-quote paper account. LIVE ORDERS DISABLED.

Reuses v3.2 quote sizing/fill math and shadow classification. Publication time
and journal sequence decide availability; exchange time validates quote age.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from copy import deepcopy
from pathlib import Path
import asyncio
import json
import math
import sqlite3

from .adaptive import CapitalController
from .paper_micro import PaperPolicy, size_for_quote, finish_position, prepare_rules
from .shadow_flow import ShadowPolicy, observe
from .continuous_store import SourceJournal, Timeline, canonical, digest, connect_owned


class PaperLedger:
    def __init__(self,path,source_id,policy=PaperPolicy(),shadow=ShadowPolicy()):
        if policy.initial_capital_usdt!=8 or policy.margin_fraction>.8:
            raise ValueError('v3.3 starts with one 8-USDT account and <=80% margin')
        self.db=connect_owned(path,'v33-paper-ledger')
        self.policy,self.shadow=policy,shadow
        identity=canonical({'source_id':source_id,'paper':asdict(policy),'shadow':asdict(shadow),'schema':1})
        row=self.db.execute("SELECT value FROM v33_meta WHERE key='identity'").fetchone()
        if row and row[0]!=identity:raise ValueError('Account/source/policy identity changed; never reset existing money state')
        self.db.execute('INSERT OR IGNORE INTO v33_meta VALUES (?,?)',('identity',identity))
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS processed(seq INTEGER PRIMARY KEY,sha256 TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS audit(seq INTEGER,idx INTEGER,action TEXT,payload TEXT NOT NULL,PRIMARY KEY(seq,idx));
          CREATE TABLE IF NOT EXISTS closed_positions(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'Immutable audit'); END;
          CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'Immutable audit'); END;
        ''')
        row=self.db.execute('SELECT payload FROM checkpoint WHERE id=1').fetchone()
        self.state=json.loads(row[0]) if row else {
            'cursor':0,'now_ms':-1,'input_digest':'','cash':8.,'peak':8.,'last_equity':8.,
            'halted':False,'max_drawdown':0.,'external_flows':0.,'realized':0.,'fees':0.,'carry':0.,
            'paused':False,'position':None,'pending':None,'exit_request':None,'scan':None,
            'books':{},'quotes':{},'trades':{},'episodes':{},'last_print':{},'counts':{},'mark_status':'FLAT'}

    def close(self):self.db.close()

    def audit(self,action,**detail):
        self.db.execute('INSERT INTO audit VALUES (?,?,?,?)',
                        (self.seq,self.idx,action,canonical({'time_ms':self.state['now_ms'],**detail})))
        self.idx+=1
        self.state['counts'][action]=self.state['counts'].get(action,0)+1

    def pins(self):
        return sorted({x['symbol'] for x in (self.state['position'],self.state['pending'],self.state['exit_request']) if x})

    def spec(self,symbol):
        scan=self.state['scan']
        if not scan or symbol in scan['unavailable']:return None
        return scan['specs'].get(symbol)

    def rules(self,symbol):
        spec=self.spec(symbol)
        return prepare_rules({'paper_contract_specs':{symbol:spec}})[symbol] if spec else None

    def book_ok(self,symbol,quote=None):
        now=self.state['now_ms'];book=self.state['books'].get(symbol)
        if not book or not book.get('verified') or not 0<=now-book['available_ms']<=self.shadow.max_book_age_ms:
            return False
        if quote is not None:
            # Only actually displayed best-level liquidity, never invented depth.
            for name,qkey in [('best_bid','bid'),('best_ask','ask')]:
                if name not in book or float(book[name])!=float(quote[qkey]):return False
            if min(float(book.get('bid_base_size',0)),float(book.get('ask_base_size',0)))<=0:return False
        return True

    def valid_quote(self,q,now):
        try:
            bid,ask=float(q['bid']),float(q['ask'])
            sizes=[float(q[k]) for k in ('bid_base_size','ask_base_size')]
            t=int(q['timestamp'])
            return (all(math.isfinite(v) and v>0 for v in (bid,ask,*sizes)) and bid<ask
                    and 0<=now-t<=self.policy.max_quote_age_ms)
        except (ValueError,TypeError,KeyError):return False

    def executable_quote(self,symbol,q):
        if not self.book_ok(symbol,q):return None
        book=self.state['books'][symbol]
        return {**q,'bid_base_size':min(float(q['bid_base_size']),float(book['bid_base_size'])),
                'ask_base_size':min(float(q['ask_base_size']),float(book['ask_base_size']))}

    def request_exit(self,reason):
        pos=self.state['position']
        if pos is None:return
        priority={'STOP':0,'ACCOUNT_HALT':1,'TARGET':2,'TIME':3,'FLOW_INVALIDATION':4,
                  'SPREAD':5,'DEPTH':6,'DATA_HEALTH':7,'CONTRACT_CHANGED':1}
        old=self.state['exit_request']
        if old and priority.get(old['reason'],9)<=priority.get(reason,9):return
        q=self.state['quotes'].get(pos['symbol'],{})
        self.state['exit_request']={'symbol':pos['symbol'],'reason':reason,'requested_seq':self.seq,
                'requested_ms':self.state['now_ms'],'provider_ms':q.get('timestamp',pos['entry_provider_ms'])}
        self.audit('EXIT_REQUEST',symbol=pos['symbol'],reason=reason,position_id=pos['id'])

    def unresolved(self,reason):
        pos=self.state['position']
        if pos and pos.get('unresolved')!=reason:
            pos['unresolved']=reason
            self.audit('UNRESOLVED',symbol=pos['symbol'],reason=reason,position_id=pos['id'])

    def mark(self,external_flow=0.):
        s=self.state;pos=s['position'];equity=s['cash']
        valid=True
        if pos:
            q=s['quotes'].get(pos['symbol'])
            if not q or not self.valid_quote(q,s['now_ms']) or not self.book_ok(pos['symbol']):
                valid=False;s['mark_status']='UNRESOLVED_STALE_MARK'
                self.request_exit('DATA_HEALTH');self.unresolved('missing_or_stale_executable_mark')
                equity=s['last_equity']+external_flow
            else:
                mtm=finish_position(pos,q,s['now_ms'],'MARK_ONLY',self.policy)
                equity=s['cash']+mtm['gross_pnl_usdt']-mtm['exit_fee_usdt']-mtm['modeled_carry_usdt']
                s['mark_status']='OBSERVED_QUOTE_WITH_MODELED_EXIT_COSTS'
        else:s['mark_status']='FLAT'
        ctrl=CapitalController(max(s['peak'],1e-9))
        ctrl.peak=s['peak'];ctrl.halted=s['halted'];ctrl.last_equity=s['last_equity']
        if equity<=0:
            ctrl.halted=True;ctrl.peak=max(1e-9,ctrl.peak+external_flow)
            dd=max(0,(ctrl.peak-equity)/ctrl.peak)
        else:
            decision=ctrl.evaluate(equity=equity,external_capital_flow=external_flow,
                fresh_market_data=valid,strategy_validated=False,executable_contract=False,
                market_regime='micro',execution_costs_acceptable=False)
            dd=decision.drawdown_fraction
        newly=ctrl.halted and not s['halted']
        s['peak'],s['halted'],s['last_equity']=ctrl.peak,ctrl.halted,equity
        s['max_drawdown']=max(s['max_drawdown'],dd)
        if newly:self.audit('HALTED',drawdown=dd)
        if s['halted']:
            self.request_exit('ACCOUNT_HALT')
            if s['pending']:
                self.audit('REJECTED',reason='latched_account_halt',signal_id=s['pending']['id']);s['pending']=None

    def scan(self,payload):
        new=Timeline.scan(payload,self.state['now_ms'])
        old=self.state['scan']
        for obj in (self.state['position'],self.state['pending']):
            if not obj:continue
            sym=obj['symbol'];spec=new['specs'].get(sym)
            changed=(not spec or sym in new['unavailable'] or digest(spec['rules'])!=obj['rules_hash'])
            if changed:
                if obj is self.state['pending']:
                    self.audit('REJECTED',symbol=sym,reason='contract_changed_or_unavailable',signal_id=obj['id'])
                    self.state['pending']=None
                else:
                    self.request_exit('CONTRACT_CHANGED');self.unresolved('contract_changed_or_unavailable')
        self.state['scan']=new
        protected=set(new['watch']['deep_symbols'])|set(self.pins())
        for name in ('trades','episodes','last_print','books','quotes'):
            self.state[name]={k:v for k,v in self.state[name].items() if k in protected}
        self.audit('SCAN',scan_id=self.key,selected=new['watch']['deep_symbols'],pins=self.pins(),
                   unavailable=new['unavailable'],capacity_exhausted=new['watch'].get('capacity_exhausted',False))

    def quote(self,sym,q):
        s=self.state;now=s['now_ms']
        if not self.valid_quote(q,now):
            self.audit('REJECTED_QUOTE',symbol=sym,reason='stale_future_or_invalid_quote');return
        previous=s['quotes'].get(sym)
        if previous and int(q['timestamp'])<int(previous['timestamp']):
            self.audit('REJECTED_QUOTE',symbol=sym,reason='quote_timestamp_regression');return
        q={**q,'available_ms':now,'source_seq':self.seq}
        s['quotes'][sym]=q
        pos=s['position']
        if pos and pos['symbol']==sym:
            sign=1 if pos['direction']=='LONG' else -1
            executable=float(q['bid'] if sign==1 else q['ask'])
            if sign*(executable-pos['planned_stop_mid'])<=0:self.request_exit('STOP')
            elif sign*(executable-pos['planned_target_mid'])>=0:self.request_exit('TARGET')
            elif now-pos['entry_received_ms']>=self.policy.maximum_holding_ms:self.request_exit('TIME')
            spread=(float(q['ask'])-float(q['bid']))/((float(q['ask'])+float(q['bid']))/2)*10000
            if spread>self.shadow.max_spread_bps:self.request_exit('SPREAD')
        self.mark()
        pos=s['position']
        if pos and pos['symbol']==sym:
            current=self.spec(sym)
            request=s['exit_request']
            data=self.executable_quote(sym,q)
            if not current or digest(current['rules'])!=pos['rules_hash']:
                self.request_exit('CONTRACT_CHANGED');self.unresolved('missing_or_changed_asof_exit_rules')
            elif request and self.seq>request['requested_seq'] and now-request['requested_ms']>=self.policy.minimum_entry_latency_ms and int(q['timestamp'])>request['provider_ms']:
                needed=pos['quantity_contracts']*pos['contract_multiplier']
                available=float(data['bid_base_size' if pos['direction']=='LONG' else 'ask_base_size']) if data else 0
                if available<needed:
                    self.unresolved('insufficient_verified_depth_for_full_exit')
                else:
                    closing={**pos,'fee_rate':max(current['taker_fee_rate'],self.policy.minimum_taker_fee_rate)}
                    done=finish_position(closing,data,now,request['reason'],self.policy)
                    done['exit_source_seq']=self.seq;done['exit_provider_ms']=int(q['timestamp'])
                    s['cash']+=done['gross_pnl_usdt']-done['exit_fee_usdt']-done['modeled_carry_usdt']
                    s['fees']+=done['exit_fee_usdt'];s['carry']+=done['modeled_carry_usdt'];s['realized']+=done['net_pnl_usdt']
                    self.db.execute('INSERT INTO closed_positions VALUES (?,?)',(pos['id'],canonical(done)))
                    self.audit('CLOSED',position_id=pos['id'],reason=request['reason'],net_pnl=done['net_pnl_usdt'])
                    s['position']=s['exit_request']=None
                    self.mark()
            return  # no same-event round-trip or immediate new signal after exit
        pending=s['pending']
        if pending and pending['symbol']==sym:
            elapsed=now-pending['signal_ms']
            if elapsed>=self.policy.minimum_entry_latency_ms and self.seq>pending['source_seq'] and int(q['timestamp'])>pending['provider_ms']:
                reason=None;plan=None
                current=self.spec(sym);scan=s['scan'];data=self.executable_quote(sym,q)
                if s['paused'] or s['halted']:reason='paused_or_halted'
                elif not current or digest(current['rules'])!=pending['rules_hash']:reason='missing_or_changed_asof_entry_rules'
                elif sym not in scan['watch']['deep_symbols'] or sym in scan['watch'].get('blocked_new_entries',[]):reason='not_current_entry_candidate'
                elif not data:reason='unverified_or_unaligned_depth_at_entry'
                elif abs((float(q['bid'])+float(q['ask']))/2-pending['signal_mid'])/pending['signal_mid']*10000>self.policy.maximum_entry_drift_bps:reason='price_drift'
                elif (float(q['ask'])-float(q['bid']))/((float(q['ask'])+float(q['bid']))/2)*10000>self.shadow.max_spread_bps:reason='spread_over_budget'
                else:
                    rule,fee=self.rules(sym)
                    plan,reason=size_for_quote(equity=s['cash'],peak=s['peak'],quote=data,
                        direction=pending['direction'],rules=rule,observed_fee=fee,policy=self.policy)
                s['pending']=None
                if plan is None:self.audit('REJECTED',signal_id=pending['id'],symbol=sym,reason=reason)
                else:
                    s['cash']-=plan['entry_fee_usdt'];s['fees']+=plan['entry_fee_usdt']
                    s['position']={**plan,'id':'position:'+pending['id'],'symbol':sym,'rules_hash':pending['rules_hash'],
                        'signal_received_ms':pending['signal_ms'],'entry_received_ms':now,
                        'entry_provider_ms':int(q['timestamp']),'entry_source_seq':self.seq,'unresolved':None}
                    self.audit('OPENED',position_id=s['position']['id'],symbol=sym,direction=plan['direction'],
                               quantity=plan['quantity_contracts'],planned_loss=plan['planned_loss_usdt'])
                    self.mark()
                return
        if s['position'] or s['pending'] or s['paused'] or s['halted'] or not s['scan']:return
        scan=s['scan'];spec=self.spec(sym)
        if (not spec or sym not in scan['watch']['deep_symbols'] or sym in scan['watch'].get('blocked_new_entries',[])
                or scan['watch'].get('capacity_exhausted') or now-scan['available_ms']>600000):return
        feature=observe(received_ms=now,recent_trades=s['trades'].get(sym,[]),
                        book_received_ms=s['books'].get(sym,{}).get('available_ms') if self.book_ok(sym,q) else None,
                        quote=q,policy=self.shadow)
        if feature['state']!='PRESSURE_CANDIDATE':return
        prior=s['episodes'].get(sym);newest=s['last_print'].get(sym,-1)
        if prior and (newest<=prior[1] or (now-prior[0]<self.shadow.window_ms and feature['direction']==prior[2])):return
        s['episodes'][sym]=[now,newest,feature['direction']]
        direction='LONG' if feature['direction']=='LONG_PRESSURE' else 'SHORT'
        s['pending']={'id':f'signal:{self.seq}:{sym}:{direction}','symbol':sym,'direction':direction,
            'source_seq':self.seq,'signal_ms':now,'provider_ms':int(q['timestamp']),
            'signal_mid':(float(q['bid'])+float(q['ask']))/2,'rules_hash':digest(spec['rules'])}
        self.audit('SIGNAL',**s['pending'],strategy_validated=False)

    def control(self,p):
        s=self.state;action=p['action']
        if action in ('pause','resume'):
            s['paused']=action=='pause'
            if s['paused'] and s['pending']:
                self.audit('REJECTED',reason='operator_pause',signal_id=s['pending']['id']);s['pending']=None
        elif action=='reset-halt':
            if len(p.get('review_note','').strip())<8 or s['position'] or s['pending'] or s['cash']<=0:
                raise ValueError('Reviewed reset requires a note, positive equity, and a flat account')
            s['halted']=False;s['peak']=s['cash']
        elif action=='capital-flow':
            amount=float(p['amount'])
            reserved=s['position']['margin_reserved_usdt'] if s['position'] else 0
            if not math.isfinite(amount) or not amount or s['cash']+amount<=reserved:
                raise ValueError('Invalid simulated capital flow or insufficient free cash')
            s['cash']+=amount;s['external_flows']+=amount
            self.mark(external_flow=amount)
        else:raise ValueError('Unsupported paper control')
        self.audit('CONTROL',operator_action=action,**{k:v for k,v in p.items() if k!='action'})

    def apply(self,rows):
        previous=deepcopy(self.state)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for seq,available,kind,key,payload,sha in rows:
                known=self.db.execute('SELECT sha256 FROM processed WHERE seq=?',(seq,)).fetchone()
                if known:
                    if known[0]!=sha:raise ValueError('Conflicting replay record')
                    continue
                if seq!=self.state['cursor']+1 or available<self.state['now_ms']:
                    raise ValueError('Missing or out-of-order publication journal')
                if sha!=digest({'kind':kind,'key':key,'available_ms':available,'payload':payload}):
                    raise ValueError('Source record digest mismatch')
                self.seq,self.idx,self.key=seq,0,key
                s=self.state;s['now_ms']=available
                if s['pending'] and available-s['pending']['signal_ms']>self.policy.entry_ttl_ms:
                    self.audit('UNFILLED',reason='entry_ttl',signal_id=s['pending']['id']);s['pending']=None
                if kind=='SCAN':self.scan(payload)
                elif kind=='CONTROL':
                    try:self.control(payload)
                    except (ValueError,KeyError,TypeError) as exc:
                        self.audit('CONTROL_REJECTED',reason=str(exc),operator_action=payload.get('action'))
                elif kind=='HEALTH':
                    affected=payload.get('symbol')
                    for symbol in list(s['books']):
                        if affected is None or affected==symbol:s['books'].pop(symbol,None)
                    if s['position'] and (affected is None or affected==s['position']['symbol']):
                        self.request_exit('DATA_HEALTH');self.unresolved(payload['state'])
                    self.audit('HEALTH',**payload)
                elif kind=='MARKET':
                    sym,channel=payload['symbol'],payload['channel'];data=payload['normalized']
                    if int(payload['event_ms'])>available or int(payload['received_ms'])>available:
                        raise ValueError('Future market data publication')
                    if channel=='level2':
                        s['books'][sym]={**data,'available_ms':available}
                    elif channel=='execution':
                        if not isinstance(data['buyer_is_maker'],bool) or not all(math.isfinite(float(data[k])) and float(data[k])>0 for k in ('price','quantity')):
                            raise ValueError('Invalid trade side/units')
                        records=s['trades'].setdefault(sym,[])
                        records.append({**data,'received_ms':available})
                        s['trades'][sym]=[v for v in records if available-v['received_ms']<=self.shadow.window_ms][-5000:]
                        s['last_print'][sym]=available
                    elif channel=='tickerV2':self.quote(sym,data)
                    else:raise ValueError('Unknown market channel')
                elif kind!='CLOCK':raise ValueError('Unknown journal kind')
                self.mark()
                if s['position'] and available-s['position']['entry_received_ms']>=self.policy.maximum_holding_ms:
                    self.request_exit('TIME')
                s['cursor']=seq;s['input_digest']=digest([s['input_digest'],sha])
                self.db.execute('INSERT INTO processed VALUES (?,?)',(seq,sha))
            self.db.execute('INSERT INTO checkpoint VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(canonical(self.state),))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');self.state=previous;raise

    def report(self):
        s=self.state
        return {'status':'PAPER_ONLY','live_orders_enabled':False,'strategy_validated':False,
            'initial_capital':8.,'cash':s['cash'],'equity_last_mark':s['last_equity'],'mark_status':s['mark_status'],
            'realized_net_pnl':s['realized'],'cash_pnl_excluding_external_flows':s['cash']-8-s['external_flows'],
            'external_simulated_flows':s['external_flows'],'fees':s['fees'],'modeled_carry':s['carry'],
            'peak':s['peak'],'maximum_drawdown':s['max_drawdown'],'halted':s['halted'],'paused_new_entries':s['paused'],
            'open_position':s['position'],'pending_entry':s['pending'],'pending_exit':s['exit_request'],
            'pins':self.pins(),'source_cursor':s['cursor'],'input_digest':s['input_digest'],
            'counts':s['counts'],'scan':s['scan'],'checkpoint_available_ms':s['now_ms'],
            '24h_host_gate':'BLOCKED — HOST NOT PROVISIONED'}


class Pipeline:
    """One dedicated writer thread; source commit precedes idempotent paper apply."""
    def __init__(self,source_path,paper_path,policy=PaperPolicy(),shadow=ShadowPolicy()):
        if Path(source_path).resolve()==Path(paper_path).resolve():raise ValueError('Independent source and paper files required')
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='v33-sqlite')
        def initialize():
            self.source=SourceJournal(source_path)
            self.ledger=PaperLedger(paper_path,self.source.source_id,policy,shadow)
            self.recover()
        try:self.executor.submit(initialize).result()
        except BaseException:self.executor.shutdown();raise

    def recover(self):
        while True:
            rows=self.source.after(self.ledger.state['cursor'])
            if not rows:break
            self.ledger.apply(rows)

    def _append(self,packets):
        self.source.append(packets)
        self.recover()
        return self.ledger.report()

    async def append(self,packets):
        return await asyncio.get_running_loop().run_in_executor(self.executor,self._append,packets)

    async def report(self):
        return await asyncio.get_running_loop().run_in_executor(self.executor,self.ledger.report)

    def close(self):
        self.executor.submit(lambda:(self.ledger.close(),self.source.close())).result()
        self.executor.shutdown()
