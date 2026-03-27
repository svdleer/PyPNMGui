from functools import wraps
import os
from datetime import datetime
import re

from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
import requests

from . import auth_bp
from app.core.auth_db import auth_db
from app.core.cmts_provider import CMTSProvider
from app.core.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, normalize_locale, translate


def _prefixed(path: str) -> str:
    base = (current_app.config.get("APP_ROOT", "") or "").rstrip("/")
    if not base:
        return path
    if path.startswith(base + "/") or path == base:
        return path
    return f"{base}{path}"


def _poller_api_base() -> str:
    explicit = (os.environ.get("PYPNM_POLLER_API_BASE") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    pypnm_base = (os.environ.get("PYPNM_API_URL") or os.environ.get("PYPNM_BASE_URL") or "http://172.17.0.1:8081").rstrip("/")
    return f"{pypnm_base}/api/admin"


def _poller_api_request(method: str, path: str, *, payload=None, params=None) -> dict:
    timeout = int(os.environ.get("PYPNM_POLLER_API_TIMEOUT_SEC", "20"))
    url = f"{_poller_api_base()}{path}"
    resp = requests.request(method=method, url=url, json=payload, params=params, timeout=timeout, verify=False)
    resp.raise_for_status()
    try:
        return resp.json() if resp.content else {"status": "success"}
    except Exception:
        return {"status": "success", "raw": resp.text}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _normalize_time_24h(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("PT"):
        # Supports ISO-8601 duration forms like PT5H30M, PT5H, PT30M.
        m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
        if m:
            try:
                hh = int(m.group(1) or 0)
                mm = int(m.group(2) or 0)
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return text
        if text.endswith("M"):
            try:
                mins = int(text[2:-1])
                hh = mins // 60
                mm = mins % 60
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return text
    if len(text) >= 5 and text[2] == ":":
        return text[:5]
    return text


def _normalize_datetime_24h(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d-%m-%y %H:%M:%S")
    except Exception:
        return text


def login_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(_prefixed(url_for("auth.login", next=request.path)))
        return view_func(*args, **kwargs)

    return _wrapped


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(_prefixed(url_for("auth.login", next=request.path)))
        if session.get("role") != "admin":
            flash("Admin role required", "danger")
            return redirect(_prefixed(url_for("main.index")))
        return view_func(*args, **kwargs)

    return _wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(_prefixed(url_for("main.index")))
        base_path = current_app.config.get("APP_ROOT", "")
        return render_template("login.html", base_path=base_path)

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = auth_db.verify_user(username, password)
    if not user:
        flash("Invalid username/password", "danger")
        return redirect(_prefixed(url_for("auth.login")))

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["locale"] = normalize_locale(user.get("language_preference") or DEFAULT_LOCALE)

    next_url = request.args.get("next") or url_for("main.index")
    return redirect(_prefixed(next_url))


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(_prefixed(url_for("auth.login")))


@auth_bp.route("/account", methods=["GET"])
@login_required
def account():
    base_path = current_app.config.get("APP_ROOT", "")
    user = auth_db.get_user_by_id(session.get("user_id")) or {}
    return render_template(
        "account.html",
        base_path=base_path,
        auth_username=session.get("username", ""),
        auth_role=session.get("role", "user"),
        current_locale=normalize_locale(user.get("language_preference") or session.get("locale") or DEFAULT_LOCALE),
        supported_locales=SUPPORTED_LOCALES,
    )


@auth_bp.route("/account/password", methods=["POST"])
@login_required
def account_change_password():
    current_password = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if len(new_password) < 8:
        flash("New password must be at least 8 characters", "danger")
        return redirect(_prefixed(url_for("auth.account")))
    if new_password != confirm_password:
        flash("Password confirmation does not match", "danger")
        return redirect(_prefixed(url_for("auth.account")))

    ok, msg = auth_db.change_password(session["user_id"], current_password, new_password)
    flash(msg, "success" if ok else "danger")
    return redirect(_prefixed(url_for("auth.account")))


@auth_bp.route("/account/language", methods=["POST"])
@login_required
def account_change_language():
    locale = normalize_locale(request.form.get("language_preference") or DEFAULT_LOCALE)
    if locale not in SUPPORTED_LOCALES:
        flash(translate(session.get("locale") or DEFAULT_LOCALE, "language.invalid"), "danger")
        return redirect(_prefixed(url_for("auth.account")))
    auth_db.set_language_preference(session["user_id"], locale)
    session["locale"] = locale
    flash(translate(locale, "language.saved"), "success")
    return redirect(_prefixed(url_for("auth.account")))


@auth_bp.route("/admin", methods=["GET"])
@admin_required
def admin_page():
    import os
    base_path = current_app.config.get("APP_ROOT", "")
    users = auth_db.list_users()
    api_keys = auth_db.list_api_keys()
    data_flag = '/app/data/MAINTENANCE'
    maintenance_active = (
        os.environ.get('MAINTENANCE_MODE', '').lower() == 'true'
        or os.path.exists(data_flag)
    )

    # Auth DB status/config panel
    db_backend = getattr(auth_db, "backend", "sqlite")
    db_connected = True
    db_error = None
    try:
        conn = auth_db._connect()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        conn.close()
    except Exception as exc:
        db_connected = False
        db_error = str(exc)

    db_status = {
        "backend": db_backend,
        "connected": db_connected,
        "error": db_error,
        "sqlite_path": getattr(auth_db, "sqlite_path", None),
        "mysql_host": os.environ.get("AUTH_DB_HOST"),
        "mysql_port": os.environ.get("AUTH_DB_PORT", "3306"),
        "mysql_user": os.environ.get("AUTH_DB_USER"),
        "mysql_name": os.environ.get("AUTH_DB_NAME"),
    }

    # Poller settings/jobs status (remote PyPNM poller API)
    poller_settings = []
    poller_jobs = []
    cmts_systems = []
    snapshot_counts = []
    snapshot_analytics = {}
    poller_scheduler_status = {"enabled": False, "running": False, "last_tick": None}
    data_store_error = None
    try:
        settings_resp = _poller_api_request("GET", "/poller-settings")
        poller_settings = settings_resp.get("pollers") or settings_resp.get("poller_settings") or []
        for p in poller_settings:
            p["enabled"] = _as_bool(p.get("enabled"))
            p["collect_identity"] = _as_bool(p.get("collect_identity"))
            p["collect_scqam"] = _as_bool(p.get("collect_scqam"))
            p["collect_rxmer"] = _as_bool(p.get("collect_rxmer"))
            p["run_window_start"] = _normalize_time_24h(p.get("run_window_start"))
            p["run_window_end"] = _normalize_time_24h(p.get("run_window_end"))
            p["heavy_window_start"] = _normalize_time_24h(p.get("heavy_window_start"))
            p["heavy_window_end"] = _normalize_time_24h(p.get("heavy_window_end"))

        jobs_resp = _poller_api_request("GET", "/poller-jobs", params={"limit": 30})
        poller_jobs = jobs_resp.get("jobs") or []
        for j in poller_jobs:
            j["created_at"] = _normalize_datetime_24h(j.get("created_at"))
            j["started_at"] = _normalize_datetime_24h(j.get("started_at"))
            j["finished_at"] = _normalize_datetime_24h(j.get("finished_at"))

        cmts_systems = CMTSProvider.get_all_cmts()

        snapshot_counts_resp = _poller_api_request("GET", "/poller-snapshots/by-day", params={"lookback_days": 14, "limit": 300})
        snapshot_counts = snapshot_counts_resp.get("rows") or snapshot_counts_resp.get("snapshot_counts") or []

        snapshot_analytics_resp = _poller_api_request("GET", "/poller-snapshots/analytics", params={"lookback_days": 14})
        snapshot_analytics = snapshot_analytics_resp.get("analytics") or {}

        scheduler_resp = _poller_api_request("GET", "/poller-scheduler/status")
        poller_scheduler_status.update(scheduler_resp.get("scheduler") or scheduler_resp.get("status") or {})
        poller_scheduler_status["enabled"] = _as_bool(poller_scheduler_status.get("enabled"))
        poller_scheduler_status["running"] = _as_bool(poller_scheduler_status.get("running"))
        poller_scheduler_status["last_tick"] = _normalize_datetime_24h(poller_scheduler_status.get("last_tick"))
        poller_scheduler_status["decisions"] = [
            d for d in (poller_scheduler_status.get("decisions") or [])
            if str((d or {}).get("reason") or "").strip().lower() not in {"interval_not_due", "active_job_exists"}
        ]
    except Exception as exc:
        data_store_error = f"Remote poller API unavailable: {exc}"

    return render_template(
        "admin.html",
        base_path=base_path,
        users=users,
        api_keys=api_keys,
        auth_username=session.get("username", ""),
        auth_role=session.get("role", "user"),
        maintenance_active=maintenance_active,
        db_status=db_status,
        poller_settings=poller_settings,
        poller_jobs=poller_jobs,
        cmts_systems=cmts_systems,
        snapshot_counts=snapshot_counts,
        snapshot_analytics=snapshot_analytics,
        poller_scheduler_status=poller_scheduler_status,
        data_store_backend="PyPNM",
        data_store_error=data_store_error,
    )


@auth_bp.route("/admin/poller-settings/upsert", methods=["POST"])
@admin_required
def admin_upsert_poller_setting():
    try:
        payload = {
            "id": request.form.get("id") or None,
            "name": (request.form.get("name") or "default").strip(),
            "enabled": request.form.get("enabled") == "on",
            "scope_type": request.form.get("scope_type") or "all_cmts",
            "scope_json": (request.form.get("scope_json") or "").strip() or None,
            "collect_identity": request.form.get("collect_identity") == "on",
            "collect_scqam": request.form.get("collect_scqam") == "on",
            "collect_rxmer": request.form.get("collect_rxmer") == "on",
            "interval_minutes": int(request.form.get("interval_minutes") or 1440),
            "run_window_start": (request.form.get("run_window_start") or "").strip() or None,
            "run_window_end": (request.form.get("run_window_end") or "").strip() or None,
            "max_concurrency": int(request.form.get("max_concurrency") or 4),
            "max_agent_queue_depth": int(request.form.get("max_agent_queue_depth") or 20),
            "retention_days": int(request.form.get("retention_days") or 30),
            "heavy_window_start": (request.form.get("heavy_window_start") or "00:30").strip(),
            "heavy_window_end": (request.form.get("heavy_window_end") or "05:30").strip(),
            "heavy_max_modems": int(request.form.get("heavy_max_modems") or 300),
            "heavy_delay_ms": int(request.form.get("heavy_delay_ms") or 0),
            "max_runtime_sec": int(request.form.get("max_runtime_sec") or 14400),
        }
        save_resp = _poller_api_request("POST", "/poller-settings", payload=payload)
        saved_id = save_resp.get("poller_id") or save_resp.get("id") or "?"
        flash(f"Poller setting saved (id={saved_id})", "success")
    except Exception as exc:
        flash(f"Save poller setting failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-settings/<int:poller_id>/run", methods=["POST"])
@admin_required
def admin_run_poller_setting(poller_id):
    try:
        run_resp = _poller_api_request("POST", f"/poller-settings/{int(poller_id)}/run", payload={"source": "admin-ui"})
        job_id = run_resp.get("job_id") or "?"
        flash(f"Run queued for poller {poller_id} (job {job_id})", "success")
    except Exception as exc:
        flash(f"Queue run failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-settings/<int:poller_id>/delete", methods=["POST"])
@admin_required
def admin_delete_poller_setting(poller_id):
    try:
        _poller_api_request("DELETE", f"/poller-settings/{int(poller_id)}")
        flash(f"Deleted poller setting {poller_id}", "success")
    except Exception as exc:
        flash(f"Delete poller failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-scheduler/toggle", methods=["POST"])
@admin_required
def admin_toggle_poller_scheduler():
    try:
        enabled = request.form.get("enabled") == "on"
        _poller_api_request("POST", "/poller-scheduler/toggle", payload={"enabled": enabled})
        flash(f"Poller scheduler {'enabled' if enabled else 'disabled'}", "success")
    except Exception as exc:
        flash(f"Toggle poller scheduler failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-scheduler/poll", methods=["POST"])
@admin_required
def admin_set_poller_scheduler_poll():
    try:
        poll_sec = int(request.form.get("poll_sec") or 60)
        _poller_api_request("POST", "/poller-scheduler/poll", payload={"poll_sec": poll_sec})
        flash(f"Poller scheduler poll set to {max(5, poll_sec)}s", "success")
    except Exception as exc:
        flash(f"Invalid poll interval: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-scheduler/run-once", methods=["POST"])
@admin_required
def admin_run_poller_scheduler_once():
    try:
        run_resp = _poller_api_request("POST", "/poller-scheduler/run-once", payload={})
        queued = run_resp.get("queued") or run_resp.get("count") or 0
        flash(f"Poller scheduler run complete; queued {queued} poller job(s)", "success")
    except Exception as exc:
        flash(f"Poller scheduler run failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-scheduler/decisions/clear", methods=["POST"])
@admin_required
def admin_clear_poller_scheduler_decisions():
    try:
        clear_resp = _poller_api_request("POST", "/poller-scheduler/decisions/clear", payload={})
        deleted = clear_resp.get("deleted") or 0
        flash(f"Cleared {deleted} scheduler decision row(s)", "success")
    except Exception as exc:
        flash(f"Clear scheduler decisions failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-jobs/clear", methods=["POST"])
@admin_required
def admin_clear_poller_jobs():
    try:
        clear_resp = _poller_api_request("POST", "/poller-jobs/clear", payload={})
        deleted = clear_resp.get("deleted") or 0
        flash(f"Cleared {deleted} finished poller job(s)", "success")
    except Exception as exc:
        flash(f"Clear jobs failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-jobs/clear-all", methods=["POST"])
@admin_required
def admin_clear_all_poller_jobs():
    try:
        clear_resp = _poller_api_request("POST", "/poller-jobs/clear-all", payload={})
        deleted = clear_resp.get("deleted") or 0
        flash(f"Cleared all {deleted} poller job(s) (running/queued kept)", "success")
    except Exception as exc:
        flash(f"Clear all jobs failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/poller-jobs/<int:job_id>/kill", methods=["POST"])
@admin_required
def admin_kill_poller_job(job_id):
    try:
        kill_resp = _poller_api_request("POST", f"/poller-jobs/{int(job_id)}/kill", payload={})
        killed = int(kill_resp.get("killed") or 0)
        state = kill_resp.get("state") or "unknown"
        if killed:
            flash(f"Killed poller job {job_id}", "success")
        else:
            flash(f"Poller job {job_id} not killed (state: {state})", "warning")
    except Exception as exc:
        flash(f"Kill job failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/maintenance", methods=["POST"])
@admin_required
def admin_maintenance_toggle():
    import os
    action = request.form.get("action", "")
    data_flag = '/app/data/MAINTENANCE'
    off_flag  = '/app/data/MAINTENANCE_OFF'
    os.makedirs('/app/data', exist_ok=True)
    if action == "enable":
        # Remove any OFF override, then create the flag file
        if os.path.exists(off_flag):
            os.remove(off_flag)
        open(data_flag, 'w').close()
        flash("Maintenance mode enabled", "warning")
    elif action == "disable":
        if os.path.exists(data_flag):
            os.remove(data_flag)
        # Write OFF file to override env-var-based maintenance too
        open(off_flag, 'w').close()
        flash("Maintenance mode disabled", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/users/create", methods=["POST"])
@admin_required
def admin_create_user():
    username = (request.form.get("username") or "").strip()
    role = (request.form.get("role") or "user").strip()
    password = request.form.get("password") or ""

    if not username:
        flash("Username is required", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))
    if role not in {"admin", "user"}:
        flash("Invalid role", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))
    if len(password) < 8:
        flash("Password must be at least 8 characters", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    try:
        auth_db.create_user(username=username, password=password, role=role, is_active=True)
        flash(f"User '{username}' created", "success")
    except Exception as exc:
        flash(f"Create user failed: {exc}", "danger")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/users/<int:user_id>/update", methods=["POST"])
@admin_required
def admin_update_user(user_id):
    user = auth_db.get_user_by_id(user_id)
    if not user:
        flash("User not found", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    role = (request.form.get("role") or user["role"]).strip()
    is_active = request.form.get("is_active") == "on"
    if role not in {"admin", "user"}:
        flash("Invalid role", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    # Hard-protect admin accounts: no disable/demotion from UI.
    if user["role"] == "admin" and (role != "admin" or not is_active):
        flash("Admin accounts cannot be disabled or demoted", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    auth_db.update_user(user_id=user_id, role=role, is_active=is_active)
    flash(f"User '{user['username']}' updated", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_set_password(user_id):
    user = auth_db.get_user_by_id(user_id)
    if not user:
        flash("User not found", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    new_password = request.form.get("new_password") or ""
    if len(new_password) < 8:
        flash("Password must be at least 8 characters", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    auth_db.set_password(user_id=user_id, new_password=new_password)
    flash(f"Password updated for '{user['username']}'", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = auth_db.get_user_by_id(user_id)
    if not user:
        flash("User not found", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    if user.get("role") == "admin":
        flash("Admin accounts cannot be deleted", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    auth_db.delete_user(user_id)
    flash(f"User '{user['username']}' deleted", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/apikeys/create", methods=["POST"])
@admin_required
def admin_create_api_key():
    name = (request.form.get("name") or "").strip()
    role = (request.form.get("role") or "user").strip()
    description = (request.form.get("description") or "").strip()
    if not name:
        flash("API key name is required", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))
    if role not in {"admin", "user"}:
        flash("Invalid role", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    _, plain = auth_db.create_api_key(name=name, role=role, description=description, created_by=session["user_id"])
    flash(f"API key created. Copy now: {plain}", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/apikeys/<int:key_id>/update", methods=["POST"])
@admin_required
def admin_update_api_key(key_id):
    name = (request.form.get("name") or "").strip()
    role = (request.form.get("role") or "user").strip()
    description = (request.form.get("description") or "").strip()
    is_active = request.form.get("is_active") == "on"

    if not name:
        flash("Name is required", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))
    if role not in {"admin", "user"}:
        flash("Invalid role", "danger")
        return redirect(_prefixed(url_for("auth.admin_page")))

    auth_db.update_api_key(key_id=key_id, name=name, role=role, is_active=is_active, description=description)
    flash("API key updated", "success")
    return redirect(_prefixed(url_for("auth.admin_page")))


@auth_bp.route("/admin/export-sql", methods=["GET"])
@admin_required
def admin_export_sql():
    """Export current auth DB (users + api_keys) as MySQL-compatible INSERT SQL."""
    from datetime import datetime, timezone
    from flask import Response

    users    = auth_db._fetchall("SELECT * FROM users ORDER BY id")
    api_keys = auth_db._fetchall("SELECT * FROM api_keys ORDER BY id")

    def _esc(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool) or isinstance(v, int):
            return str(int(v))
        return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = [
        "-- PyPNMGui auth export",
        f"-- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "-- Source backend: " + getattr(auth_db, 'backend', 'sqlite'),
        "",
        "CREATE DATABASE IF NOT EXISTS `pypnm_auth` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "USE `pypnm_auth`;",
        "",
        "CREATE TABLE IF NOT EXISTS `users` (",
        "  `id` BIGINT PRIMARY KEY AUTO_INCREMENT,",
        "  `username` VARCHAR(64) NOT NULL UNIQUE,",
        "  `password_hash` VARCHAR(255) NOT NULL,",
        "  `role` VARCHAR(16) NOT NULL,",
        "  `language_preference` VARCHAR(16) NOT NULL DEFAULT 'en-US',",
        "  `is_active` BOOLEAN NOT NULL DEFAULT TRUE,",
        "  `created_at` DATETIME NOT NULL,",
        "  `updated_at` DATETIME NOT NULL",
        ");",
        "",
        "CREATE TABLE IF NOT EXISTS `api_keys` (",
        "  `id` BIGINT PRIMARY KEY AUTO_INCREMENT,",
        "  `name` VARCHAR(128) NOT NULL,",
        "  `key_hash` VARCHAR(255) NOT NULL,",
        "  `key_prefix` VARCHAR(16) NOT NULL,",
        "  `role` VARCHAR(16) NOT NULL,",
        "  `is_active` BOOLEAN NOT NULL DEFAULT TRUE,",
        "  `description` VARCHAR(255),",
        "  `created_by` BIGINT,",
        "  `created_at` DATETIME NOT NULL,",
        "  `updated_at` DATETIME NOT NULL",
        ");",
        "",
    ]

    if users:
        lines.append("-- Users")
        for u in users:
            cols = "(`username`, `password_hash`, `role`, `language_preference`, `is_active`, `created_at`, `updated_at`)"
            vals = ", ".join(_esc(u.get(c)) for c in ("username", "password_hash", "role", "language_preference", "is_active", "created_at", "updated_at"))
            lines.append(f"INSERT IGNORE INTO `users` {cols} VALUES ({vals});")
        lines.append("")

    if api_keys:
        lines.append("-- API Keys")
        for k in api_keys:
            cols = "(`name`, `key_hash`, `key_prefix`, `role`, `is_active`, `description`, `created_by`, `created_at`, `updated_at`)"
            vals = ", ".join(_esc(k[c]) for c in ("name", "key_hash", "key_prefix", "role", "is_active", "description", "created_by", "created_at", "updated_at"))
            lines.append(f"INSERT IGNORE INTO `api_keys` {cols} VALUES ({vals});")
        lines.append("")

    sql = "\n".join(lines)
    return Response(
        sql,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=pypnm_auth_export.sql"}
    )


@auth_bp.route("/api/auth/me", methods=["GET"])
def auth_me():
    if not session.get("user_id"):
        return jsonify({"authenticated": False}), 401
    return jsonify(
        {
            "authenticated": True,
            "user": {
                "id": session.get("user_id"),
                "username": session.get("username"),
                "role": session.get("role"),
                "locale": normalize_locale(session.get("locale") or DEFAULT_LOCALE),
            },
        }
    )
