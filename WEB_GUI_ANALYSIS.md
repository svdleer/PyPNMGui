# PyPNM Web GUI Analysis & Architecture Proposal

## Executive Summary

PyPNM is a comprehensive **DOCSIS Proactive Network Maintenance (PNM) toolkit** for analyzing cable modems. It already has:
- ✅ A robust **FastAPI REST API** backend
- ✅ Extensive SNMP operations for cable modems
- ✅ PNM measurement capabilities (RxMER, Spectrum Analysis, Constellation Display, etc.)
- ✅ File management and data processing
- ✅ Support for IP/MAC address based modem identification

## What PyPNM Does

PyPNM is designed to:
1. **Connect to cable modems** via IP address and MAC address
2. **Perform SNMP operations** to retrieve modem statistics and diagnostics
3. **Execute PNM measurements** like:
   - Downstream/Upstream OFDM/OFDMA analysis
   - RxMER (Receive Modulation Error Ratio) measurements
   - Spectrum analysis
   - Constellation displays
   - FEC (Forward Error Correction) summaries
4. **Store and analyze** capture files
5. **Generate reports** and visualizations

---

## Current Architecture

### Backend (Already Implemented)
```
PyPNM/
├── src/pypnm/
│   ├── api/
│   │   ├── main.py                    # FastAPI application
│   │   └── routes/
│   │       ├── system/                # System info endpoints
│   │       ├── docs/                  # DOCSIS endpoints
│   │       │   ├── dev/              # Event logs, reset
│   │       │   ├── if30/             # DOCSIS 3.0
│   │       │   ├── if31/             # DOCSIS 3.1
│   │       │   └── pnm/              # PNM measurements
│   │       │       ├── ds/ofdm/      # Downstream OFDM
│   │       │       ├── us/ofdma/     # Upstream OFDMA
│   │       │       ├── files/        # File management
│   │       │       └── interface/    # Interface stats
│   │       └── advance/
│   │           └── multi_rxmer/      # Multi-RxMER captures
│   ├── docsis/
│   │   └── cable_modem.py            # CableModem class
│   └── lib/
│       ├── inet.py                    # IP address handling
│       └── mac_address.py            # MAC address handling
```

### API Structure
- **Base URL**: `http://127.0.0.1:8000`
- **API Docs**: `/docs` (Swagger UI)
- **Key Endpoints**:
  - `/system/sysDescr` - Get modem system description
  - `/system/upTime` - Get modem uptime
  - `/docs/pnm/ds/ofdm/rxmer/getMeasurement` - Get RxMER measurement
  - `/docs/pnm/spectrumAnalyzer/getCapture` - Spectrum analysis
  - `/docs/pnm/files/query` - Query PNM files
  - `/advance/multi/rxmer/start` - Start multi-RxMER capture
  - `/advance/multi/rxmer/status/{operation_id}` - Check status
  - `/advance/multi/rxmer/analysis` - Analyze results

---

## Proposed Web GUI Architecture

### Technology Stack Recommendation

#### Option 1: Vue.js + Bootstrap (Recommended)
**Pros:**
- Modern, reactive framework
- Excellent for real-time updates (polling modem status)
- Vue 3 Composition API is powerful and clean
- Bootstrap 5 provides professional UI components
- Good ecosystem with Vue Router, Pinia (state management)

**Cons:**
- Requires build process
- Steeper learning curve than vanilla JS

#### Option 2: React + Bootstrap
**Pros:**
- Very popular, large ecosystem
- Excellent for complex UIs
- Strong typing with TypeScript

**Cons:**
- More complex setup
- Larger bundle size

#### Option 3: Vanilla JS + Bootstrap (Simplest)
**Pros:**
- No build process needed
- Easy to understand and deploy
- Fast development for simple UIs

**Cons:**
- More manual DOM manipulation
- Less reactive

### Recommended: **Vue 3 + Bootstrap 5 + Flask** (for serving static files)

---

## Web GUI Feature Specifications

### 1. Cable Modem Selection Interface

#### Search/Filter Options:
```javascript
{
  searchBy: [
    'IP Address',
    'MAC Address', 
    'CMTS Name',
    'CMTS Interface'
  ]
}
```

