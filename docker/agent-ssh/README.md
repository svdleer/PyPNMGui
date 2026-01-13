# Place SSH private keys here
# These files will be mounted into the agent container at /home/pypnm/.ssh/
#
# Required keys depend on your configuration:
#
# 1. id_pypnm_server - For SSH tunnel to PyPNM server (if tunnel enabled)
# 2. id_cm_proxy     - For SSH access to CM Proxy server
# 3. id_cmts         - For SSH access to CMTS
# 4. id_tftp         - For SSH access to TFTP server
#
# Generate keys:
#   ssh-keygen -t ed25519 -f id_cm_proxy -N ''
#
# Deploy public key to target server:
#   ssh-copy-id -i id_cm_proxy.pub user@cm-proxy-server
#
# Then copy the private key here:
#   cp id_cm_proxy ./
#
# IMPORTANT: Set correct permissions
#   chmod 600 id_*
