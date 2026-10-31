"""Persistent, credential-free candle scanner and simulated paper worker.

Only public GET market-data requests exist. Not a broker or live execution API.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import signal as os_signal
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from .backtest import run
from .data import digest, exchange_rules, fetch
from .models import Candle, INTERVALS, SYMBOLS, RiskConfig, StrategyConfig
from .strategy import signal


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def now_ms():
    return int(time.time()*1000)


class Store:
    """One transaction commits input, signals, fills and checkpoint together."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT, time INTEGER, payload TEXT NOT NULL, PRIMARY KEY(symbol,time));
            CREATE TABLE IF NOT EXISTS signals (
                symbol TEXT, time INTEGER, side TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(symbol,time,side));
            CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS equity (time INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS responses (
                id INTEGER PRIMARY KEY, fetched_at INTEGER, url TEXT, sha256 TEXT, payload BLOB);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, time INTEGER, kind TEXT, detail TEXT);
        ''')

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                        (key, canonical(value)))

    def event(self, kind, detail):
        self.db.execute('INSERT INTO events(time,kind,detail) VALUES (?,?,?)',
                        (now_ms(), kind, str(detail)))

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def control(self, stopped):
        with self.transaction():
            self.set('stop', stopped)
            self.event('stop' if stopped else 'resume', 'Local operator control')

    def health(self):
        beat = self.get('heartbeat', {})
        cfg = self.get('configuration', {})
        interval = INTERVALS.get(cfg.get('interval'), 300_000)
        age = now_ms()-beat.get('time', 0)
        stopped = self.get('stop', False)
        last = self.get('checkpoint', {}).get('last_time')
        stale = last is None or now_ms()-(last+interval) > 3*interval
        healthy = (age < max(60_000, cfg.get('poll_seconds', 10)*3000)
                   and beat.get('status') in ('running', 'stopped')
                   and (stopped or not stale))
        live = self.get('kucoin_health')
        if live is not None:
            healthy = healthy and (stopped or (live.get('ready',False) and now_ms()-live.get('time',0) < 15000))
        paper_status=self.get('kucoin_paper_status')
        if paper_status is not None and not stopped:
            healthy=healthy and paper_status.get('status')=='running'
        return {'paper_status':paper_status, 'live_market': live, 'healthy': healthy, 'stopped': stopped, 'heartbeat': beat,
                'data_stale': stale, 'last_processed_open': last,
                'metrics': self.get('metrics'), 'simulation_only': True,
                'positions': self.get('checkpoint', {}).get('positions', [])}


class PublicFuturesSource:
    """Documented Binance USD-M REST alternative to daily archive downloads."""
    BASE = 'https://fapi.binance.com'

    def __init__(self):
        self.responses = []

    def read(self, path, params=None):
        if path not in ('/fapi/v1/time', '/fapi/v1/klines'):
            raise ValueError('Only public time and kline GET endpoints are permitted')
        url = self.BASE+path+('?' + urlencode(params) if params else '')
        payload = fetch(url)
        self.responses.append((now_ms(), url, digest(payload), payload))
        return json.loads(payload)

    def clock(self):
        return int(self.read('/fapi/v1/time')['serverTime'])

    def candles(self, symbol, interval, start, end):
        if symbol not in SYMBOLS or interval not in INTERVALS:
            raise ValueError('Unsupported market')
        rows = self.read('/fapi/v1/klines', {'symbol': symbol, 'interval': interval,
                         'startTime': start, 'endTime': end-1, 'limit': 1000})
        if not isinstance(rows, list):
            raise ValueError('Expected public kline list')
        result = []
        for row in rows:
            t = int(row[0])
            if int(row[6]) != t+INTERVALS[interval]-1:
                raise ValueError('Invalid REST candle close time')
            result.append(Candle(t, *(float(v) for v in row[1:6])))
        return result


class Worker:
    def __init__(self, store, config, rules, rules_payload, source=None, after_process=None):
        self.store, self.cfg, self.rules = store, config, rules
        self.after_process = after_process
        self.source = source or PublicFuturesSource()
        self.strategy = StrategyConfig(**config.get('strategy', {}))
        self.risk = RiskConfig(**config.get('risk', {}))
        self.symbols = sorted(config['symbols'])
        if not self.symbols or len(set(self.symbols)) != len(self.symbols) or not set(self.symbols) <= set(SYMBOLS):
            raise ValueError('Choose unique supported symbols')
        self.interval = INTERVALS[config['interval']]
        self.warmup = max(self.strategy.lookback, self.strategy.atr_period+1)
        if self.warmup > 900:
            raise ValueError('Service warm-up must fit within one 1000-row REST page')
        if not 1 <= config.get('poll_seconds', 10) <= 300:
            raise ValueError('Poll interval must be 1..300 seconds')
        if not 1 <= config.get('max_catchup_bars', 1000) <= 10_000:
            raise ValueError('Catch-up limit must be 1..10000 bars')
        # Changing a strategy, rules, or engine implementation requires a new paper account.
        identity = {'config': config, 'rules_sha256': digest(rules_payload),
                    'source_sha256': {name: digest(Path(__file__).with_name(name).read_bytes())
                                      for name in ('backtest.py','strategy.py','risk.py','models.py','data.py','service.py')}}
        with store.transaction():
            existing = store.get('identity')
            if existing is not None and existing != identity:
                raise ValueError('Service identity changed; use a new database, never reset an existing account')
            store.set('identity', identity)
            store.set('configuration', config)
            store.set('rules_snapshot', json.loads(rules_payload))

    def beat(self, status, error=None):
        self.store.set('heartbeat', {'time': now_ms(), 'status': status, 'error': error})

    def tick(self):
        if self.store.get('stop', False):
            self.beat('stopped')
            return 0
        self.source.responses = []
        server_time = self.source.clock()
        if abs(server_time-now_ms()) > 60_000:
            raise ValueError('Host/exchange clock difference exceeds 60 seconds')
        latest = server_time//self.interval*self.interval-self.interval
        checkpoint = self.store.get('checkpoint')
        if checkpoint:
            next_time = checkpoint['last_time']+self.interval
            if next_time > latest:
                self.beat('running')
                return 0
            backlog = (latest-next_time)//self.interval+1
            if backlog > self.cfg.get('max_catchup_bars', 1000):
                raise ValueError('Recovery backlog exceeds configured maximum; account remains unchanged')
            end = min(latest+self.interval, next_time+500*self.interval)
            warm = {}
            for s in self.symbols:
                rows = self.store.db.execute(
                    'SELECT payload FROM candles WHERE symbol=? AND time<? ORDER BY time DESC LIMIT ?',
                    (s, next_time, self.warmup)).fetchall()
                warm[s] = [Candle(**json.loads(row[0])) for row in reversed(rows)]
                if len(warm[s]) != self.warmup:
                    raise ValueError('Missing persisted indicator warm-up')
            start = self.warmup
        else:
            next_time = latest-self.warmup*self.interval
            end = latest+self.interval
            warm = {s: [] for s in self.symbols}
            start = self.warmup  # cold start warms history; no backfilled initial trades
        incoming = {s: self.source.candles(s, self.cfg['interval'], next_time, end)
                    for s in self.symbols}
        expected = list(range(next_time, end, self.interval))
        if any([b.time for b in incoming[s]] != expected for s in self.symbols):
            raise ValueError('Missing, duplicate, open, or unsynchronized public candles')
        window = {s: warm[s]+incoming[s] for s in self.symbols}
        # Stop is rechecked under the same write transaction as the checkpoint.
        with self.store.transaction():
            if self.store.get('stop', False):
                self.beat('stopped')
                return 0
            result = run(window, self.rules, self.strategy, self.risk, start=start,
                         checkpoint=checkpoint, finalize=False)
            for s in self.symbols:
                for b in incoming[s]:
                    self.store.db.execute('INSERT INTO candles VALUES (?,?,?)',
                                          (s,b.time,canonical(asdict(b))))
                for i in range(start, len(window[s])):
                    sig = signal(window[s], i, self.strategy)
                    if sig:
                        self.store.db.execute('INSERT INTO signals VALUES (?,?,?,?)',
                                              (s,window[s][i].time,sig.side,canonical(asdict(sig))))
            for trade in result['trades']:
                payload = canonical(trade)
                self.store.db.execute('INSERT INTO trades VALUES (?,?)', (digest(payload.encode()),payload))
            for point in result['equity_curve']:
                self.store.db.execute('INSERT INTO equity VALUES (?,?)', (point['time'],canonical(point)))
            self.store.db.executemany(
                'INSERT INTO responses(fetched_at,url,sha256,payload) VALUES (?,?,?,?)', self.source.responses)
            self.store.set('checkpoint', result['checkpoint'])
            self.store.set('metrics', result['metrics'])
            if self.after_process is not None:
                self.after_process(result, window, start)
            self.store.event('processed', f'{result["checkpoint"]["last_time"]}; recovered={bool(checkpoint)}')
            self.beat('running')
        return len(result['equity_curve'])


@contextmanager
def single_worker(path):
    with open(str(path)+'.lock', 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another worker already owns this database') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only scanner and simulated paper service (Linux)')
    parser.add_argument('command', choices=['run', 'health', 'stop', 'resume', 'backup'])
    parser.add_argument('--db', type=Path, default=Path('state/paper.sqlite3'))
    parser.add_argument('--config', type=Path, default=Path('configs/service.json'))
    parser.add_argument('--rules-file', type=Path, default=Path('data/exchangeInfo.json'))
    parser.add_argument('--backup-to', type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args(argv)
    if args.command != 'run' and not args.db.exists():
        parser.error('Database does not exist')
    store = Store(args.db)
    try:
        if args.command in ('stop','resume'):
            store.control(args.command == 'stop')
            print(canonical({'stopped': store.get('stop')}))
        elif args.command == 'health':
            health = store.health()
            print(json.dumps(health, indent=2))
            return 0 if health['healthy'] else 1
        elif args.command == 'backup':
            if args.backup_to is None or args.backup_to.exists():
                parser.error('Choose a new --backup-to path')
            args.backup_to.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(args.backup_to) as target:
                store.db.backup(target)
        else:
            cfg = json.loads(args.config.read_text())
            rules, _ = exchange_rules(args.db.parent, snapshot=args.rules_file)
            with single_worker(args.db):
                worker = Worker(store, cfg, rules, args.rules_file.read_bytes())
                quitting = threading.Event()
                for sig in (os_signal.SIGINT, os_signal.SIGTERM):
                    os_signal.signal(sig, lambda *_: quitting.set())
                failures = 0
                while not quitting.is_set():
                    try:
                        worker.tick()
                        failures = 0
                    except Exception as exc:
                        failures += 1
                        message = f'{type(exc).__name__}: {exc}'
                        with store.transaction():
                            worker.beat('error', message)
                            store.event('error', message)
                        print(canonical({'error': message, 'attempt': failures}), flush=True)
                        if args.once:
                            return 1
                    if args.once:
                        break
                    quitting.wait(min(300, cfg.get('poll_seconds',10)*2**min(failures,5)))
                worker.beat('shutdown')
    finally:
        store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
