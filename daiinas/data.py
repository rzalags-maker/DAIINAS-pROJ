"""Public Binance USD-M archives with publisher SHA-256 verification."""
import csv
import hashlib
import io
import json
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile
from .models import Candle, INTERVALS, SYMBOLS
from .risk import ContractRules


def fetch(url: str) -> bytes:
    # urllib honors the environment proxy and verified system CA trust.
    with urlopen(Request(url, headers={'User-Agent': 'DAIINAS-research/0.1'}), timeout=60) as response:
        return response.read()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def download(symbol: str, interval: str, start: date, end: date, root: Path) -> list[dict]:
    if symbol not in SYMBOLS or interval not in INTERVALS or start >= end:
        raise ValueError('Unsupported symbol, interval, or date range')
    directory = root / symbol / interval
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    day = start
    while day < end:
        name = f'{symbol}-{interval}-{day.isoformat()}.zip'
        url = f'https://data.binance.vision/data/futures/um/daily/klines/{symbol}/{interval}/{name}'
        path = directory / name
        checksum_path = directory / (name + '.CHECKSUM')
        if not checksum_path.exists():
            checksum_path.write_bytes(fetch(url+'.CHECKSUM'))
        expected = checksum_path.read_text().split()[0]
        if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected.lower()):
            raise ValueError(f'Invalid publisher checksum: {name}')
        if not path.exists():
            payload = fetch(url)
            if digest(payload) != expected.lower():
                raise ValueError(f'Publisher checksum mismatch: {name}')
            path.write_bytes(payload)
        if digest(path.read_bytes()) != expected.lower():
            raise ValueError(f'Corrupted cache: {path}; remove and re-download')
        records.append({'symbol': symbol, 'interval': interval, 'date': day.isoformat(),
                        'url': url, 'sha256': expected.lower()})
        day += timedelta(days=1)
    return records


def load(symbol: str, interval: str, start: date, end: date, root: Path) -> list[Candle]:
    bars = []
    day = start
    while day < end:
        path = root / symbol / interval / f'{symbol}-{interval}-{day.isoformat()}.zip'
        expected = Path(str(path)+'.CHECKSUM').read_text().split()[0]
        payload = path.read_bytes()
        if digest(payload) != expected:
            raise ValueError(f'Checksum mismatch: {path}')
        with ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if len(names) != 1 or not names[0].endswith('.csv'):
                raise ValueError('Expected one CSV per archive')
            for row in csv.reader(io.TextIOWrapper(archive.open(names[0]), encoding='utf-8')):
                if row[0] in ('open_time', 'Open time'):
                    continue
                t = int(row[0])
                if t > 10**14:
                    t //= 1000
                bars.append(Candle(t, *(float(v) for v in row[1:6])))
        day += timedelta(days=1)
    expected_start = int(datetime.combine(start, time(), timezone.utc).timestamp()*1000)
    expected_end = expected_start + (end-start).days*86_400_000
    if not bars or bars[0].time != expected_start or bars[-1].time != expected_end-INTERVALS[interval]:
        raise ValueError('Incomplete requested date range')
    if any(b.time-a.time != INTERVALS[interval] for a, b in zip(bars, bars[1:])):
        raise ValueError('Missing, duplicate, or out-of-order candles')
    return bars


def exchange_rules(root: Path, refresh=False, snapshot: Path | None = None) -> tuple[dict[str, ContractRules], dict]:
    path = snapshot or root / 'exchangeInfo.json'
    root.mkdir(parents=True, exist_ok=True)
    if snapshot is not None and (refresh or not path.exists()):
        raise ValueError('Explicit rules snapshot must exist and cannot be refreshed')
    if refresh or not path.exists():
        payload = fetch('https://fapi.binance.com/fapi/v1/exchangeInfo')
        raw = json.loads(payload)
        if 'symbols' not in raw:
            raise ValueError('Exchange metadata response lacks symbols')
        path.write_bytes(payload)
    payload = path.read_bytes()
    raw = json.loads(payload)
    rules = {}
    for row in raw['symbols']:
        if row['symbol'] not in SYMBOLS:
            continue
        if row['contractType'] != 'PERPETUAL' or row['quoteAsset'] != 'USDT':
            raise ValueError('Expected USDT perpetual contract')
        filters = {f['filterType']: f for f in row['filters']}
        # Simulated market entry: obey both LOT_SIZE and MARKET_LOT_SIZE.
        lot, market = filters['LOT_SIZE'], filters.get('MARKET_LOT_SIZE', filters['LOT_SIZE'])
        from decimal import Decimal
        from math import lcm
        steps = [Decimal(lot['stepSize']), Decimal(market['stepSize'])]
        steps = [v for v in steps if v > 0]
        scale = 10**max(-v.as_tuple().exponent for v in steps)
        step = Decimal(lcm(*(int(v*scale) for v in steps))) / scale
        rules[row['symbol']] = ContractRules(row['symbol'],
            str(max(Decimal(lot['minQty']), Decimal(market['minQty']))),
            str(min(Decimal(lot['maxQty']), Decimal(market['maxQty']))), str(step),
            filters['PRICE_FILTER']['tickSize'], filters['MIN_NOTIONAL']['notional'])
    if set(rules) != set(SYMBOLS):
        raise ValueError('Missing required contract metadata')
    return rules, {'url': 'https://fapi.binance.com/fapi/v1/exchangeInfo',
                   'sha256': digest(payload), 'server_time': raw.get('serverTime'),
                   'limitation': 'Current snapshot applied to historical candles; not historical exchange filters.'}
