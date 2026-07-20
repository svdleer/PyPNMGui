from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, flash, redirect, request, session, url_for

from app.core.auth_providers import AuthProvider, sanitize_next_path
from app.core.i18n import DEFAULT_LOCALE, normalize_locale

try:
    import msal
except Exception:  # pragma: no cover - optional dependency
    msal = None

try:
    from flask_session import Session
except Exception:  # pragma: no cover - optional dependency
    Session = None


oidc_auth_bp = Blueprint("oidc_auth", __name__)
_MSAL_SCOPES = ["User.Read"]


def _provider_label() -> str:
    return (os.environ.get("OIDC_PROVIDER_LABEL") or "Microsoft 365").strip() or "Microsoft 365"


def _oidc_enabled() -> bool:
    provider = (os.environ.get("AUTH_PROVIDER") or "internal").strip().lower()
    return provider in {"oidc", "o365", "office365", "azure", "microsoft", "entra"}


def _azure_authority() -> str:
    return (os.environ.get("AZURE_AUTHORITY") or "https://login.microsoftonline.com/common").strip().rstrip("/")


def _oidc_discovery_url() -> str:
    """Expose the derived URL for diagnostics; MSAL uses the authority directly."""
    return f"{_azure_authority()}/v2.0/.well-known/openid-configuration"


def _oidc_client_id() -> str:
    return (os.environ.get("AZURE_CLIENT_ID") or "").strip()


def _oidc_client_secret() -> str:
    return (os.environ.get("AZURE_CLIENT_SECRET") or "").strip()


def _claims_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _env_values(*names: str, default: str = "") -> set[str]:
    value = next((os.environ.get(name) for name in names if os.environ.get(name)), default)
    return {item.strip().lower() for item in (value or "").split(",") if item.strip()}


