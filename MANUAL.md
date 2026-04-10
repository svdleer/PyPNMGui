# PyPNMGui Manual

This document is the practical runbook for installing, starting, stopping, updating, and checking PyPNMGui.

## 1. Scope

PyPNMGui is the GUI and backend-for-frontend layer.

It serves the web pages and proxies API traffic to PyPNM. It should not be treated as the place for SNMP logic, modem enrichment, or plant analysis. Those functions belong in the PyPNM API.

## 2. What You Need Before Starting

- Linux or macOS shell access
- Python 3.10 or newer
- Docker and Docker Compose if you want container-based startup
- A reachable PyPNM API instance

Default ports used by the stack:

- PyPNMGui: `5050`
- PyPNM API: `8000`

## 3. Local Install and Start

From the repository root:

```bash
cd PyPNMGui
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

Start the GUI:

```bash
export PYPNM_API_URL=http://127.0.0.1:8000
python backend/run.py
```

Open:

```text
http://127.0.0.1:5050
```

To stop the local process, interrupt the running terminal.

## 4. Docker Install and Start

Prepare the environment file:

```bash
cd PyPNMGui/docker
cp .env.example .env
```

At minimum, set these values in `.env`:

- `PYPNM_API_URL`
- `APPLICATION_ROOT` if the GUI is mounted under a reverse-proxy path

Start containers:

```bash
docker compose -f docker-compose.prod.yml up -d
```

Check status:

```bash
docker compose -f docker-compose.prod.yml ps
```

Stop containers:

```bash
docker compose -f docker-compose.prod.yml down
```

Restart without rebuild:

```bash
docker compose -f docker-compose.prod.yml restart
```

Restart with rebuild after code changes:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## 5. Health Checks

Check the GUI:

```bash
curl -s http://127.0.0.1:5050/api/health
```

Check the API:

```bash
curl -s http://127.0.0.1:8000/health
```

The GUI health response should indicate that the app is up and that PyPNM connectivity is working.

## 6. Updating the Application

Update the code with git:

```bash
git pull
```

Then restart in the mode you use:

- Local mode: stop and run `python backend/run.py` again
- Docker mode: run `docker compose -f docker-compose.prod.yml up -d --build`

## 7. Common Problems

### The GUI opens but does not show data

- Check `PYPNM_API_URL`
- Confirm PyPNM responds on `/health`
- Inspect browser network requests for failing proxied calls

### The health endpoint shows PyPNM is disconnected

- PyPNM API is down
- The configured API URL is wrong
- The GUI host cannot reach the API host

### Docker exits immediately

```bash
docker compose -f docker-compose.prod.yml logs --tail=200
```

### Port 5050 is already in use

```bash
lsof -i :5050
```

## 8. Related Documents

- `README.md`
- `QUICKSTART.md`
- `docs/PROXY_SETUP.md`
- `docs/PYPNM_INTEGRATION.md`
- `docs/NETWORK_ARCHITECTURE.md`
