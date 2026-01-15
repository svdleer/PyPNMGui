# PyPNM Web GUI

A modern web-based graphical user interface for [PyPNM](https://github.com/PyPNMApps/PyPNM) - the Proactive Network Maintenance toolkit for DOCSIS cable modems.

## ⚠️ Important: Understanding This Project

**This project is a Web GUI frontend for PyPNM. It does NOT replace PyPNM.**

PyPNM is a complete, standalone FastAPI server that provides all PNM (Proactive Network Maintenance) functionality for DOCSIS cable modems. This Web GUI project provides a modern browser-based interface to interact with PyPNM's API.

### Architecture

```
┌────────────────────────────────────┐
│  PyPNM Server (Separate Install)  │
│  FastAPI on port 8000              │
│  - SNMP operations                 │
│  - PNM measurements                │
│  - Data processing                 │
└──────────────▲─────────────────────┘
               │ HTTP API
┌──────────────┴─────────────────────┐
│  PyPNM Web GUI (This Project)      │
│  Flask on port 5050                │
│  - Modern Vue.js interface         │
│  - Proxies PyPNM API               │
│  - CMTS management                 │
└──────────────▲─────────────────────┘
               │ Browser
          ┌────┴────┐
          │  User   │
          └─────────┘
```

## Prerequisites

1. **Python 3.10+**
2. **PyPNM installed and running** - See [PyPNM Installation](#pypnm-installation)
3. **Network access to cable modems** (or remote agent setup)

## PyPNM Installation

Before using this Web GUI, you MUST install and run PyPNM:

```bash
# Install PyPNM (in a separate directory)
git clone https://github.com/PyPNMApps/PyPNM.git
cd PyPNM
./install.sh

# Start PyPNM server
./scripts/pypnm-cli.sh start

# Verify PyPNM is running
# Open http://127.0.0.1:8000/docs in your browser
```

**For detailed PyPNM installation instructions, see:**
- Official Docs: https://www.pypnm.io/
- Installation Guide: https://www.pypnm.io/docker/install/
- GitHub README: https://github.com/PyPNMApps/PyPNM

## Quick Start (Web GUI)
1. Clone or navigate to this repository:
```bash
cd /Users/silvester/PythonDev/Git/PyPNMGui
```

2. Create and activate a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows
```

3. Install Python dependencies:
```bash
pip install -r backend/requirements.txt
```

4. Configure PyPNM server URL (optional, defaults to http://127.0.0.1:8000):
```bash
export PYPNM_BASE_URL=http://127.0.0.1:8000
```

5. Run the Web GUI:
```bash
./start.sh
# or manually:
cd backend
python run.py
```

6. Open your browser:
```
http://localhost:5050
```

## Features

- 🔍 **Cable Modem Search** - Search by IP, MAC, CMTS, or interface
- 📊 **Real-time Statistics** - View downstream/upstream channel stats via PyPNM
- 🔬 **PNM Measurements** - Run RxMER, Spectrum Analysis, Constellation Display
- 📋 **Event Log Viewer** - Browse modem event logs
- 📈 **Data Visualization** - Charts for RxMER and other measurements
- 🎨 **Modern UI** - Bootstrap 5 + Vue.js 3 + SweetAlert2
- 🔄 **PyPNM Integration** - Seamless proxy to PyPNM FastAPI

## Configuration

### Environment Variables

```bash
# PyPNM server URL (default: http://127.0.0.1:8000)
export PYPNM_BASE_URL=http://127.0.0.1:8000

# Flask server port (default: 5050)
export FLASK_PORT=5050

# Redis cache (optional, for CMTS data caching)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_TTL=21600
```

### PyPNM Configuration

For PyPNM configuration (SNMP settings, TFTP servers, etc.), edit PyPNM's `system.json`:
```bash
cd PyPNM
nano src/pypnm/settings/system.json
```

See PyPNM documentation: https://www.pypnm.io/system/system-config/

## Project Structure

```
PyPNMGui/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Flask app factory
│   │   ├── core/
│   │   │   ├── config.py        # Configuration settings
│   │   │   ├── pypnm_client.py  # PyPNM API client wrapper
│   │   │   └── cmts_provider.py # CMTS list provider
│   │   └── routes/
│   │       ├── main_routes.py   # Frontend serving
│   │       └── api_routes.py    # API endpoints (proxies to PyPNM)
│   ├── run.py                   # Entry point
│   └── requirements.txt         # Python dependencies
├── frontend/
│   ├── templates/
│   │   └── index.html           # Main HTML template
│   └── static/
│       ├── css/
│       │   └── style.css        # Custom styles
│       └── js/
│           └── app.js           # Vue.js application
├── agent/                       # Optional: Remote agent for Jump Server
│   └── ... (for environments where PyPNM can't reach modems directly)
├── pypnm_integration/           # Reference: Files to integrate into PyPNM
│   └── ... (for adding remote agent support TO PyPNM)
├── docs/
│   └── INTEGRATION_PLAN.md      # Detailed integration architecture
├── README.md                    # This file
└── start.sh                     # Quick start script
```

## API Endpoints

This Web GUI proxies requests to PyPNM's FastAPI endpoints. All data comes from PyPNM.

### Web GUI Endpoints (proxy layer)

| Endpoint | Method | Description | PyPNM Target |
|----------|--------|-------------|--------------|
| `/api/health` | GET | Check PyPNM connectivity | - |
| `/api/modem/<mac>/system-info` | POST | Get sysDescr | `/system/sysDescr` |
| `/api/modem/<mac>/uptime` | POST | Get uptime | `/system/upTime` |
| `/api/modem/<mac>/event-log` | POST | Get event log | `/docs/dev/eventLog` |
| `/api/modem/<mac>/ds-channels` | POST | Downstream stats | `/docs/if30/ds/*` + `/docs/if31/ds/*` |
| `/api/modem/<mac>/us-channels` | POST | Upstream stats | `/docs/if30/us/*` + `/docs/if31/us/*` |
| `/api/modem/<mac>/rxmer` | POST | RxMER measurement | `/docs/pnm/ds/ofdm/rxmer/getCapture` |
| `/api/modem/<mac>/spectrum` | POST | Spectrum analysis | `/docs/pnm/spectrumAnalyzer/getCapture` |
| `/api/modem/<mac>/constellation` | POST | Constellation | `/docs/pnm/ds/ofdm/const_display/getCapture` |

### PyPNM Direct Endpoints

For complete API documentation, see PyPNM's Swagger UI at: **http://127.0.0.1:8000/docs**

### Request Format

Example POST request to Web GUI:
```bash
curl -X POST http://localhost:5050/api/modem/aa:bb:cc:dd:ee:ff/system-info \
  -H "Content-Type: application/json" \
  -d '{
    "modem_ip": "192.168.100.10",
    "community": "private"
  }'
```

This is proxied to PyPNM as:
```bash
curl -X POST http://127.0.0.1:8000/system/sysDescr \
  -H "Content-Type: application/json" \
  -d '{
    "cable_modem": {
      "mac_address": "aa:bb:cc:dd:ee:ff",
      "ip_address": "192.168.100.10",
      "snmp": {
        "snmpV2C": {
          "community": "private"
        }
      }
    }
  }'
```

## Remote Agent (Optional)

If PyPNM cannot directly reach cable modems (firewall, network segmentation), you can deploy a remote agent on a Jump Server. See:

- [agent/README.md](agent/README.md) - Agent deployment guide
- [pypnm_integration/README.md](pypnm_integration/README.md) - How to integrate agent support into PyPNM
- [docs/PYPNM_INTEGRATION.md](docs/PYPNM_INTEGRATION.md) - Detailed architecture

## Troubleshooting

### PyPNM Not Reachable

**Error:** `PyPNM server not reachable at http://127.0.0.1:8000`

**Solution:**
1. Verify PyPNM is running: `curl http://127.0.0.1:8000/docs`
2. Check PyPNM logs: `cd PyPNM && tail -f logs/pypnm.log`
3. Start PyPNM if not running: `./scripts/pypnm-cli.sh start`

### TFTP Required for PNM Measurements

**Error:** `tftp_ipv4 required for PNM measurements`

**Reason:** PNM measurements (RxMER, Spectrum, etc.) require the cable modem to upload capture files to a TFTP server.

**Solution:**
1. Configure TFTP in PyPNM's `system.json`
2. Ensure TFTP server is reachable from cable modems
3. See: https://www.pypnm.io/system/pnm-file-retrieval/

### No Modems Found

This Web GUI does not query modems from CMTS directly. You need to either:
1. Use PyPNM's Python library to query CMTS
2. Maintain a separate database of modems
3. Search by specific MAC/IP address

## Development

### Running in Development Mode

```bash
# Terminal 1: PyPNM server
cd PyPNM
./scripts/pypnm-cli.sh start

# Terminal 2: Web GUI
cd PyPNMGui
source venv/bin/activate
export FLASK_DEBUG=1
cd backend
python run.py
```

### Adding New Features

1. Check PyPNM API docs: http://127.0.0.1:8000/docs
2. Add proxy endpoint in `backend/app/routes/api_routes.py`
3. Add method to `backend/app/core/pypnm_client.py`
4. Update frontend in `frontend/static/js/app.js`

## Resources

- **PyPNM Documentation:** https://www.pypnm.io/
- **PyPNM GitHub:** https://github.com/PyPNMApps/PyPNM
- **PyPNM API Reference:** https://www.pypnm.io/api/
- **Integration Plan:** [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md)
- **Network Architecture:** [docs/NETWORK_ARCHITECTURE.md](docs/NETWORK_ARCHITECTURE.md)

## Contributing

This project provides a Web GUI for PyPNM. For PyPNM core features (SNMP, PNM measurements, etc.), contribute to the main PyPNM project.

For Web GUI improvements:
1. Fork this repository
2. Create a feature branch
3. Test with PyPNM
4. Submit a pull request

## License

Apache-2.0

## Support

- Web GUI Issues: Create an issue in this repository
- PyPNM Issues: https://github.com/PyPNMApps/PyPNM/issues
- PyPNM Documentation: https://www.pypnm.io/issues/
