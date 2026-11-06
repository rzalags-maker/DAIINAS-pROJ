"""P06 offline feasibility only: no I/O, command methods or live-ready path.

The current models do not attest full account identity, financial reconciliation,
or independent native protection. Caller claims cannot repair that trust boundary.
Synthetic evidence exercises the decision logic, never authorizes an order.
"""
from dataclasses import dataclass

from .bitsgap_account_acceptance import AccountAcceptance
from .bitsgap_capabilities import BitsgapCapabilityRegistry, Capability, Parameter


COMMANDS = ('order_place', 'order_detail', 'order_cancel', 'position_close')
TOPICS = ('balance', 'orders', 'positions', 'positions_settings')
REQUIRED = {
    'native_contract': ('sl_create', 'tp_create', 'trigger_reference', 'trigger_type',
                        'venue_child_ack', 'reduce_only', 'partial_entry_resize',
                        'partial_exit_resize', 'sibling_cancel', 'replacement_reconcile'),
    'native_persistence': ('independent_venue_evidence', 'bitsgap_disconnect',
                           'controller_disconnect', 'stop_preserves_protection'),
    'account_identity': ('independent_account_identity', 'real_futures_usdt'),
    'account_financials': ('equity', 'free_margin', 'committed_collateral', 'fees_funding'),
    'inventory': ('account_wide_inventory', 'external_exposure_resolved'),
    'command_permission': COMMANDS,
    'transport_contract': ('provider_conflict_resolved', 'scoped_transport'),
    'order_lifecycle': ('ack_not_fill', 'apiid_id_eid', 'exactly_once_recovery',
                        'uncertain_ack_reconciliation', 'settled_costs'),
    'risk': ('existing_model_a', 'contract_minimums', 'actual_fees', 'money_caps',
             'gap_budget', 'emergency_stop_with_exposure'),
    'owner_authorization': ('one_way_authorized', 'scoped_start_live_reviewed'),
}
KINDS = ('PUBLIC_DOC', 'READ_ONLY_LIVE_CATALOG_DECLARED', 'ACCOUNT_VERIFIED',
         'UNVERIFIED', 'BLOCKED', 'NOT_SUPPORTED_WITH_EVIDENCE', 'SYNTHETIC')
PROVENANCE = ('PROVIDER_DOCUMENT', 'ACCOUNT_OBSERVATION', 'SYNTHETIC', 'UI', 'OPERATOR', 'MOCK')


@dataclass(frozen=True, repr=False)
class Proof:
    """Sanitized *claims*, not attestations; no identifiers, amounts or free text."""
    name: str
    kind: str = 'UNVERIFIED'
    provenance: str = 'OPERATOR'
    observed_ms: int | None = None
    generation: int | None = None
    facts: tuple = ()

    def __post_init__(self):
        if (type(self.name) is not str or self.name not in REQUIRED or self.kind not in KINDS or self.provenance not in PROVENANCE
                or self.observed_ms is not None and (type(self.observed_ms) is not int or self.observed_ms < 0)
                or self.generation is not None and (type(self.generation) is not int or self.generation < 0)
                or type(self.facts) is not tuple or any(type(x) is not str or x not in REQUIRED[self.name] for x in self.facts)
                or len(set(self.facts)) != len(self.facts)):
            raise ValueError('INVALID_FIRST_ORDER_PROOF')

    def __repr__(self):
        return 'Proof(CLAIMS_NOT_ACCOUNT_ATTESTATION)'


