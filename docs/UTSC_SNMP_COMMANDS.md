# UTSC SNMP Commands Reference

## Community Strings
- **Read**: `Z1gg0@LL`
- **Write**: `Z1gg0Sp3c1@l`

## Targets
- **Lab Casa**: `172.16.6.160`
- **Production Casa**: `172.28.51.60`

---

## 1. Verify Device Type (System Detection)

**Get system description to detect vendor (Casa vs EVO)**
```bash
snmpget -v2c -c Z1gg0@LL 172.16.6.160 1.3.6.1.2.1.1.1.0
```

---

## 2. Discover RF Port Interfaces

**Get interface descriptions to identify RPHY RF ports**
```bash
snmpwalk -v2c -c Z1gg0@LL 172.16.6.160 1.3.6.1.2.1.2.2.1.2
```

---

## 3. List Existing UTSC Configuration Rows

**Get current UTSC trigger mode (field .3) to find existing rows**
```bash
snmpwalk -v2c -c Z1gg0@LL 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.3
```

---

## 4. Destroy Old UTSC Configuration (Optional)

**Set RowStatus to destroy (6) to clean up old row**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1 i 6
```

---

## 5. Create New UTSC Configuration Row

**Create row using "create and go" (RowStatus = 4)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1 i 4
```

---

## 6. Set Trigger Mode

**Set to FreeRunning (2) - Casa/EVO may reject this**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.3.{RF_PORT}.1 i 2
```

**Or set to IdleSID (5) - Casa/EVO default**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.3.{RF_PORT}.1 i 5
```

---

## 7. Set Center Frequency (Hz)

**Set to 42.5 MHz (42,500,000 Hz)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.8.{RF_PORT}.1 u 42500000
```

---

## 8. Set Frequency Span (Hz)

**Set to 85 MHz (85,000,000 Hz)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.9.{RF_PORT}.1 u 85000000
```

---

## 9. Set FFT Bin Count

**Set to 3200 bins**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.10.{RF_PORT}.1 u 3200
```

---

## 10. Set Output Format (Optional)

**Set to FFT magnitude (format = 1)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.17.{RF_PORT}.1 i 1
```

---

## 11. Set Window Function (Optional)

**Set to Hamming window (type = 2)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.16.{RF_PORT}.1 i 2
```

---

## 12. Set Free-Run Duration (milliseconds)

**Set to 120 seconds (120,000 ms)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.19.{RF_PORT}.1 u 120000
```

---

## 13. Set Repeat Period (microseconds)

**Set to 400 ms (400,000 µs)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.18.{RF_PORT}.1 u 400000
```

---

## 14. Set Trigger Count

**Set to 10 triggers (ignored in FreeRunning mode)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 x0{RF_PORT}.1 u 10
```

---

## 15. Set Output Filename

**Set capture filename**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.12.{RF_PORT}.1 s "utsc_capture.bin"
```

---

## 16. Set Logical Channel Interface Index

**Set to OFDMA logical channel (160001728 for Casa) - requires notInService state**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{RF_PORT}.1 u 160001728
```

---

## 17. Set BDT Destination Index (Requires notInService)

**Bind to BDT row 1 for TFTP upload**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.24.{RF_PORT}.1 u 1
```

---

## 18. Activate Row (Set RowStatus to Active)

**Activate configuration row (RowStatus = 1)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1 i 1
```

---

## 19. Verify Row is Active

**Get RowStatus to confirm active state**
```bash
snmpget -v2c -c Z1gg0@LL 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1
```

---

## 20. Initiate Test Capture

**Start UTSC capture (InitiateTest = 1)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{RF_PORT}.1 i 1
```

---

## 21. Poll Measurement Status

**Check capture progress (poll until status = 4 or 5)**
```bash
snmpget -v2c -c Z1gg0@LL 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.4.1.1.{RF_PORT}.1
```

**Status values:**
- `1` = other
- `2` = inactive
- `3` = triggered
- `4` = sampleReady (capture complete)
- `5` = error
- `6` = measurementBusy (capturing)
- `7` = sampleTruncated

---

## 22. Stop Test Capture

**Abort UTSC capture (InitiateTest = 2)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.3.1.1.{RF_PORT}.1 i 2
```

---

## BDT (Bulk Data Transfer) Configuration

### Setup TFTP Server Destination

**Set destination IP (Casa)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1.3.1 x "D4 B2 DA EA"
```
*(212.178.218.234 in hex)*

**Set upload path**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1.4.1 s "/"
```

**Set upload control (Casa: autoUpload)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1.5.1 i 3
```

**Set PNM test selector (UTSC bit 8 = 0x0080)**
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.1.1.5.1.6.1 x "00 80"
```

---

## State Machine: notInService Pattern

**When parameters reject write while active, use this pattern:**

1. Set row to notInService (2)
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1 i 2
```

2. Modify parameters (e.g., LogicalChIfIndex)
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.2.{RF_PORT}.1 u 160001728
```

3. Reactivate (1)
```bash
snmpset -v2c -c Z1gg0Sp3c1@l 172.16.6.160 1.3.6.1.4.1.4491.2.1.27.1.3.10.2.1.21.{RF_PORT}.1 i 1
```

---

## Variable Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `{RF_PORT}` | RF port ifIndex | `120001728` (Casa), `40001280` (EVO) |
| `{COMMUNITY_RO}` | Read community | `Z1gg0@LL` |
| `{COMMUNITY_RW}` | Write community | `Z1gg0Sp3c1@l` |
| `{CMTS_IP}` | CMTS management IP | `172.16.6.160` |
| `{TFTP_IP}` | TFTP server IP (hex) | `D4 B2 DA EA` = 212.178.218.234 |

---

## Type Suffixes

- `i` = INTEGER
- `u` = Unsigned INTEGER (Gauge32, Counter32)
- `s` = STRING
- `x` = HEX STRING (MAC, binary data)
- `t` = TIMETICKS
- `d` = DECIMAL STRING
