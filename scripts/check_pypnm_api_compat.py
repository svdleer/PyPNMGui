import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


root = Path("backend/app")
pc = (root / "core" / "pypnm_client.py").read_text()
pr = (root / "routes" / "pypnm_routes.py").read_text()


def extract_calls(text, pattern):
    out = set()
    for m in re.finditer(pattern, text):
        out.add((m.group(1).upper(), m.group(2)))
    return out


client_calls = extract_calls(pc, r"return\s+self\._(post|get)\(\s*['\"]([^'\"]+)['\"]")
client_calls |= extract_calls(pr, r"client\._(post|get)\(\s*['\"]([^'\"]+)['\"]")

proxy_calls = set()
for p in [root / "routes" / "auth_routes.py", root / "routes" / "data_routes.py"]:
    txt = p.read_text()
    for m in re.finditer(r"_poller_(?:api_request|proxy)\(\s*['\"]([A-Z]+)['\"]\s*,\s*f?['\"]([^'\"]+)['\"]", txt):
        proxy_calls.add((m.group(1), m.group(2)))

bases = []
for b in [
    os.getenv("PYPNM_API_URL"),
    os.getenv("PYPNM_BASE_URL"),
    "http://172.17.0.1:8081",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]:
    if b and b not in bases:
        bases.append(b.rstrip("/"))


def get_spec(base):
    request_timeout = float(os.getenv("PYPNM_OPENAPI_TIMEOUT", "2"))
    for suffix in ["/openapi.json", "/api/openapi.json"]:
        url = base + suffix
        try:
            r = requests.get(url, timeout=request_timeout, verify=False)
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, dict) and "paths" in j:
                    return url, j
        except Exception:
            pass
    return None, None


live = []
if bases:
    with ThreadPoolExecutor(max_workers=min(len(bases), 6)) as executor:
        future_map = {executor.submit(get_spec, b): b for b in bases}
        for future in as_completed(future_map):
            b = future_map[future]
            u, j = future.result()
            if j:
                live.append((b, u, j))

print("=== OUTBOUND INVENTORY ===")
print("client/direct calls:", len(client_calls))
print("poller proxy calls:", len(proxy_calls))

if not live:
    print("\n=== LIVE CHECK ===")
    print("No reachable OpenAPI on:")
    for b in bases:
        print("-", b)
    raise SystemExit(0)

print("\n=== LIVE OPENAPI ===")
for b, u, _ in live:
    print("-", b, "via", u)

base, url, spec = live[0]
paths = spec.get("paths", {})


def exists(method, path):
    return path in paths and method.lower() in paths[path]


def normalize_path_params(path):
    return re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\(([^{}]+)\)\}", r"{\1}", path)


def proxy_candidates(path):
    normalized = normalize_path_params(path if path.startswith("/") else f"/{path}")
    return [
        normalized,
        f"/admin{normalized}",
        f"/api/admin{normalized}",
    ]


missing_client = []
for m, p in sorted(client_calls):
    normalized = normalize_path_params(p)
    if not exists(m, normalized):
        missing_client.append((m, p))
missing_proxy = []
for m, p in sorted(proxy_calls):
    candidates = proxy_candidates(p)
    if not any(exists(m, candidate) for candidate in candidates):
        missing_proxy.append((m, p, candidates))

print("\n=== COVERAGE ===")
print("base:", base)
print("client/direct matched:", len(client_calls) - len(missing_client), "/", len(client_calls))
print("poller proxy matched:", len(proxy_calls) - len(missing_proxy), "/", len(proxy_calls))

print("\n=== MISSING CLIENT/DIRECT (first 80) ===")
for m, p in missing_client[:80]:
    print("-", m, p)

print("\n=== MISSING POLLER PROXY ===")
for m, p, candidates in missing_proxy:
    print("-", m, p, "(checked", ", ".join(candidates) + ")")


def _safe_get_json(path, params=None):
    try:
        r = requests.get(base + path, params=params, timeout=5, verify=False)
        if r.status_code >= 400:
            return None
        return r.json() if r.content else None
    except Exception:
        return None


def _first_json(paths_to_try, params=None):
    for path in paths_to_try:
        payload = _safe_get_json(path, params=params)
        if isinstance(payload, dict):
            return path, payload
    return None, None


behavior_warnings = []

scheduler_path, scheduler_payload = _first_json([
    "/api/admin/poller-scheduler/status",
    "/admin/poller-scheduler/status",
    "/poller-scheduler/status",
])
jobs_path, jobs_payload = _first_json([
    "/api/admin/poller-jobs",
    "/admin/poller-jobs",
    "/poller-jobs",
], params={"limit": 50})
analytics_path, analytics_payload = _first_json([
    "/api/admin/poller-snapshots/analytics",
    "/admin/poller-snapshots/analytics",
    "/poller-snapshots/analytics",
], params={"lookback_days": 14})
pollers_path, pollers_payload = _first_json([
    "/api/admin/poller-settings",
    "/admin/poller-settings",
    "/poller-settings",
])

if isinstance(scheduler_payload, dict) and isinstance(jobs_payload, dict):
    scheduler_state = scheduler_payload.get("scheduler") or scheduler_payload.get("status") or {}
    jobs = jobs_payload.get("jobs") or []
    enabled = bool(scheduler_state.get("enabled"))
    if enabled and jobs and all(str(j.get("status", "")).lower() == "queued" for j in jobs):
        behavior_warnings.append(
            "Scheduler is enabled but all sampled jobs remain in queued state; worker/DB execution may be missing"
        )

if isinstance(analytics_payload, dict):
    analytics = analytics_payload.get("analytics") or {}
    total_snapshots = int(analytics.get("total_snapshots") or 0)
    pollers = (pollers_payload or {}).get("pollers") or []
    rf_expected = any(bool(int((p.get("collect_scqam") or 0))) or bool(int((p.get("collect_rxmer") or 0))) for p in pollers)
    if rf_expected and total_snapshots == 0 and isinstance(jobs_payload, dict) and (jobs_payload.get("jobs") or []):
        behavior_warnings.append(
            "Jobs exist but snapshot analytics total is 0; persistence pipeline may be inactive"
        )

print("\n=== BEHAVIORAL WARNINGS ===")
if not behavior_warnings:
    print("none")
else:
    if scheduler_path:
        print("scheduler source:", scheduler_path)
    if jobs_path:
        print("jobs source:", jobs_path)
    if analytics_path:
        print("analytics source:", analytics_path)
    for warning in behavior_warnings:
        print("-", warning)
