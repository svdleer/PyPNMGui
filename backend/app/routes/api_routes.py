# PyPNM Web GUI - API Routes

import os
import json
import logging
from flask import jsonify, request, current_app
from . import api_bp
from app.core.cmts_provider import CMTSProvider
from app.core.pypnm_client import PyPNMClient

logger = logging.getLogger(__name__)

# Default TFTP server (same as pypnm_routes.py)
DEFAULT_TFTP_IP = os.environ.get('TFTP_IPV4', '172.22.147.18')


def get_default_community():
    """Get default SNMP community for modems."""
    return os.environ.get('MODEM_COMMUNITY', os.environ.get('CM_SNMP_COMMUNITY', 'private'))


def get_cmts_community():
    """Get default SNMP community for CMTS operations."""
    return os.environ.get('CMTS_COMMUNITY', os.environ.get('CMTS_SNMP_COMMUNITY', 'public'))


# Redis for caching modem data
try:
    import redis
    REDIS_HOST = os.environ.get('REDIS_HOST', 'eve-li-redis')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    REDIS_TTL = int(os.environ.get('REDIS_TTL', '86400'))  # 24 hour cache
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


@api_bp.route('/cmts/<cmts_name>/modems', methods=['GET'])
def get_cmts_modems(cmts_name):
    """Get modems from a specific CMTS via PyPNM API -> Agent -> SNMP."""
    logger = logging.getLogger(__name__)
    
    # Get CMTS info from provider
    cmts = CMTSProvider.get_cmts_by_hostname(cmts_name)
    if not cmts:
        return jsonify({
            "status": "error",
            "message": f"CMTS '{cmts_name}' not found"
        }), 404
    
    # Get query parameters
    community = request.args.get('community', get_cmts_community())
    limit = int(request.args.get('limit', 10000))
    enrich = request.args.get('enrich', 'true').lower() == 'true'  # Enable enrichment by default
    modem_community = request.args.get('modem_community', get_default_community())
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    try:
        # CMTSProvider returns 'IPAddress' from appdb format
        cmts_ip = cmts.get('IPAddress') or cmts.get('ip') or cmts.get('ip_address')
        
        if not cmts_ip:
            logger.error(f"CMTS {cmts_name} has no IP address: {cmts}")
            return jsonify({
                "status": "error",
                "message": f"CMTS '{cmts_name}' has no IP address configured"
            }), 500
        
        # Check Redis cache first (unless force_refresh)
        if REDIS_AVAILABLE and redis_client and not force_refresh:
            try:
                cache_key = f"modems:{cmts_name}"
                cached = redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    cached_modems = data.get('modems', [])
                    # Stamp cmts_ip/cmts_community onto cached modems in case they're missing
                    for m in cached_modems:
                        if not m.get('cmts_ip'):
                            m['cmts_ip'] = cmts_ip
                            m['cmts_community'] = community
                    logger.info(f"Returning {len(cached_modems)} modems from Redis cache for {cmts_name}")
                    return jsonify({
                        "status": "success",
                        "cmts": cmts_name,
                        "cmts_hostname": cmts_name,
                        "cmts_ip": cmts_ip,
                        "agent_id": "cached",
                        "modems": cached_modems,
                        "count": len(cached_modems),
                        "enriched": True,  # Cached data is already enriched
                        "cached": True,
                        "enriching": False
                    })
            except Exception as e:
                logger.warning(f"Redis cache read error: {e}")
        
        # Call PyPNM API which will route to agent for SNMP
        # Enrichment queries each modem for model/firmware via modem_community
        client = PyPNMClient()
        result = client.get_cmts_modems(
            cmts_ip=cmts_ip,
            community=community,
            limit=limit,
            enrich=enrich,
            modem_community=modem_community
        )
        
        if result.get('success'):
            modems = result.get('modems', [])
            logger.info(f"Retrieved {len(modems)} modems from {cmts_name} via PyPNM API/agent")

            # Stamp cmts_ip and cmts_community onto every modem record so
            # channel-stats and other per-modem endpoints can use them
            for m in modems:
                m['cmts_ip'] = cmts_ip
                m['cmts_community'] = community

            # Only cache in Redis if enrichment is complete (not still in progress)
            is_enriched = result.get('enriched', False)
            is_enriching = result.get('enriching', False)
            
            if REDIS_AVAILABLE and redis_client and is_enriched and not is_enriching:
                try:
                    cache_key = f"modems:{cmts_name}"
                    redis_client.setex(cache_key, REDIS_TTL, json.dumps({
                        "cmts": cmts_name,
                        "modems": modems,
                        "timestamp": result.get('timestamp')
                    }))
                    logger.info(f"Cached {len(modems)} enriched modems for {cmts_name}")
                except Exception as e:
                    logger.warning(f"Redis cache error: {e}")
            
            return jsonify({
                "status": "success",
                "cmts": cmts_name,
                "cmts_hostname": cmts_name,
                "cmts_ip": cmts_ip,
                "agent_id": result.get('agent_id', 'agent'),
                "modems": modems,
                "count": len(modems),
                "enriched": result.get('enriched', False),
                "cached": result.get('cached', False),
                "enriching": result.get('enriching', False)
            })
        else:
            error_msg = result.get('error', 'Unknown error from PyPNM API')
            logger.error(f"PyPNM API error for {cmts_name}: {error_msg}")
            return jsonify({
                "status": "error",
                "message": error_msg
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting modems from {cmts_name}: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============== System Information Endpoints ==============

@api_bp.route('/modem/<mac_address>/system-info', methods=['POST'])
def get_system_info(mac_address):
    """Get system information for a modem via PyPNM API."""
    request_data = request.get_json() or {}
    modem_ip = request_data.get('modem_ip')
    community = request_data.get('community', get_default_community())
    
    if not modem_ip:
        return jsonify({"status": "error", "message": "modem_ip required"}), 400
    
    try:
        # Use PyPNM API - it will route through agent automatically
        client = PyPNMClient()
        result = client._post(
            '/docs/pnm/ds/status/getChannelStatus',
            client._build_cable_modem_request(mac_address, modem_ip, community)
        )
        
        if result.get('status_code') == 200:
            return jsonify({"status": 0, "success": True, **result})
        else:
            return jsonify({"status": 1, "error": result.get('message', 'Unknown error')}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============== Removed Endpoints ==============
# The following endpoints were removed (Phase 3 migration).
# Use /api/pypnm/* endpoints instead, which route through PyPNM API.
# ============================================================


# ============== Health Check ==============

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "PyPNM Web GUI",
        "use_mock_data": current_app.config.get('USE_MOCK_DATA', True)
    })


@api_bp.route('/pypnm/health', methods=['GET'])
def pypnm_health_check():
    """Check PyPNM API health by testing connection to pypnm-api service."""
    import requests
    pypnm_api_url = os.environ.get('PYPNM_BASE_URL', os.environ.get('PYPNM_API_URL', 'http://localhost:8000'))
    
    try:
        # Use /docs endpoint as health check (root returns 404)
        response = requests.get(f"{pypnm_api_url}/docs", timeout=3)
        if response.status_code == 200:
            return jsonify({
                "status": "ok",
                "pypnm_healthy": True,
                "pypnm_api_url": pypnm_api_url
            })
        else:
            return jsonify({
                "status": "error",
                "pypnm_healthy": False,
                "message": f"PyPNM API returned status {response.status_code}"
            })
    except requests.exceptions.RequestException as e:
        return jsonify({
            "status": "error",
            "pypnm_healthy": False,
            "message": str(e)
        })


# ============== Cache Management ==============

@api_bp.route('/cmts/<cmts_name>/cache/clear', methods=['POST'])
def clear_cmts_modem_cache(cmts_name):
    """Clear all cached modem data for a specific CMTS (Redis + API in-memory)."""
    logger = logging.getLogger(__name__)
    cleared = []

    # 1. Clear Redis cache for this CMTS
    if REDIS_AVAILABLE and redis_client:
        try:
            key = f"modems:{cmts_name}"
            if redis_client.delete(key):
                cleared.append(f"Redis key '{key}'")
        except Exception as e:
            logger.warning(f"Redis cache clear error: {e}")

    # 2. Clear PyPNM API in-memory enrichment cache
    try:
        import requests
        pypnm_url = os.environ.get('PYPNM_API_URL', 'http://pypnm-api:8000')
        resp = requests.post(f"{pypnm_url}/cache/clear", timeout=5)
        if resp.status_code == 200:
            cleared.append("API enrichment cache")
    except Exception as e:
        logger.warning(f"API cache clear error: {e}")

    msg = f"Cleared cache for {cmts_name}: {', '.join(cleared)}" if cleared else f"No cache found for {cmts_name}"
    logger.info(msg)
    return jsonify({"status": "success", "message": msg})


@api_bp.route('/cache/flush', methods=['POST'])
def flush_cache():
    """Flush all Redis cache."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        redis_client.flushdb()
        return jsonify({"status": "success", "message": "Cache flushed"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/flush/modems', methods=['POST'])
def flush_modem_cache():
    """Flush modem cache (modems:*)."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        keys = redis_client.keys("modems:*")
        if keys:
            redis_client.delete(*keys)
            count = len(keys)
        else:
            count = 0
        return jsonify({"status": "success", "message": f"Flushed {count} modem cache keys"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/flush/cmts', methods=['POST'])
def flush_cmts_cache():
    """Flush CMTS cache (cmts:*)."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        keys = redis_client.keys("cmts:*")
        if keys:
            redis_client.delete(*keys)
            count = len(keys)
        else:
            count = 0
        return jsonify({"status": "success", "message": f"Flushed {count} CMTS cache keys"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/cache/stats', methods=['GET'])
def cache_stats():
    """Get Redis cache statistics."""
    if not REDIS_AVAILABLE or not redis_client:
        return jsonify({"status": "error", "message": "Redis not available"}), 503
    
    try:
        info = redis_client.info()
        stats = {
            "status": "ok",
            "keys": redis_client.dbsize(),
            "memory_used": info.get('used_memory_human', 'N/A'),
            "memory_peak": info.get('used_memory_peak_human', 'N/A'),
            "hits": info.get('keyspace_hits', 0),
            "misses": info.get('keyspace_misses', 0),
            "hit_rate": f"{info.get('keyspace_hits', 0) / max(info.get('keyspace_hits', 0) + info.get('keyspace_misses', 1), 1) * 100:.1f}%"
        }
        return jsonify(stats)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route('/agent/status', methods=['GET'])
def agent_status():
    """Get WebSocket agent connection status from PyPNM API."""
    try:
        import requests as _requests
        from app.core.config import Config
        base_url = Config.PYPNM_API_URL.rstrip('/')
        resp = _requests.get(f"{base_url}/api/agents", timeout=5)
        response = resp.json() if resp.status_code == 200 else None
        
        # Check if we got a valid response
        if response and isinstance(response, dict):
            agents = response.get('agents', [])
            # Normalize: add status field based on is_alive so frontend filter works
            for a in agents:
                if 'status' not in a:
                    a['status'] = 'connected' if a.get('is_alive') else 'disconnected'
            connected_count = len([a for a in agents if a.get('status') == 'connected'])
            return jsonify({
                "status": "ok",
                "agents": agents,
                "count": connected_count
            })
        else:
            # PyPNM API doesn't have agents endpoint or returned error
            return jsonify({
                "status": "ok",
                "agents": [],
                "count": 0
            })
    except Exception as e:
        logger.warning(f"Failed to get agent status: {e}")
        return jsonify({
            "status": "ok",
            "agents": [],
            "count": 0
        })


# ============== Agent-Based CMTS Modem Lookup ==============

