"""
LAB Configuration - Direct access to access-engineering.nl
15 CMTS systems for testing via direct SSH port 65001
"""

import os

# Direct SSH access to LAB server
LAB_SSH_HOST = os.environ.get('LAB_SSH_HOST', 'access-engineering.nl')
LAB_SSH_PORT = int(os.environ.get('LAB_SSH_PORT', '65001'))
LAB_SSH_USER = os.environ.get('LAB_SSH_USER', 'svdleer')

# SNMP communities are optional and environment-only. Read and write
# credentials remain independent.
SNMP_COMMUNITY_ARRIS = os.environ.get('SNMP_COMMUNITY_ARRIS')
SNMP_COMMUNITY_CASA = os.environ.get('SNMP_COMMUNITY_CASA')
SNMP_WRITE_COMMUNITY_ARRIS = os.environ.get('SNMP_WRITE_COMMUNITY_ARRIS')
SNMP_WRITE_COMMUNITY_CASA = os.environ.get('SNMP_WRITE_COMMUNITY_CASA')
CM_RW_COMMUNITY = os.environ.get('CM_RW_COMMUNITY')  # Read-write community for modem SNMP SET
SNMP_COMMUNITY_CISCO = os.environ.get('SNMP_COMMUNITY_CISCO')
SNMP_WRITE_COMMUNITY_CISCO = os.environ.get('SNMP_WRITE_COMMUNITY_CISCO')
SNMP_COMMUNITY_COMMSCOPE = os.environ.get('SNMP_COMMUNITY_COMMSCOPE')
SNMP_WRITE_COMMUNITY_COMMSCOPE = os.environ.get('SNMP_WRITE_COMMUNITY_COMMSCOPE')

# Modem SNMP community for direct modem access.
CM_SNMP_COMMUNITY = os.environ.get('CM_SNMP_COMMUNITY')

LAB_CMTS_SYSTEMS = [
    {
        'name': 'asd-gt0003-ccap001',
        'ip': '172.16.2.110',
        'public_ip': '213.51.253.251',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'E6000',
        'vendor': 'Arris',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0003'
    },
    {
        'name': 'asd-gt0003-ccap101',
        'ip': '172.16.2.120',
        'public_ip': '213.51.251.251',
        'snmp_community': SNMP_COMMUNITY_CASA,
        'write_community': SNMP_WRITE_COMMUNITY_CASA,
        'type': 'C100G',
        'vendor': 'Casa',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0003'
    },
    {
        'name': 'asd-gt0003-ccap201',
        'ip': '172.16.2.114',
        'public_ip': '213.51.255.251',
        'snmp_community': SNMP_COMMUNITY_CISCO,
        'write_community': SNMP_WRITE_COMMUNITY_CISCO,
        'type': 'cBR8',
        'vendor': 'Cisco',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0003'
    },
    {
        'name': 'asd-gt0003-ccapv001',
        'ip': '172.16.2.159',
        'snmp_community': SNMP_COMMUNITY_COMMSCOPE,
        'write_community': SNMP_WRITE_COMMUNITY_COMMSCOPE,
        'type': 'EVO',
        'vendor': 'Commscope',
        'ccap_role': 'vCCAP',
        'location': 'LAB-ASD-GT0003'
    },
    {
        'name': 'asd-gt0004-ccap002',
        'ip': '172.16.2.150',
        'public_ip': '213.51.253.252',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'E6000',
        'vendor': 'Arris',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0004'
    },
    {
        'name': 'asd-gt0004-ccap003',
        'ip': '172.16.2.151',
        'public_ip': '213.51.253.253',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'E6000',
        'vendor': 'Arris',
        'ccap_role': 'cCCAP',
        'location': 'LAB-ASD-GT0004'
    },
    {
        'name': 'asd-gt0004-ccap102',
        'ip': '172.16.2.154',
        'public_ip': '213.51.251.252',
        'snmp_community': SNMP_COMMUNITY_CASA,
        'write_community': SNMP_WRITE_COMMUNITY_CASA,
        'type': 'C100G',
        'vendor': 'Casa',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0004'
    },
    {
        'name': 'asd-gt0004-ccap202',
        'ip': '172.16.2.156',
        'public_ip': '213.51.255.252',
        'snmp_community': SNMP_COMMUNITY_CISCO,
        'write_community': SNMP_WRITE_COMMUNITY_CISCO,
        'type': 'cBR8',
        'vendor': 'Cisco',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0004'
    },
    {
        'name': 'asd-gt0004-ccap203',
        'ip': '172.16.2.157',
        'public_ip': '213.51.255.253',
        'snmp_community': SNMP_COMMUNITY_CISCO,
        'write_community': SNMP_WRITE_COMMUNITY_CISCO,
        'type': 'cBR8',
        'vendor': 'Cisco',
        'ccap_role': 'iCCAP',
        'location': 'LAB-ASD-GT0004'
    },
    {
        'name': 'mnd-gt0002-ccap001',
        'ip': '172.16.6.200',
        'public_ip': '213.51.253.250',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'E6000',
        'vendor': 'Arris',
        'ccap_role': 'iCCAP',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap002',
        'ip': '172.16.6.212',
        'public_ip': '213.51.253.254',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'E6000',
        'vendor': 'Arris',
        'ccap_role': 'cCCAP',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap101',
        'ip': '172.16.6.201',
        'public_ip': '213.51.251.254',
        'snmp_community': SNMP_COMMUNITY_CASA,
        'write_community': SNMP_WRITE_COMMUNITY_CASA,
        'type': 'C100G',
        'vendor': 'Casa',
        'ccap_role': 'iCCAP',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap201',
        'ip': '172.16.6.202',
        'public_ip': '213.51.255.254',
        'snmp_community': SNMP_COMMUNITY_CISCO,
        'write_community': SNMP_WRITE_COMMUNITY_CISCO,
        'type': 'cBR8',
        'vendor': 'Cisco',
        'ccap_role': 'iCCAP',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv002',
        'ip': '172.16.6.130',
        'public_ip': '213.51.254.233',
        'snmp_community': SNMP_COMMUNITY_COMMSCOPE,
        'write_community': SNMP_WRITE_COMMUNITY_COMMSCOPE,
        'type': 'EVO',
        'vendor': 'Commscope',
        'ccap_role': 'vCCAP',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv003',
        'ip': '172.16.6.160',
        'public_ip': '213.51.251.253',
        'snmp_community': SNMP_COMMUNITY_COMMSCOPE,
        'write_community': SNMP_WRITE_COMMUNITY_COMMSCOPE,
        'type': 'EVO',
        'vendor': 'Commscope',
        'ccap_role': 'vCCAP',
        'location': 'LAB-ASD-GT0003'
    }
]

# Omit unconfigured or empty credentials from the runtime LAB inventory.
for _cmts in LAB_CMTS_SYSTEMS:
    for _community_key in ('snmp_community', 'write_community'):
        _community_value = _cmts.get(_community_key)
        if _community_value is None or (
            isinstance(_community_value, str) and not _community_value.strip()
        ):
            _cmts.pop(_community_key, None)

# LAB mode - direct SNMP access via SSH to access-engineering.nl
LAB_MODE = True
DIRECT_SSH_ACCESS = True
