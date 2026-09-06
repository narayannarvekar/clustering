# Delivery Friction Hotspot Service

Identifies statistically significant delivery-performance hotspots across a metro area,
so gig-worker pay incentives can be targeted at the zones that actually need them.

- **H3 hexes** (resolution 7) tile the metro area with a **friction score (0–1)** built from
  late-delivery rate and average delay.
- **Getis-Ord Gi\*** hotspot analysis finds hexes whose friction is significantly elevated
  relative to their neighborhood (not just noisy individual hexes).
- Contiguous significant hexes are grouped into **clusters**, each with a severity score and a
  suggested pay-intervention tier (Monitor / Incentive Bonus / Priority Pay).
- Two metros are included out of the box: **South Florida** (Miami–Fort Lauderdale–West Palm
  Beach) and **Dallas–Fort Worth**, each using its real Census MSA boundary and synthetic order
  data standing in for a real order-performance feed.

## Prerequisites

- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) for dependency management:
  ```bash
  curl -LsSf https://astral.sh/install.sh | sh
  # or: brew install uv
  ```

## Quick start

```bash
./start.sh
```

First run creates a virtual environment in `backend/.venv` and installs dependencies; every run
after that just starts the server. Then open **http://localhost:8000/**.

Use a different port with `PORT=8001 ./start.sh`.

## Manual setup

```bash
cd backend
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

## Project structure

```
clustering/
  start.sh
  backend/
    requirements.txt
    app/
      main.py          # FastAPI app, serves API + static frontend
      api.py            # /api/* routes
      geo.py             # metro registry, H3 hex generation from real MSA boundaries
      synthetic_data.py  # per-metro synthetic order generation
      friction.py        # friction score formula
      gistar.py           # Getis-Ord Gi* implementation
      clusters.py         # connected-component clustering, severity, intervention tiers
      dataset.py           # per-metro dataset cache/build orchestration
      data/metros/          # real Census MSA boundary GeoJSON per metro
  frontend/
    index.html
    app.js
    styles.css
```

## API endpoints

All endpoints take a `?metro=miami` or `?metro=dallas` query param (default `miami`).

| Endpoint | Description |
|---|---|
| `GET /api/metros` | List available metros (id, name, map center/zoom) |
| `GET /api/boundary` | Metro's real MSA boundary, as GeoJSON |
| `GET /api/hexes` | All H3 hexes with friction score + Gi* stats, as GeoJSON |
| `GET /api/clusters` | Dissolved cluster polygons with severity/intervention, as GeoJSON |
| `GET /api/stats` | Summary counts for the current dataset |
| `POST /api/regenerate` | Reshuffle synthetic order data with a new random seed |

## Troubleshooting

**`uv` fails to fetch packages with a TLS/native-tls error** — usually a corporate proxy/VPN
doing SSL inspection that `uv`'s bundled cert store doesn't trust. Use the OS certificate store
instead:
```bash
uv pip install --native-tls --python .venv/bin/python -r requirements.txt
```
or set it once: `export UV_NATIVE_TLS=1`.

**Port already in use** — run with a different port: `PORT=8001 ./start.sh`.

## Using real order data

`synthetic_data.py` is the only place that fabricates data. Replace
`generate_hex_stats()`'s output with a query against your real orders table (per-hex
`order_count`, `late_rate`, `avg_delay_minutes`) and the friction/Gi*/cluster pipeline downstream
is unchanged.