#### UI Components:
- **Search Bar** with dropdown for search type
- **Advanced Filters Panel**:
  - IP Address (with validation)
  - MAC Address (with auto-formatting: `aa:bb:cc:dd:ee:ff`)
  - CMTS dropdown (pre-populated from config)
  - CMTS Interface dropdown (pre-populated from config)
- **Recent Searches** - Save last 10 searches
- **Favorites** - Bookmark frequently accessed modems

### 2. SNMP Configuration Panel

```javascript
{
  snmpConfig: {
    version: 'v2c',          // or 'v3'
    community: 'private',     // for v2c
    timeout: 5,               // seconds
    retries: 3
  }
}
```

### 3. Dashboard Layout

#### Main Navigation:
- 🏠 **Home** - Modem search & quick status
- 📊 **Live Monitoring** - Real-time stats
- 🔬 **PNM Diagnostics** - Run PNM tests
- 📈 **History** - View past measurements
- 📁 **Files** - Browse capture files
- ⚙️ **Settings** - Configuration

#### Modem Overview Panel (After Selection):
```
┌─────────────────────────────────────────────────┐
│ Cable Modem Information                         │
├─────────────────────────────────────────────────┤
│ MAC Address:    aa:bb:cc:dd:ee:ff              │
│ IP Address:     192.168.100.10                 │
│ Status:         🟢 Online                       │
│ Uptime:         5d 12h 35m                     │
│ System Desc:    ARRIS CM8200...               │
│ DOCSIS Version: 3.1                           │
└─────────────────────────────────────────────────┘
```

### 4. PNM Measurement Operations

#### Quick Actions Panel:
- **📡 Spectrum Analysis** - Capture and analyze RF spectrum
- **📊 RxMER Measurement** - Downstream signal quality
- **🔷 Constellation Display** - Signal constellation
- **📈 Channel Statistics** - US/DS channel info
- **⚡ Multi-RxMER Capture** - Long-term monitoring
- **📋 Event Log** - View modem event log

#### Measurement Request Flow:
```javascript
// Example: RxMER Measurement
{
  cable_modem: {
    mac_address: "aa:bb:cc:dd:ee:ff",
    ip_address: "192.168.100.10",
    snmp: {
      snmpV2C: {
        community: "private"
      }
    },
    pnm_parameters: {
      tftp: {
        ipv4: "192.168.1.100",
        ipv6: ""
      }
    }
  },
  analysis: {
    output: {
      type: "JSON"  // or "ARCHIVE"
    }
  }
}
```

### 5. Real-Time Status Updates

Use **polling** or **WebSockets** for:
- ✅ Modem reachability (ping status)
- 📊 Ongoing measurement progress
- 🔔 Alerts and notifications
- 📈 Live statistics updates

### 6. Results Visualization

#### Charts & Graphs (using Chart.js or Plotly.js):
- **RxMER over frequency**
- **Spectrum amplitude**
- **Channel power levels**
- **MER vs Time** (for multi-capture)

#### Data Tables (using DataTables or AG-Grid):
- **Channel statistics**
- **Event logs**
- **File listings**

---

## Implementation Plan

### Phase 1: Basic Setup ✅
1. Create Flask app structure
2. Set up Vue.js frontend with Vite
3. Configure Bootstrap 5
4. Integrate SweetAlert2 for notifications

### Phase 2: Modem Selection 🎯
1. Build search interface
2. Implement IP/MAC/CMTS filtering
3. Add modem validation (ping/SNMP check)
4. Create modem profile page

### Phase 3: SNMP Operations 📡
1. System information display
2. Basic SNMP queries
3. Error handling with SweetAlert

### Phase 4: PNM Measurements 🔬
1. Implement measurement triggers
2. Progress tracking UI
3. Results display
4. File download functionality

### Phase 5: Advanced Features 🚀
1. Multi-RxMER long-term monitoring
2. Historical data charts
3. Report generation
4. Export functionality

---

## Technical Architecture

### Frontend Structure
```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── main.js
│   ├── App.vue
│   ├── router/
│   │   └── index.js
│   ├── views/
│   │   ├── Home.vue
│   │   ├── ModemDetails.vue
│   │   ├── PnmMeasurements.vue
│   │   ├── Files.vue
│   │   └── Settings.vue
│   ├── components/
│   │   ├── ModemSearch.vue
│   │   ├── ModemInfo.vue
│   │   ├── MeasurementPanel.vue
│   │   ├── StatusIndicator.vue
│   │   └── ChartDisplay.vue
│   ├── services/
│   │   ├── api.js           # Axios API wrapper
│   │   └── modemService.js  # Modem-specific API calls
│   ├── store/
│   │   └── index.js         # Pinia store
│   └── utils/
│       ├── validators.js    # IP/MAC validation
│       └── formatters.js    # Data formatting
└── package.json
```

