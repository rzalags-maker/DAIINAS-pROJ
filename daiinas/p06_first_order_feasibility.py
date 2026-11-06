"""P06 first-order feasibility gate. No network, trading transport, money or ledger.

All inputs are read-only observations/claims. This module can identify missing
proof, but it CANNOT grant START_LIVE or authorize a venue order. In particular,
an authenticated discovery catalog is not an exchange protection attestation.
"""
from collections.abc import Mapping
from dataclasses import dataclass

from .bitsgap_capabilities import BitsgapCapabilityRegistry


_REQUIRED_COMMANDS = ('order_place', 'order_detail', 'order_cancel', 'position_close')
_PROTECTIVE = ('native_tp_sl', 'trigger_reference', 'partial_child_resize',
               'sibling_cancel', 'restart_persistence')


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    evidence_kind: str
    reason: str
    source_age_ms: int | None = None

    def safe_dict(self):
        return {'gate': self.name, 'status': self.status,
                'evidence_kind': self.evidence_kind, 'reason': self.reason,
                'source_age_ms': self.source_age_ms}


def _age(timestamp, now_ms, max_age_ms):
    if type(timestamp) is not int or type(now_ms) is not int:
        return None
    difference = now_ms - timestamp
    return difference if 0 <= difference <= max_age_ms else None


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def assess_first_order(registry, acceptance, *, now_ms, max_age_ms=15000,
                       protection_evidence=None):
    """Classify first-order prerequisites; ALWAYS fail closed.

    registry: the existing BitsgapCapabilityRegistry, never user-entered codes.
    acceptance: P05.1's redacted observation output, NOT the private account.
    protection_evidence: optional claimed/synthetic semantic data; it can only
    reduce confidence, never promote a control to verified without an independent
    trusted venue attestation path (which is not implemented).
    This API deliberately exposes no submit, cancel, close or modify operation.
    """
    if not isinstance(registry, BitsgapCapabilityRegistry):
        raise TypeError('REGISTRY_REQUIRED')
    if not isinstance(acceptance, Mapping):
        raise TypeError('SANITIZED_ACCEPTANCE_REQUIRED')
    if type(now_ms) is not int or now_ms < 0:
        raise ValueError('INVALID_OBSERVATION_TIME')
    if type(max_age_ms) is not int or max_age_ms <= 0 or max_age_ms > 60000:
        raise ValueError('INVALID_FRESHNESS_POLICY')

    gates = []

    def add(name, status, evidence_kind, reason, age=None):
        gates.append(Gate(name, status, evidence_kind, reason, age))

    # Registry declarations are metadata, not permission for writing.
    place = registry.get('order_place')
    scope_age = _age(place.validated_ms, now_ms, max_age_ms)
    scope_discovered = (not registry.synthetic and place.market_id > 0
                        and place.exchange == 'KUCOIN_FUTURES'
                        and scope_age is not None
                        and place.verification in ('LIVE_DISCOVERED', 'LIVE_VERIFIED'))
    add('market_and_catalog',
        'DECLARED_ONLY' if scope_discovered else 'UNVERIFIED',
        'READ_ONLY_LIVE_CATALOG_DECLARED' if scope_discovered else 'UNVERIFIED',
        'CATALOG_DECLARATION_NOT_ACCOUNT_IDENTITY_CERTIFICATION' if scope_discovered
        else 'BLOCKED_REAL_FUTURES_CATALOG_NOT_VERIFIED', scope_age)

    command_records = [registry.get(name) for name in _REQUIRED_COMMANDS]
    commands_declared = (scope_discovered and
                         all(record.market_id == place.market_id
                             and record.verification in ('LIVE_DISCOVERED', 'LIVE_VERIFIED')
                             and 'WS' in record.transports
                             and _age(record.validated_ms, now_ms, max_age_ms) is not None
                             for record in command_records))
    add('order_command_transport',
        'DECLARED_ONLY' if commands_declared else 'UNVERIFIED',
        'READ_ONLY_LIVE_CATALOG_DECLARED' if commands_declared else 'PUBLIC_DOC',
        'BLOCKED_COMMAND_PERMISSION_AND_ASYNC_TRANSPORT_NOT_PROVEN'
        if commands_declared else 'BLOCKED_ORDER_COMMANDS_OR_TRANSPORT_UNVERIFIED',
        scope_age)

    type_parameter = next((x for x in place.parameters if x.name == 'eot'), None)
    ro_parameter = next((x for x in place.parameters if x.name == 'ro'), None)
    schema_declared = (commands_declared and place.schema_known
                       and type_parameter is not None and bool(type_parameter.enum)
                       and ro_parameter is not None)
    add('order_shape_and_reduce_only',
        'DECLARED_ONLY' if schema_declared else 'UNVERIFIED',
        'READ_ONLY_LIVE_CATALOG_DECLARED' if schema_declared else 'PUBLIC_DOC',
        'BLOCKED_REDUCE_ONLY_ENFORCEMENT_NOT_VERIFIED' if schema_declared
        else 'BLOCKED_ORDER_SCHEMA_TYPES_OR_REDUCE_ONLY_UNVERIFIED',
        scope_age)

    sample = _mapping(acceptance.get('session_evidence'))
    topics = _mapping(sample.get('topics'))
    transport = _mapping(acceptance.get('transport'))
    sampled_ms = sample.get('captured_ms')
    sample_age = _age(sampled_ms, now_ms, max_age_ms)
    sampled_auth = (acceptance.get('authenticated_market_scope') ==
                    'KUCOIN_FUTURES_USDT'
                    and transport.get('rest_catalog_auth') == 'PASS'
                    and transport.get('websocket_auth') == 'PASS'
                    and sample.get('connection') == 'CONNECTED'
                    and sample_age is not None)
    add('authenticated_read_observation',
        'OBSERVED_ONLY' if sampled_auth else 'UNVERIFIED',
        'READ_ONLY_OBSERVATION' if sampled_auth else 'UNVERIFIED',
        'BLOCKED_READ_OBSERVATION_IS_NOT_WRITE_AUTHORIZATION'
        if sampled_auth else 'BLOCKED_ACCOUNT_SCOPE_AUTH_OR_AGE_UNVERIFIED',
        sample_age)

    orders = _mapping(topics.get('orders')).get('state', 'UNVERIFIED')
    positions = _mapping(topics.get('positions')).get('state', 'UNVERIFIED')
    exposure_topics = ('VERIFIED_EMPTY', 'VERIFIED_ACTIVE')
    exposure_visible = (sampled_auth and orders in exposure_topics
                        and positions in exposure_topics)
    if orders == 'PROVIDER_NO_DATA' or positions == 'PROVIDER_NO_DATA':
        exposure_reason = 'BLOCKED_EXPOSURE_PROVIDER_NO_DATA'
    elif not exposure_visible:
        exposure_reason = 'BLOCKED_EXPOSURE_STALE_OR_UNVERIFIED'
    else:
        exposure_reason = 'BLOCKED_FULL_EXPOSURE_INVENTORY_NOT_PROVEN'
    add('complete_orders_positions_and_external_exposure',
        'OBSERVED_COUNTS_ONLY' if exposure_visible else 'UNVERIFIED',
        'READ_ONLY_OBSERVATION' if exposure_visible else 'UNVERIFIED',
        exposure_reason, sample_age)

    mode = sample.get('position_mode')
    settings = _mapping(topics.get('positions_settings')).get('state')
    oneway_observed = sampled_auth and mode == 'ONE_WAY' and settings == 'VALIDATED'
    add('one_way_position_mode',
        'OBSERVED_ONLY' if oneway_observed else 'UNVERIFIED',
        'READ_ONLY_OBSERVATION' if oneway_observed else 'UNVERIFIED',
        'BLOCKED_MODE_OBSERVATION_IS_NOT_TRADE_PERMISSION' if oneway_observed
        else 'BLOCKED_ONE_WAY_POSITION_MODE_UNVERIFIED', sample_age)

    # P05.1 intentionally never promotes wallet t/a to eligible free margin.
    add('equity_free_margin_collateral_and_costs', 'UNVERIFIED', 'UNVERIFIED',
        'BLOCKED_EQUITY_FREE_MARGIN_AND_COSTS_UNVERIFIED')
    add('native_trigger_tp_sl', 'UNVERIFIED', 'PUBLIC_DOC',
        'BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED')
    add('native_child_sizing_oco_and_persistence', 'UNVERIFIED', 'UNVERIFIED',
        'BLOCKED_PROTECTIVE_CHILD_AND_RESTART_PERSISTENCE_UNVERIFIED')

    # Even a user-entered 'VERIFIED' or MOCK_NATIVE evidence is unauthenticated.
    claim = _mapping(protection_evidence)
    if claim.get('source_kind') in ('MOCK_NATIVE', 'SYNTHETIC', 'UI_ASSERTION'):
        proof_reason = 'BLOCKED_MOCK_OR_UI_PROTECTION_IS_NOT_VENUE_PROOF'
    else:
        proof_reason = 'BLOCKED_INDEPENDENT_VENUE_PROTECTION_ATTESTATION_ABSENT'
    add('venue_protection_attestation', 'UNVERIFIED', 'UNVERIFIED', proof_reason)
    add('idempotent_live_receipts_and_settlement', 'UNVERIFIED', 'PUBLIC_DOC',
        'BLOCKED_LIVE_ACK_FILL_PROTECTION_SETTLEMENT_NOT_TESTED')
    add('owner_session_and_stop_with_exposure', 'BLOCKED', 'UNVERIFIED',
        'BLOCKED_AUTHENTICATED_LIVE_SESSION_AND_REMOTE_STOP_UNAVAILABLE')
    add('live_execution_runtime', 'BLOCKED', 'BLOCKED',
        'BLOCKED_START_LIVE_NO_LIVE_TRANSPORT')

    # Deterministic precedence: protection contract is the decisive P06 gap.
    reasons = ['BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED']
    reasons.extend(gate.reason for gate in gates if gate.reason not in reasons)
    if registry.synthetic:
        reasons.append('SYNTHETIC_NOT_LIVE_VERIFIED')

    return {'first_order_readiness': {
        'status': 'BLOCKED', 'decision': 'NO_GO',
        'reason': reasons[0], 'reasons': reasons,
        'gates': [gate.safe_dict() for gate in gates],
        'source': 'P06_READ_ONLY_FEASIBILITY',
        'synthetic_evidence': registry.synthetic,
        'account_verified': False, 'native_tp_sl_verified': False,
        'orders_enabled': False, 'live_trading': 'DISABLED',
        'new_entry': 'NO_TRADE_ACCOUNT_NOT_RECONCILED'}}


def from_p051_report(registry, report, *, now_ms, max_age_ms=15000):
    """Compatibility wrapper using only the existing redacted P05.1 report."""
    return assess_first_order(registry, report, now_ms=now_ms, max_age_ms=max_age_ms)
