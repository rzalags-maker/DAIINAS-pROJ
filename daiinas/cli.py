import argparse
from dataclasses import asdict
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
from . import data
from .backtest import run
from .models import INTERVALS, SYMBOLS, RiskConfig, StrategyConfig


def utc(t):
    return datetime.fromtimestamp(t/1000, timezone.utc).isoformat()


def configuration(path):
    cfg = json.loads(Path(path).read_text())
    if not cfg['symbols'] or len(set(cfg['symbols'])) != len(cfg['symbols']) or not set(cfg['symbols']) <= set(SYMBOLS):
        raise ValueError('Choose unique supported symbols')
    if cfg['interval'] not in INTERVALS or not 0.1 <= cfg['in_sample_fraction'] <= 0.9:
        raise ValueError('Unsupported interval or split (must be .1 to .9)')
    if date.fromisoformat(cfg['start']) >= date.fromisoformat(cfg['end']):
        raise ValueError('End date must follow start (end exclusive)')
    cfg['strategy'] = asdict(StrategyConfig(**cfg['strategy']))
    cfg['risk'] = asdict(RiskConfig(**cfg['risk']))
    return cfg


def markdown(report):
    lines = ['# DAIINAS v1 research backtest', '',
             '**Simulation only. Candle patterns are not order-flow evidence.**', '',
             f"Config SHA-256: `{report['config_sha256']}`", '',
             '| Metric | In sample | Out of sample |', '|---|---:|---:|']
    left, right = [report['results'][k]['metrics'] for k in ('in_sample', 'out_of_sample')]
    for key in ('total_trades', 'win_rate', 'net_pnl', 'profit_factor', 'maximum_drawdown',
                'average_profit_per_trade', 'final_balance', 'signals', 'drawdown_halted'):
        def fmt(v):
            if v is None:
                return 'undefined'
            return f'{v:.6f}' if isinstance(v, float) else str(v)
        lines.append(f'| {key} | {fmt(left[key])} | {fmt(right[key])} |')
    for name,m in [('In sample',left), ('Out of sample',right)]:
        lines += ['', f"{name}: {utc(m['start_time'])} through {utc(m['end_time'])} (exclusive).",
                  f"Rejected signals: `{json.dumps(m['rejections'], sort_keys=True)}`."]
    lines += ['', 'Both samples start independently with configured capital, flat positions and no pending orders. '
              'Out-of-sample uses preceding candles only for indicator warm-up. No optimization was performed.', '',
              'A positive result over this short period would not establish persistent profitability. '
              'Negative or zero-trade results must not be interpreted as a profitable strategy.', '',
              '## Execution assumptions and limitations', '']
    lines += [f'- {x}' for x in report['assumptions']]
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Simulation-only Binance USD-M research')
    parser.add_argument('command', choices=['download', 'backtest'])
    parser.add_argument('--config', default='configs/default.json')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, default=Path('reports/default'))
    parser.add_argument('--refresh-rules', action='store_true')
    parser.add_argument('--rules-file', type=Path, help='Frozen public exchangeInfo snapshot')
    args = parser.parse_args(argv)
    cfg = configuration(args.config)
    start, end = date.fromisoformat(cfg['start']), date.fromisoformat(cfg['end'])
    if args.command == 'download':
        manifest = []
        for symbol in sorted(cfg['symbols']):
            print(f'Downloading/verifying {symbol} {cfg["interval"]}', flush=True)
            manifest.extend(data.download(symbol, cfg['interval'], start, end, args.data_dir))
        _, metadata = data.exchange_rules(args.data_dir, args.refresh_rules, args.rules_file)
        args.data_dir.mkdir(parents=True, exist_ok=True)
        (args.data_dir / 'manifest.json').write_text(json.dumps({'archives': manifest,
                                                               'exchange_rules': metadata}, indent=2)+'\n')
        print('Verified archives and public exchange rules cached.')
        return
    candles = {s: data.load(s, cfg['interval'], start, end, args.data_dir) for s in cfg['symbols']}
    if not (args.rules_file or args.data_dir / 'exchangeInfo.json').exists():
        raise ValueError('Run download first to obtain exchange filters')
    rules, metadata = data.exchange_rules(args.data_dir, snapshot=args.rules_file)
    strategy, risk = StrategyConfig(**cfg['strategy']), RiskConfig(**cfg['risk'])
    split = int(len(next(iter(candles.values())))*cfg['in_sample_fraction'])
    if split <= max(strategy.lookback,strategy.atr_period + 1) or len(next(iter(candles.values())))-split < 2:
        raise ValueError('Insufficient candles for separate samples')
    results = {'in_sample': run(candles, rules, strategy, risk, end=split),
               'out_of_sample': run(candles, rules, strategy, risk, start=split)}
    archive_hashes = []
    day = start
    while day < end:
        for s in sorted(candles):
            path = args.data_dir / s / cfg['interval'] / f'{s}-{cfg["interval"]}-{day}.zip'
            archive_hashes.append({'file': str(path.relative_to(args.data_dir)),
                                   'sha256': data.digest(path.read_bytes())})
        day += timedelta(days=1)
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    canonical = json.dumps(cfg, sort_keys=True, separators=(',', ':'))
    report = {'config': cfg, 'config_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
              'source_revision': revision, 'source_dirty': dirty,
              'source_files_sha256': {str(p): data.digest(p.read_bytes()) for p in sorted(Path('daiinas').glob('*.py'))},
              'exchange_rules': metadata, 'applied_rules': {s: asdict(rules[s]) for s in candles},
              'archives': archive_hashes, 'results': results,
              'assumptions': [
                  'USD-M linear perpetual contracts. Separate (symbol, LONG/SHORT) legs share one cash and margin account.',
                  'Completed-candle sweep/re-entry signals; next-open market entries and invalidation exits. No fixed holding time.',
                  'Adverse half-spread plus slippage on every fill; taker fee on both sides. Stops win ambiguous candles.',
                  'Gap stops fill at the adverse open; profit exits receive no favorable gap improvement.',
                  'Quantity rounds down to the common LOT_SIZE/MARKET_LOT_SIZE increment; stop and target prices use exchange ticks.',
                  'Current public exchange filters applied historically. Filters may have changed; historical filter reconstruction is unavailable.',
                  'Funding is an assumed conservative charge to both directions at UTC 00/08/16, not historical funding payments.',
                  'Drawdown checked at bar opens and closes, including estimated exit costs; breaches flatten and halt. Intrabar drawdown may be greater.',
                  'No depth, queue, partial-fill, latency, mark-price liquidation, or exchange outage model. Low leverage and margin reserve reduce but do not eliminate these limitations.',
                  'OHLCV only: liquidity sweeps are price-pattern proxies. No book or trade-flow signals have been tested.',
                  'Samples start flat with independent capital; prior candles warm indicators only. Fixed parameters, chronological split; no parameter search.'
              ]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    args.output.with_suffix('.md').write_text(markdown(report))
    print(markdown(report))


if __name__ == '__main__':
    main()
