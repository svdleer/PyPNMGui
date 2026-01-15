# PyPNM Web GUI - Quick Start Guide

## Prerequisites Check

- [ ] Python 3.10 or higher installed
- [ ] Git installed
- [ ] Network access to cable modems (or Jump Server setup)

## Step 1: Install PyPNM (Required)

PyPNM is the backend server that provides all PNM functionality. It MUST be installed first.

```bash
# Clone PyPNM repository (in a separate directory)
cd ~ # or wherever you want PyPNM installed
git clone https://github.com/PyPNMApps/PyPNM.git
cd PyPNM

# Run the installer
./install.sh

# This will:
# - Create Python virtual environment
# - Install all dependencies
# - Set up configuration
# - May take a few minutes
```

## Step 2: Configure PyPNM (Optional but Recommended)

```bash
cd PyPNM

# Edit configuration
nano src/pypnm/settings/system.json

# Key settings to configure:
# - SNMP community strings
# - TFTP server IP (required for PNM measurements)
# - File storage paths
# - Network timeouts
```

For detailed configuration options, see: https://www.pypnm.io/system/system-config/

## Step 3: Start PyPNM Server

```bash
cd PyPNM
./scripts/pypnm-cli.sh start

# You should see output like:
# INFO:     Started server process
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Verify PyPNM is running:**
```bash
# Open in browser:
open http://127.0.0.1:8000/docs

# Or use curl:
curl http://127.0.0.1:8000/docs
```

You should see PyPNM's Swagger API documentation.

## Step 4: Install Web GUI

```bash
# Navigate to Web GUI project
cd /Users/silvester/PythonDev/Git/PyPNMGui
# Or wherever you cloned it

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r backend/requirements.txt
```

## Step 5: Configure Web GUI (Optional)

```bash
# Set environment variables (optional - defaults work for local setup)
export PYPNM_BASE_URL=http://127.0.0.1:8000  # PyPNM server URL
export FLASK_PORT=5050                        # Web GUI port
```

Or create a `.env` file:
```bash
cat > .env << EOF
PYPNM_BASE_URL=http://127.0.0.1:8000
FLASK_PORT=5050
EOF
```

## Step 6: Start Web GUI

```bash
# Make sure you're in PyPNMGui directory
cd /Users/silvester/PythonDev/Git/PyPNMGui

# Activate virtual environment if not already active
source venv/bin/activate

# Start the server
./start.sh

# Or manually:
cd backend
python run.py
```

You should see:
```
 * Running on http://0.0.0.0:5050
```

## Step 7: Access Web GUI

Open your browser and navigate to:
```
http://localhost:5050
```

## Quick Test

### Test 1: Health Check

```bash
curl http://localhost:5050/api/health
```

Expected response:
```json
{
  "status": "ok",
  "pypnm_connected": true,
  "pypnm_url": "http://127.0.0.1:8000",
  "redis_available": false
}
```

If `pypnm_connected` is `false`, make sure PyPNM is running (Step 3).

### Test 2: Query a Modem

Replace `aa:bb:cc:dd:ee:ff` with actual modem MAC and `192.168.100.10` with actual IP:

```bash
curl -X POST http://localhost:5050/api/modem/aa:bb:cc:dd:ee:ff/system-info \
  -H "Content-Type: application/json" \
  -d '{
    "modem_ip": "192.168.100.10",
    "community": "private"
  }'
```

If modem is reachable, you'll get system description and hardware details.

## Troubleshooting

### PyPNM Not Reachable

**Symptom:** `"pypnm_connected": false` or connection errors

**Solution:**
```bash
# Check if PyPNM is running
curl http://127.0.0.1:8000/docs

# If not running, start it:
cd PyPNM
./scripts/pypnm-cli.sh start

# Check PyPNM logs:
tail -f logs/pypnm.log
```

### Port Already in Use

**Symptom:** `Address already in use: 5050`

**Solution:**
```bash
# Find process using port 5050
lsof -i :5050

# Kill it (replace PID)
kill <PID>

# Or use different port
export FLASK_PORT=5051
./start.sh
```

### TFTP Required Error

**Symptom:** `tftp_ipv4 required for PNM measurements`

**Reason:** PNM measurements need TFTP server for capture files

**Solution:**
1. Set up TFTP server (or use existing one)
2. Configure in PyPNM's `system.json`:
```json
{
  "tftp": {
    "server": "192.168.1.100",
    "directory": "/tftpboot",
    "timeout": 30
  }
}
```
3. See: https://www.pypnm.io/system/pnm-file-retrieval/

### Cannot Reach Cable Modems

**Symptom:** Modem queries timeout or fail

**Options:**

1. **Direct Access** (simplest)
   - Ensure PyPNM server has network access to modems
   - Check firewall rules
   - Verify SNMP community string

2. **Remote Agent** (for isolated networks)
   - Deploy agent on Jump Server that can reach modems
   - See: [agent/README.md](agent/README.md)
   - Agent connects to PyPNM via WebSocket

## Next Steps

1. **Configure TFTP** for PNM measurements
2. **Load CMTS list** (optional, for modem discovery)
3. **Try PNM measurements:**
   - System Info
   - Channel Statistics
   - RxMER Measurement
   - Spectrum Analysis

4. **Read Documentation:**
   - [README.md](README.md) - Full documentation
   - [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) - Architecture details
   - [PROJECT_CLEANUP_SUMMARY.md](PROJECT_CLEANUP_SUMMARY.md) - What was changed

## Development Mode

If you want to modify the code:

```bash
# Terminal 1: PyPNM (with debug logging)
cd PyPNM
export LOG_LEVEL=DEBUG
./scripts/pypnm-cli.sh start

# Terminal 2: Web GUI (with Flask debug mode)
cd PyPNMGui
source venv/bin/activate
export FLASK_DEBUG=1
cd backend
python run.py
```

## Stopping Services

### Stop Web GUI
```bash
# Press Ctrl+C in the terminal where it's running
# Or if running in background:
pkill -f "python run.py"
```

### Stop PyPNM
```bash
cd PyPNM
./scripts/pypnm-cli.sh stop
```

## Resources

- **PyPNM Docs:** https://www.pypnm.io/
- **PyPNM GitHub:** https://github.com/PyPNMApps/PyPNM
- **PyPNM API Reference:** https://www.pypnm.io/api/
- **This Project's Docs:** [README.md](README.md)

## Getting Help

1. **Web GUI Issues:** Create issue in this repository
2. **PyPNM Issues:** https://github.com/PyPNMApps/PyPNM/issues
3. **Integration Questions:** Read [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md)

---

**Remember:** PyPNM is the actual PNM engine. This Web GUI is just a user-friendly interface to it. Both must be running for full functionality.
