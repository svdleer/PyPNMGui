# PyPNM Web GUI - API Routes
# SPDX-License-Identifier: Apache-2.0

import os
import json
import logging
from flask import jsonify, request, current_app
from . import api_bp
from app.core.cmts_provider import CMTSProvider
from app.core.simple_ws import get_simple_agent_manager

# Redis for caching modem data
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    REDIS_TTL = int(os.environ.get('REDIS_TTL', '21600'))  # 6 hour cache
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    print(f"[INFO] Redis cache connected: {REDIS_HOST}:{REDIS_PORT}", flush=True)
except Exception as e:
    REDIS_AVAILABLE = False
    redis_client = None
    print(f"[WARNING] Redis not available: {e}", flush=True)


# Helper function to handle agent task results
def handle_agent_result(result, success_field='success'):
    """Handle agent task result with proper None checking."""
    logger = logging.getLogger(__name__)
    
    if not result:
        logger.warning("Agent task returned None (timeout or no response)")
        return jsonify({"status": "error", "message": "Agent task timeout or no response"}), 504
    
    result_data = result.get('result')
    if not result_data:
        logger.warning(f"Agent task returned empty result: {result}")
        return jsonify({"status": "error", "message": "No result from agent"}), 500
    
    if result_data.get(success_field):
        return jsonify(result_data)
    
    error_msg = result_data.get('error', 'Unknown error')
    logger.warning(f"Agent task failed: {error_msg}")
    return jsonify({"status": "error", "message": error_msg}), 500


# ============== Cable Modem Endpoints ==============

@api_bp.route('/modems', methods=['GET'])
def get_modems():
    """Get list of cable modems - redirects to CMTS modem endpoint."""
    return jsonify({
        "status": "error",
        "message": "Use /api/cmts/<hostname>/modems to get modems from a specific CMTS"
    }), 400


@api_bp.route('/modems/<mac_address>', methods=['GET'])
def get_modem(mac_address):
    """Get a specific modem by MAC address from cache or mock data."""
    # Normalize MAC address
    mac_normalized = mac_address.lower().replace('-', ':')
    
    # Try to find in Redis cache first
    if REDIS_AVAILABLE and redis_client:
        try:
            # Search all modem caches
            keys = redis_client.keys('modems:*')
            for key in keys:
                cached = redis_client.get(key)
                if cached:
                    data = json.loads(cached)
                    modems = data.get('modems', [])
                    for modem in modems:
                        cached_mac = modem.get('mac_address', '').lower().replace('-', ':')
                        if cached_mac == mac_normalized:
                            return jsonify({
                                "status": "success",
                                "modem": modem
                            })
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis search error: {e}")
    
    return jsonify({
        "status": "error",
        "message": "Modem not found in cache. Load modems from CMTS first."
    }), 404


# ============== CMTS Endpoints ==============

@api_bp.route('/cmts', methods=['GET'])
def get_cmts_list():
    """
    Get list of CMTS devices from appdb.
    
    Query params:
        - vendor: Filter by vendor (Arris, Casa, Cisco)
        - type: Filter by type (E6000, C100G, cBR-8)
        - search: Search by hostname, alias, or IP
        - refresh: Force cache refresh (true/false)
    """
    vendor = request.args.get('vendor')
    cmts_type = request.args.get('type')
    search = request.args.get('search')
    refresh = request.args.get('refresh', '').lower() == 'true'
    
    # Get CMTS data (from cache or API)
    if vendor:
        cmts_list = CMTSProvider.get_cmts_by_vendor(vendor)
    elif cmts_type:
        cmts_list = CMTSProvider.get_cmts_by_type(cmts_type)
    elif search:
        cmts_list = CMTSProvider.search_cmts(search)
    else:
        cmts_list = CMTSProvider.get_all_cmts(force_refresh=refresh)
    
    return jsonify({
        "status": "success",
        "count": len(cmts_list),
        "cmts_list": cmts_list,
        "cache_info": CMTSProvider.get_cache_info()
    })


