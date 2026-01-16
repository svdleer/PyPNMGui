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
        'name': 'mnd-gt0002-ccap001',
        'ip': 'mnd-gt0002-ccap001',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Arris',  # ccap0x = Arris E6000
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap002', 
        'ip': 'mnd-gt0002-ccap002',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Arris',  # ccap0x = Arris E6000
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap101',
        'ip': 'mnd-gt0002-ccap101', 
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Casa',  # ccap1x = Casa 100G
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccap201',
        'ip': 'mnd-gt0002-ccap201',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Cisco',  # ccap2xx = Cisco cBR8
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv001',
        'ip': 'mnd-gt0002-ccapv001',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Commscope',  # ccapvxxx = Commscope EVO vCCAP
        'location': 'LAB-MND-GT0002'
    },
    {
        'name': 'mnd-gt0002-ccapv002',
        'ip': 'mnd-gt0002-ccapv002',
        'snmp_community': 'oss1nf0',
        'type': 'CCAP',
        'vendor': 'Commscope',  # ccapvxxx = Commscope EVO vCCAP
        'location': 'LAB-MND-GT0002'
    }
]

# LAB mode - direct SNMP access via SSH to access-engineering.nl
LAB_MODE = True
DIRECT_SSH_ACCESS = True
