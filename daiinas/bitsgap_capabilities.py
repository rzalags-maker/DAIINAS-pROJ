"""Typed catalog metadata only. No command transport or execution authority."""
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
import re
import time

from .bitsgap_futures_observe import _index_catalog, _enum_tables

DOCS = 'Bitsgap/bitsgap-api-docs@d27611b63d56c65c9797e61d34b40b1f175a7664'
READS = ('manual','conf_enums','conf_pairs','price','market_price','balance','orders',
         'positions','positions_settings','orders_history','order_detail')
WRITES = ('order_place','order_cancel','position_close','leverage_change','margin_type_change','margin_size_change')
PROTECTION = ('native_tp_sl','trigger_reference','partial_child_resize','sibling_cancel','restart_persistence')
STATES = ('DOCUMENTED','LIVE_DISCOVERED','LIVE_VERIFIED','UNVERIFIED','UNSUPPORTED')


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: str
    required: bool
    enum: tuple = ()
    max_len: int = 250
    positive: bool = False
    minimum: str | None = None


@dataclass(frozen=True)
class Capability:
    operation: str
    transports: tuple
    parameters: tuple
    exchange: str
    market_id: int
    safety: str
    permission: str
    verification: str
    evidence: str
    validated_ms: int | None
    schema_known: bool = False
    limits: tuple = ()
    reason: str = 'ACCOUNT_PERMISSION_AND_SEMANTICS_NOT_VERIFIED'
    runtime_enabled: bool = False

    def safe_status(self):
        return asdict(self)


