# Delivery Friction Clustering Service

Identifies statistically significant delivery-performance hotspots across a metro area,
so gig-worker pay incentives can be targeted at the zones that actually need them.

This service does **not** compute friction scores — that's a separate upstream service's job.
It consumes friction scores (pushed via `POST /api/clusters/compute`) and is purely focused on:

- **Getis-Ord Gi\*** hotspot analysis over an H3 (resolution 7) hex grid, finding hexes whose
  friction is significantly elevated relative to their neighborhood (not just noisy individual
  hexes).
- Grouping contiguous significant hexes into **clusters**, each with a severity score and a
  suggested pay-intervention tier (Monitor / Incentive Bonus / Priority Pay).

Two metros are included out of the box: **South Florida** (Miami–Fort Lauderdale–West Palm
Beach) and **Dallas–Fort Worth**, each using its real Census MSA boundary. Locally, each metro
is seeded with synthetic friction data at startup (see `synthetic_data.py`) so the app is
usable without a real upstream service — see "Local demo data" below.

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
      main.py            # FastAPI app: mounts both routers + static frontend
      api_clusters.py     # /api/clusters/* — the actual clustering product
      api_map.py           # /api/map/* — UX-supporting endpoints (metros, boundary, friction display, stats)
      api_common.py         # shared metro-validation helper for both routers
      geo.py                 # metro registry, H3 hex generation from real MSA boundaries
      synthetic_data.py       # LOCAL DEMO ONLY: fabricates friction data shaped like a real push
      gistar.py                 # Getis-Ord Gi* implementation
      clusters.py                # connected-component clustering, severity, intervention tiers
      dataset.py                  # per-metro ingest -> Gi*/cluster cache
      data/metros/                  # real Census MSA boundary GeoJSON per metro
  frontend/
    index.html
    app.js
    styles.css
```

## API endpoints

All endpoints take a `?metro=miami` or `?metro=dallas` query param (default `miami`). Full
per-endpoint docs (params, response schemas, "Try it out") are live at **`/docs`** — this table
is just a quick-reference. Endpoints are split into two groups by responsibility:

**`/api/clusters/*`** — the actual clustering product. Never computes friction scores itself.

| Endpoint | Description |
|---|---|
| `GET /api/clusters` | Cached severity-scored hotspot clusters (`hex_ids`, not geometry — the frontend dissolves the boundary client-side via h3-js). Pure read, does not compute anything. |
| `POST /api/clusters/compute` | The upstream friction-scoring service pushes a fresh set of per-hex friction scores here; runs Gi*/clustering on them. This service retains no friction data between calls, so `hexes` is required on every call. |

**`/api/map/*`** — UX-supporting endpoints. No Gi*/cluster fields live here.

| Endpoint | Description |
|---|---|
| `GET /api/map/metros` | List available metros (id, name, map center/zoom) |
| `GET /api/map/boundary` | Metro's real MSA boundary, as a GeoJSON `Feature` (the only endpoint that ships geometry — static reference geography, not derived from the hex grid) |
| `GET /api/map/hexes` | Every H3 hex's friction display data. No Gi*/`spot_type` (that's `/api/clusters`) and no geometry (the frontend derives each hex's boundary client-side via h3-js) |
| `GET /api/map/stats` | Summary counts for the current dataset |

If the frontend needs a hex's friction display *and* its cluster membership in one place (e.g. a
popup), it fetches both endpoints and merges by `h3` id client-side — there's no endpoint that
returns both, by design.

**On computation timing:** Gi*/clustering does not re-run on every `GET /api/clusters` call — it
runs once when a metro's dataset is built (server startup) and again whenever
`POST /api/clusters/compute` is called, and is cached from there.

## Production integration

This service expects a friction-scoring service to push data to it — it never generates or
computes friction scores itself, and it retains no friction data between calls. Every
`POST /api/clusters/compute?metro=<id>` call is a full, self-contained push:

```json
{
  "k": 2,
  "hexes": [
    {"h3": "8744acc05ffffff", "friction_score": 0.42, "order_count": 89, "late_rate": 0.13, "avg_delay_minutes": 4.1}
  ]
}
```

`hexes` is required — there's no "recompute using whatever was last stored" mode, by design.
`k` is optional (defaults to the metro's current neighborhood radius). `order_count`/`late_rate`/
`avg_delay_minutes` are optional display context cached for `/api/map/hexes`; only `h3` and
`friction_score` are required per hex. Each call **replaces** that metro's cached cluster output
(and hex display data) in full.

## Local demo data

Without a real upstream service, `synthetic_data.py` seeds each metro with fabricated friction
data at startup (`build_demo_friction_records()`) so the app is usable out of the box. It
produces the exact same shape `POST /api/clusters/compute` expects, so nothing downstream
knows the difference. This module is dev/demo-only — it has no role in production once a real
friction-scoring service is pushing data.

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
