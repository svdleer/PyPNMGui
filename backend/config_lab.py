"""
LAB Configuration - Direct CMTS access without agent
4 CMTS systems for testing
"""

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

# LAB mode - no agent needed, direct SNMP access
LAB_MODE = True
AGENT_REQUIRED = False
