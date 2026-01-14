# PyPNM Web GUI - API Routes
# SPDX-License-Identifier: Apache-2.0

import os
import json
import logging
from flask import jsonify, request, current_app
from . import api_bp
from app.models import MockDataProvider
from app.core.cmts_provider import CMTSProvider

# Redis for caching modem data
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    REDIS_TTL = int(os.environ.get('REDIS_TTL', '3600'))  # 60 min cache
    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    logging.getLogger(__name__).info(f"Redis cache connected: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    REDIS_AVAILABLE = False
    redis_client = None
    logging.getLogger(__name__).warning(f"Redis not available: {e}")


# ============== Cable Modem Endpoints ==============

@api_bp.route('/modems', methods=['GET'])
def get_modems():
    """Get list of cable modems with optional filtering."""
    search_type = request.args.get('search_type')
    search_value = request.args.get('search_value')
    cmts = request.args.get('cmts')
    interface = request.args.get('interface')
    
    modems = MockDataProvider.get_cable_modems(
        search_type=search_type,
        search_value=search_value,
        cmts=cmts,
        interface=interface
    )
    
    return jsonify({
        "status": "success",
        "count": len(modems),
        "modems": modems
    })


@api_bp.route('/modems/<mac_address>', methods=['GET'])
def get_modem(mac_address):
    """Get a specific modem by MAC address."""
    modem = MockDataProvider.get_modem_by_mac(mac_address)
    
    if modem:
        return jsonify({
            "status": "success",
            "modem": modem
        })
    else:
        return jsonify({
            "status": "error",
            "message": "Modem not found"
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
    """Get system information for a modem (simulates /system/sysDescr)."""
    data = MockDataProvider.get_system_info(mac_address)
    return jsonify(data)


@api_bp.route('/modem/<mac_address>/uptime', methods=['POST'])
def get_uptime(mac_address):
    """Get uptime for a modem (simulates /system/upTime)."""
    data = MockDataProvider.get_uptime(mac_address)
    return jsonify(data)


# ============== Channel Statistics Endpoints ==============

@api_bp.route('/modem/<mac_address>/ds-channels', methods=['POST'])
def get_ds_channels(mac_address):
    """Get downstream OFDM channel statistics."""
    data = MockDataProvider.get_ds_channel_stats(mac_address)
    return jsonify(data)


@api_bp.route('/modem/<mac_address>/us-channels', methods=['POST'])
def get_us_channels(mac_address):
    """Get upstream OFDMA channel statistics."""
    data = MockDataProvider.get_us_channel_stats(mac_address)
    return jsonify(data)


@api_bp.route('/modem/<mac_address>/interface-stats', methods=['POST'])
def get_interface_stats(mac_address):
    """Get interface statistics."""
    data = MockDataProvider.get_interface_stats(mac_address)
    return jsonify(data)


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
        # Fallback to mock data if no agent
        data = MockDataProvider.get_rxmer_measurement(mac_address, request_data.get('channel_ids', [159]))
        data['mock'] = True
        return jsonify(data)
    
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
        data = MockDataProvider.get_spectrum_analysis(mac_address)
        data['mock'] = True
        return jsonify(data)
    
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
        data = MockDataProvider.get_fec_summary(mac_address)
        data['mock'] = True
        return jsonify(data)
    
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
        data = MockDataProvider.get_event_log(mac_address)
        data['mock'] = True
        return jsonify(data)
    
    agent_manager = get_simple_agent_manager()
    agent = agent_manager.get_agent_for_capability('cm_proxy') if agent_manager else None
    
    if not agent:
        data = MockDataProvider.get_event_log(mac_address)
        data['mock'] = True
        return jsonify(data)
    
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
            data = MockDataProvider.get_event_log(mac_address)
            data['mock'] = True
            return jsonify(data)
    except Exception as e:
        data = MockDataProvider.get_event_log(mac_address)
        data['mock'] = True
        return jsonify(data)


# ============== Multi-RxMER Endpoints ==============

@api_bp.route('/multi-rxmer/start', methods=['POST'])
def start_multi_rxmer():
    """Start a multi-RxMER capture."""
    request_data = request.get_json() or {}
    mac_address = request_data.get('mac_address')
    config = request_data.get('config', {})
    
    if not mac_address:
        return jsonify({
            "status": "error",
            "message": "mac_address is required"
        }), 400
    
    data = MockDataProvider.start_multi_rxmer(mac_address, config)
    return jsonify(data)


@api_bp.route('/multi-rxmer/status/<operation_id>', methods=['GET'])
def get_multi_rxmer_status(operation_id):
    """Get status of a multi-RxMER capture."""
    data = MockDataProvider.get_multi_rxmer_status(operation_id)
    return jsonify(data)


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
        enrich = request.args.get('enrich', 'false').lower() == 'true'
        modem_community = request.args.get('modem_community', 'm0d3m1nf0')
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
        if enrich and agent_manager.get_agent_for_capability('cm_proxy'):
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
