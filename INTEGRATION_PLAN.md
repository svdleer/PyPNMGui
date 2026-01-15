# PyPNM Web GUI - Proper Integration Plan

## Critical Understanding

**PyPNM IS ALREADY A COMPLETE FASTAPI SERVER** - It does NOT need to be "integrated" into this project. Instead, this Web GUI should be a **frontend client** that calls PyPNM's existing API.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   PyPNM Server (Standalone)                                │
│   ════════════════════════════                              │
│   FastAPI Server on port 8000                               │
│   └── /docs (Swagger UI)                                    │
│   └── /system/sysDescr                                      │
│   └── /system/upTime                                        │
│   └── /docs/pnm/ds/ofdm/rxmer/getCapture                    │
│   └── /docs/pnm/spectrumAnalyzer/getCapture                 │
│   └── ... (all PNM endpoints)                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │ HTTP/WebSocket
                         │
┌────────────────────────┼─────────────────────────────────────┐
│   PyPNM Web GUI        │                                     │
│   ═══════════════      │                                     │
│   Flask Server (port 5050)                                   │
│   ├── Frontend (Vue.js/HTML/CSS/JS)                         │
│   └── Backend (Flask - thin proxy layer)                    │
│       ├── Serves static files                               │
│       └── Optional: proxy/cache PyPNM API calls             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │
                         │ HTTP
                         │
                    ┌────┴────┐
                    │ Browser │
                    └─────────┘
```

## How PyPNM Works (Reference)

### 1. Installation
```bash
git clone https://github.com/PyPNMApps/PyPNM.git
cd PyPNM
./install.sh
```

### 2. Running PyPNM
```bash
cd PyPNM
./scripts/pypnm-cli.sh start
# PyPNM FastAPI server starts on http://127.0.0.1:8000
```

### 3. PyPNM API Structure
- **Base URL**: `http://127.0.0.1:8000`
- **Swagger Docs**: `http://127.0.0.1:8000/docs`
- **Key Endpoints**:
  - `POST /system/sysDescr` - Get modem system description
  - `POST /system/upTime` - Get modem uptime
  - `POST /docs/pnm/ds/ofdm/rxmer/getCapture` - RxMER measurement
  - `POST /docs/pnm/spectrumAnalyzer/getCapture` - Spectrum analysis
  - `POST /docs/dev/eventLog` - Event log retrieval
  - `POST /advance/multi/rxmer/start` - Multi-RxMER capture

### 4. PyPNM Request Format
All endpoints expect this structure:
```json
{
  "cable_modem": {
    "mac_address": "aa:bb:cc:dd:ee:ff",
    "ip_address": "192.168.100.10",
    "snmp": {
      "snmpV2C": {
        "community": "private"
      }
    },
    "pnm_parameters": {
      "tftp": {
        "ipv4": "192.168.1.100",
        "ipv6": ""
      }
    }
  }
}
```

## Integration Strategy

### Option 1: Direct API Calls (Recommended)
**The frontend calls PyPNM API directly via JavaScript fetch/axios**

**Pros:**
- Simplest architecture
- No backend duplication
- Direct access to all PyPNM features
- Easy to maintain

**Cons:**
- Requires CORS configuration on PyPNM
- Frontend must handle PyPNM's request format

**Implementation:**
1. Configure PyPNM to allow CORS from `http://localhost:5050`
2. Update frontend to call `http://127.0.0.1:8000` endpoints
3. Keep Flask backend only for serving static files

### Option 2: Flask Proxy Layer (Current Approach - Needs Fixing)
**Flask backend proxies requests to PyPNM**

**Pros:**
- Can add caching/rate limiting
- Can simplify request format for frontend
- Can aggregate multiple PyPNM calls
- Better for production (single origin)

**Cons:**
- Extra complexity
- Potential performance overhead
- Need to keep proxy updated with PyPNM API changes

**Implementation:**
1. Flask receives simplified requests from frontend
2. Flask transforms to PyPNM format
3. Flask forwards to PyPNM API
4. Flask returns response to frontend

### Option 3: Integrate Remote Agent INTO PyPNM (Advanced)
**Add the remote agent WebSocket support directly to PyPNM source**

