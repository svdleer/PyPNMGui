"""
LAB Configuration - Direct access to access-engineering.nl
4 CMTS systems for testing via direct SSH port 65001
"""

import os

# Direct SSH access to LAB server
LAB_SSH_HOST = os.environ.get('LAB_SSH_HOST', 'access-engineering.nl')
LAB_SSH_PORT = int(os.environ.get('LAB_SSH_PORT', '65001'))
LAB_SSH_USER = os.environ.get('LAB_SSH_USER', 'svdleer')

# SNMP Communities from environment
SNMP_COMMUNITY_ARRIS = os.environ.get('SNMP_COMMUNITY_ARRIS', 'public')
SNMP_COMMUNITY_CASA = os.environ.get('SNMP_COMMUNITY_CASA', 'public')
SNMP_WRITE_COMMUNITY_ARRIS = os.environ.get('SNMP_WRITE_COMMUNITY_ARRIS', SNMP_COMMUNITY_ARRIS)
SNMP_WRITE_COMMUNITY_CASA = os.environ.get('SNMP_WRITE_COMMUNITY_CASA', SNMP_COMMUNITY_CASA)
CM_RW_COMMUNITY = os.environ.get('CM_RW_COMMUNITY', 'z1gg0m0n1t0r1ng')  # Read-Write community for modem SNMP SET
SNMP_COMMUNITY_CISCO = os.environ.get('SNMP_COMMUNITY_CISCO', 'public')
SNMP_WRITE_COMMUNITY_CISCO = os.environ.get('SNMP_WRITE_COMMUNITY_CISCO', SNMP_COMMUNITY_CISCO)
SNMP_COMMUNITY_COMMSCOPE = os.environ.get('SNMP_COMMUNITY_COMMSCOPE', 'public')
SNMP_WRITE_COMMUNITY_COMMSCOPE = os.environ.get('SNMP_WRITE_COMMUNITY_COMMSCOPE', SNMP_COMMUNITY_COMMSCOPE)

# Modem SNMP communities (for direct modem access requiring SET operations)
CM_SNMP_COMMUNITY = os.environ.get('CM_SNMP_COMMUNITY', 'z1gg0m0n1t0r1ng')

LAB_CMTS_SYSTEMS = [
    {
        'name': 'mnd-gt0002-ccap001',
        'ip': '172.16.6.200',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'CCAP',
        'vendor': 'Arris',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap002', 
        'ip': '172.16.6.212',
        'snmp_community': SNMP_COMMUNITY_ARRIS,
        'write_community': SNMP_WRITE_COMMUNITY_ARRIS,
        'type': 'CCAP',
        'vendor': 'Arris',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap101',
        'ip': '172.16.6.201', 
        'snmp_community': SNMP_COMMUNITY_CASA,
        'write_community': SNMP_WRITE_COMMUNITY_CASA,
        'type': 'CCAP',
        'vendor': 'Casa',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap201',
        'ip': '172.16.6.202',
        'snmp_community': SNMP_COMMUNITY_CISCO,
        'write_community': SNMP_WRITE_COMMUNITY_CISCO,
        'type': 'CCAP',
        'vendor': 'Cisco',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv001',
        'ip': '172.16.6.160',
        'snmp_community': SNMP_COMMUNITY_COMMSCOPE,
        'write_community': SNMP_WRITE_COMMUNITY_COMMSCOPE,
        'type': 'CCAP',
        'vendor': 'Commscope',
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv002',
        'ip': '172.16.6.130',
        'snmp_community': SNMP_COMMUNITY_COMMSCOPE,
        'write_community': SNMP_WRITE_COMMUNITY_COMMSCOPE,
        'type': 'CCAP',
        'vendor': 'Commscope',
        'location': 'LAB-MND-GT0002'
    }
]

# LAB mode - direct SNMP access via SSH to access-engineering.nl
LAB_MODE = True
DIRECT_SSH_ACCESS = True