class BitsgapCapabilityRegistry:
    def __init__(self, records, *, synthetic):
        self.records = {x.operation:x for x in records}
        self.synthetic = synthetic

    @classmethod
    def documented(cls):
        records=[]
        for name in (*READS,*WRITES,*PROTECTION,'reduce_only','transfer','withdraw'):
            write = name in WRITES
            protection = name in PROTECTION
            forbidden = name in ('transfer','withdraw')
            records.append(Capability(name, ('WS',) if write else ('REST','WS') if name in READS else (),
                (), 'KUCOIN_FUTURES', 0, 'PROHIBITED' if forbidden else 'MUTATING' if write else 'SEMANTIC' if protection or name=='reduce_only' else 'READ_ONLY',
                'NEVER' if forbidden else 'START_LIVE_OWNER_AUTHORIZATION' if write else 'OBSERVE',
                'UNVERIFIED' if protection or forbidden else 'DOCUMENTED', DOCS, None,
                reason='PERSISTENCE_AND_TRIGGER_CONTRACT_MISSING' if protection else 'LIVE_CATALOG_PENDING'))
        return cls(records, synthetic=True)

    @classmethod
    def from_catalogs(cls, manual, enums, *, observed_ms, authenticated=False):
        if type(observed_ms) is not int or observed_ms < 0 or type(authenticated) is not bool:
            raise ValueError('INVALID_CAPABILITY_PROVENANCE')
        catalog = _index_catalog(manual,'MANUAL');tables = _index_catalog(enums,'ENUMS')
        market = _enum_tables(tables)
        records=[]
        for name, old in cls.documented().records.items():
            desc=catalog.get(name)
            if name in PROTECTION or name in ('transfer','withdraw'):
                records.append(Capability(**{**asdict(old),'market_id':market}));continue
            if name=='reduce_only':
                ro=catalog.get('order_place',{}).get('params',{}).get('ro') if isinstance(catalog.get('order_place'),dict) else None
                if not isinstance(ro,dict):
                    records.append(replace(old,market_id=market,transports=(),verification='UNVERIFIED',
                        reason='REDUCE_ONLY_SCHEMA_NOT_ADVERTISED',validated_ms=observed_ms));continue
                desc={'transport':{},'params':{}}
            if desc is None:
                records.append(Capability(**{**asdict(old),'market_id':market,'transports':(),
                    'verification':'UNSUPPORTED','evidence':'AUTHENTICATED_MANUAL' if authenticated else 'SYNTHETIC_MANUAL',
                    'validated_ms':observed_ms,'reason':'NOT_ADVERTISED_BY_THIS_CATALOG'}));continue
            if not isinstance(desc,dict):raise ValueError('INVALID_CAPABILITY_SCHEMA')
            if desc.get('demo_only') is True:
                records.append(Capability(**{**asdict(old),'market_id':market,'transports':(),
                    'verification':'UNSUPPORTED','reason':'DEMO_ONLY_NOT_REAL_FUTURES','validated_ms':observed_ms}));continue
            transport=desc.get('transport',{})
            if not isinstance(transport,dict) or any(k not in ('ws','rest') or type(v) is not bool for k,v in transport.items()):
                raise ValueError('INVALID_CAPABILITY_TRANSPORT')
            parameters=[];known=isinstance(desc.get('params'),dict)
            for key, spec in (desc.get('params',{}) if known else {}).items():
                if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',key) or not isinstance(spec,dict):
                    raise ValueError('INVALID_CAPABILITY_PARAMETER')
                kind=spec.get('type','UNKNOWN');required=spec.get('required',False)
                if type(required) is not bool:raise ValueError('INVALID_CAPABILITY_PARAMETER')
                items=()
                if 'enum' in spec:
                    table=tables.get(spec['enum'],{});raw=table.get('items') if isinstance(table,dict) else None
                    if (not isinstance(raw,dict) or not raw or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in raw.items())
                            or len(set(raw.values()))!=len(raw)):
                        known=False
                    else:items=tuple(sorted(raw.items()))
                if 'value' in spec and spec['value'] not in ('> 0','>0','>= 1','>=1'):
                    known=False
                if not isinstance(kind,str):raise ValueError('INVALID_CAPABILITY_PARAMETER')
                if kind not in ('unsigned(enum)','unsigned(bool)','string','string(decimal)','string(pair)'):
                    known=False
                maximum=spec.get('max_len',250)
                if type(maximum) is not int or not 0<maximum<=4096:raise ValueError('INVALID_CAPABILITY_PARAMETER')
                parameters.append(Parameter(key,kind,required,items,maximum,spec.get('value') in ('> 0','>0'),
                    '1' if spec.get('value') in ('>= 1','>=1') else None))
            limits=desc.get('limit',{})
            if not isinstance(limits,dict) or any(k not in ('s1','s10','h1','d1') or type(v) is not int or v<=0 for k,v in limits.items()):
                raise ValueError('INVALID_CAPABILITY_LIMIT')
            records.append(Capability(name,tuple(k.upper() for k,v in sorted(transport.items()) if v),tuple(parameters),
                'KUCOIN_FUTURES',market,old.safety,old.permission,
                'LIVE_DISCOVERED' if authenticated else 'DOCUMENTED',
                'AUTHENTICATED_MANUAL_AND_CONF_ENUMS' if authenticated else 'SYNTHETIC_CATALOG_NOT_LIVE',
                observed_ms,known,tuple(sorted(limits.items())),
                'DECLARED_NOT_EXECUTED_OR_ACCOUNT_PERMISSION_VERIFIED'))
        return cls(records, synthetic=not authenticated)

    @classmethod
    def discover(cls, observer):
        # Existing allowlisted signed reads ONLY. Never calls read(command).
        manual=observer.topic('manual');enums=observer.topic('conf_enums')
        return cls.from_catalogs(manual,enums,observed_ms=int(time.time()*1000),authenticated=True)

    def get(self, name):
        if name not in self.records:raise ValueError('UNKNOWN_CAPABILITY')
        return self.records[name]

    def validate_parameters(self,name,params,*,transport='WS'):
        """Validate a future command shape without sending it or enabling it."""
        record=self.get(name)
        if record.safety=='PROHIBITED' or record.verification in ('UNVERIFIED','UNSUPPORTED'):
            raise ValueError('CAPABILITY_NOT_AVAILABLE')
        if transport not in record.transports or not record.schema_known or not isinstance(params,dict):
            raise ValueError('CAPABILITY_SCHEMA_OR_TRANSPORT_UNVERIFIED')
        schema={p.name:p for p in record.parameters}
        if set(params)-set(schema) or any(p.required and p.name not in params for p in record.parameters):
            raise ValueError('UNEXPECTED_OR_MISSING_PARAMETER')
        if record.market_id<=0 or type(params.get('em')) is not int or params['em']!=record.market_id:
            raise ValueError('FOREIGN_FUTURES_MARKET')
        for key,value in params.items():
            p=schema[key]
            if p.kind=='unsigned(enum)':
                if type(value) is not int or value not in dict(p.enum).values():raise ValueError('INVALID_ENUM')
            elif p.kind=='unsigned(bool)':
                if type(value) is not int or value not in (0,1):raise ValueError('INVALID_BOOL_CODE')
            else:
                if not isinstance(value,str) or not 0<len(value)<=p.max_len:raise ValueError('INVALID_PARAMETER')
                if p.kind=='string(pair)' and not re.fullmatch(r'[A-Z0-9]{2,30}_[A-Z0-9]{2,30}',value):raise ValueError('INVALID_PAIR')
                if p.kind=='string(decimal)':
                    try:d=Decimal(value)
                    except InvalidOperation:raise ValueError('INVALID_DECIMAL') from None
                    if not d.is_finite() or d<0 or p.positive and d<=0 or p.minimum is not None and d<Decimal(p.minimum):raise ValueError('INVALID_DECIMAL')
        if name=='order_place':
            types=dict(schema['eot'].enum) if 'eot' in schema else {}
            label=next((label for label,code in types.items() if code==params.get('eot')),None)
            if label is not None and 'LIMIT' in label.upper() and 'pr' not in params:
                raise ValueError('LIMIT_PRICE_REQUIRED')
        return dict(params)

    def verify_observations(self,state):
        if self.synthetic:raise ValueError('SYNTHETIC_CANNOT_BECOME_LIVE_VERIFIED')
        status=state.status()
        if status['connection']!='CONNECTED':return
        for name in ('balance','orders','positions','positions_settings'):
            record=self.get(name)
            if (record.market_id==state.market_id and record.verification=='LIVE_DISCOVERED'
                    and status['topics'][name]['state'] in ('VALIDATED','VERIFIED_EMPTY','VERIFIED_ACTIVE')):
                self.records[name]=replace(record,verification='LIVE_VERIFIED',
                    evidence='VALIDATED_ACCOUNTSTATE_READ_NOT_WRITE_PERMISSION',validated_ms=state.clock())

    def safe_status(self):
        return {'synthetic':self.synthetic,'capabilities':[r.safe_status() for r in self.records.values()],
                'orders_enabled':False,'live_transport':'NOT_IMPLEMENTED'}