**This is what the `pypnm_integration/` files are for!**

**Implementation:**
1. Clone PyPNM repository
2. Copy files to PyPNM:
   - `pypnm_integration/transport/` → `PyPNM/src/pypnm/transport/`
   - `pypnm_integration/api/agent_router.py` → `PyPNM/src/pypnm/api/routers/`
3. Modify PyPNM's `main.py` to include agent router
4. Run modified PyPNM

## Recommended Implementation

### Phase 1: Quick Start (Use PyPNM as-is)
1. Install PyPNM separately following official docs
2. Start PyPNM server: `./scripts/pypnm-cli.sh start`
3. Update Web GUI frontend to call PyPNM API at `http://127.0.0.1:8000`
4. Keep Flask backend minimal (just serve static files + CMTS provider)

### Phase 2: Add Remote Agent (If Needed)
1. Only if you need remote agent functionality
2. Follow `pypnm_integration/README.md` to add agent support to PyPNM
3. Deploy agents on jump servers
4. Agents connect to PyPNM WebSocket endpoint

### Phase 3: Polish
1. Add authentication
2. Add caching layer in Flask
3. Improve error handling
4. Add monitoring/logging

## What Needs to be Fixed in This Project

### 1. Remove Duplicate API Routes
The current `backend/app/routes/api_routes.py` tries to implement PyPNM functionality. This should be removed or converted to a simple proxy.

### 2. Update README
Document that PyPNM must be installed and running separately.

### 3. Update Frontend
Change API calls from `/api/modem/...` to `http://127.0.0.1:8000/system/...` (PyPNM endpoints).

### 4. Configuration
Add PyPNM server URL to configuration:
```python
# backend/app/core/config.py
PYPNM_BASE_URL = os.environ.get('PYPNM_BASE_URL', 'http://127.0.0.1:8000')
```

### 5. Remove Mock Data
The mock data in `backend/app/models/mock_data.py` should be removed since PyPNM provides real data.

## Quick Start Guide (Updated)

### Prerequisites
1. Python 3.10+
2. PyPNM installed and running

### Installation

#### 1. Install PyPNM
```bash
# In a separate directory
git clone https://github.com/PyPNMApps/PyPNM.git
cd PyPNM
./install.sh
./scripts/pypnm-cli.sh start
# Verify: http://127.0.0.1:8000/docs
```

#### 2. Install Web GUI
```bash
cd /Users/silvester/PythonDev/Git/PyPNMGui
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

#### 3. Configure
```bash
# Create .env file
cat > .env << EOF
PYPNM_BASE_URL=http://127.0.0.1:8000
FLASK_PORT=5050
EOF
```

#### 4. Run Web GUI
```bash
./start.sh
# Open: http://localhost:5050
```

## Directory Structure (Cleaned Up)

```
PyPNMGui/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── core/
│   │   │   ├── config.py           # Configuration
│   │   │   ├── pypnm_client.py     # NEW: PyPNM API client
│   │   │   └── cmts_provider.py    # CMTS list provider (from appdb)
│   │   └── routes/
│   │       ├── main_routes.py      # Serve frontend
│   │       └── api_routes.py       # REFACTOR: Proxy to PyPNM
│   ├── run.py
│   └── requirements.txt
├── frontend/
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js              # REFACTOR: Call PyPNM endpoints
├── agent/                          # Optional: Remote agent
│   └── ... (for jump server deployment)
├── pypnm_integration/              # Reference: How to integrate into PyPNM
│   ├── README.md
│   └── ... (files to copy to PyPNM source)
├── docs/
│   └── ... (documentation)
├── README.md
├── INTEGRATION_PLAN.md             # This file
└── start.sh
```

## Next Steps

1. **Read this document carefully**
2. **Install PyPNM** following official docs
3. **Start PyPNM server** and verify it's working
4. **Update Web GUI** to call PyPNM API (not duplicate it)
5. **Test integration** with real cable modem

## Resources

- PyPNM Docs: https://www.pypnm.io/
- PyPNM GitHub: https://github.com/PyPNMApps/PyPNM
- PyPNM API Reference: https://www.pypnm.io/api/
- PyPNM Installation: https://www.pypnm.io/docker/install/
