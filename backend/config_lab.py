"""
LAB Configuration - Direct access to access-engineering.nl
4 CMTS systems for testing via direct SSH port 65001
"""

# Direct SSH access to LAB server
LAB_SSH_HOST = 'access-engineering.nl'
LAB_SSH_PORT = 65001
LAB_SSH_USER = 'svdleer'  # Current user has direct access

LAB_CMTS_SYSTEMS = [
    {
        'name': 'GV-LC0001-CCAP001',
        'ip': '172.16.19.11',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'location': 'LAB-LC0001'
    },
    {
        'name': 'GV-LC0002-CCAP001', 
        'ip': '172.16.19.12',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'location': 'LAB-LC0002'
    },
    {
        'name': 'GV-LC0003-CCAP001',
        'ip': '172.16.19.13', 
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'location': 'LAB-LC0003'
    },
    {
        'name': 'GV-LC0004-CCAP001',
        'ip': '172.16.19.14',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'location': 'LAB-LC0004'
    }
]

# LAB mode - direct SNMP access via SSH to access-engineering.nl
LAB_MODE = True
DIRECT_SSH_ACCESS = True
