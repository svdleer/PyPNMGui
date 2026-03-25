#!/usr/bin/env python3
# PyPNM Web GUI - Application Entry Point

import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    print(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
