"""Synthetic discovery; no live account capability or permissions are attested."""
import copy
import json
import unittest
from daiinas.bitsgap_capabilities import BitsgapCapabilityRegistry
from daiinas.bitsgap_futures_observe import BitsgapFuturesObserver
from test_bitsgap_futures_observe import FakeWire,new_pem


def catalog():
    w=FakeWire()
    w.manual['data']['order_place']['params']={
        'em':{'required':True,'type':'unsigned(enum)','enum':'market'},
        'pair':{'required':True,'type':'string(pair)'},
        'eot':{'required':True,'type':'unsigned(enum)','enum':'order_type'},
        'am':{'required':True,'type':'string(decimal)','value':'> 0'},
        'pr':{'type':'string(decimal)','value':'> 0'},
        'lv':{'type':'string(decimal)','value':'>= 1'},
        'ro':{'type':'unsigned(bool)'}}
    return w


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.w=catalog();self.registry=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.params={'em':72,'pair':'BTC_USDT','eot':1,'am':'1','pr':'1','lv':'2','ro':1}

    def test_typed_scope_enums_permissions_and_no_runtime_enable(self):
        c=self.registry.get('order_place')
        self.assertEqual(c.market_id,72);self.assertEqual(c.verification,'DOCUMENTED')
        self.assertIn(('LIMIT',1),next(x.enum for x in c.parameters if x.name=='eot'))
        self.assertEqual(c.permission,'START_LIVE_OWNER_AUTHORIZATION')
        self.assertFalse(c.runtime_enabled);self.assertFalse(self.registry.safe_status()['orders_enabled'])
        self.assertEqual(self.registry.validate_parameters('order_place',self.params),self.params)

    def test_unexpected_or_foreign_parameters_and_bad_financial_values_denied(self):
        for values in ({'em':71},{'em':True},{'pair':'BTCUSDT'},{'eot':999},{'am':'NaN'},
                       {'am':'0'},{'lv':'.5'},{'ro':True},{'api_key':'SYNTHETIC'}, {'am':'-1'}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                self.registry.validate_parameters('order_place',{**self.params,**values})
        no_price=dict(self.params);del no_price['pr']
        with self.assertRaises(ValueError):self.registry.validate_parameters('order_place',no_price)
        p=dict(self.params);del p['am']
        with self.assertRaises(ValueError):self.registry.validate_parameters('order_place',p)

    def test_missing_catalog_topic_not_advertised_not_guessed(self):
        del self.w.manual['data']['order_place']
        r=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.assertEqual(r.get('order_place').verification,'UNSUPPORTED')
        self.assertEqual(r.get('native_tp_sl').verification,'UNVERIFIED')
        with self.assertRaises(ValueError):r.validate_parameters('order_place',self.params)

    def test_absent_parameter_schema_keeps_serialization_unverified(self):
        del self.w.manual['data']['order_place']['params']
        r=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.assertFalse(r.get('order_place').schema_known)
        self.assertEqual(r.get('reduce_only').verification,'UNVERIFIED')
        with self.assertRaises(ValueError):r.validate_parameters('order_place',self.params)

    def test_demo_only_is_not_real_futures_capability(self):
        self.w.manual['data']['order_place']['demo_only']=True
        r=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.assertEqual(r.get('order_place').verification,'UNSUPPORTED')

    def test_missing_enum_and_bad_catalog_fail_closed(self):
        del self.w.enums['data']['order_type']
        r=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.assertFalse(r.get('order_place').schema_known)
        for manual in ({'data':[]},{'data':{'balance':'INVALID'}}):
            with self.assertRaises(Exception):BitsgapCapabilityRegistry.from_catalogs(manual,self.w.enums,observed_ms=1000)

    def test_only_signed_discovery_topics_called_never_a_command(self):
        _,pem=new_pem();api=BitsgapFuturesObserver(pem,transport=self.w)
        r=BitsgapCapabilityRegistry.discover(api)
        self.assertEqual([x[0] for x in self.w.calls],['manual','conf_enums'])
        self.assertEqual(r.get('order_place').verification,'LIVE_DISCOVERED')
        # Above is an injected signed-wire fixture, not a report of production access.
        self.assertTrue(all(not x.runtime_enabled for x in r.records.values()))

    def test_synthetic_registry_never_becomes_live_verified(self):
        with self.assertRaises(ValueError):self.registry.verify_observations(object())
        self.assertEqual(self.registry.get('restart_persistence').verification,'UNVERIFIED')
        self.assertEqual(self.registry.get('withdraw').permission,'NEVER')

    def test_transport_flags_and_rate_limits_are_not_invented(self):
        self.w.manual['data']['order_place']['transport']={'ws':True}
        self.w.manual['data']['order_place']['limit']={'s1':5,'s10':20}
        r=BitsgapCapabilityRegistry.from_catalogs(self.w.manual,self.w.enums,observed_ms=1000)
        self.assertEqual(r.get('order_place').transports,('WS',))
        self.assertIn(('s10',20),r.get('order_place').limits)
        with self.assertRaises(ValueError):r.validate_parameters('order_place',self.params,transport='REST')
