# GUI Session Testing

Automated browser testing for the PyPNM GUI that emulates a real user session.

## Quick Start

```bash
# Install dependencies (first time only)
pip install playwright
playwright install chromium

# Run quick check (fast CMTS validation)
./test_gui_session.sh quick

# Run full session test (UTSC live monitoring)
./test_gui_session.sh full

# Test against remote lab server
./test_gui_session.sh remote
```

## What It Tests

### Quick Mode (`quick`)
- GUI loads successfully
- CMTS list populates
- Takes ~5 seconds

### Full Mode (`full`)
1. âœ… GUI loads
2. âœ… CMTS dropdown populated
3. âœ… Select CMTS
4. âœ… Get live modems (SNMP walk)
5. âœ… Select first modem
6. âœ… Switch to Upstream tab
7. âœ… Auto-discover RF port
8. âœ… Configure UTSC parameters (50 MHz center, 80 MHz span, 800 bins)
9. âœ… Start live monitoring (enable checkbox)
10. âœ… Verify WebSocket connection
11. âœ… Monitor for 60 seconds
12. âœ… Verify spectrum data streaming
13. âœ… Stop monitoring

Takes ~2-3 minutes.

### Remote Mode (`remote### Remote Mode (`remote### Remote Mode (`remote### Remote Mode (`remote### Rab ### Remote Mans up tunne### Remote Mode (`remote### Remote M provides real-time progress### Remote Mode (`remotowser.### Remote Mode (`remote### Remoteost:505### Remote Mode (`remotelecti### Remote Mode (`remote### Remote Mode (`rem
ğğğğğğğğğğğğğğğğğğğodems...
âœ… Found 12 modems
ğŸ–±ï¸ SelectğŸ–±ï¸ SelectğŸ–±ï¸ Sellected modem: fc:01:7c:bf:73:e3
âš™ï¸ Configuring UTSC parameters...
ğŸ¬ Starting UTSC live monitğŸ¬ ...
â³ Monitoring for 60 seconds...
âœ… Spectrum data being displayed
â±ï¸ 10s / 60s - âœ… Streaming
â±ï¸ 20s / 60s - âœ… Streaming
...
â¹ï¸ Stopping live monitoring...
========================================================================================================================================================================================================== s========================t_sessi=====================================r =================r inspection
- Set `headless=False` in script to watch test execution

## CI/CD Integration

```bash
# In your CI pipeline
./test_gui_session.sh full
if [ $? -eq 0 ]; then
  echo "GUI tests passed"
else
  echo "GUI tests failed"
  exit 1
fi
```

## Troubleshooting

**"No CMTS systems found"**
- Check GUI is running: `curl http://localhost:5050`
- Verify LAB_MODE: Check `docker logs pypnm-gui-lab | grep "LAB MODE"`

**"No modems found"**
- SNMP community may be wrong
- CMTS may have no online modems
- Check agent connection: `docker logs pypnm-agent-lab | tail`

**"WebSocket connection failed"**
- Check GUI logs: `docker logs pypnm-gui-lab | grep WebSocket`
- Verify agent is connected

**"No data received"**
- Check PyPNM API: `curl http://localhost:8000/docs`
- Verify TFTP files: `ls -lt /var/lib/tftpboot/ | head`
- Check backend logs for errors
