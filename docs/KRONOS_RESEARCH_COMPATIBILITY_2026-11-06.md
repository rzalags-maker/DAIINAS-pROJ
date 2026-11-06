# Kronos research compatibility and conditional integration

**Status:** `EXPERIMENT_FURTHER`, not `INTEGRATE`.

This is a source audit and integration decision for Issue-free experimental work
on top of DAIINAS P06 `7fe74ca08f482cafa1301c51b10a93f5e6a3fb17`. It makes no
claim about real or demo trading, signal profitability, account readiness, or
exchange-native protection. Model A, P04, P06, the risk engine, the capital
ledger and all execution boundaries remain unchanged.

## Decision

Kronos is technically *format-compatible* with DAIINAS closed 1m/5m/15m OHLCV
research, but it is not currently evaluable in this repository environment. The
necessary preconditions for an evidence-based PAPER experiment are absent:

| Requirement | Observed state | Decision impact |
| --- | --- | --- |
| Kronos-small weights and matching tokenizer | Not present locally; model cards are external Hugging Face references | No inference or weight-license claim made |
| PyTorch runtime | Not installed in the research interpreter | Do not add a heavyweight core dependency |
| GPU / declared CPU inference budget | No GPU reported; no measured CPU latency | Cannot claim event-loop compatibility |
| Contiguous historical 1m/5m/15m OHLCV | No reusable local dataset found | No fair walk-forward result is possible |
| Historical contract metadata, fees, spread, slippage and funding | No timestamp-aligned dataset found | Cannot make realistic net-performance claims |

Accordingly, no Kronos adapter, feature flag, dependency, model download, or
execution integration is added. Installing a model without the above evaluation
inputs would increase complexity without establishing incremental value.

## Pinned upstream audit

Audited source: `shiyu-coder/Kronos` commit
`67b630e67f6a18c9e9be918d9b4337c960db1e9` (cloned 2026-11-06).

- Repository code licence: MIT (`LICENSE`). This does **not** establish the
  licence or redistribution terms for Hugging Face model weights; verify the
  exact small-model and tokenizer model cards before any download or release.
- `README.md` describes a two-stage design: a tokenizer quantizes OHLCV into
  hierarchical discrete tokens, then a decoder-only autoregressive Transformer
  forecasts future K-lines.
- Published model table: `Kronos-small` has 24.7M parameters and 512 maximum
  context; it requires `Kronos-Tokenizer-base`. `Kronos-mini` is 4.1M/2048
  context, but the requested first candidate is small.
- `requirements.txt` requires `torch>=2.0`, NumPy, pandas, einops,
  Hugging Face Hub, safetensors and related packages. These remain upstream
  optional experiment dependencies, not DAIINAS runtime dependencies.
- The documented predictor takes timestamped `open`, `high`, `low`, `close`,
  with optional `volume` and `amount`, then generates sampled forecast paths.
  It is not an order, position, risk, execution, portfolio or P&L model.
- The upstream fine-tuning example itself warns that its illustrative Qlib
  backtest is not a production quantitative strategy. No Kronos source proves
  a profitable KuCoin Futures signal for DAIINAS.

## Capability map

| DAIINAS v4.7 area | Existing evidence-backed role | Possible Kronos experiment | Integration conclusion |
| --- | --- | --- | --- |
| Closed candles / continuity | Validates contiguous closed 1m/5m/15m contexts and blocks gaps | Convert an already validated context to Kronos input | Compatible only after data provenance is retained |
| Sniper / market pulse | Ranks LONG, SHORT and NO_TRADE from current market evidence | Forecast-distribution feature may be one candidate-ranking input | Do not replace selector or create automatic admission |
| Contract, fees and execution assumptions | Computes cost, spread, slippage, latency and feasible trade plans | Test whether forecast information survives costs | Must use identical assumptions in both arms |
| Model A / Capital Ladder | Durable capital allocation and loss/risk policy | None | No model output can increase allocation or weaken limits |
| P04 and P06 boundaries | MOCK-only execution and fail-closed live feasibility | None | Kronos remains PAPER-only and cannot bypass either boundary |
| Protection and STOP | Modeled protection/reconciliation; native live contract still unverified | None | Forecasts cannot compensate for missing native TP/SL proof |

The genuine gap Kronos might address is a probabilistic multi-horizon price-path
estimate, potentially useful as a *research-only* ranking feature or a NO_TRADE
filter. DAIINAS already supplies market-quality, cost, sizing, leverage, risk,
capital, lifecycle and protection logic. Kronos must not duplicate or replace
those components.

## Required experiment before any optional adapter

The smallest defensible next experiment is off-path and removable:

1. Obtain a licence-reviewed Kronos-small tokenizer and weights in an external
   experiment environment, keeping them out of DAIINAS source control and core
   dependencies.
2. Supply a versioned, checksummed, contiguous closed-candle dataset for the
   same KuCoin Futures symbols and 1m/5m/15m intervals. Preserve source time,
   gaps, delistings and contract changes; do not forward-fill.
3. Freeze a forecast-to-score rule before evaluation. It may only rank or veto
   an existing DAIINAS candidate; it may not alter direction, position size,
   leverage, stop, target, Model A or risk limits.
4. Run chronological walk-forward folds. At each decision timestamp, give both
   baseline and Kronos arms exactly the same candles, eligible symbols, latency,
   entry type, spread, slippage, maker/taker fees, funding rule and stop/target
   simulator. Forecast generation time must be measured and included as latency.
5. Report out-of-sample net return, trade count, hit rate, turnover, maximum
   drawdown, tail loss, exposure time, cost attribution and fold/regime results.
   Compare against both the existing selector and a no-trade control. Do not
   select a sampling temperature, horizon or threshold using held-out outcomes.
6. Integrate only if improvement is stable across predeclared folds and regimes,
   remains after costs and latency, and does not increase drawdown or architectural
   risk. Otherwise reject and remove the optional experiment.

## Current performance result

**No performance result is available.** This is an explicit limitation, not a
zero return, neutral result, or failed model. No compatible data, weights, CPU/GPU
budget or inference runtime was available, so no forecast was produced and no
historical comparison was run.

## Recommendation

`EXPERIMENT_FURTHER` only if the listed data, model-card licence, compute and
walk-forward inputs are supplied. Do **not** integrate Kronos into DAIINAS v4.7
now. Until measurable out-of-sample incremental value is demonstrated, keeping
Kronos absent is the lower-complexity and lower-risk choice.
