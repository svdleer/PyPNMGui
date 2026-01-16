# PyPNM OFDM Spectrum Analysis Integration

## Overview

The PyPNM GUI now includes DOCSIS 3.1 OFDM downstream spectrum capture and visualization capabilities. This allows you to:

- Capture RxMER (Receive Modulation Error Ratio) spectrum data from cable modems
- Visualize OFDM subcarrier performance with interactive graphs
- Analyze signal quality across the entire OFDM channel

## Features

✅ **OFDM Channel Discovery** - Automatically detect available OFDM channels on the modem
✅ **RxMER Capture** - Trigger spectrum captures via PyPNM's PNM capabilities  
✅ **Real-time Graphing** - Interactive charts showing MER across all subcarriers
✅ **Multi-modem Support** - Capture from any modem accessible through your agent network
✅ **Cached Results** - Fast retrieval of recent captures via Redis

## Accessing the OFDM Analyzer

Navigate to: **http://appdb-sh:5050/ofdm-spectrum**

Or from your local tunnel: **http://localhost:5050/ofdm-spectrum**

## Usage

### 1. Enter Modem Information
```
MAC Address: 20:b8:2b:53:c5:e8
IP Address:  10.214.157.17
```

### 2. Load Available OFDM Channels
Click **"Refresh Channel List"** to query the modem for DOCSIS 3.1 OFDM channels.

### 3. Trigger Capture
1. Select the OFDM channel from the dropdown
2. Click **"Trigger RxMER Capture"**
3. Wait 10-15 seconds for the capture to complete
4. Click **"Fetch Capture Data"** (or wait for auto-fetch)

### 4. View Spectrum Graph
The RxMER spectrum will display showing:
- **X-axis**: Subcarrier index
- **Y-axis**: MER in dB
- **Line plot**: MER across the entire OFDM channel bandwidth

## API Endpoints

### Trigger Capture
```bash
POST /api/pnm/ofdm/capture/trigger
{
  "modem_ip": "10.214.157.17",
  "mac_address": "20:b8:2b:53:c5:e8",
  "ofdm_channel": 0,
  "filename": "rxmer_capture"
}
```

### Get Capture Status
```bash
GET /api/pnm/ofdm/capture/status/20:b8:2b:53:c5:e8
```

### Get OFDM Channels
```bash
POST /api/pnm/ofdm/channels
{
  "modem_ip": "10.214.157.17",
  "mac_address": "20:b8:2b:53:c5:e8"
}
```

### Get RxMER Data
```bash
GET /api/pnm/ofdm/rxmer/20:b8:2b:53:c5:e8
```

## Architecture

```
Browser → Backend API → PyPNM OfdmCaptureManager → AgentCableModem → 
  AgentSnmpTransport → Backend → WebSocket → Agent → cm_proxy → Modem
```

## PyPNM Integration

The OFDM capture uses PyPNM methods:
- `getDocsIf31CmDsOfdmChanEntry()` - Get OFDM channel list
- `setDocsPnmCmDsOfdmRxMer()` - Trigger RxMER capture
- `getDocsPnmCmDsOfdmRxMerEntry()` - Retrieve capture data

## Requirements

- **DOCSIS 3.1** cable modem
- **PNM capabilities** enabled on modem
- **TFTP server** accessible from modem (for capture file transfer)
- **Redis** for caching capture data

## Troubleshooting

### No OFDM Channels Found
- Modem may be DOCSIS 3.0 only (no OFDM support)
- Check if modem has active OFDM downstream channels

### Capture Times Out
- Ensure TFTP server is configured and accessible
- Check modem PNM capabilities are enabled
- Verify SNMP write community string is correct

### No Data After Capture
- Wait longer (captures can take 15-30 seconds)
- Check backend logs for TFTP/SNMP errors
- Verify Redis is running for data caching

## Example: Test OFDM Capture from CLI

```python
import asyncio
from pypnm_integration.ofdm_capture import get_ofdm_manager

async def test_capture():
    manager = get_ofdm_manager("http://localhost:5050")
    
    # Get OFDM channels
    channels = await manager.get_ofdm_channels(
        mac_address="20:b8:2b:53:c5:e8",
        modem_ip="10.214.157.17"
    )
    print(f"Found {len(channels)} OFDM channels")
    
    # Trigger capture
    result = await manager.trigger_rxmer_capture(
        mac_address="20:b8:2b:53:c5:e8",
        modem_ip="10.214.157.17",
        ofdm_channel=0
    )
    print(f"Capture result: {result}")
    
    # Wait and fetch data
    await asyncio.sleep(15)
    data = await manager.get_rxmer_data(
        mac_address="20:b8:2b:53:c5:e8",
        modem_ip="10.214.157.17"
    )
    print(f"Got {len(data['subcarriers'])} subcarriers")

asyncio.run(test_capture())
```

## Future Enhancements

- [ ] FEC (Forward Error Correction) capture
- [ ] Channel estimation coefficient capture
- [ ] Upstream OFDMA capture
- [ ] Historical capture comparison
- [ ] Export data to CSV/JSON
- [ ] Automated capture scheduling

## References

- [PyPNM OFDM Examples](https://github.com/PyPNMApps/PyPNM/blob/main/docs/examples/cli-fastapi-curl.md#downstream-ofdm-capture-endpoints)
- [DOCSIS 3.1 PNM Specification](https://www.cablelabs.com/specifications/CM-SP-PNMv3.1)