@dataclass(frozen=True, repr=False)
class FirstOrderEvidenceBundle:
    registry: BitsgapCapabilityRegistry
    account: AccountAcceptance
    acceptance: dict
    expected_market_id: int
    environment: str = 'REAL'
    proofs: tuple = ()
    transport: str = 'WS'
    # P05.1 does not serialize generation. Only synthetic tests may supply this
    # fixture linkage; a caller-supplied number is never production identity proof.
    synthetic_generation: int | None = None
    # Hypothetical integer lots: entry filled, exit filled, remaining SL, remaining TP.
    coverage: tuple | None = None

    def __post_init__(self):
        if (type(self.registry) is not BitsgapCapabilityRegistry or type(self.account) is not AccountAcceptance
                or type(self.acceptance) is not dict or type(self.expected_market_id) is not int
                or self.expected_market_id < 0 or self.environment not in ('REAL', 'DEMO', 'SYNTHETIC')
                or self.transport not in ('WS', 'REST') or type(self.proofs) is not tuple
                or any(type(x) is not Proof for x in self.proofs)
                or len({x.name for x in self.proofs}) != len(self.proofs)
                or self.synthetic_generation is not None and (type(self.synthetic_generation) is not int or self.synthetic_generation < 0)
                or self.coverage is not None and (type(self.coverage) is not tuple or len(self.coverage) != 4
                    or any(type(x) is not int or x < 0 for x in self.coverage))):
            raise ValueError('INVALID_FIRST_ORDER_BUNDLE')

    def __repr__(self):
        return 'FirstOrderEvidenceBundle(REDACTED_NOT_TRADE_AUTHORIZATION)'


def _mapping(value):
    return value if type(value) is dict else {}


