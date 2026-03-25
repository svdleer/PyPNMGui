# PyPNM Web GUI

Web-based management interface for [PyPNM](https://github.com/svdleer/PyPNM) — Proactive Network Maintenance for DOCSIS HFC networks.

## Overview

PyPNM Web GUI provides operators with a single-pane-of-glass for cable plant monitoring, PNM diagnostics, and modem management. It acts as a Backend-for-Frontend (BFF) that proxies and orchestrates calls to the PyPNM API.

### System Architecture

```
Browser ──► PyPNM Web GUI (Flask, port 5050)
                 │
                 ├── PyPNM API (FastAPI, port 8000) ──► CMTS / Cable Modems (SNMP)
                 │
                 └── pyPNM Agent (optional, SNMP relay on jump server)
```

| Component | Port | Purpose |
|-----------|------|---------|
| **PyPNM Web GUI** (this repo) | 5050 | Web UI + BFF layer |
| **[PyPNM](https://github.com/svdleer/PyPNM)** | 8000 | Core PNM API — SNMP, spectrum analysis, modem inventory |
| **[pyPNM Agent](https://github.com/svdleer/pyPNMAgent)** | — | Remote SNMP agent for network-segmented environments |

## Features

- **Modem Search** — Find modems by IP, MAC, hostname, or fiber node
- **RF Diagnostics** — Downstream/upstream channel statistics, OFDM/OFDMA status
- **PNM Measurements** — RxMER capture, upstream spectrum analysis (UTSC), constellation display
- **FiberNode Analysis** — Per-fiber-node RxMER scans, downstream suckout detection, plant assessment
- **Topology Module** — Network graph explorer with CSV-imported topology data (optional)
- **CMTS Management** — Multi-CMTS support with Redis-cached modem inventories
- **Modem Inventory** — Polled modem database with enrichment (DOCSIS version, OFDM/OFDMA capability)
- **Authentication** — Role-based access control with MySQL or SQLite backend
- **Internationalisation** — Multi-language UI (English, Dutch)

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/svdleer/PyPNMGui.git
cd PyPNMGui/docker
cp .env.example .env          # Edit with your CMTS/SNMP settings
docker compose -f docker-compose.prod.yml up -d
```

### Manual

```bash
git clone https://github.com/svdleer/PyPNMGui.git
cd PyPNMGui
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt
cd backend && python run.py
```

Open `http://localhost:5050` in your browser.

> **Prerequisite:** PyPNM API must be running. See [PyPNM install guide](https://github.com/svdleer/PyPNM).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PYPNM_API_URL` | `http://127.0.0.1:8000` | PyPNM API base URL |
| `FLASK_PORT` | `5050` | Web GUI listen port |
| `APPLICATION_ROOT` | `/` | Base path for reverse proxy (e.g. `/cmtool`) |
| `DATA_MODE` | `direct` | `direct` / `agent` / `mock` |
| `ENABLE_TOPOLOGY` | `false` | Enable topology module with CSV data |
| `REDIS_HOST` | — | Redis host for CMTS modem cache |
| `REDIS_PORT` | `6379` | Redis port |
| `AUTH_DB_HOST` | — | MySQL host for auth DB (SQLite fallback) |
| `SNMP_COMMUNITY` | — | Default SNMP read community |

### Authentication Setup

```bash
# Initialise auth database and bootstrap admin user
python backend/scripts/init_auth_db.py
```

Set `AUTH_DB_HOST`, `AUTH_DB_USER`, `AUTH_DB_PASSWORD`, `AUTH_DB_NAME` for MySQL, or omit for SQLite fallback.

## Project Structure

```
PyPNMGui/
├── backend/
│   ├── app/
│   │   ├── __init__.py              # Flask app factory
│   │   ├── core/                    # Config, clients, plotters, auth
│   │   └── routes/                  # Flask routes (api, auth, pypnm, topology, ws)
│   ├── run.py                       # Entry point
│   └── requirements.txt
├── frontend/
│   ├── templates/                   # Jinja2 templates (index, topology, admin)
│   └── static/
│       ├── css/style.css
│       └── js/app.js                # Vue.js 3 SPA
├── docker/
│   ├── docker-compose.prod.yml      # Production deployment
│   ├── Dockerfile.server            # GUI container image
│   └── .env.example
├── deploy/                          # Agent installation scripts
├── config/                          # System configuration
└── docs/                            # Additional documentation
```

## Deployment

Deploy via git — never copy files manually:

```bash
ssh your-server
cd /path/to/PyPNMGui && git pull
cd docker && docker compose -f docker-compose.prod.yml up -d --build
```

See [docker/README.md](docker/README.md) for production setup details.

## Documentation

- [Proxy Setup](docs/PROXY_SETUP.md) — Reverse proxy with custom base path
- [Network Architecture](docs/NETWORK_ARCHITECTURE.md) — Detailed system topology
- [PyPNM Integration](docs/PYPNM_INTEGRATION.md) — BFF ↔ API communication
- [SSH Tunnel Setup](docs/SSH_TUNNEL_SETUP.md) — Secure access to remote CMTS
- [Redis Caching](docs/REDIS_OPTIONAL.md) — Optional Redis for modem inventory cache

## Development

```bash
# Terminal 1: PyPNM API
cd PyPNM && source .venv/bin/activate && pypnm

# Terminal 2: Web GUI (debug mode)
cd PyPNMGui && source venv/bin/activate
FLASK_DEBUG=1 python backend/run.py
```

## License

Apache-2.0
