import re
from pathlib import Path
import requests

BASE = "http://localhost:8000"

root = Path("backend/app")
pc = (root / "core" / "pypnm_client.py").read_text()
pr = (root / "routes" / "pypnm_routes.py").read_text()


def extract_calls(text: str, pattern: str):
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
        proxy_calls.add((m.group(1).upper(), m.group(2)))

spec = None
spec_url = None
for suffix in ["/openapi.json", "/api/openapi.json"]:
    url = BASE + suffix
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and "paths" in j:
                spec = j
                spec_url = url
                break
    except Exception:
        pass

print("BASE", BASE)
print("OPENAPI_URL", spec_url or "NONE")
print("CLIENT_CALLS", len(client_calls))
print("PROXY_CALLS", len(proxy_calls))

if not spec:
    print("ERROR No OpenAPI reachable at localhost:8000")
    raise SystemExit(0)

paths = spec.get("paths", {})


def exists(method: str, path: str) -> bool:
    p = paths.get(path)
    return bool(p and method.lower() in p)


def normalize_path_params(path: str) -> str:
    return re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\(([^{}]+)\)\}", r"{\1}", path)


def proxy_candidates(path: str):
    normalized = normalize_path_params(path if path.startswith("/") else f"/{path}")
    return [
        normalized,
        f"/admin{normalized}",
        f"/api/admin{normalized}",
    ]


missing_client = []
for method, path in sorted(client_calls):
    normalized = normalize_path_params(path)
    if not exists(method, normalized):
        missing_client.append((method, path))

missing_proxy = []
for method, path in sorted(proxy_calls):
    candidates = proxy_candidates(path)
    if not any(exists(method, candidate) for candidate in candidates):
        missing_proxy.append((method, path, candidates))

print("MATCH_CLIENT", len(client_calls) - len(missing_client), "/", len(client_calls))
print("MATCH_PROXY", len(proxy_calls) - len(missing_proxy), "/", len(proxy_calls))

print("---MISSING_CLIENT_START---")
for method, path in missing_client:
    print(method, path)
print("---MISSING_CLIENT_END---")

print("---MISSING_PROXY_START---")
for method, path, candidates in missing_proxy:
    print(method, path, "|checked", ", ".join(candidates))
print("---MISSING_PROXY_END---")
