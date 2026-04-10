# PyPNMGui

PyPNMGui is the Flask and Vue frontend for the PyPNM stack.

Its job is straightforward: present the operator interface, handle session and admin flows, and proxy requests to the PyPNM API. SNMP collection, modem analysis, topology processing, and the rest of the plant logic belong in PyPNM itself.

## Where It Fits

```text
Browser -> PyPNMGui (:5050) -> PyPNM API (:8000) -> CMTS / Cable Modems
```

The GUI repository contains the web frontend, the Flask backend-for-frontend layer, deployment assets, and supporting documentation for local and Docker-based operation.

## Main Functions

- Web interface for modem search and diagnostics
- Proxy layer to the PyPNM API
- Auth and admin pages
- Optional topology views
- Reverse-proxy aware deployment through `APPLICATION_ROOT`

## Start Here

- Quick setup: `QUICKSTART.md`
- Full run and install manual: `MANUAL.md`

## Common Configuration

- `PYPNM_API_URL`: URL of the PyPNM API, usually `http://127.0.0.1:8000`
- `APPLICATION_ROOT`: base path when the GUI runs behind a reverse proxy
- `DATA_MODE`: `direct`, `agent`, or `mock`
- `ENABLE_TOPOLOGY`: enable or disable topology pages

## Local Start

```bash
cd PyPNMGui
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
export PYPNM_API_URL=http://127.0.0.1:8000
python backend/run.py
```

Open `http://localhost:5050`.

## Related Documentation

- `QUICKSTART.md`
- `MANUAL.md`
- `docs/PROXY_SETUP.md`
- `docs/NETWORK_ARCHITECTURE.md`
- `docs/PYPNM_INTEGRATION.md`

## License

Apache-2.0