@api_bp.route('/cmts/summary', methods=['GET'])
def get_cmts_summary():
    """Get summary of CMTS systems by vendor and type."""
    return jsonify({
        "status": "success",
        "total": CMTSProvider.get_cmts_count(),
        "by_vendor": CMTSProvider.get_vendors_summary(),
        "by_type": CMTSProvider.get_types_summary(),
        "cache_info": CMTSProvider.get_cache_info()
    })


@api_bp.route('/cmts/<hostname>', methods=['GET'])
def get_cmts_by_hostname(hostname):
    """Get a specific CMTS by hostname."""
    cmts = CMTSProvider.get_cmts_by_hostname(hostname)
    
    if cmts:
        return jsonify({
            "status": "success",
            "cmts": cmts
        })
    else:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{hostname}' not found"
        }), 404


@api_bp.route('/cmts/<cmts_name>/interfaces', methods=['GET'])
def get_cmts_interfaces(cmts_name):
    """Get interfaces for a specific CMTS (placeholder - needs PyPNM integration)."""
    cmts = CMTSProvider.get_cmts_by_hostname(cmts_name)
    
    if cmts:
        # TODO: Integrate with PyPNM to get real interface data
        return jsonify({
            "status": "success",
            "cmts": cmts_name,
            "interfaces": [],
            "message": "Interface discovery requires PyPNM agent connection"
        })
    
    return jsonify({
        "status": "error",
        "message": f"CMTS '{cmts_name}' not found"
    }), 404


# ============== System Information Endpoints ==============

@api_bp.route('/modem/<mac_address>/system-info', methods=['POST'])
def get_system_info(mac_address):
    """Get system information for a modem via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_channel_info',
            params={'mac_address': mac_address, 'modem_ip': modem_ip, 'community': community},
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/uptime', methods=['POST'])
def get_uptime(mac_address):
    """Get uptime for a modem via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        # Query sysUpTime OID
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_get',
            params={'target_ip': modem_ip, 'oid': '1.3.6.1.2.1.1.3.0', 'community': community},
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        if result and result.get('result', {}).get('success'):
            output = result.get('result', {}).get('output', '')
            # Parse uptime from SNMP output
            uptime_ticks = 0
            if 'Timeticks:' in output:
                import re
                match = re.search(r'\((\d+)\)', output)
                if match:
                    uptime_ticks = int(match.group(1))
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "uptime_ticks": uptime_ticks,
                "uptime_seconds": uptime_ticks // 100,
                "uptime_days": uptime_ticks // 100 // 86400
            })
        return jsonify({"status": "error", "message": "Query failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== Channel Statistics Endpoints ==============

@api_bp.route('/modem/<mac_address>/ds-channels', methods=['POST'])
def get_ds_channels(mac_address):
    """Get downstream channel statistics via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_channel_info',
            params={'mac_address': mac_address, 'modem_ip': modem_ip, 'community': community},
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            data = result.get('result')
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "channels": data.get('downstream', [])
            })
        return jsonify({"status": "error", "message": "Query failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/us-channels', methods=['POST'])
def get_us_channels(mac_address):
    """Get upstream channel statistics via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_channel_info',
            params={'mac_address': mac_address, 'modem_ip': modem_ip, 'community': community},
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            data = result.get('result')
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "channels": data.get('upstream', [])
            })
        return jsonify({"status": "error", "message": "Query failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/interface-stats', methods=['POST'])
def get_interface_stats(mac_address):
    """Get interface statistics via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        # Query ifInOctets, ifOutOctets for cable interface
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_walk',
            params={'target_ip': modem_ip, 'oid': '1.3.6.1.2.1.2.2.1', 'community': community},
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify({
                "success": True,
                "mac_address": mac_address,
                "raw_output": result.get('result', {}).get('output', '')
            })
        return jsonify({"status": "error", "message": "Query failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== PNM Measurement Endpoints ==============

@api_bp.route('/modem/<mac_address>/rxmer', methods=['POST'])
def get_rxmer(mac_address):
    """Get RxMER measurement for a modem via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    if not agent_manager:
        return jsonify({"status": "error", "message": "Agent manager not initialized"}), 503
    
    agent = agent_manager.get_agent_for_capability('cm_proxy')
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_rxmer',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Unknown error')}), 500
    except Exception as e:
        logging.getLogger(__name__).error(f"RxMER request failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/spectrum', methods=['POST'])
def get_spectrum(mac_address):
    """Get spectrum analysis data via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_spectrum',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=120
        )
        result = agent_manager.wait_for_task(task_id, timeout=120)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Unknown error')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/fec-summary', methods=['POST'])
def get_fec_summary(mac_address):
    """Get FEC summary statistics via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_fec',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Unknown error')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/pre-eq', methods=['POST'])