def assess_first_order(bundle, *, now_ms, max_age_ms=15000):
    """Return fixed-vocabulary evidence gates; never invoke observer/transport/ledger.

    Use AccountAcceptance.from_state to project an existing AccountState outside
    this pure function. Production proofs remain UNVERIFIED until a separately
    reviewed, independent verifier exists. No spelling of READY is emitted.
    """
    if type(bundle) is not FirstOrderEvidenceBundle:
        raise ValueError('INVALID_FIRST_ORDER_BUNDLE')
    bundle.__post_init__()
    bundle.account.__post_init__()
    if type(now_ms) is not int or now_ms < 0 or type(max_age_ms) is not int or not 0 < max_age_ms <= 15000:
        raise ValueError('INVALID_FIRST_ORDER_CLOCK')
    for proof in bundle.proofs:
        proof.__post_init__()
    synthetic = bundle.environment == 'SYNTHETIC' and bundle.registry.synthetic is True
    account, session = bundle.account, bundle.acceptance
    cohort = _mapping(session.get('session_evidence'))
    topics = _mapping(cohort.get('topics'))
    transport = _mapping(session.get('transport'))
    receipts = _mapping(cohort.get('oldest_receipt_ms'))
    proofs = {p.name: p for p in bundle.proofs}
    gates = []

    def age(timestamp):
        return now_ms - timestamp if type(timestamp) is int and 0 <= timestamp <= now_ms else None

    def fresh(timestamp):
        value = age(timestamp)
        return value is not None and value <= max_age_ms

    def gate(name, passed, reason, missing, *, timestamp=None, kind='UNVERIFIED', status=None):
        gates.append({'gate': name, 'status': status or ('SATISFIED_SYNTHETIC' if passed and synthetic
                      else 'OBSERVED_NOT_ACCOUNT_VERIFIED' if passed else 'BLOCKED'),
                      'evidence_kind': kind, 'source_age_ms': age(timestamp),
                      'missing_proof': [] if passed else list(missing),
                      'reason': None if passed else reason})

    # Independent proof gates come first so the decisive protection blocker is stable.
    reason_codes = {'native_contract': 'BLOCKED_NATIVE_PROTECTION_CONTRACT_UNVERIFIED',
                    'native_persistence': 'BLOCKED_NATIVE_PERSISTENCE_UNVERIFIED',
                    'account_financials': 'BLOCKED_REAL_FREE_MARGIN_UNVERIFIED'}
    for name, required in REQUIRED.items():
        proof = proofs.get(name)
        missing = [fact for fact in required if proof is None or fact not in proof.facts]
        current = proof is not None and fresh(proof.observed_ms) and proof.generation == account.generation
        if not current:
            missing.append('current_same_generation_evidence')
        trusted_fixture = (synthetic and proof is not None and proof.kind == 'SYNTHETIC'
                           and proof.provenance == 'SYNTHETIC')
        if not trusted_fixture:
            missing.append('independent_live_verifier_not_implemented')
        passed = trusted_fixture and current and not missing
        # Never echo caller-asserted ACCOUNT_VERIFIED as a verified evidence kind.
        kind = 'SYNTHETIC' if trusted_fixture else ('PUBLIC_DOC' if proof is not None
                and proof.kind == 'PUBLIC_DOC' and proof.provenance == 'PROVIDER_DOCUMENT' else 'UNVERIFIED')
        gate(name, passed, reason_codes.get(name, 'BLOCKED_' + name.upper() + '_UNVERIFIED'),
             missing, timestamp=proof.observed_ms if proof else None, kind=kind,
             status='DOCUMENTED' if kind == 'PUBLIC_DOC' else None)

    gate('real_market_scope', bundle.expected_market_id > 0 and bundle.environment in ('REAL', 'SYNTHETIC') and account.account_scope_matches
         and session.get('authenticated_market_scope') == 'KUCOIN_FUTURES_USDT',
         'BLOCKED_ACCOUNT_SCOPE_MISMATCH', ('real_kucoin_futures_usdt_same_account',), timestamp=account.observed_ms)
    gate('account_freshness', fresh(account.observed_ms), 'BLOCKED_ACCOUNT_EVIDENCE_STALE',
         ('current_account_receipt',), timestamp=account.observed_ms)
    active = (account.connection == cohort.get('connection') == session.get('connection_after_stop') == 'CONNECTED'
              and transport.get('stop') == 'RUNNING')
    gate('active_session', active, 'BLOCKED_SESSION_INACTIVE_OR_STOPPED',
         ('current_running_session_not_bounded_stop',), timestamp=cohort.get('captured_ms'))
    gate('signed_channel', transport.get('websocket_auth') == transport.get('rest_catalog_auth') == 'PASS',
         'BLOCKED_SIGNED_CHANNEL_UNVERIFIED', ('authenticated_catalog_and_ws',), timestamp=cohort.get('captured_ms'))
    gate('cohort_binding', synthetic and bundle.synthetic_generation == account.generation,
         'BLOCKED_COHORT_BINDING_UNVERIFIED', ('independent_scope_and_generation_binding',),
         timestamp=cohort.get('captured_ms'), kind='SYNTHETIC' if synthetic else 'UNVERIFIED')
    source_times = []
    sources_valid = True
    sources = _mapping(cohort.get('sources'))
    for name in TOPICS:
        topic_sources = _mapping(sources.get(name))
        for source in ('REST', 'WS'):
            record = _mapping(topic_sources.get(source))
            started, received = record.get('started_ms'), record.get('received_ms')
            valid = (fresh(started) and fresh(received) and started <= received
                     and received - started <= 5000 and record.get('quality') == 'VALIDATED')
            sources_valid = sources_valid and valid
            if valid:
                source_times.extend((started, received))
        if topic_sources and not all(type(k) is str and k in ('REST', 'WS') for k in topic_sources):
            sources_valid = False
    coherent = (sources_valid and len(source_times) == 16 and max(source_times) - min(source_times) <= 5000
                and fresh(cohort.get('captured_ms')) and all(fresh(receipts.get(t)) for t in TOPICS)
                and all(receipts.get(t) == min(_mapping(_mapping(sources.get(t)).get(s)).get('received_ms', now_ms)
                                             for s in ('REST', 'WS')) for t in TOPICS)
                and account.observed_ms == min(receipts[t] for t in TOPICS)
                and max(source_times) <= cohort['captured_ms'])
    gate('current_cohort', coherent, 'BLOCKED_STALE_OR_INCOHERENT_COHORT',
         ('matching_current_rest_ws_receipts_and_capture',), timestamp=min(source_times) if source_times else None)
    for name in ('balance', 'orders', 'positions', 'positions_settings'):
        state = _mapping(topics.get(name)).get('state')
        expected = getattr(account, name, 'VALIDATED')
        valid = state == expected and state == ('VALIDATED' if name in ('balance', 'positions_settings') else 'VERIFIED_EMPTY')
        reason = ('BLOCKED_EXPOSURE_PROVIDER_NO_DATA' if name in ('orders', 'positions')
                  and 'PROVIDER_NO_DATA' in (state, expected) else 'BLOCKED_' + name.upper() + '_UNKNOWN_OR_ACTIVE')
        gate(name, valid, reason, ('complete_consistent_empty_inventory' if name in ('orders', 'positions')
                                  else 'validated_current_topic',), timestamp=receipts.get(name))
    gate('one_way', account.position_mode == cohort.get('position_mode') == 'ONE_WAY',
         'BLOCKED_ONE_WAY_UNVERIFIED', ('current_owner_required_one_way',), timestamp=receipts.get('positions_settings'))

    records = _mapping(bundle.registry.records)
    catalog_ok = True
    catalog_times = []
    for name in COMMANDS:
        record = records.get(name)
        valid_record = type(record) is Capability
        parameters = record.parameters if valid_record and type(record.parameters) is tuple else ()
        schema = {p.name: p for p in parameters if type(p) is Parameter and type(p.name) is str}
        scope_ok = (valid_record and record.exchange == 'KUCOIN_FUTURES'
                    and type(record.market_id) is int and record.market_id == bundle.expected_market_id)
        schema_ok = (valid_record and record.schema_known is True and len(schema) == len(parameters)
                     and 'em' in schema and schema['em'].kind == 'unsigned(enum)'
                     and ('KUCOIN_FUTURES', bundle.expected_market_id) in schema['em'].enum)
        if name == 'order_place':
            schema_ok = schema_ok and all(key in schema for key in ('pair', 'eot', 'eos', 'am', 'ro'))
            schema_ok = schema_ok and schema['eot'].kind == 'unsigned(enum)' and bool(schema['eot'].enum)
        declared = valid_record and record.verification in ('DOCUMENTED', 'LIVE_DISCOVERED', 'LIVE_VERIFIED')
        selected_transport = (valid_record and type(record.transports) is tuple and bool(record.transports)
                              and all(x in ('WS', 'REST') for x in record.transports)
                              and bundle.transport in record.transports)
        current = valid_record and fresh(record.validated_ms)
        passed = scope_ok and schema_ok and declared and selected_transport and current and record.runtime_enabled is False
        catalog_ok = catalog_ok and passed
        if current:
            catalog_times.append(record.validated_ms)
        gate('catalog_' + name, passed, 'BLOCKED_COMMAND_SCHEMA_SCOPE_OR_TRANSPORT_UNVERIFIED',
             ('fresh_scoped_declared_schema_and_selected_transport',), timestamp=record.validated_ms if valid_record else None,
             kind='SYNTHETIC' if synthetic else 'PUBLIC_DOC' if declared else 'UNVERIFIED',
             status='DOCUMENTED' if passed and not synthetic else None)
    gate('catalog_cohort', catalog_ok and bool(catalog_times) and max(catalog_times) - min(catalog_times) <= 5000,
         'BLOCKED_CATALOG_COHORT_UNVERIFIED', ('coherent_current_catalog',), timestamp=min(catalog_times) if catalog_times else None)
    coverage = bundle.coverage
    coverage_ok = (coverage is not None and coverage[1] <= coverage[0]
                   and coverage[2] == coverage[3] == coverage[0] - coverage[1] and coverage[0] > 0)
    gate('protection_coverage', synthetic and coverage_ok, 'BLOCKED_PROTECTION_SIZE_MISMATCH_OR_UNVERIFIED',
         ('both_native_children_match_remaining_exposure',), kind='SYNTHETIC' if synthetic else 'UNVERIFIED')
    gate('live_evidence_boundary', synthetic, 'BLOCKED_INDEPENDENT_LIVE_VERIFIER_NOT_IMPLEMENTED',
         ('independently_verified_account_permission_and_native_protection',), kind='SYNTHETIC' if synthetic else 'UNVERIFIED')
    reasons = list(dict.fromkeys(g['reason'] for g in gates if g['reason']))
    status = 'SYNTHETIC_NOT_LIVE_VERIFIED' if synthetic and not reasons else 'BLOCKED'
    return {'first_order_readiness': status, 'status': status,
            'decision_reason': reasons[0] if reasons else 'SYNTHETIC_ONLY_NO_TRADE_AUTHORIZATION',
            'reasons': reasons, 'gates': gates,
            'provenance': 'SYNTHETIC' if synthetic else 'UNVERIFIED_INPUT_CLAIMS',
            'orders_enabled': False, 'live_trading': 'DISABLED',
            'eligible_capital': None, 'new_entry': 'NO_TRADE_ACCOUNT_NOT_RECONCILED'}
