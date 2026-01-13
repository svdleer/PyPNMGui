#!/usr/bin/env python3
# PyPNM Web GUI - Application Entry Point
# SPDX-License-Identifier: Apache-2.0

import os
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    
    # Check if we should use SocketIO (for agent support)
    if socketio is not None and app.config.get('ENABLE_AGENT_WEBSOCKET'):
        print(f"Starting with WebSocket support on port {port}")
        socketio.run(app, host='0.0.0.0', port=port, debug=True)
    else:
        print(f"Starting standard Flask server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=True)
