from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for

from app.core.auth_providers import AuthProvider, sanitize_next_path
from app.core.i18n import DEFAULT_LOCALE, normalize_locale

try:
    from authlib.integrations.flask_client import OAuth
except Exception:  # pragma: no cover - optional dependency
    OAuth = None


oidc_auth_bp = Blueprint("oidc_auth", __name__)
oauth = OAuth() if OAuth is not None else None
_CLIENT_NAME = "pypnm_oidc"


def _provider_label() -> str:
    return (os.environ.get("OIDC_PROVIDER_LABEL") or "Single Sign-On").strip() or "Single Sign-On"


def _oidc_enabled() -> bool:
    provider = (os.environ.get("AUTH_PROVIDER") or "internal").strip().lower()
    return provider in {"oidc", "o365", "office365", "azure", "microsoft", "entra"}


def _oidc_discovery_url() -> str:
    direct = (os.environ.get("OIDC_DISCOVERY_URL") or "").strip()
    if direct:
        return direct
    authority = (os.environ.get("AZURE_AUTHORITY") or "").strip().rstrip("/")
    if authority:
        return f"{authority}/v2.0/.well-known/openid-configuration"
    return ""


def _oidc_client_id() -> str:
    return (os.environ.get("OIDC_CLIENT_ID") or os.environ.get("AZURE_CLIENT_ID") or "").strip()


def _oidc_client_secret() -> str:
    return (os.environ.get("OIDC_CLIENT_SECRET") or os.environ.get("AZURE_CLIENT_SECRET") or "").strip()


def _oidc_client():
    if oauth is None:
        abort(503)
    client = oauth.create_client(_CLIENT_NAME)
    if client is None:
        abort(503)
    return client


def _claims_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


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
    admin_roles = {
        role.strip().lower()
        for role in (os.environ.get("OIDC_ADMIN_ROLES") or "admin").split(",")
        if role.strip()
    }
    admin_emails = {
        value.strip().lower()
        for value in (os.environ.get("OIDC_ADMIN_EMAILS") or "").split(",")
        if value.strip()
    }
    viewer_roles = {
        role.strip().lower()
        for role in (os.environ.get("OIDC_VIEWER_ROLES") or "viewer").split(",")
        if role.strip()
    }
    viewer_emails = {
        value.strip().lower()
        for value in (os.environ.get("OIDC_VIEWER_EMAILS") or "").split(",")
        if value.strip()
    }
    roles = _extract_roles(claims)
    email = str(claims.get("email") or "").strip().lower()
    if admin_roles.intersection(roles) or (email and email in admin_emails):
        return "admin"
    if viewer_roles.intersection(roles) or (email and email in viewer_emails):
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


def configure_app(app) -> None:
    if oauth is None:
        app.logger.warning("OIDC auth module found but Authlib is not installed")
        return
    if not _oidc_enabled():
        return

    discovery_url = _oidc_discovery_url()
    client_id = _oidc_client_id()
    client_secret = _oidc_client_secret()
    if not discovery_url or not client_id or not client_secret:
        app.logger.warning("OIDC auth selected but OIDC_DISCOVERY_URL / OIDC_CLIENT_ID / OIDC_CLIENT_SECRET are incomplete")
        return

    oauth.init_app(app)
    oauth.register(
        name=_CLIENT_NAME,
        server_metadata_url=discovery_url,
        client_id=client_id,
        client_secret=client_secret,
        client_kwargs={
            "scope": (os.environ.get("OIDC_SCOPES") or "openid profile email").strip(),
        },
    )
    app.logger.info("OIDC auth provider configured (%s)", _provider_label())


@oidc_auth_bp.route("/auth/oidc/login", methods=["GET"])
def oidc_login():
    if not _oidc_enabled():
        return redirect(url_for("auth.login"))
    client = _oidc_client()
    next_path = sanitize_next_path(request.args.get("next"), default=url_for("main.index"))
    session["post_login_next"] = next_path
    redirect_uri = url_for("oidc_auth.oidc_callback", _external=True)
    return client.authorize_redirect(redirect_uri)


@oidc_auth_bp.route("/auth/oidc/callback", methods=["GET"])
def oidc_callback():
    if not _oidc_enabled():
        return redirect(url_for("auth.login"))
    client = _oidc_client()
    try:
        token = client.authorize_access_token()
        claims = token.get("userinfo")
        if not claims:
            claims = client.parse_id_token(token)
        if not claims:
            claims = client.userinfo()
    except Exception as exc:
        current_app.logger.error("OIDC callback failed: %s", exc)
        flash("Single sign-on failed", "danger")
        return redirect(url_for("auth.login"))

    claims = dict(claims or {})
    subject = str(claims.get("sub") or _claims_username(claims)).strip()
    username = _claims_username(claims)
    locale = _claims_locale(claims)
    role = _claims_role(claims)

    session.clear()
    session["user_id"] = f"oidc:{subject}"
    session["auth_source"] = "oidc"
    session["username"] = username
    session["role"] = role
    session["email"] = str(claims.get("email") or "").strip()
    session["locale"] = locale
    session["auth_display_name"] = _provider_label()
    session["oidc_id_token"] = token.get("id_token")

    next_path = sanitize_next_path(session.pop("post_login_next", None), default=url_for("main.index"))
    return redirect(next_path)


@oidc_auth_bp.route("/auth/oidc/logout", methods=["GET", "POST"])
def oidc_logout():
    id_token = session.get("oidc_id_token")
    post_logout_redirect = url_for("auth.login", _external=True)
    session.clear()

    if not _oidc_enabled():
        return redirect(post_logout_redirect)

    try:
        client = _oidc_client()
        metadata = getattr(client, "server_metadata", {}) or {}
        end_session_endpoint = metadata.get("end_session_endpoint")
        if end_session_endpoint:
            params = {"post_logout_redirect_uri": post_logout_redirect}
            if id_token:
                params["id_token_hint"] = id_token
            return redirect(f"{end_session_endpoint}?{urlencode(params)}")
    except Exception as exc:
        current_app.logger.warning("OIDC logout fallback used: %s", exc)

    return redirect(post_logout_redirect)


def register_auth_provider(registry) -> None:
    registry.register(
        AuthProvider(
            name="oidc",
            label=_provider_label(),
            login_endpoint="oidc_auth.oidc_login",
            logout_endpoint="oidc_auth.oidc_logout",
            public_prefixes=("/auth/oidc/login", "/auth/oidc/callback", "/auth/oidc/logout"),
            is_internal=False,
            supports_username_password=False,
            user_management_enabled=False,
            password_management_enabled=False,
            blueprints=[oidc_auth_bp],
            configure_callback=configure_app,
        )
    )