# PyPNMGui — Copilot Instructions

> GUI frontend + BFF (Backend for Frontend) for the PyPNM cable-plant monitoring system.

## Architecture Overview

Three Docker containers form the system:

| Container | Repo | Framework | Port | Role |
|-----------|------|-----------|------|------|
| **PyPNMGui** | `PyPNMGui/` | Flask 3 + Vue.js 3 | 5050 | GUI + BFF — proxies calls to PyPNM API |
| **PyPNM** | `PyPNM/` | FastAPI | 8000 | Core API — SNMP, PNM parsing, topology storage |
| **pyPNMAgent** | `pyPNMAgent/` | Standalone | — | SNMP agent — data collection from CMTS/CMs |

Data flow: **Browser → PyPNMGui (Flask) → PyPNM (FastAPI) → CMTS/CM (SNMP)**

## Key Directories

```
PyPNMGui/
├── backend/
│   ├── app/core/         # Config, topology_db, topology_loader, CMTS providers
│   ├── app/routes/       # Flask routes (api_, topology_, pypnm_, ws_routes)
│   └── run.py            # Entry point (port 5050)
├── frontend/
│   ├── templates/        # Jinja2 (index.html, topology.html)
│   └── static/js/app.js  # Vue.js 3 SPA
├── docker/               # docker-compose.prod.yml, Dockerfile.server
├── topology/             # CSV data files (NL_topology_*, NL_modemlocation_*)
└── config/               # pypnm_system.json

PyPNM/
├── src/pypnm/
│   ├── api/routes/       # FastAPI routes (topology/, cmts/, pnm/, cm/)
│   ├── api/routes/common/service/fiber_node_utils.py  # Shared OID parsing
│   ├── lib/              # types.py, constants.py, conversions/
│   ├── pnm/              # PNM file parsers & analysis
│   └── snmp/             # SNMP utilities
└── tests/

pyPNMAgent/
├── agent.py              # Main agent loop
├── ssh_tunnel.py         # SSH tunnel management
└── tftp_server.py        # TFTP server for PNM file collection
```

## Coding Conventions

See [CODING_AGENTS.md](../../PyPNM/CODING_AGENTS.md) for full rules. Key points:

- **Python:** Type all args/returns, use `list[str]` not `List[str]`, `A | B` not `Union`, Pydantic `BaseModel` for public interfaces
- **No `Any`** unless justified. Strict typing everywhere.
- **SPDX headers** required on code files: `SPDX-License-Identifier: Apache-2.0`
- **Flask templates** use `[[ ]]` delimiters (not `{{ }}`) for Vue.js compatibility
- **Minimal diffs** — no formatting churn, preserve existing whitespace/alignment
- **match/case** over long if/else chains
- **Logger pattern:** `self.logger = logging.getLogger(f"{self.__class__.__name__}")`

## Deployment — CRITICAL

- **NEVER use SCP.** Deploy ONLY via git: `git commit → push → ssh → git pull → docker restart`
- **Do not run ssh-tunnel-prod.sh** unless explicitly asked
- See `/memories/repo/deployment-procedure.md` for exact commands

## Build & Test

```bash
# PyPNMGui (Flask)
pip install -r backend/requirements.txt
python backend/run.py                      # Dev server :5050

# PyPNM (FastAPI)
cd PyPNM
python3 -m compileall src                  # Compile check
ruff check src && ruff format --check .    # Lint
pytest -q                                  # Tests

# Docker (production)
cd docker/ && docker-compose -f docker-compose.prod.yml up -d
```

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `PYPNM_API_URL` | PyPNM API base URL (default `http://127.0.0.1:8000`) |
| `DATA_MODE` | `mock` / `agent` / `direct` |
| `ENABLE_TOPOLOGY` | Enable topology module (`true`/`false`) |
| `TOPOLOGY_DB_HOST` | MySQL host for topology storage |
| `APPLICATION_ROOT` | Base path for reverse proxy (e.g., `/cmtool`) |
| `SNMP_COMMUNITY` | Default SNMP read community |

## Topology & FiberNode Module

**Topology** manages CSV-imported network graph data (nodes, edges, modem locations).
- GUI: `topology.html` — explorer with stats, search, import
- BFF routes: `backend/app/routes/topology_routes.py` — proxies to PyPNM API
- PyPNM storage: `src/pypnm/api/routes/topology/service.py` — MySQL tables

**FiberNode** provides per-fiber-node RF analysis (RxMER, pre-EQ, group delay).
- GUI: FiberNode view in `index.html` + `app.js`
- BFF routes: `backend/app/routes/pypnm_routes.py` — scan orchestration
- PyPNM: `fiber_node_utils.py` — DOCS-IF3-MIB OID parsing for FN→SG mapping
- Scan flow: SNMP walk → RxMER capture → analysis → plot → plant assessment