### Backend Integration (Flask)
```python
# backend/app.py
from flask import Flask, render_template, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

# PyPNM API URL
PYPNM_API = "http://127.0.0.1:8000"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/modem/info', methods=['POST'])
def get_modem_info():
    """Proxy to PyPNM API"""
    data = request.json
    response = requests.post(
        f"{PYPNM_API}/system/sysDescr",
        json=data
    )
    return jsonify(response.json())

# Additional proxy endpoints...
```

---

## UI Component Examples

### 1. Modem Search Component (Vue)
```vue
<template>
  <div class="modem-search">
    <div class="card">
      <div class="card-header">
        <h5>Cable Modem Search</h5>
      </div>
      <div class="card-body">
        <div class="row mb-3">
          <div class="col-md-3">
            <select v-model="searchType" class="form-select">
              <option value="ip">IP Address</option>
              <option value="mac">MAC Address</option>
              <option value="cmts">CMTS</option>
              <option value="interface">CMTS Interface</option>
            </select>
          </div>
          <div class="col-md-7">
            <input 
              v-model="searchValue" 
              type="text" 
              class="form-control"
              :placeholder="placeholder"
              @keyup.enter="searchModem"
            />
          </div>
          <div class="col-md-2">
            <button @click="searchModem" class="btn btn-primary w-100">
              🔍 Search
            </button>
          </div>
        </div>
        
        <!-- SNMP Configuration -->
        <div class="row">
          <div class="col-md-6">
            <label>SNMP Community</label>
            <input v-model="snmpCommunity" type="text" class="form-control" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue';
import { useModemStore } from '@/store/modem';
import Swal from 'sweetalert2';

const modemStore = useModemStore();
const searchType = ref('ip');
const searchValue = ref('');
const snmpCommunity = ref('private');

const placeholder = computed(() => {
  const placeholders = {
    ip: 'e.g., 192.168.100.10',
    mac: 'e.g., aa:bb:cc:dd:ee:ff',
    cmts: 'Select CMTS',
    interface: 'Select Interface'
  };
  return placeholders[searchType.value];
});

const searchModem = async () => {
  if (!searchValue.value) {
    Swal.fire('Error', 'Please enter a search value', 'error');
    return;
  }
  
  try {
    await modemStore.findModem(searchType.value, searchValue.value, snmpCommunity.value);
    Swal.fire('Success', 'Modem found!', 'success');
  } catch (error) {
    Swal.fire('Error', error.message, 'error');
  }
};
</script>
```

### 2. PNM Measurement Panel
```vue
<template>
  <div class="pnm-measurements">
    <h5>PNM Diagnostics</h5>
    <div class="row">
      <div class="col-md-4" v-for="test in pnmTests" :key="test.id">
        <div class="card test-card">
          <div class="card-body text-center">
            <div class="test-icon">{{ test.icon }}</div>
            <h6>{{ test.name }}</h6>
            <p class="small text-muted">{{ test.description }}</p>
            <button 
              @click="runTest(test.id)" 
              class="btn btn-sm btn-primary"
              :disabled="isRunning"
            >
              {{ isRunning ? 'Running...' : 'Start Test' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { usePnmStore } from '@/store/pnm';

const pnmStore = usePnmStore();
const isRunning = ref(false);

const pnmTests = [
  {
    id: 'rxmer',
    name: 'RxMER Measurement',
    icon: '📊',
    description: 'Downstream signal quality analysis'
  },
  {
    id: 'spectrum',
    name: 'Spectrum Analysis',
    icon: '📡',
    description: 'RF spectrum capture and analysis'
  },
  {
    id: 'constellation',
    name: 'Constellation Display',
    icon: '🔷',
    description: 'Signal constellation visualization'
  }
];

const runTest = async (testId) => {
  isRunning.value = true;
  try {
    await pnmStore.runMeasurement(testId);
  } finally {
    isRunning.value = false;
  }
};
</script>
```

