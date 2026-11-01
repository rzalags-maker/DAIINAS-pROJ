# Draft: v4.7 adaptive leverage and whole-market PAPER position conveyor

The current-account v4 ledger now evaluates x1–x5 independently for every
cost/risk-qualified candidate, ranks the complete public Futures catalog, and
runs entry, modeled protection, fee-adjusted net target, partial exit and fresh
candidate replacement in the existing durable SQLite engine. Model A, immutable
INITIAL_FUNDING, early WIN permissions and financial risk limits are preserved.

Forty coupled stop/leverage/liquidity alternatives distinguish 0.5%/1% price stops
from unchanged monetary risk. Bounded five-hour PAPER sessions persist START/STOP,
protection and reconciliation holds. The inert gateway has no real order transport;
normalized native MOCK receipts test exact fees, partial inventory, offline closes,
sibling proof and WS/REST idempotency. Public book synchronization uses bounded
backoff and strict sequence bridges; unhealthy observations never erase pinned risk.

Validation: 298 tests on Python 3.11/3.12/3.13; real public KuCoin smoke covering
717 contracts / 130.571 seconds, independent cash verification and identical replay;
synthetic profitable and losing/partial/x5/ten-position lifecycle proofs. All eleven
existing public v4/legacy acceptance stages also passed; the separate legacy
8-USDT account recorded five losses (net −0.02358720524548885 USDT). Public
smoke produced no qualified orders and zero net P&L: no alpha claim. Earlier failed
smokes remain preserved. See `reports/V47_VALIDATION.md` and its checksummed JSON.

Keep Draft. Actual account/private connector, exchange-native protection, host and
mobile control remain NOT_CONNECTED/unverified; five-hour expiry is virtual-clock
proof, not hosted uptime. Live orders disabled. Do not merge stable or PR #7/#9.

Prepared comparison: https://github.com/rzalags-maker/DAIINAS-pROJ/compare/daiinas-v1...feature/v4-ladder-integration
Repository policy currently prevents Actions from creating the draft PR (recorded
HTTP 403); this file and branch are reviewable, but are not an opened PR.
