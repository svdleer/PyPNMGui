# PyPNM Web GUI - API Routes
# SPDX-License-Identifier: Apache-2.0

from flask import jsonify, request, current_app
from . import api_bp
from app.models import MockDataProvider


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
    """Get list of CMTS devices."""
    cmts_list = MockDataProvider.get_cmts_list()
    return jsonify({
        "status": "success",
        "cmts_list": cmts_list
    })


@api_bp.route('/cmts/<cmts_name>/interfaces', methods=['GET'])
def get_cmts_interfaces(cmts_name):
    """Get interfaces for a specific CMTS."""
    cmts_list = MockDataProvider.get_cmts_list()
    for cmts in cmts_list:
        if cmts['name'] == cmts_name:
            return jsonify({
                "status": "success",
                "interfaces": cmts['interfaces']
            })
    
    return jsonify({
        "status": "error",
        "message": "CMTS not found"
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
    """Get RxMER measurement."""
    request_data = request.get_json() or {}
    channel_ids = request_data.get('channel_ids', [159])
    
    data = MockDataProvider.get_rxmer_measurement(mac_address, channel_ids)
    return jsonify(data)


@api_bp.route('/modem/<mac_address>/spectrum', methods=['POST'])
def get_spectrum(mac_address):
    """Get spectrum analysis data."""
    data = MockDataProvider.get_spectrum_analysis(mac_address)
    return jsonify(data)


@api_bp.route('/modem/<mac_address>/fec-summary', methods=['POST'])
def get_fec_summary(mac_address):
    """Get FEC summary statistics."""
    data = MockDataProvider.get_fec_summary(mac_address)
    return jsonify(data)


# ============== Event Log Endpoint ==============

@api_bp.route('/modem/<mac_address>/event-log', methods=['POST'])
def get_event_log(mac_address):
    """Get modem event log."""
    data = MockDataProvider.get_event_log(mac_address)
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