---

## API Integration Examples

### Modem Service (JavaScript)
```javascript
// services/modemService.js
import axios from 'axios';

const API_BASE = 'http://127.0.0.1:8000';

export const modemService = {
  async getSystemInfo(macAddress, ipAddress, community = 'private') {
    const response = await axios.post(`${API_BASE}/system/sysDescr`, {
      cable_modem: {
        mac_address: macAddress,
        ip_address: ipAddress,
        snmp: {
          snmpV2C: {
            community: community
          }
        }
      }
    });
    return response.data;
  },

  async getUptime(macAddress, ipAddress, community = 'private') {
    const response = await axios.post(`${API_BASE}/system/upTime`, {
      cable_modem: {
        mac_address: macAddress,
        ip_address: ipAddress,
        snmp: {
          snmpV2C: { community }
        }
      }
    });
    return response.data;
  },

  async runRxMerMeasurement(config) {
    const response = await axios.post(
      `${API_BASE}/docs/pnm/ds/ofdm/rxmer/getMeasurement`,
      config
    );
    return response.data;
  },

  async startMultiRxMer(config) {
    const response = await axios.post(
      `${API_BASE}/advance/multi/rxmer/start`,
      config
    );
    return response.data;
  },

  async checkMultiRxMerStatus(operationId) {
    const response = await axios.get(
      `${API_BASE}/advance/multi/rxmer/status/${operationId}`
    );
    return response.data;
  }
};
```

---

## Configuration Management

### System Configuration (system.json)
```json
{
  "pypnm_api": {
    "base_url": "http://127.0.0.1:8000",
    "timeout": 30
  },
  "default_snmp": {
    "community": "private",
    "version": "v2c",
    "timeout": 5,
    "retries": 3
  },
  "cmts_list": [
    {
      "name": "CMTS-01",
      "ip": "10.0.0.1",
      "interfaces": ["Cable1/0/0", "Cable1/0/1"]
    }
  ],
  "tftp": {
    "ipv4": "192.168.1.100",
    "ipv6": "",
    "path": "/tftpboot"
  }
}
```

---

## Security Considerations

1. **SNMP Community Strings**: Store securely (not in frontend code)
2. **API Authentication**: Implement JWT or session-based auth
3. **CORS**: Configure properly for production
4. **Input Validation**: Validate all IP/MAC addresses
5. **Rate Limiting**: Prevent API abuse

---

## Deployment Options

### Option 1: Docker Container
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/
RUN pip install -r backend/requirements.txt
EXPOSE 5000
CMD ["python", "backend/app.py"]
```

### Option 2: Traditional Deployment
1. Deploy PyPNM API (already running)
2. Deploy Flask app for GUI
3. Configure reverse proxy (nginx)

---

## Next Steps

1. **Set up development environment**
   - Install Node.js, npm
   - Install Python dependencies
   - Clone/create frontend structure

2. **Create basic Flask app**
   - Set up routing
   - Add API proxy endpoints

3. **Build Vue.js frontend**
   - Initialize Vue project with Vite
   - Install Bootstrap, SweetAlert2
   - Create basic layout

4. **Implement core features**
   - Modem search
   - System info display
   - Basic PNM measurements

5. **Add advanced features**
   - Multi-RxMER monitoring
   - File management
   - Historical data

---

## Questions to Consider

1. **CMTS Integration**: Do you have a CMTS database to query for modems?
2. **Authentication**: Do you need user login/authentication?
3. **Multi-user**: Will multiple users access the system simultaneously?
4. **Data Retention**: How long should measurements be stored?
5. **Alerts**: Do you need email/SMS notifications?

---

## Conclusion

PyPNM already has a **solid foundation** with its FastAPI backend. The web GUI will:
- Provide an intuitive interface for modem selection
- Enable easy SNMP operations
- Visualize PNM measurements beautifully
- Support both quick checks and long-term monitoring

The recommended stack (Vue 3 + Bootstrap 5 + Flask) offers the best balance of:
- ✅ Modern, reactive UI
- ✅ Professional design
- ✅ Easy API integration
- ✅ Maintainability

Ready to proceed? I can help you:
1. Generate the initial project structure
2. Create sample Vue components
3. Set up the Flask proxy server
4. Implement specific features

Let me know what you'd like to start with! 🚀
