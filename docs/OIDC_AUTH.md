# OIDC / O365 Authentication Module

> Generic OpenID Connect authentication for Flask, compatible with Microsoft 365 / Entra ID, Keycloak, and any OIDC-compliant identity provider.

## Architecture

The OIDC module is a drop-in plugin for the `AuthProviderRegistry`. When `AUTH_PROVIDER=oidc` is set, it replaces the internal username/password login with an external SSO flow. When disabled (the default), the module is completely inert — the app falls back to internal auth.

### Key Files

| File | Role |
|------|------|
| `backend/app/auth_modules/oidc_module.py` | Full OIDC flow: login, callback, logout, role extraction |
| `backend/app/auth_modules/__init__.py` | Package marker — modules ending with `_module.py` are auto-discovered |
| `backend/app/core/auth_providers.py` | Plugin registry that loads auth modules via `pkgutil.iter_modules` |
| `backend/app/core/config.py` | `OIDC_*` configuration variables |

### Login Flow

```
Browser → /auth/oidc/login
  → redirect to IdP (Entra ID / Keycloak)
    → user authenticates
      → IdP redirects to /auth/oidc/callback
        → token exchange → userinfo claims parsed → Flask session populated
          → redirect to app
```

### Logout Flow

```
Browser → /auth/oidc/logout
  → clear Flask session
    → redirect to IdP end_session_endpoint (with id_token_hint)
      → IdP clears SSO session
        → redirect back to login page
```

### Role Mapping

Claims are checked in this order:

1. `roles` and `groups` top-level claims
2. `realm_access.roles` (Keycloak)
3. `resource_access.<client_id>.roles` (Keycloak client roles)

Mapped to application roles:

| App Role | Condition |
|----------|-----------|
| `admin` | Roles matching `OIDC_ADMIN_ROLES` or email in `OIDC_ADMIN_EMAILS` |
| `viewer` | Roles matching `OIDC_VIEWER_ROLES` or email in `OIDC_VIEWER_EMAILS` |
| `user` | Everyone else |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_PROVIDER` | `internal` | Set to `oidc` to enable SSO |
| `OIDC_DISCOVERY_URL` | *(required)* | OpenID Connect discovery endpoint |
| `OIDC_CLIENT_ID` | *(required)* | Client ID from IdP app registration |
| `OIDC_CLIENT_SECRET` | *(required)* | Client secret from IdP app registration |
| `OIDC_SCOPES` | `openid profile email` | OAuth scopes to request |
| `OIDC_PROVIDER_LABEL` | `Single Sign-On` | Display name on login page |
| `OIDC_ADMIN_ROLES` | `admin` | Comma-separated IdP roles → admin |
| `OIDC_ADMIN_EMAILS` | *(empty)* | Comma-separated emails → admin |
| `OIDC_VIEWER_ROLES` | `viewer` | Comma-separated IdP roles → viewer |
| `OIDC_VIEWER_EMAILS` | *(empty)* | Comma-separated emails → viewer |

### Example: Microsoft 365 / Entra ID

```env
AUTH_PROVIDER=oidc
OIDC_DISCOVERY_URL=https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration
OIDC_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
OIDC_CLIENT_SECRET=your-client-secret
OIDC_PROVIDER_LABEL=Microsoft 365
OIDC_ADMIN_EMAILS=admin@yourdomain.com
```

### Example: Keycloak

```env
AUTH_PROVIDER=oidc
OIDC_DISCOVERY_URL=https://keycloak.example.com/realms/myrealm/.well-known/openid-configuration
OIDC_CLIENT_ID=my-app
OIDC_CLIENT_SECRET=your-client-secret
OIDC_PROVIDER_LABEL=Keycloak
OIDC_ADMIN_ROLES=realm-admin,app-admin
```

## Dependency

```
authlib>=1.3
```

Imported with try/except — the app starts without it; the module logs a warning and stays inactive.

## Reusing in Another Flask Project

The module is self-contained. To copy it to another Flask app:

### 1. Copy `oidc_module.py`

Copy `backend/app/auth_modules/oidc_module.py` into your project.

### 2. Replace project-specific imports

The module imports two small helpers. Replace:

```python
from app.core.auth_providers import AuthProvider, sanitize_next_path
from app.core.i18n import DEFAULT_LOCALE, normalize_locale
```

With these inlined equivalents:

```python
DEFAULT_LOCALE = "en-US"

def normalize_locale(value):
    """Normalize a locale string to 'll-RR' form, or return DEFAULT_LOCALE."""
    text = (str(value) if value else "").strip().replace("_", "-")
    if not text:
        return DEFAULT_LOCALE
    return text

def sanitize_next_path(next_path: str | None, default: str = "/") -> str:
    """Prevent open-redirect by rejecting absolute/external URLs."""
    text = (next_path or "").strip()
    if not text:
        return default
    if text.startswith(("http://", "https://", "//")):
        return default
    if not text.startswith("/"):
        return f"/{text}"
    return text
```

The `AuthProvider` dataclass is only used in `register_auth_provider()` at the bottom. If you don't use the plugin registry, remove that function and wire the module manually.

### 3. Integrate in your Flask app

```python
from your_auth.oidc_module import oidc_auth_bp, configure_app

app.register_blueprint(oidc_auth_bp)
configure_app(app)
```

### 4. Adapt route references

The module references these endpoints (update to match your app):

- `url_for("auth.login")` — your internal login page
- `url_for("main.index")` — your app index/home page

### 5. Set environment variables and install Authlib

```bash
pip install authlib>=1.3
```

Set the `OIDC_*` env vars listed above.
