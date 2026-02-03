# PyPNM Web GUI - Mock Data Provider
# SPDX-License-Identifier: Apache-2.0
# Based on PyPNM API response structures

import random
from datetime import datetime, timedelta
from typing import Any


class MockDataProvider:
    """Provides mock data simulating PyPNM API responses."""
    
    # Sample cable modems database
    CABLE_MODEMS = [
        {
            "mac_address": "aa:bb:cc:dd:ee:01",
            "ip_address": "192.168.100.10",
            "name": "CM-Residential-01",
            "cmts": "CMTS-CORE-01",
            "cmts_interface": "Cable1/0/0",
            "docsis_version": "3.1",
            "vendor": "ARRIS",
            "model": "CM8200",
            "status": "online"
        },
        {
            "mac_address": "aa:bb:cc:dd:ee:02",
            "ip_address": "192.168.100.11",
            "name": "CM-Residential-02",
            "cmts": "CMTS-CORE-01",
            "cmts_interface": "Cable1/0/0",
            "docsis_version": "3.1",
            "vendor": "Technicolor",
            "model": "TC4400",
            "status": "online"
        },
        {
            "mac_address": "aa:bb:cc:dd:ee:03",
            "ip_address": "192.168.100.12",
            "name": "CM-Business-01",
            "cmts": "CMTS-CORE-01",
            "cmts_interface": "Cable1/0/1",
            "docsis_version": "3.1",
            "vendor": "Netgear",
            "model": "CM1200",
            "status": "online"
        },
        {
            "mac_address": "aa:bb:cc:dd:ee:04",
            "ip_address": "192.168.100.13",
            "name": "CM-Residential-03",
            "cmts": "CMTS-CORE-02",
            "cmts_interface": "Cable2/0/0",
            "docsis_version": "3.0",
            "vendor": "Motorola",
            "model": "SB6183",
            "status": "offline"
        },
        {
            "mac_address": "aa:bb:cc:dd:ee:05",
            "ip_address": "192.168.100.14",
            "name": "CM-Business-02",
            "cmts": "CMTS-CORE-02",
            "cmts_interface": "Cable2/0/1",
            "docsis_version": "4.0",
            "vendor": "ARRIS",
            "model": "S33",
            "status": "online"
        },
        {
            "mac_address": "aa:bb:cc:dd:ee:06",
            "ip_address": "192.168.100.15",
            "name": "CM-Residential-04",
            "cmts": "CMTS-EDGE-01",
            "cmts_interface": "Cable3/0/0",
            "docsis_version": "3.1",
            "vendor": "Hitron",
            "model": "CODA-4582",
            "status": "online"
        }
    ]
    
    CMTS_LIST = [
        {
            "name": "CMTS-CORE-01",
            "ip": "10.0.0.1",
            "interfaces": ["Cable1/0/0", "Cable1/0/1", "Cable1/0/2", "Cable1/0/3"],
            "location": "Datacenter A"
        },
        {
            "name": "CMTS-CORE-02",
            "ip": "10.0.0.2",
            "interfaces": ["Cable2/0/0", "Cable2/0/1", "Cable2/0/2"],
            "location": "Datacenter A"
        },
        {
            "name": "CMTS-EDGE-01",
            "ip": "10.0.1.1",
            "interfaces": ["Cable3/0/0", "Cable3/0/1"],
            "location": "Hub Site B"
        }
    ]
    
    @classmethod
    def get_cable_modems(cls, 
                         search_type: str = None, 
                         search_value: str = None,
                         cmts: str = None,
                         interface: str = None) -> list[dict]:
        """Get cable modems with optional filtering."""
        modems = cls.CABLE_MODEMS.copy()
        
        if search_type and search_value:
            search_value = search_value.lower()
            if search_type == 'ip':
                modems = [m for m in modems if search_value in m['ip_address'].lower()]
            elif search_type == 'mac':
                modems = [m for m in modems if search_value in m['mac_address'].lower().replace(':', '')]
            elif search_type == 'name':
                modems = [m for m in modems if search_value in m['name'].lower()]
        
        if cmts:
            modems = [m for m in modems if m['cmts'] == cmts]
            
        if interface:
            modems = [m for m in modems if m['cmts_interface'] == interface]
            
        return modems
    
    @classmethod
    def get_modem_by_mac(cls, mac_address: str) -> dict | None:
        """Get a specific modem by MAC address."""
        mac_normalized = mac_address.lower().replace('-', ':')
        for modem in cls.CABLE_MODEMS:
            if modem['mac_address'].lower() == mac_normalized:
                return modem
        return None
    
    @classmethod
    def get_modem_by_ip(cls, ip_address: str) -> dict | None:
        """Get a specific modem by IP address."""
        for modem in cls.CABLE_MODEMS:
            if modem['ip_address'] == ip_address:
                return modem
        return None
    
    @classmethod
    def get_cmts_list(cls) -> list[dict]:
        """Get list of CMTS devices."""
        return cls.CMTS_LIST.copy()
    
    @classmethod
    def get_system_info(cls, mac_address: str) -> dict:
        """Simulate /system/sysDescr response."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        uptime_seconds = random.randint(86400, 86400 * 30)  # 1-30 days
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "sysDescr": f"<<{modem['vendor']}>> {modem['model']} DOCSIS {modem['docsis_version']} Cable Modem",
                "vendor": modem['vendor'],
                "model": modem['model'],
                "hardware_version": "1.0",
                "software_version": "10.2.1.1234567",
                "boot_version": "2.5.0",
                "docsis_version": modem['docsis_version'],
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": cls._format_uptime(uptime_seconds)
            }
        }
    
    @classmethod
    def get_uptime(cls, mac_address: str) -> dict:
        """Simulate /system/upTime response."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        uptime_seconds = random.randint(86400, 86400 * 30)
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "uptime_ticks": uptime_seconds * 100,
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": cls._format_uptime(uptime_seconds)
            }
        }
    
    @classmethod
    def get_ds_channel_stats(cls, mac_address: str) -> dict:
        """Simulate downstream OFDM channel statistics."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        channels = []
        num_channels = random.randint(1, 2)  # 1-2 OFDM channels
        
        for i in range(num_channels):
            channel_id = 159 + i
            channels.append({
                "channel_id": channel_id,
                "frequency_start_hz": 258000000 + (i * 192000000),
                "frequency_end_hz": 450000000 + (i * 192000000),
                "plc_frequency_hz": 354000000 + (i * 192000000),
                "active_subcarriers": random.randint(3700, 3800),
                "modulation": "4096-QAM",
                "power_dbmv": round(random.uniform(-5, 10), 1),
                "snr_db": round(random.uniform(35, 42), 1),
                "mer_db": round(random.uniform(38, 45), 1)
            })
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "downstream_ofdm_channels": channels
            }
        }
    
    @classmethod
    def get_us_channel_stats(cls, mac_address: str) -> dict:
        """Simulate upstream OFDMA channel statistics."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        channels = []
        num_channels = random.randint(1, 2)
        
        for i in range(num_channels):
            channel_id = 33 + i
            channels.append({
                "channel_id": channel_id,
                "frequency_start_hz": 10400000 + (i * 48000000),
                "frequency_end_hz": 58400000 + (i * 48000000),
                "active_subcarriers": random.randint(1900, 2000),
                "modulation": "256-QAM",
                "power_dbmv": round(random.uniform(35, 48), 1),
                "timing_offset": random.randint(-100, 100)
            })
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "upstream_ofdma_channels": channels
            }
        }
    
    @classmethod
    def get_rxmer_measurement(cls, mac_address: str, channel_ids: list = None) -> dict:
        """Simulate RxMER measurement data."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        if not channel_ids:
            channel_ids = [159]
        
        measurements = []
        for channel_id in channel_ids:
            # Generate RxMER per subcarrier (simplified - just averages per segment)
            num_subcarriers = 3800
            subcarrier_data = []
            
            for sc in range(0, num_subcarriers, 100):  # Sample every 100th
                mer = round(random.gauss(40, 2), 1)  # Average 40 dB with std dev 2
                subcarrier_data.append({
                    "subcarrier_index": sc,
                    "mer_db": max(20, min(50, mer))  # Clamp between 20-50
                })
            
            measurements.append({
                "channel_id": channel_id,
                "average_mer_db": round(random.uniform(38, 42), 2),
                "min_mer_db": round(random.uniform(32, 36), 2),
                "max_mer_db": round(random.uniform(44, 48), 2),
                "std_dev_mer_db": round(random.uniform(1, 3), 2),
                "subcarrier_count": num_subcarriers,
                "subcarrier_samples": subcarrier_data
            })
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "rxmer_measurements": measurements
            }
        }
    
    @classmethod
    def get_spectrum_analysis(cls, mac_address: str) -> dict:
        """Simulate spectrum analysis data."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        # Generate spectrum data points
        spectrum_data = []
        start_freq = 5000000  # 5 MHz
        end_freq = 1218000000  # 1218 MHz
        step = 1000000  # 1 MHz steps
        
        for freq in range(start_freq, end_freq, step):
            # Simulate typical cable spectrum with carriers
            amplitude = -50  # Base noise floor
            
            # Add some carriers at typical frequencies
            if 54000000 <= freq <= 860000000:  # Downstream range
                if freq % 6000000 < 1000000:  # SC-QAM carriers every 6 MHz
                    amplitude = random.uniform(-10, 5)
                else:
                    amplitude = random.uniform(-45, -35)
            elif 5000000 <= freq <= 42000000:  # Upstream range
                if freq % 3200000 < 1000000:
                    amplitude = random.uniform(35, 50)
                else:
                    amplitude = random.uniform(-50, -40)
            
            spectrum_data.append({
                "frequency_hz": freq,
                "amplitude_dbmv": round(amplitude, 1)
            })
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "start_frequency_hz": start_freq,
                "end_frequency_hz": end_freq,
                "resolution_hz": step,
                "spectrum_points": spectrum_data[:200]  # Limit for demo
            }
        }
    
    @classmethod
    def get_event_log(cls, mac_address: str) -> dict:
        """Simulate modem event log."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        event_types = [
            ("notice", "DHCP RENEW SUCCESS"),
            ("notice", "Time of day set from NTP"),
            ("warning", "No Ranging Response received"),
            ("notice", "Ranging Successful"),
            ("error", "T3 timeout"),
            ("notice", "DOCSIS 3.1 Registration Complete"),
            ("warning", "MDD message lost"),
            ("notice", "REG-RSP-MP Complete"),
            ("critical", "No UCD from CMTS"),
            ("notice", "Downstream Channel Acquisition")
        ]
        
        events = []
        base_time = datetime.now()
        
        for i in range(15):
            event = random.choice(event_types)
            event_time = base_time - timedelta(hours=random.randint(0, 72))
            events.append({
                "event_id": 1000 + i,
                "timestamp": event_time.isoformat(),
                "level": event[0],
                "message": event[1],
                "priority": random.randint(1, 7)
            })
        
        # Sort by timestamp descending
        events.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "events": events
            }
        }
    
    @classmethod
    def get_interface_stats(cls, mac_address: str) -> dict:
        """Simulate interface statistics."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        interfaces = [
            {
                "if_index": 1,
                "if_type": "docsCableMaclayer",
                "if_descr": "DOCSIS Cable MAC Layer",
                "if_oper_status": "up",
                "in_octets": random.randint(1000000000, 9999999999),
                "out_octets": random.randint(100000000, 999999999),
                "in_errors": random.randint(0, 100),
                "out_errors": random.randint(0, 50)
            },
            {
                "if_index": 9,
                "if_type": "docsOfdmDownstream",
                "if_descr": "OFDM Downstream Channel",
                "if_oper_status": "up",
                "in_octets": random.randint(1000000000, 9999999999),
                "out_octets": 0,
                "in_errors": random.randint(0, 10),
                "out_errors": 0
            },
            {
                "if_index": 17,
                "if_type": "docsOfdmaUpstream",
                "if_descr": "OFDMA Upstream Channel",
                "if_oper_status": "up",
                "in_octets": 0,
                "out_octets": random.randint(100000000, 999999999),
                "in_errors": 0,
                "out_errors": random.randint(0, 5)
            }
        ]
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "interfaces": interfaces
            }
        }
    
    @classmethod
    def get_fec_summary(cls, mac_address: str) -> dict:
        """Simulate FEC summary statistics."""
        modem = cls.get_modem_by_mac(mac_address)
        if not modem:
            return {"status": "error", "message": "Modem not found"}
        
        return {
            "mac_address": modem['mac_address'],
            "status": "success",
            "data": {
                "channel_id": 159,
                "total_codewords": random.randint(1000000, 9999999),
                "correctable_codewords": random.randint(100, 1000),
                "uncorrectable_codewords": random.randint(0, 10),
                "ber_pre_ldpc": round(random.uniform(1e-6, 1e-4), 8),
                "ber_post_ldpc": round(random.uniform(1e-10, 1e-8), 12)
            }
        }
    
    @classmethod
    def start_multi_rxmer(cls, mac_address: str, config: dict) -> dict:
        """Simulate starting a multi-RxMER capture."""
        import uuid
        operation_id = str(uuid.uuid4())[:8]
        
        return {
            "mac_address": mac_address,
            "status": "success",
            "operation_id": operation_id,
            "message": "Multi-RxMER capture started",
            "config": config
        }
    
    @classmethod
    def get_multi_rxmer_status(cls, operation_id: str) -> dict:
        """Simulate multi-RxMER status check."""
        # Randomly return different states
        states = ["running", "running", "running", "completed"]
        state = random.choice(states)
        
        return {
            "operation_id": operation_id,
            "status": "success",
            "state": state,
            "collected": random.randint(1, 10),
            "time_remaining": random.randint(0, 300) if state == "running" else 0
        }
    
    @staticmethod
    def _format_uptime(seconds: int) -> str:
        """Format uptime seconds to human readable string."""
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"
