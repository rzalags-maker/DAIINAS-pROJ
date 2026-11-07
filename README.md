# DAIINAS Control Room

A local, public-data-only market observation screen for manual analysis.

It reads public Binance and Kraken data. It has no credentials, account access,
order API, paper portfolio, execution gateway or automated trade admission.

Run it with Python 3.11–3.13:

```sh
python -m daiinas.control_room
```

Open `http://127.0.0.1:8765`. The page is deliberately fail-closed when public
data is unavailable or source timestamps are not supplied by the provider.

```sh
python -m unittest discover -s tests -v
```
