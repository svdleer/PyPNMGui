# Transparent Proxy Configuration

This document explains how to configure PyPNM GUI to work behind a transparent proxy with a custom base path (e.g., `/cmtool/`).

## Overview

When running behind a transparent proxy that routes requests to a specific path prefix, the application needs to be aware of this base path to correctly generate URLs for static resources, API calls, and links.

## Configuration

### Environment Variable

Set the `APPLICATION_ROOT` environment variable to your proxy path:

```bash
export APPLICATION_ROOT=/cmtool
```

### Docker Compose

Add the environment variable to your docker-compose configuration:

```yaml
services:
  gui-server:
    environment:
      - APPLICATION_ROOT=/cmtool
```

Or use an environment variable in your `.env` file:

```env
APPLICATION_ROOT=/cmtool
```

Then reference it in docker-compose.yml:

```yaml
services:
  gui-server:
    environment:
      - APPLICATION_ROOT=${APPLICATION_ROOT:-/}
```

## Example Nginx Proxy Configuration

Here's an example nginx configuration for proxying to PyPNM GUI:

```nginx
location /cmtool/ {
    proxy_pass http://backend-server:5050/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Increase timeouts for long-running requests
    proxy_read_timeout 300;
    proxy_connect_timeout 300;
    proxy_send_timeout 300;
}
```

## How It Works

1. **Backend (Flask)**: The `APPLICATION_ROOT` config tells Flask to mount all routes under the specified path prefix.

2. **Frontend (JavaScript)**: The base path is passed to the frontend via a template variable, which sets `window.BASE_PATH`.

3. **Static Resources**: All static resource paths (CSS, JS) are prefixed with the base path in HTML templates.

4. **API Calls**: The frontend JavaScript uses `BASE_PATH + '/api'` for all API requests.

## Testing

After configuration, access your application at:

```
http://your-domain/cmtool/
```

The application should work correctly with:
- Static resources loading from `/cmtool/static/...`
- API calls going to `/cmtool/api/...`
- Internal links using the correct base path

## Troubleshooting

### Static Resources Not Loading

Check that:
1. `APPLICATION_ROOT` is set correctly (include leading slash, no trailing slash)
2. Browser developer console shows requests going to the correct paths
3. Proxy is correctly rewriting paths

### API Calls Failing

Verify that:
1. The proxy passes through the full path to the backend
2. CORS settings allow requests from the proxy domain
3. WebSocket connections work if using agent mode

### Example: Working vs Non-Working Paths

✅ **Correct Configuration:**
- Environment: `APPLICATION_ROOT=/cmtool`
- Access URL: `http://domain/cmtool/`
- Static resource: `http://domain/cmtool/static/css/style.css`
- API call: `http://domain/cmtool/api/health`

❌ **Incorrect (missing APPLICATION_ROOT):**
- Environment: `APPLICATION_ROOT=/` (or not set)
- Access URL: `http://domain/cmtool/`
- Static resource: `http://domain/static/css/style.css` ← FAILS
- API call: `http://domain/api/health` ← FAILS

## Default Behavior

If `APPLICATION_ROOT` is not set or is set to `/`, the application works as before with no base path prefix.