def get_pre_eq(mac_address):
    """Get pre-equalization coefficients via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_pre_eq',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Unknown error')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/modem/<mac_address>/channel-info', methods=['POST'])
def get_channel_info(mac_address):
    """Get downstream/upstream channel info via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_channel_info',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Unknown error')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== Event Log Endpoint ==============

@api_bp.route('/modem/<mac_address>/event-log', methods=['POST'])
def get_event_log(mac_address):
    """Get modem event log via agent."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_event_log',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': community
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        if result and result.get('result', {}).get('success'):
            return jsonify(result.get('result'))
        else:
            return jsonify({"status": "error", "message": result.get('result', {}).get('error', 'Query failed')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== Multi-RxMER Endpoints ==============
# TODO: Implement multi-RxMER via agent when needed


# ============== Health Check ==============

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "PyPNM Web GUI",
        "use_mock_data": current_app.config.get('USE_MOCK_DATA', True)
    })


# ============== Agent-Based CMTS Modem Lookup ==============

@api_bp.route('/cmts/<hostname>/modems', methods=['GET'])
def get_cmts_modems(hostname):
    """
    Get list of cable modems from a CMTS via SNMP (through WebSocket agent).
    
    Query params:
        - community: SNMP community string (default: private)
        - limit: Max number of modems to return (default: 100)
    """
    from app.core.simple_ws import get_simple_agent_manager
    
    community = request.args.get('community', 'Z1gg0@LL')
    limit = int(request.args.get('limit', 500))
    
    # Get CMTS IP from our CMTS provider
    cmts = CMTSProvider.get_cmts_by_hostname(hostname)
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{hostname}' not found in inventory"
        }), 404
    
    cmts_ip = cmts.get('IPAddress')
    if not cmts_ip:
        return jsonify({
            "status": "error", 
            "message": f"No IP address for CMTS '{hostname}'"
        }), 400
    
    # Check Redis cache first (unless refresh requested)
    use_cache = request.args.get('refresh', 'false').lower() != 'true'
    cache_key = f"modems:{hostname}:{cmts_ip}"
    
    logging.getLogger(__name__).info(f"Cache check: use_cache={use_cache}, REDIS_AVAILABLE={REDIS_AVAILABLE}, key={cache_key}")
    
    if use_cache and REDIS_AVAILABLE and redis_client:
        try:
            cached = redis_client.get(cache_key)
            logging.getLogger(__name__).info(f"Redis get result: {type(cached)}, len={len(cached) if cached else 0}")
            if cached:
                logging.getLogger(__name__).info(f"Returning cached modems for {hostname}")
                cached_data = json.loads(cached)
                cached_data['cached'] = True
                return jsonify(cached_data)
        except Exception as e:
            logging.getLogger(__name__).warning(f"Redis cache read error: {e}")
    
    # Get agent manager
    agent_manager = get_simple_agent_manager()
    if not agent_manager:
        return jsonify({
            "status": "error",
            "message": "Agent manager not initialized"
        }), 503
    
    # Find an agent with SNMP capability
    agent = agent_manager.get_agent_for_capability('snmp_walk')
    if not agent:
        return jsonify({
            "status": "error",
            "message": "No connected agent with SNMP capability. Deploy an agent first.",
            "hint": "Copy agent files to script3a and run install-script3a.sh"
        }), 503
    
    try:
        # Check if enriched data exists in cache
        # Enrich is enabled by default
        enrich = request.args.get('enrich', 'true').lower() != 'false'
        modem_community = request.args.get('modem_community', 'z1gg0m0n1t0r1ng')
        enriched_cache_key = f"modems_enriched:{hostname}:{cmts_ip}"
        
        # Try enriched cache first if enrich requested
        if enrich and use_cache and REDIS_AVAILABLE and redis_client:
            try:
                enriched_cached = redis_client.get(enriched_cache_key)
                if enriched_cached:
                    logging.getLogger(__name__).info(f"Returning enriched cached modems for {hostname}")
                    cached_data = json.loads(enriched_cached)
                    cached_data['cached'] = True
                    cached_data['enriched'] = True
                    return jsonify(cached_data)
            except Exception as e:
                logging.getLogger(__name__).warning(f"Redis enriched cache read error: {e}")
        
        # Send task to agent - never block on enrichment, do it in background
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='cmts_get_modems',
            params={
                'cmts_ip': cmts_ip,
                'community': community,
                'limit': limit,
                'enrich_modems': False,  # Never enrich inline - too slow
                'modem_community': modem_community
            },
            timeout=300  # 5 min for large CMTS walks
        )
        
        # Wait for result
        result = agent_manager.wait_for_task(task_id, timeout=180)
        
        if result is None:
            return jsonify({
                "status": "error",
                "message": "Task timed out"
            }), 504
        
        if result.get('error'):
            return jsonify({
                "status": "error",
                "message": result.get('error')
            }), 500
        
        task_result = result.get('result', {})
        
        response_data = {
            "status": "success",
            "cmts_hostname": hostname,
            "cmts_ip": cmts_ip,
            "cmts_community": cmts.get('snmp_rw_community', 'Z1gg0Sp3c1@l'),
            "tftp_ip": cmts.get('tftp_ip', cmts_ip),
            "cmts_vendor": cmts.get('Vendor'),
            "cmts_type": cmts.get('Type'),
            "count": task_result.get('count', 0),
            "modems": task_result.get('modems', []),
            "agent_id": agent.agent_id,
            "cached": False,
            "enriched": False
        }
        
        # Cache result in Redis
        if REDIS_AVAILABLE and redis_client and task_result.get('count', 0) > 0:
            try:
                redis_client.setex(cache_key, REDIS_TTL, json.dumps(response_data))
                logging.getLogger(__name__).info(f"Cached {task_result.get('count')} modems for {hostname} (TTL={REDIS_TTL}s)")
            except Exception as e:
                logging.getLogger(__name__).warning(f"Redis cache write error: {e}")
        
        # Start background enrichment if requested - enrich ALL modems in batches
        enrich_agent = agent_manager.get_agent_for_capability('enrich_modems') or agent_manager.get_agent_for_capability('cm_proxy')
        logging.getLogger(__name__).info(f"Enrich check: enrich={enrich}, enrich_agent={enrich_agent is not None}")
        if enrich and enrich_agent:
            import threading
            all_modems = task_result.get('modems', [])
            
            def enrich_background():
                try:
                    batch_size = 200
                    enriched_modems = []
                    
                    # Process all modems in batches
                    for i in range(0, len(all_modems), batch_size):
                        batch = all_modems[i:i+batch_size]
                        batch_num = (i // batch_size) + 1
                        total_batches = (len(all_modems) + batch_size - 1) // batch_size
                        
                        logging.getLogger(__name__).info(f"Enrichment batch {batch_num}/{total_batches}: {len(batch)} modems")
                        
                        enrich_task_id = agent_manager.send_task_sync(
                            agent_id=agent.agent_id,
                            command='enrich_modems',
                            params={
                                'modems': batch,
                                'modem_community': modem_community,
                            },
                            timeout=300
                        )
                        enrich_result = agent_manager.wait_for_task(enrich_task_id, timeout=300)
                        
                        if enrich_result and enrich_result.get('result', {}).get('success'):
                            enriched_modems.extend(enrich_result.get('result', {}).get('modems', []))
                        else:
                            # Keep original batch if enrichment failed
                            enriched_modems.extend(batch)
                    
                    # Update cache with enriched data (same key - replaces original)
                    if enriched_modems and REDIS_AVAILABLE and redis_client:
                        enriched_data = response_data.copy()
                        enriched_data['modems'] = enriched_modems
                        enriched_data['enriched'] = True
                        enriched_data['count'] = len(enriched_modems)
                        redis_client.setex(cache_key, REDIS_TTL, json.dumps(enriched_data))
                        logging.getLogger(__name__).info(f"Enrichment complete: {len(enriched_modems)} modems updated in cache")
                        
                except Exception as e:
                    logging.getLogger(__name__).error(f"Background enrichment failed: {e}")
            
            thread = threading.Thread(target=enrich_background, daemon=True)
            thread.start()
            response_data['enriching'] = True
        
        return jsonify(response_data)
    
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Failed to send task: {str(e)}"
        }), 500


@api_bp.route('/agents', methods=['GET'])
def get_connected_agents():
    """Get list of connected WebSocket agents."""
    from app.core.simple_ws import get_simple_agent_manager
    
    agent_manager = get_simple_agent_manager()
    if not agent_manager:
        return jsonify({
            "status": "success",
            "agents": [],
            "message": "Agent manager not initialized"
        })
    
    agents = agent_manager.get_available_agents()
    
    return jsonify({
        "status": "success",
        "count": len(agents),
        "agents": agents
    })


@api_bp.route('/snmp/set', methods=['POST'])
def snmp_set():
    """Execute SNMP SET via agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    oid = data.get('oid')
    value = data.get('value')
    
    if not all([modem_ip, oid, value]):
        return jsonify({
            "status": "error",
            "message": "modem_ip, oid, and value required"
        }), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('snmp_set') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent with snmp_set capability"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_set',
            params={
                'target_ip': modem_ip,
                'oid': oid,
                'value': value,
                'type': data.get('type', 'i'),
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/snmp/get', methods=['POST'])
def snmp_get():
    """Execute SNMP GET via agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    oid = data.get('oid')
    
    if not all([modem_ip, oid]):
        return jsonify({
            "status": "error",
            "message": "modem_ip and oid required"
        }), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('snmp_get') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent with snmp_get capability"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_get',
            params={
                'target_ip': modem_ip,
                'oid': oid,
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/snmp/walk', methods=['POST'])
def snmp_walk():
    """Execute SNMP WALK via agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    oid = data.get('oid')
    
    if not all([modem_ip, oid]):
        return jsonify({
            "status": "error",
            "message": "modem_ip and oid required"
        }), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('snmp_walk') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent with snmp_walk capability"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_walk',
            params={
                'target_ip': modem_ip,
                'oid': oid,
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/snmp/bulk_get', methods=['POST'])
def snmp_bulk_get():
    """Execute SNMP BULKGET via agent for faster data retrieval."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    oids = data.get('oids', [])
    
    if not modem_ip or not oids:
        return jsonify({"status": "error", "message": "modem_ip and oids required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('snmp_bulk_get') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent with snmp_bulk_get capability"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='snmp_bulk_get',
            params={
                'target_ip': modem_ip,
                'oids': oids,
                'community': data.get('community', 'm0d3m1nf0'),
                'non_repeaters': data.get('non_repeaters', 0),
                'max_repetitions': data.get('max_repetitions', 25)
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== PyPNM OFDM Capture Endpoints ==============

@api_bp.route('/pnm/ofdm/tftp/configure', methods=['POST'])
def configure_ofdm_tftp():
    """Configure modem TFTP destination for PNM captures."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    mac_address = data.get('mac_address')
    tftp_server = data.get('tftp_server', '149.210.167.40')  # vps.serial.nl
    tftp_path = data.get('tftp_path', '')
    
    if not all([modem_ip, mac_address]):
        return jsonify({"status": "error", "message": "modem_ip and mac_address required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('pnm_set_tftp') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available with pnm_set_tftp capability"}), 503
    
    try:
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_set_tftp',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'tftp_server': tftp_server,
                'tftp_path': tftp_path,
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        return handle_agent_result(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@api_bp.route('/pnm/ofdm/capture/trigger', methods=['POST'])
def trigger_ofdm_capture():
    """Trigger OFDM RxMER capture on modem via PyPNM agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    mac_address = data.get('mac_address')
    ofdm_channel = data.get('ofdm_channel', 0)
    filename = data.get('filename', f'rxmer_{mac_address.replace(":", "")}')
    tftp_server = data.get('tftp_server', '149.210.167.40')  # vps.serial.nl
    
    if not all([modem_ip, mac_address]):
        return jsonify({"status": "error", "message": "modem_ip and mac_address required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        # Step 1: Configure TFTP destination first
        tftp_task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_set_tftp',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'tftp_server': tftp_server,
                'tftp_path': '',
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        tftp_result = agent_manager.wait_for_task(tftp_task_id, timeout=30)
        
        if not tftp_result or not tftp_result.get('result', {}).get('success'):
            return jsonify({
                "status": "error", 
                "message": f"Failed to configure TFTP: {tftp_result.get('result', {}).get('error', 'Unknown error')}"
            }), 500
        
        # Step 2: Trigger OFDM capture
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_ofdm_capture',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'ofdm_channel': ofdm_channel,
                'filename': filename,
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=60
        )
        result = agent_manager.wait_for_task(task_id, timeout=60)
        
        if result and result.get('result', {}).get('success'):
            # Store capture status in Redis
            if REDIS_AVAILABLE:
                capture_key = f"pnm:capture:{mac_address}"
                redis_client.setex(capture_key, 600, json.dumps({
                    "modem_ip": modem_ip,
                    "mac_address": mac_address,
                    "ofdm_channel": ofdm_channel,
                    "filename": filename,
                    "status": "completed",
                    "task_id": task_id
                }))
            
            return jsonify({
                "success": True,
                "message": "OFDM capture triggered successfully",
                "mac_address": mac_address,
                "ofdm_channel": ofdm_channel,
                "task_id": task_id
            })
        else:
            error_msg = result.get('result', {}).get('error', 'Unknown error') if result else 'No response from agent'
            return jsonify({"status": "error", "message": error_msg}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/pnm/ofdm/capture/status/<mac_address>', methods=['GET'])
def get_ofdm_capture_status(mac_address):
    """Get OFDM capture status."""
    if not REDIS_AVAILABLE:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    capture_key = f"pnm:capture:{mac_address}"
    data = redis_client.get(capture_key)
    
    if not data:
        return jsonify({"status": "not_found", "message": "No capture found"}), 404
    
    return jsonify(json.loads(data))


@api_bp.route('/pnm/ofdm/channels', methods=['POST'])
def get_ofdm_channels():
    """Get list of OFDM channels for modem via PyPNM agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    data = request.json
    modem_ip = data.get('modem_ip')
    mac_address = data.get('mac_address')
    
    if not all([modem_ip, mac_address]):
        return jsonify({"status": "error", "message": "modem_ip and mac_address required"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        # Query OFDM channels via agent
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_ofdm_channels',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': data.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        
        if result and result.get('result', {}).get('success'):
            channels = result.get('result', {}).get('channels', [])
            return jsonify({
                "success": True,
                "channels": channels
            })
        else:
            # Return empty list if modem doesn't support OFDM
            return jsonify({
                "success": True,
                "channels": [],
                "message": "No OFDM channels found (modem may be DOCSIS 3.0 only)"
            })
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/pnm/ofdm/rxmer/<mac_address>', methods=['GET'])
def get_ofdm_rxmer_data(mac_address):
    """Get OFDM RxMER spectrum data via PyPNM agent."""
    from app.core.simple_ws import get_simple_agent_manager
    
    # Check if we have cached data first
    if REDIS_AVAILABLE:
        data_key = f"pnm:rxmer:{mac_address}"
        cached_data = redis_client.get(data_key)
        if cached_data:
            return jsonify(json.loads(cached_data))
    
    # Need modem_ip from query params or capture status
    modem_ip = request.args.get('modem_ip')
    
    if not modem_ip and REDIS_AVAILABLE:
        # Try to get from capture status
        capture_key = f"pnm:capture:{mac_address}"
        capture_data = redis_client.get(capture_key)
        if capture_data:
            modem_ip = json.loads(capture_data).get('modem_ip')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required (provide as query param)"}), 400
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        return jsonify({"status": "error", "message": "No agent available"}), 503
    
    try:
        # Fetch RxMER data via agent
        task_id = agent_manager.send_task_sync(
            agent_id=agent.agent_id,
            command='pnm_ofdm_rxmer',
            params={
                'mac_address': mac_address,
                'modem_ip': modem_ip,
                'community': request.args.get('community', 'm0d3m1nf0')
            },
            timeout=30
        )
        result = agent_manager.wait_for_task(task_id, timeout=30)
        
        if result and result.get('result', {}).get('success'):
            spectrum_data = result.get('result', {}).get('data', {})
            
            # Cache for 5 minutes
            if REDIS_AVAILABLE and spectrum_data:
                data_key = f"pnm:rxmer:{mac_address}"
                redis_client.setex(data_key, 300, json.dumps(spectrum_data))
            
            return jsonify(spectrum_data)
        else:
            return jsonify({
                "status": "not_found",
                "message": "No RxMER data available yet. Try again in a few seconds."
            }), 404
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== PyPNM API Proxy Routes ==============
# These routes proxy requests to PyPNM FastAPI for PNM operations

@api_bp.route('/pypnm/health', methods=['GET'])
def pypnm_health():
    """Check PyPNM API health."""
    from app.core.pypnm_client import PyPNMClient
    
    client = PyPNMClient()
    try:
        import requests
        response = requests.get(f"{client.config.base_url}/health", timeout=5)
        if response.ok:
            return jsonify({
                "status": "ok",
                "pypnm_url": client.config.base_url,
                "pypnm_healthy": True
            })
        else:
            return jsonify({
                "status": "error",
                "pypnm_url": client.config.base_url,
                "pypnm_healthy": False
            }), 503
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Cannot reach PyPNM: {str(e)}",
            "pypnm_url": client.config.base_url,
            "pypnm_healthy": False
        }), 503


@api_bp.route('/pypnm/modem/<mac_address>/rxmer', methods=['POST'])
def pypnm_rxmer(mac_address):
    """Get RxMER capture via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    import os
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    # Use LAB community in LAB mode, otherwise default
    default_community = 'z1gg0m0n1t0r1ng' if os.environ.get('PYPNM_MODE') == 'lab' else 'm0d3m1nf0'
    community = data.get('community', default_community)
    # Default TFTP IP for lab environment - 172.22.147.18 is the working TFTP server
    tftp_ip = data.get('tftp_ip', os.environ.get('TFTP_IPV4', '172.22.147.18'))
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    if not tftp_ip:
        return jsonify({"status": "error", "message": "TFTP server not configured. Set TFTP_IPV4 environment variable."}), 400
    
    client = PyPNMClient()
    result = client.get_rxmer_capture(mac_address, modem_ip, tftp_ip, community)
    
    # PyPNM returns status: 0 for success
    if result.get('status') != 0:
        return jsonify(result), 500
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/spectrum', methods=['POST'])
def pypnm_spectrum(mac_address):
    """Get spectrum analyzer capture via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    tftp_ip = data.get('tftp_ip', '')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_spectrum_capture(mac_address, modem_ip, tftp_ip, community)
    
    if result.get('status') == 'error':
        return jsonify(result), 500
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/fec', methods=['POST'])
def pypnm_fec(mac_address):
    """Get FEC summary via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    tftp_ip = data.get('tftp_ip', '')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_fec_summary(mac_address, modem_ip, tftp_ip, community)
    
    if result.get('status') == 'error':
        return jsonify(result), 500
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/constellation', methods=['POST'])
def pypnm_constellation(mac_address):
    """Get constellation display via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    tftp_ip = data.get('tftp_ip', '')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_constellation_display(mac_address, modem_ip, tftp_ip, community)
    
    if result.get('status') == 'error':
        return jsonify(result), 500
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/channel-stats', methods=['POST'])
def pypnm_channel_stats(mac_address):
    """Get DOCSIS channel statistics via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    
    # Get all channel stats
    ds_scqam = client.get_ds_scqam_stats(mac_address, modem_ip, community)
    ds_ofdm = client.get_ds_ofdm_stats(mac_address, modem_ip, community)
    us_atdma = client.get_us_atdma_stats(mac_address, modem_ip, community)
    us_ofdma = client.get_us_ofdma_stats(mac_address, modem_ip, community)
    
    return jsonify({
        "mac_address": mac_address,
        "downstream": {
            "scqam": ds_scqam,
            "ofdm": ds_ofdm
        },
        "upstream": {
            "atdma": us_atdma,
            "ofdma": us_ofdma
        }
    })


@api_bp.route('/pypnm/modem/<mac_address>/pre-eq', methods=['POST'])
def pypnm_pre_eq(mac_address):
    """Get pre-equalization data via PyPNM (ATDMA only, no TFTP needed)."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_us_pre_equalization(mac_address, modem_ip, community)
    
    if result.get('status') == 'error':
        return jsonify(result), 500
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/sysdescr', methods=['POST'])
def pypnm_sysdescr(mac_address):
    """Get system description via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    import re
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_sys_descr(mac_address, modem_ip, community)
    
    # PyPNM returns status: 0 for success
    if result.get('status') != 0:
        return jsonify(result), 500
    
    # Check if PyPNM returned empty sysDescr (parsing failed)
    sys_descr = result.get('results', {}).get('sysDescr', {})
    if sys_descr.get('_is_empty', True):
        # Try direct SNMP query as fallback
        try:
            from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((modem_ip, 161), timeout=2, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))
            )
            errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
            
            if not errorIndication and not errorStatus and varBinds:
                raw_sysdescr = str(varBinds[0][1])
                # Parse the <<...>> format ourselves
                pattern = re.compile(r'<<\s*(.*?)\s*>>')
                match = pattern.search(raw_sysdescr)
                if match:
                    content = match.group(1)
                    entries = [item.strip() for item in content.split(';') if item.strip()]
                    parsed = {}
                    for entry in entries:
                        if ':' in entry:
                            key, val = [part.strip() for part in entry.split(':', 1)]
                            parsed[key] = val
                    
                    result['results']['sysDescr'] = {
                        'hw_rev': parsed.get('HW_REV', ''),
                        'vendor': parsed.get('VENDOR', ''),
                        'boot_rev': parsed.get('BOOTR', ''),
                        'sw_rev': parsed.get('SW_REV', ''),
                        'model': parsed.get('MODEL', ''),
                        '_is_empty': False,
                        '_raw': raw_sysdescr
                    }
        except Exception as e:
            logging.getLogger(__name__).warning(f"Fallback SNMP sysDescr failed: {e}")
    
    return jsonify(result)


@api_bp.route('/pypnm/modem/<mac_address>/event-log', methods=['POST'])
def pypnm_event_log(mac_address):
    """Get event log via PyPNM."""
    from app.core.pypnm_client import PyPNMClient
    
    data = request.get_json() or {}
    modem_ip = data.get('modem_ip')
    community = data.get('community', 'm0d3m1nf0')
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    client = PyPNMClient()
    result = client.get_event_log(mac_address, modem_ip, community)
    
    # PyPNM returns status: 0 for success
    if result.get('status') != 0:
        return jsonify(result), 500
    return jsonify(result)
