from __future__ import annotations

import importlib
import os
import pkgutil
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AuthProvider:
    name: str
    label: str
    login_endpoint: str
    logout_endpoint: str
    public_prefixes: tuple[str, ...]
    is_internal: bool = False
    supports_username_password: bool = False
    user_management_enabled: bool = False
    password_management_enabled: bool = False
    blueprints: list[Any] = field(default_factory=list)
    configure_callback: Any | None = None

    def configure_app(self, app) -> None:
        if callable(self.configure_callback):
            self.configure_callback(app)


class AuthProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AuthProvider] = {}
        self._modules_loaded = False
        self.register(
            AuthProvider(
                name="internal",
                label="Internal",
                login_endpoint="auth.login",
                logout_endpoint="auth.logout",
                public_prefixes=("/login", "/logout"),
                is_internal=True,
                supports_username_password=True,
                user_management_enabled=True,
                password_management_enabled=True,
            )
        )

    def register(self, provider: AuthProvider) -> None:
        self._providers[provider.name] = provider

    def load_modules(self) -> None:
        if self._modules_loaded:
            return
        self._modules_loaded = True
        try:
            package = importlib.import_module("app.auth_modules")
        except Exception:
            return

        for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}."):
            if not module_info.name.endswith("_module"):
                continue
            try:
                module = importlib.import_module(module_info.name)
            except Exception:
                continue
            register = getattr(module, "register_auth_provider", None)
            if callable(register):
                register(self)

    @property
    def requested_provider_name(self) -> str:
        value = (os.environ.get("AUTH_PROVIDER") or "internal").strip().lower()
        if value in {"o365", "office365", "azure", "microsoft", "entra"}:
            return "oidc"
        return value or "internal"

    @property
    def active_provider(self) -> AuthProvider:
        self.load_modules()
        return self._providers.get(self.requested_provider_name, self._providers["internal"])

    @property
    def all_public_prefixes(self) -> tuple[str, ...]:
        self.load_modules()
        prefixes: list[str] = []
        for provider in self._providers.values():
            prefixes.extend(provider.public_prefixes)
        return tuple(dict.fromkeys(prefixes))

    @property
    def blueprints(self) -> list[Any]:
        self.load_modules()
        blueprints: list[Any] = []
        for provider in self._providers.values():
            blueprints.extend(provider.blueprints)
        return blueprints

    @property
    def providers(self) -> tuple[AuthProvider, ...]:
        self.load_modules()
        return tuple(self._providers.values())


_registry = AuthProviderRegistry()


def get_auth_registry() -> AuthProviderRegistry:
    _registry.load_modules()
    return _registry


def get_active_auth_provider() -> AuthProvider:
    return get_auth_registry().active_provider


def get_session_auth_source(auth_session) -> str:
    source = (auth_session.get("auth_source") or "internal").strip().lower()
    return source or "internal"


def _session_matches_provider(auth_session, provider: AuthProvider) -> bool:
    source = get_session_auth_source(auth_session)
    if source == provider.name:
        return True
    return source == "internal" and provider.supports_username_password


def is_authenticated_session(auth_session) -> bool:
    user_id = auth_session.get("user_id")
    if not user_id:
        return False
    return _session_matches_provider(auth_session, get_active_auth_provider())


def session_matches_active_provider(auth_session) -> bool:
    if not auth_session.get("user_id"):
        return True
    return _session_matches_provider(auth_session, get_active_auth_provider())


def local_user_id(auth_session) -> int | None:
    if get_session_auth_source(auth_session) != "internal":
        return None
    user_id = auth_session.get("user_id")
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def sanitize_next_path(next_path: str | None, default: str = "/") -> str:
    text = (next_path or "").strip()
    if not text:
        return default
    if text.startswith("http://") or text.startswith("https://") or text.startswith("//"):
        return default
    if not text.startswith("/"):
        return f"/{text}"
    return text


def auth_template_context() -> dict[str, Any]:
    provider = get_active_auth_provider()
    return {
        "auth_provider_name": provider.name,
        "auth_provider_label": provider.label,
        "auth_supports_username_password": provider.supports_username_password,
        "auth_user_management_enabled": provider.user_management_enabled,
        "auth_password_management_enabled": provider.password_management_enabled,
        "auth_is_external": not provider.is_internal,
    }