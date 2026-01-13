# PyPNM Web GUI - Agent API Routes
# SPDX-License-Identifier: Apache-2.0

from flask import jsonify, request, current_app
from . import api_bp

try:
    from app.core.agent_manager import agent_manager
    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False


@api_bp.route('/agents', methods=['GET'])
def get_agents():
    """Get list of connected agents."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Agent support not available"
        }), 501
    
    agents = agent_manager.get_available_agents()
    
    return jsonify({
        "status": "success",
        "count": len(agents),
        "agents": agents
    })


@api_bp.route('/agents/<agent_id>/ping', methods=['POST'])
def ping_via_agent(agent_id):
    """Ping a target IP via specific agent."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error", 
            "message": "Agent support not available"
        }), 501
    
    data = request.get_json() or {}
    target_ip = data.get('target_ip')
    
    if not target_ip:
        return jsonify({
            "status": "error",
            "message": "target_ip is required"
        }), 400
    
    try:
        result = agent_manager.ping_modem(target_ip, agent_id=agent_id)
        return jsonify({
            "status": "success" if result.get('success') else "error",
            "data": result
        })
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@api_bp.route('/agents/<agent_id>/snmp/get', methods=['POST'])
def snmp_get_via_agent(agent_id):
    """Execute SNMP GET via specific agent."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Agent support not available"
        }), 501
    
    data = request.get_json() or {}
    target_ip = data.get('target_ip')
    oid = data.get('oid')
    community = data.get('community', 'private')
    
    if not target_ip or not oid:
        return jsonify({
            "status": "error",
            "message": "target_ip and oid are required"
        }), 400
    
    try:
        result = agent_manager.execute_snmp_get(
            target_ip=target_ip,
            oid=oid,
            community=community,
            agent_id=agent_id
        )
        return jsonify({
            "status": "success" if result.get('success') else "error",
            "data": result
        })
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


@api_bp.route('/agents/<agent_id>/snmp/walk', methods=['POST'])
def snmp_walk_via_agent(agent_id):
    """Execute SNMP WALK via specific agent."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Agent support not available"
        }), 501
    
    data = request.get_json() or {}
    target_ip = data.get('target_ip')
    oid = data.get('oid')
    community = data.get('community', 'private')
    
    if not target_ip or not oid:
        return jsonify({
            "status": "error",
            "message": "target_ip and oid are required"
        }), 400
    
    try:
        result = agent_manager.execute_snmp_walk(
            target_ip=target_ip,
            oid=oid,
            community=community,
            agent_id=agent_id
        )
        return jsonify({
            "status": "success" if result.get('success') else "error",
            "data": result
        })
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# Auto-select agent routes (uses any available agent)

@api_bp.route('/remote/ping', methods=['POST'])
def remote_ping():
    """Ping a target via any available agent."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Agent support not available"
        }), 501
    
    data = request.get_json() or {}
    target_ip = data.get('target_ip')
    
    if not target_ip:
        return jsonify({
            "status": "error",
            "message": "target_ip is required"
        }), 400
    
    result = agent_manager.ping_modem(target_ip)
    return jsonify({
        "status": "success" if result.get('success') else "error",
        "data": result
    })


@api_bp.route('/remote/snmp/get', methods=['POST'])
def remote_snmp_get():
    """Execute SNMP GET via any available agent."""
    if not AGENT_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "Agent support not available"
        }), 501
    
    data = request.get_json() or {}
    target_ip = data.get('target_ip')
    oid = data.get('oid')
    community = data.get('community', 'private')
    
    if not target_ip or not oid:
        return jsonify({
            "status": "error",
            "message": "target_ip and oid are required"
        }), 400
    
    result = agent_manager.execute_snmp_get(
        target_ip=target_ip,
        oid=oid,
        community=community
    )
    return jsonify({
        "status": "success" if result.get('success') else "error",
        "data": result
    })
