# QUICKSTART

## Requirements

- Python 3.10+
- Running PyPNM API
- Optional: Docker and Docker Compose

## Option 1: Run With Docker

```bash
cd PyPNMGui/docker
cp .env.example .env
# Edit .env and set at least PYPNM_API_URL

docker compose -f docker-compose.prod.yml up -d
```

Access:
- `http://localhost:5050`
- or `http://<host>:5050`

## Option 2: Run Without Docker

```bash
cd PyPNMGui
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

export PYPNM_API_URL=http://127.0.0.1:8000
python backend/run.py
```

Access:
- `http://localhost:5050`

## Health Check

```bash
curl -s http://127.0.0.1:5050/api/health
```

Expected key fields:
- `status: ok`
- `pypnm_connected: true`

## If It Does Not Start

- Port 5050 in use:
```bash
lsof -i :5050
```
- PyPNM not reachable:
  - verify `PYPNM_API_URL`
  - verify PyPNM API is up (`http://127.0.0.1:8000/health`)

For full install/run operations, see `MANUAL.md`.