def _extract_roles(claims: dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    for claim_name in ("roles", "groups"):
        roles.update(_claims_list(claims.get(claim_name)))

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        roles.update(_claims_list(realm_access.get("roles")))

    resource_access = claims.get("resource_access")
    client_id = _oidc_client_id()
    if isinstance(resource_access, dict) and client_id and isinstance(resource_access.get(client_id), dict):
        roles.update(_claims_list(resource_access[client_id].get("roles")))

    return {role.lower() for role in roles if role}


def _claims_role(claims: dict[str, Any]) -> str:
    """Map LI-compatible Entra role, group, and email settings to PyPNM roles."""
    roles = _extract_roles(claims)
    groups = {value.lower() for value in _claims_list(claims.get("groups"))}
    email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()

    admin_roles = _env_values("OIDC_ADMIN_ROLES", "O365_ADMIN_ROLES", default="admin") | {"li-admin", "li_xml_admin"}
    viewer_roles = _env_values("OIDC_VIEWER_ROLES", "O365_VIEWER_ROLES", default="viewer") | {"li-viewer", "li_xml_viewer"}
    admin_emails = _env_values("OIDC_ADMIN_EMAILS", "O365_ADMIN_EMAILS")
    viewer_emails = _env_values("OIDC_VIEWER_EMAILS", "O365_VIEWER_EMAILS")
    admin_groups = _env_values("O365_ADMIN_GROUPS")
    viewer_groups = _env_values("O365_VIEWER_GROUPS")

    if roles.intersection(admin_roles) or (email and email in admin_emails) or groups.intersection(admin_groups):
        return "admin"
    if roles.intersection(viewer_roles) or (email and email in viewer_emails) or groups.intersection(viewer_groups):
        return "viewer"
    return "user"


def _claims_username(claims: dict[str, Any]) -> str:
    for claim_name in ("preferred_username", "email", "name", "upn", "sub"):
        value = str(claims.get(claim_name) or "").strip()
        if value:
            return value
    return "oidc-user"


def _claims_locale(claims: dict[str, Any]) -> str:
    return normalize_locale(claims.get("locale") or claims.get("lang") or DEFAULT_LOCALE)


def _local_auth_allowed() -> bool:
    """Match LI: O365 disables local login unless explicitly enabled for emergencies."""
    emergency = (os.environ.get("EMERGENCY_LOCAL_AUTH") or "false").strip().lower()
    return not _oidc_enabled() or emergency in {"1", "true", "yes", "on"}


def _configure_server_side_sessions(app) -> bool:
    """Use LI-style filesystem sessions so the MSAL token cache is never put in a cookie."""
    if Session is None:
        app.logger.warning("MSAL auth requires Flask-Session for server-side token caching")
        return False
    if app.config.get("MSAL_SESSION_CONFIGURED"):
        return True

    data_dir = os.environ.get("PYPNM_DATA_DIR")
    if not data_dir:
        data_dir = "/app/data" if os.path.isdir("/app/data") else app.instance_path
    session_dir = os.environ.get("MSAL_SESSION_DIR", os.path.join(data_dir, "flask_session"))
    try:
        os.makedirs(session_dir, exist_ok=True)
    except OSError as exc:
        app.logger.error("Cannot create MSAL session directory %s: %s", session_dir, exc)
        return False

    app.config.update(
        SESSION_TYPE="filesystem",
        SESSION_PERMANENT=False,
        SESSION_FILE_DIR=session_dir,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        MSAL_SESSION_CONFIGURED=True,
    )
    Session(app)
    return True


def _msal_http_timeout() -> int:
    try:
        return max(1, int(os.environ.get("MSAL_HTTP_TIMEOUT_SEC", "15")))
    except (TypeError, ValueError):
        return 15


class _TimeoutSession(requests.Session):
    """Apply a finite timeout to MSAL's metadata and token HTTP calls."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", _msal_http_timeout())
        return super().request(method, url, **kwargs)


def _build_msal_app(cache=None, authority: str | None = None):
    if msal is None:
        raise RuntimeError("MSAL is not installed")
    return msal.ConfidentialClientApplication(
        _oidc_client_id(),
        authority=authority or _azure_authority(),
        client_credential=_oidc_client_secret(),
        token_cache=cache,
        http_client=_TimeoutSession(),
    )


def _external_callback_url() -> str:
    """Build the public callback URL even when Apache strips /cmtool upstream."""
    callback_path = url_for("oidc_auth.oidc_callback")
    app_root = (current_app.config.get("APP_ROOT", "") or "").rstrip("/")
    if app_root and callback_path != app_root and not callback_path.startswith(f"{app_root}/"):
        callback_path = f"{app_root}{callback_path}"
    return f"{request.scheme}://{request.host}{callback_path}"


def _build_auth_url(authority: str | None = None, scopes: list[str] | None = None, state: str | None = None) -> str:
    """Build the Entra authorization URL through the LI-compatible MSAL client."""
    return _build_msal_app(authority=authority).get_authorization_request_url(
        scopes or _MSAL_SCOPES,
        state=state or str(uuid.uuid4()),
        redirect_uri=_external_callback_url(),
    )


def _load_cache():
    cache = msal.SerializableTokenCache()
    serialized = session.get("token_cache")
    if serialized:
        cache.deserialize(serialized)
    return cache


def _save_cache(cache) -> None:
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()


def _fetch_graph_groups(access_token: str) -> list[str] | None:
    """Match LI's optional Microsoft Graph group enrichment for group-based RBAC."""
    url = "https://graph.microsoft.com/v1.0/me/memberOf?$select=id&$top=100"
    headers = {"Authorization": f"Bearer {access_token}"}
    group_ids: list[str] = []
    try:
        while url:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                current_app.logger.warning("Graph API memberOf returned %s: %s", response.status_code, response.text[:200])
                return None
            payload = response.json()
            group_ids.extend(str(item["id"]) for item in payload.get("value", []) if item.get("id"))
            url = payload.get("@odata.nextLink")
        current_app.logger.info("Graph API returned %d group memberships", len(group_ids))
        return group_ids
    except Exception as exc:
        current_app.logger.warning("Failed to fetch Graph groups: %s", exc)
        return None


def configure_app(app) -> None:
    if not _oidc_enabled():
        return
    if msal is None:
        app.logger.warning("O365 auth selected but msal is not installed")
        return
    if not _oidc_client_id() or not _oidc_client_secret():
        app.logger.warning("O365 auth selected but AZURE_CLIENT_ID / AZURE_CLIENT_SECRET are incomplete")
        return
    if not _configure_server_side_sessions(app):
        return
    app.logger.info("O365 auth provider configured with MSAL (%s)", _provider_label())


@oidc_auth_bp.route("/auth/oidc/login", methods=["GET"])
def oidc_login():
    if not _oidc_enabled():
        return redirect(url_for("auth.login"))
    if msal is None or not _oidc_client_id() or not _oidc_client_secret():
        flash("Microsoft 365 authentication is not configured", "danger")
        return redirect(url_for("auth.login"))
    if not current_app.config.get("MSAL_SESSION_CONFIGURED"):
        current_app.logger.error("Microsoft 365 login blocked: server-side session storage is unavailable")
        flash("Microsoft 365 session storage is unavailable", "danger")
        return redirect(url_for("auth.login"))

    session["state"] = str(uuid.uuid4())
    session["post_login_next"] = sanitize_next_path(request.args.get("next"), default=url_for("main.index"))
    try:
        return redirect(_build_auth_url(scopes=_MSAL_SCOPES, state=session["state"]))
    except Exception as exc:
        current_app.logger.error("O365 authorization redirect failed: %s", exc)
        flash("Unable to start Microsoft 365 sign-in", "danger")
        return redirect(url_for("auth.login"))


@oidc_auth_bp.route("/auth/oidc/callback", methods=["GET"])
def oidc_callback():
    current_app.logger.info("O365 callback received")
    if not _oidc_enabled():
        return redirect(url_for("auth.login"))
    if request.args.get("state") != session.get("state"):
        current_app.logger.warning("O365 callback state validation failed")
        flash("Single sign-on state validation failed", "danger")
        return redirect(url_for("auth.login"))
    if "error" in request.args:
        current_app.logger.error("O365 callback error: %s", request.args.get("error"))
        flash(f"Authentication failed: {request.args.get('error')}", "danger")
        return redirect(url_for("auth.login"))
    if not request.args.get("code"):
        flash("Authentication response did not include an authorization code", "danger")
        return redirect(url_for("auth.login"))

    try:
        current_app.logger.info("O365 callback state validated; beginning Entra token exchange")
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_authorization_code(
            request.args["code"],
            scopes=_MSAL_SCOPES,
            # Must exactly match the URI supplied to Entra during oidc_login.
            redirect_uri=_external_callback_url(),
        )
    except Exception as exc:
        current_app.logger.error("O365 token acquisition failed: %s", exc)
        flash("Microsoft 365 sign-in failed", "danger")
        return redirect(url_for("auth.login"))

    if "error" in result:
        current_app.logger.error("O365 token acquisition error: %s", result.get("error"))
        flash(f"Login failed: {result.get('error')}", "danger")
        return redirect(url_for("auth.login"))

    current_app.logger.info("O365 token exchange completed")
    claims = dict(result.get("id_token_claims") or {})
    access_token = result.get("access_token")
    if access_token:
        graph_groups = _fetch_graph_groups(access_token)
        if graph_groups is not None:
            claims["groups"] = graph_groups
    _save_cache(cache)

    subject = str(claims.get("sub") or claims.get("oid") or _claims_username(claims)).strip()
    session["user"] = claims
    session["user_id"] = f"oidc:{subject}"
    session["auth_source"] = "oidc"
    session["username"] = _claims_username(claims)
    session["role"] = _claims_role(claims)
    session["email"] = str(claims.get("email") or claims.get("preferred_username") or "").strip()
    session["locale"] = _claims_locale(claims)
    session["auth_display_name"] = _provider_label()
    session["oidc_id_token"] = result.get("id_token")

    next_path = sanitize_next_path(session.pop("post_login_next", None), default=url_for("main.index"))
    app_root = (current_app.config.get("APP_ROOT", "") or "").rstrip("/")
    if app_root and next_path != app_root and not next_path.startswith(f"{app_root}/"):
        next_path = f"{app_root}{next_path}"
    return redirect(next_path)


@oidc_auth_bp.route("/auth/oidc/logout", methods=["GET", "POST"])
def oidc_logout():
    post_logout_redirect = url_for("auth.login", _external=True)
    global_logout = (os.environ.get("O365_GLOBAL_LOGOUT") or "false").strip().lower() in {"1", "true", "yes", "on"}
    session.clear()

    if _oidc_enabled() and global_logout:
        logout_url = f"{_azure_authority()}/oauth2/v2.0/logout?{urlencode({'post_logout_redirect_uri': post_logout_redirect})}"
        response = redirect(logout_url)
    else:
        response = redirect(post_logout_redirect)

    response.delete_cookie(
        key=current_app.config.get("SESSION_COOKIE_NAME", "session"),
        path=current_app.config.get("SESSION_COOKIE_PATH", "/"),
        domain=current_app.config.get("SESSION_COOKIE_DOMAIN"),
    )
    return response


def register_auth_provider(registry) -> None:
    registry.register(
        AuthProvider(
            name="oidc",
            label=_provider_label(),
            login_endpoint="oidc_auth.oidc_login",
            logout_endpoint="oidc_auth.oidc_logout",
            public_prefixes=("/auth/oidc/login", "/auth/oidc/callback", "/auth/oidc/logout"),
            is_internal=False,
            supports_username_password=_local_auth_allowed(),
            user_management_enabled=False,
            password_management_enabled=False,
            blueprints=[oidc_auth_bp],
            configure_callback=configure_app,
        )
    )
