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

## How Getis-Ord Gi\* works

Getis-Ord Gi\* answers a narrower question than "which hexes have high friction?" — it asks
"which hexes have friction **significantly higher or lower than the metro-wide average**, once
you also account for their neighbors?" A single hex with a bad friction score in isolation is
just noise; the same score surrounded by other bad hexes is a real hotspot. Gi\* is what tells
those two situations apart, and it's the only thing standing between "color hexes by friction"
and an actual statistical claim you'd stake a pay-intervention budget on.

**The formula**, implemented exactly as shown in `gistar.py`, for each hex *i*:

```
        Σⱼ wᵢⱼxⱼ − X̄ Σⱼ wᵢⱼ
Gi* = ────────────────────────────────────
        S √[ (n Σⱼ wᵢⱼ² − (Σⱼ wᵢⱼ)²) / (n−1) ]
```

- **n** — number of hexes in the study set (every hex with a friction score, metro-wide)
- **X̄, S** — mean and population standard deviation of friction scores across all *n* hexes
- **wᵢⱼ** — 1 if hex *j* is within `k` grid-steps of hex *i* (via H3's `grid_disk`), else 0.
  This service uses binary weights and includes the hex itself in its own neighborhood
  (that "self-inclusion" is precisely what makes this **Gi\*** rather than plain **Gi**).
  `k` defaults to 2 (a ~19-hex neighborhood at resolution 7) and is configurable per
  `POST /api/clusters/compute` call.
- The result **z** is a standard z-score: how many standard deviations the neighborhood's
  average friction sits from the metro-wide average. `p` is the two-tailed p-value for that
  z-score (via the normal distribution).

**Confidence tiers** (`_confidence_and_spot` in `gistar.py`), the same convention ArcGIS's
Hot Spot Analysis uses:

| `\|z\|` | `p` | Confidence | `spot_type` (if `z > 0` → hot, `z < 0` → cold) |
|---|---|---|---|
| > 2.58 | < 0.01 | 99% | hot / cold |
| > 1.96 | < 0.05 | 95% | hot / cold |
| > 1.65 | < 0.10 | 90% | hot / cold |
| otherwise | — | 0% | `not_significant` |

Only hexes that land on `hot` at ≥90% confidence are eligible to join a cluster
(`clusters.py`) — everything else, including statistically significant **cold** spots (good
performers, not a pay-intervention target), is excluded from cluster formation.

### Worked example

Ten hexes, friction scores 0–1. A/B/C are mutually adjacent (within `k`) and badly performing;
D/E/F are mutually adjacent and performing well; G/H/I/J are geographically isolated from
everyone (their only "neighbor" is themselves) and sit near the metro-wide average:

| Hex | Score | Neighbors (within k) | Σwx | z | p | Confidence | `spot_type` |
|---|---|---|---|---|---|---|---|
| A | 0.90 | A, B, C | 2.65 | **+2.585** | 0.0097 | 99% | **hot** |
| B | 0.85 | A, B, C | 2.65 | **+2.585** | 0.0097 | 99% | **hot** |
| C | 0.90 | A, B, C | 2.65 | **+2.585** | 0.0097 | 99% | **hot** |
| D | 0.05 | D, E, F | 0.20 | **−2.461** | 0.0138 | 95% | **cold** |
| E | 0.10 | D, E, F | 0.20 | **−2.461** | 0.0138 | 95% | **cold** |
| F | 0.05 | D, E, F | 0.20 | **−2.461** | 0.0138 | 95% | **cold** |
| G | 0.45 | G only | 0.45 | −0.047 | 0.962 | 0% | not_significant |
| H | 0.50 | H only | 0.50 | +0.110 | 0.912 | 0% | not_significant |
| I | 0.40 | I only | 0.40 | −0.205 | 0.838 | 0% | not_significant |
| J | 0.45 | J only | 0.45 | −0.047 | 0.962 | 0% | not_significant |

(n=10, X̄=0.465, S=0.318.) A/B/C become a 3-hex cluster via connected-component grouping;
D/E/F are statistically real cold spots but never form a "cluster" in this service's sense,
since only `hot` hexes are eligible. G–J each have a nonzero friction score too, but sitting
alone near the metro-wide average gives them z ≈ 0 — Gi\* never looks at a hex's own score in
isolation, only whether *its neighborhood's average* deviates from the metro average. That's
the whole point of the statistic: it's what separates "this hex happens to be a bit bad" from
"this is a real hotspot worth paying to fix."

## How clusters and severity work

Gi\* scores individual hexes; `clusters.py` (`build_clusters`) is what turns those scores into
something you'd actually act on — contiguous regions with a single severity score and a
suggested pay intervention. Two steps, both happening after every hex already has a
`spot_type` from Gi\*:

**1. Clustering — grouping hot hexes into contiguous regions**

```python
hot_cells = {c for c, r in gi_results.items() if r.spot_type == "hot"}
components = [comp for comp in _connected_components(hot_cells) if len(comp) >= MIN_HEX_COUNT]
```

Only `hot` hexes are candidates — cold spots (statistically real, but good performers) and
not-significant hexes never form a cluster, regardless of their raw friction score.
`_connected_components` flood-fills using **direct** H3 adjacency (`grid_disk(cell, 1)`, the
immediate ring — not the same `k` used for Gi\*'s neighborhood average) to find hot hexes that
physically touch. A group needs at least `MIN_HEX_COUNT` (2) hexes to count — one isolated hot
hex, even at 99% confidence, doesn't become a cluster by itself.

**2. Severity — one 0–1 score blending statistical strength with actual magnitude**

```python
severity = 0.5 * min(mean_z / 3.0, 1.0) + 0.5 * mean_friction
```

- `mean_z / 3.0`, capped at 1.0 — how *statistically* strong the cluster is (mean Gi\* z-score
  across its member hexes). The cap is a deliberate diminishing-returns ceiling so one extreme
  outlier hex can't dominate the score.
- `mean_friction` — how *bad* the cluster actually is in absolute terms (mean friction score
  across its member hexes).

It's an even 50/50 blend on purpose: a cluster that's statistically airtight (very high z) but
only mildly bad in absolute friction shouldn't outrank one that's merely 90%-confident but
genuinely severe. Severity then maps to an intervention tier (`SEVERITY_TIERS`):

| Severity | Intervention tier | Suggested bonus |
|---|---|---|
| ≥ 0.75 | Priority Pay + Staffing Review | +25% |
| ≥ 0.50 | Incentive Bonus | +15% |
| ≥ 0.30 | Monitor | +5% |
| < 0.30 | No action | 0% |

**Continuing the worked example above:** A/B/C (mean_z = 2.585, mean_friction = 0.883) form one
3-hex cluster:

```
severity = 0.5 · min(2.585 / 3, 1) + 0.5 · 0.883
         = 0.5 · 0.862           + 0.5 · 0.883
         = 0.431 + 0.442
         = 0.873  →  Priority Pay + Staffing Review, +25% suggested bonus
```

D/E/F, despite being an equally real 95%-confidence cold spot, never enters this pipeline at
all — only `hot` hexes are eligible, and cold spots (good performers) aren't a pay-intervention
target by definition.

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
