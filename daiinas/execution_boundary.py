"""Inert order contract + strict MOCK venue observations. No HTTP/order transport."""
from decimal import Decimal
from .continuous_store import digest


class InertOrderGateway:
    def status(self):return {'connection':'NOT_CONNECTED','orders_enabled':False,'transport':'INERT'}
    def preview(self,*,account_id,client_oid,symbol,side,quantity,leverage,order_type,stop_price,target_price,limit_price=None,best_bid=None,best_ask=None):
        if side not in ('LONG','SHORT') or order_type not in ('MARKET_IOC','LIMIT','POST_ONLY_LIMIT') or not 1<=leverage<=5:
            raise ValueError('Unsupported preview')
        if any(Decimal(str(x))<=0 for x in (quantity,stop_price,target_price)):raise ValueError('Invalid preview amounts')
        crossing=bool(limit_price is not None and best_bid is not None and best_ask is not None and (Decimal(str(limit_price))>=Decimal(str(best_ask)) if side=='LONG' else Decimal(str(limit_price))<=Decimal(str(best_bid))))
        return {'prospective_liquidity':'TAKER' if crossing or order_type=='MARKET_IOC' else 'UNVERIFIED_PASSIVE',
                'post_only_rejected':order_type=='POST_ONLY_LIMIT' and crossing,'account_id':account_id,'clientOid':client_oid,'symbol':symbol,'positionSide':side,
                'quantity':str(quantity),'leverage':leverage,'order_type':order_type,'margin_mode':'ISOLATED',
                'stop_price':str(stop_price),'target_price':str(target_price),'reduce_only_children':True,
                'orders_enabled':False,'status':'PAPER_PREVIEW_ONLY','preview_digest':digest([account_id,client_oid,symbol,side,str(quantity),leverage])}
    def place_order(self,*args,**kwargs):raise PermissionError('LIVE ORDERS DISABLED: inert gateway has no transport')
    def cancel_order(self,*args,**kwargs):raise PermissionError('LIVE ORDERS DISABLED: no real cancellation transport')
    def modify_order(self,*args,**kwargs):raise PermissionError('LIVE ORDERS DISABLED: no real modification transport')


def owned_order_ids(position_id):
    return {kind:'MOCK-'+kind+':'+digest(position_id)[:24] for kind in ('entry','stop','target')}


def validate_mock_receipt(packet,*,account_id,now_ms,position,known_orders):
    """Normalized future-adapter boundary, MOCK only. Never assumes a WS match=close.

    Receipt values immutable across WS/REST duplicates; authority snapshot may
    advance. Unknown sibling state freezes vacancy release until fully reconciled.
    """
    required={'source_kind','fill_id','order_id','account_id','symbol','position_side','timestamp_ms',
              'price','quantity','fee','fee_currency','liquidity','funding','authority','phase','leverage'}
    if not isinstance(packet,dict) or set(packet)!=required or packet['source_kind']!='MOCK_NATIVE':raise ValueError('Not a normalized MOCK venue fill')
    if packet['account_id']!=account_id or packet['symbol']!=position['symbol'] or packet['position_side']!=position['direction']:
        raise ValueError('Foreign account/instrument/side fill')
    if packet['order_id'] not in known_orders or not isinstance(packet['fill_id'],str) or not packet['fill_id']:
        raise ValueError('Unknown order/fill ownership')
    if type(packet['timestamp_ms']) is not int or not position['entry_received_ms']<=packet['timestamp_ms']<=now_ms:
        raise ValueError('Future/pre-entry venue fill')
    if packet['phase'] not in ('ENTRY','EXIT') or packet['leverage']!=position['leverage']:raise ValueError('Unowned phase/leverage mutation')
    if any(not isinstance(packet[k],str) for k in ('price','quantity','fee','funding')):raise ValueError('Exact decimal string required')
    numbers={k:Decimal(packet[k]) for k in ('price','quantity','fee','funding')}
    if any(not x.is_finite() for x in numbers.values()) or min(numbers['price'],numbers['quantity'])<=0 or numbers['fee']<0:
        raise ValueError('Invalid normalized fill amounts')
    if packet['fee_currency']!='USDT' or packet['liquidity'] not in ('MAKER','TAKER'):raise ValueError('Unknown charged fee attribution')
    if numbers['quantity']>Decimal(position['quantity_contracts']):raise ValueError('Exit exceeds owned position')
    authority=packet['authority']
    if not isinstance(authority,dict) or set(authority)!={'snapshot_id','timestamp_ms','complete','position_quantity','sibling_status','reduce_only','cash','free_margin','unknown_orders','order_status','protected_quantity'}:
        raise ValueError('Missing authoritative scope reconciliation')
    if (not isinstance(authority['snapshot_id'],str) or not authority['snapshot_id'] or type(authority['timestamp_ms']) is not int
        or not 0<=now_ms-authority['timestamp_ms']<=15000 or type(authority['complete']) is not bool or authority['complete'] is not True):
        raise ValueError('Incomplete/stale authoritative venue scope')
    remaining=Decimal(position['quantity_contracts'])-numbers['quantity']
    observed_quantity=numbers['quantity'] if packet['phase']=='ENTRY' else remaining
    if Decimal(authority['position_quantity'])!=observed_quantity or authority['reduce_only'] is not True or authority['unknown_orders']!=[]:
        raise ValueError('Position/owned order scope mismatch')
    expected_sibling='ACKED' if packet['phase']=='ENTRY' else 'CANCELED' if remaining==0 else 'ACKED'
    if Decimal(authority['protected_quantity'])!=observed_quantity:raise ValueError('Unconfirmed child protection quantity')
    allowed_status=('FILLED','CANCELED') if packet['phase']=='ENTRY' else ('FILLED',) if remaining==0 else ('PARTIAL',)
    if authority['order_status'] not in allowed_status:raise ValueError('Unfilled/unknown entry or exit status')
    if authority['sibling_status']!=expected_sibling:raise ValueError('Sibling cancellation/protection pending reconciliation')
    cash,free=Decimal(authority['cash']),Decimal(authority['free_margin'])
    if not cash.is_finite() or not free.is_finite() or not 0<=free<=cash:raise ValueError('Invalid reconciled venue cash/free margin')
    return numbers,digest({k:v for k,v in packet.items() if k!='authority'})
