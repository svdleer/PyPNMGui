# Quick Start

Get PyPNM Web GUI running in under 10 minutes.

## Prerequisites

- Python 3.10+ or Docker
- PyPNM API server ([install guide](https://github.com/svdleer/PyPNM))

## Option A: Docker

```bash
cd PyPNMGui/docker
cp .env.example .env
# Edit .env — set PYPNM_API_URL, SNMP communities, TFTP IP
docker compose -f docker-compose.prod.yml up -d
```

Open `http://your-server:5050` (or the configured `APPLICATION_ROOT` path).

## Option B: Manual

```bash
cd PyPNMGui
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt

# Optional: set PyPNM API URL if not localhost
export PYPNM_API_URL=http://127.0.0.1:8000

cd backend && python run.py
```

Open `http://localhost:5050`.

## Verify

```bash
curl http://localhost:5050/api/health
```

Expected:
```json
{"status": "ok", "pypnm_connected": true}
```

If `pypnm_connected` is `false`, ensure the PyPNM API is running on the configured URL.

## Next Steps

1. **Add a CMTS** — Go to Admin > CMTS and register your CMTS IP + SNMP community
2. **Search modems** — Select a CMTS, then search by IP, MAC, or fiber node
3. **Run PNM scans** — Select a modem and use the RxMER, Spectrum, or Constellation tabs
4. **FiberNode analysis** — Switch to the FiberNode tab for per-node RF assessment

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pypnm_connected: false` | PyPNM API not running | Start PyPNM: `cd PyPNM && pypnm` |
| `Address already in use: 5050` | Port conflict | `lsof -i :5050` then kill, or set `FLASK_PORT=5051` |
| `tftp_ipv4 required` | TFTP not configured | Set TFTP IP in PyPNM `system.json` |
| No modems returned | CMTS not added or SNMP timeout | Check Admin > CMTS, verify SNMP community |
- **This Project's Docs:** [README.md](README.md)

## Getting Help

1. **Web GUI Issues:** Create issue in this repository
2. **PyPNM Issues:** https://github.com/svdleer/PyPNM/issues
3. **Integration Questions:** Read [docs/PYPNM_INTEGRATION.md](docs/PYPNM_INTEGRATION.md)

---

**Remember:** PyPNM is the actual PNM engine. This Web GUI is just a user-friendly interface to it. Both must be running for full functionality.
