# DAIINAS → Bitsgap API: authenticated REST handshake

**State:** adapter and manual GitHub Actions workflow prepared; **no authenticated access established until the operator creates a Bitsgap key and the workflow passes**. No real order execution.

## Architecture

- Existing Bitsgap ↔ KuCoin connection stays unchanged.
- DAIINAS GitHub Actions manually tests the separate Bitsgap API using Ed25519 PKCS#8 PEM.
- Only two signed read requests are allowed: **manual** and **conf_enums**. These prove the Bitsgap credential works; **they do not prove access to KuCoin balances, positions, or permissions**.
- The Bitsgap private API key grants **trading authority on connected exchanges**, according to Bitsgap's official API documentation. Client-side read-only allowlists do NOT downgrade its privileges.

## Operator setup

1. In Bitsgap: account menu → **API keys** → **Create new key**.
2. Name: **DAIINAS-PAPER-AUTH**; set a short initial expiration; **Generate**.
3. Save the PEM private key **locally and securely** immediately; Bitsgap displays it only once. Never send it in chat, commit it, put it in a PR, or upload it to the repository. Public key derives from private key.
4. In GitHub repository: Settings → Secrets and variables → Actions → **New repository secret**.
   - Name: **BITSGAP_PRIVATE_KEY_PEM**
   - Value: entire multi-line private PEM, including BEGIN PRIVATE KEY and END PRIVATE KEY boundary lines.
   - Use a GitHub Secret, not plain Actions Variable.
5. Actions → **Bitsgap authenticated read-only handshake (manual)** → **Run workflow** on **main**.
6. Check sanitized job logs for **BITSGAP_API_AUTH=PASS**, **DAIINAS_ORDER_ROUTING=DISABLED**, and **KUCOIN_ACCOUNT_RECONCILED=NO**. Failures show only category.

## Safeguards

- No trading topics (order_place, order_cancel, position_close, leverage or margin changes, etc.) are permitted by daiinas/bitsgap_readonly.py.
- No account balances or identifiers are printed to logs.
- Workflow is manual-only, read-only GitHub contents permission, main branch guard, and checkout token not persisted.
- DAIINAS remains PAPER; a trade-capable credential remains hazardous even when the application code is read-only.
- The separate direct KuCoin key must be General-only and should have IP restriction restored or be revoked if unnecessary.

## Validation after a successful handshake

1. Identify the existing KuCoin exchange identifier using conf_enums; do not log raw account data.
2. Verify whether the connected account supports the needed KuCoin Futures or Spot scope.
3. Add a separately reviewed, sanitized balance/positions-only reconciliation step.
4. Real orders stay disabled.

## Primary sources

- https://github.com/Bitsgap/bitsgap-api-docs
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/rest/README.md
- https://github.com/Bitsgap/bitsgap-api-docs/blob/main/docs/topics/reference.md
