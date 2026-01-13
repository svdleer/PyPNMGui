# PyPNM Web GUI

A modern web-based graphical user interface for PyPNM - the Proactive Network Maintenance toolkit for DOCSIS cable modems.

## Features

- 🔍 **Cable Modem Search** - Search by IP, MAC, CMTS, or interface
- 📊 **Real-time Statistics** - View downstream/upstream channel stats
- 🔬 **PNM Measurements** - Run RxMER, Spectrum Analysis, and more
- 📋 **Event Log Viewer** - Browse modem event logs
- 📈 **Data Visualization** - Charts for RxMER and other measurements
- 🎨 **Modern UI** - Bootstrap 5 + Vue.js 3 + SweetAlert2

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

1. Clone or navigate to the repository:
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

4. Run the application:
```bash
# Option 1: Use the start script
./start.sh

# Option 2: Manual start
source venv/bin/activate
cd backend
python run.py
```

5. Open your browser and navigate to:
```
http://localhost:5050
```

## Project Structure

```
PyPNMGui/
├── backend/
│   ├── app/
│   │   ├── __init__.py          # Flask app factory
│   │   ├── core/
│   │   │   └── config.py        # Configuration settings
│   │   ├── models/
│   │   │   └── mock_data.py     # Mock data provider
│   │   └── routes/
│   │       ├── main_routes.py   # Frontend serving
│   │       └── api_routes.py    # API endpoints
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
└── README.md
```

## API Endpoints

### Modem Management
- `GET /api/modems` - List all modems (with filters)
- `GET /api/modems/<mac>` - Get specific modem

### CMTS
- `GET /api/cmts` - List all CMTS devices
- `GET /api/cmts/<name>/interfaces` - Get CMTS interfaces

### System Information
- `POST /api/modem/<mac>/system-info` - Get sysDescr
- `POST /api/modem/<mac>/uptime` - Get uptime

### Channel Statistics
- `POST /api/modem/<mac>/ds-channels` - Downstream OFDM
- `POST /api/modem/<mac>/us-channels` - Upstream OFDMA
- `POST /api/modem/<mac>/interface-stats` - Interface stats

### PNM Measurements
- `POST /api/modem/<mac>/rxmer` - RxMER measurement
- `POST /api/modem/<mac>/spectrum` - Spectrum analysis
- `POST /api/modem/<mac>/fec-summary` - FEC summary
- `POST /api/modem/<mac>/event-log` - Event log

### Multi-RxMER
- `POST /api/multi-rxmer/start` - Start capture
- `GET /api/multi-rxmer/status/<id>` - Check status

## Configuration

Environment variables:
- `PYPNM_API_URL` - PyPNM API base URL (default: http://127.0.0.1:8000)
- `USE_MOCK_DATA` - Use mock data instead of real API (default: True)
- `DEBUG` - Enable debug mode (default: True)

## Technology Stack

- **Backend**: Flask, Flask-CORS
- **Frontend**: Vue.js 3, Bootstrap 5, Chart.js, SweetAlert2
- **API**: RESTful JSON API

## Mock Data

The application includes comprehensive mock data for testing:
- 6 sample cable modems
- 3 CMTS devices with multiple interfaces
- Simulated RxMER, spectrum, and event log data

## License

Apache License 2.0
