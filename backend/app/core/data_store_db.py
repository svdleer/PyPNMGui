import os
import json
import sqlite3
from datetime import datetime, timezone
from app.core.modem_filters import is_ignored_modem_ip, get_modem_ignore_networks


class DataStoreDB:
    """Data-store backend for cache-backed modem inventory and RF snapshots.

    Uses MySQL by default when existing AUTH_DB_* env vars are configured, so it
    can start from the already running MySQL database.
    """

    def __init__(self):
        self.backend = self._detect_backend()
        self.sqlite_path = os.environ.get("DATA_SQLITE_PATH", "/app/data/data_store.db")

    def _detect_backend(self):
        explicit = os.environ.get("DATA_DB_BACKEND", "").lower()
        if explicit in ("mysql", "sqlite"):
            return explicit
        if os.environ.get("DATA_DB_HOST"):
            return "mysql"
        if os.environ.get("AUTH_DB_BACKEND", "").lower() == "mysql" or os.environ.get("AUTH_DB_HOST"):
            return "mysql"
        return "sqlite"

    def _db_name(self):
        return (
            os.environ.get("DATA_DB_NAME")
            or os.environ.get("AUTH_DB_NAME")
            or "pypnm_auth"
        )

    def _connect(self):
        if self.backend == "mysql":
            try:
                import pymysql
            except ImportError as exc:
                raise RuntimeError("MySQL data-store backend selected but pymysql is not installed") from exc
            return pymysql.connect(
                host=os.environ.get("DATA_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("DATA_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306")),
                user=os.environ.get("DATA_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm"),
                password=os.environ.get("DATA_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
                database=self._db_name(),
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )

        os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _execute_ddl_safe(self, cur, ddl):
        try:
            cur.execute(ddl)
        except Exception as exc:
            # Index/table can already exist on MySQL variants lacking IF NOT EXISTS support.
            msg = str(exc).lower()
            if "duplicate key name" in msg or "already exists" in msg:
                return
            raise

    def init_db(self):
        conn = self._connect()
        cur = conn.cursor()

        if self.backend == "mysql":
            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS modem_inventory_current (
                    mac VARCHAR(17) NOT NULL,
                    ip VARCHAR(45) NULL,
                    cmts VARCHAR(128) NOT NULL,
                    cmts_ip VARCHAR(45) NULL,
                    fiber_node VARCHAR(128) NULL,
                    cable_mac VARCHAR(128) NULL,
                    status VARCHAR(64) NULL,
                    docsis_version VARCHAR(32) NULL,
                    vendor VARCHAR(64) NULL,
                    model VARCHAR(128) NULL,
                    upstream_interface VARCHAR(128) NULL,
                    ofdm_enabled BOOLEAN NULL,
                    ofdma_enabled BOOLEAN NULL,
                    partial_service BOOLEAN NULL,
                    ofdma_ifindex INT NULL,
                    upstream_ifindex INT NULL,
                    first_seen_at DATETIME NOT NULL,
                    last_seen_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    source_poller VARCHAR(64) NULL,
                    PRIMARY KEY (mac)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS modem_rf_snapshot (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    mac VARCHAR(17) NOT NULL,
                    cmts VARCHAR(128) NOT NULL,
                    collected_at DATETIME NOT NULL,
                    scqam_json JSON NULL,
                    rxmer_json JSON NULL,
                    poller_name VARCHAR(64) NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS poller_setting (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(64) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    scope_type VARCHAR(16) NOT NULL DEFAULT 'all_cmts',
                    scope_json JSON NULL,
                    collect_identity BOOLEAN NOT NULL DEFAULT TRUE,
                    collect_scqam BOOLEAN NOT NULL DEFAULT FALSE,
                    collect_rxmer BOOLEAN NOT NULL DEFAULT FALSE,
                    interval_minutes INT NOT NULL DEFAULT 1440,
                    run_window_start TIME NULL,
                    run_window_end TIME NULL,
                    max_concurrency INT NOT NULL DEFAULT 1,
                    max_agent_queue_depth INT NOT NULL DEFAULT 20,
                    retention_days INT NOT NULL DEFAULT 30,
                    heavy_window_start TIME NULL,
                    heavy_window_end TIME NULL,
                    heavy_max_modems INT NOT NULL DEFAULT 300,
                    heavy_delay_ms INT NOT NULL DEFAULT 0,
                    max_runtime_sec INT NOT NULL DEFAULT 3600,
                    last_target_offset INT NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    UNIQUE KEY uk_poller_setting_name (name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS poller_job (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    poller_id BIGINT NOT NULL,
                    trigger_type VARCHAR(24) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'queued',
                    rows_collected INT NOT NULL DEFAULT 0,
                    modems_attempted INT NOT NULL DEFAULT 0,
                    modems_succeeded INT NOT NULL DEFAULT 0,
                    modems_failed INT NOT NULL DEFAULT 0,
                    requested_by VARCHAR(64) NULL,
                    request_payload JSON NULL,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    error_text TEXT NULL,
                    cmts_breakdown JSON NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT fk_poller_job_setting FOREIGN KEY (poller_id) REFERENCES poller_setting(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS modem_refresh_request (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    mac VARCHAR(17) NOT NULL,
                    cmts VARCHAR(128) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'queued',
                    requested_by VARCHAR(64) NULL,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME NULL,
                    finished_at DATETIME NULL,
                    error_text TEXT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS scheduler_decision_log (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    tick_at DATETIME NOT NULL,
                    poller_id BIGINT NULL,
                    poller_name VARCHAR(64) NULL,
                    decision VARCHAR(16) NOT NULL,
                    reason VARCHAR(64) NULL,
                    effective_load INT NULL,
                    threshold INT NULL,
                    detail VARCHAR(255) NULL,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            self._execute_ddl_safe(cur, """
                CREATE TABLE IF NOT EXISTS retention_cleanup_log (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    retention_days INT NOT NULL,
                    deleted_count INT NOT NULL,
                    created_at DATETIME NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # Ensure backward-compatible column additions on existing deployments.
            try:
                cur.execute("ALTER TABLE poller_job ADD COLUMN rows_collected INT NOT NULL DEFAULT 0")
            except Exception as exc:
                msg = str(exc).lower()
                if "duplicate" not in msg and "exists" not in msg:
                    raise
            for ddl in [
                "ALTER TABLE poller_setting ADD COLUMN heavy_window_start TIME NULL",
                "ALTER TABLE poller_setting ADD COLUMN heavy_window_end TIME NULL",
                "ALTER TABLE poller_setting ADD COLUMN heavy_max_modems INT NOT NULL DEFAULT 300",
                "ALTER TABLE poller_setting ADD COLUMN heavy_delay_ms INT NOT NULL DEFAULT 0",
                "ALTER TABLE poller_setting ADD COLUMN max_runtime_sec INT NOT NULL DEFAULT 3600",
                "ALTER TABLE poller_setting ADD COLUMN last_target_offset INT NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_attempted INT NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_succeeded INT NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_failed INT NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN cmts_breakdown JSON NULL",
                "ALTER TABLE modem_inventory_current ADD COLUMN source_poller VARCHAR(64) NULL",
                "ALTER TABLE modem_inventory_current ADD COLUMN ofdma_ifindex INT NULL",
                "ALTER TABLE modem_inventory_current ADD COLUMN upstream_ifindex INT NULL",
            ]:
                try:
                    cur.execute(ddl)
                except Exception as exc:
                    msg = str(exc).lower()
                    if "duplicate" not in msg and "exists" not in msg:
                        raise

            # Indexes (explicit, so existing DBs get tuned too)
            for ddl in [
                "CREATE INDEX idx_inventory_cmts ON modem_inventory_current(cmts)",
                "CREATE INDEX idx_inventory_updated ON modem_inventory_current(updated_at)",
                "CREATE INDEX idx_inventory_fiber ON modem_inventory_current(fiber_node)",
                "CREATE INDEX idx_inventory_status ON modem_inventory_current(status)",
                "CREATE INDEX idx_snapshot_mac_time ON modem_rf_snapshot(mac, collected_at)",
                "CREATE INDEX idx_snapshot_cmts_time ON modem_rf_snapshot(cmts, collected_at)",
                "CREATE INDEX idx_snapshot_collected ON modem_rf_snapshot(collected_at)",
                "CREATE INDEX idx_job_poller_status ON poller_job(poller_id, status)",
                "CREATE INDEX idx_job_created ON poller_job(created_at)",
                "CREATE INDEX idx_refresh_mac_created ON modem_refresh_request(mac, created_at)",
                "CREATE INDEX idx_refresh_status_created ON modem_refresh_request(status, created_at)",
            ]:
                self._execute_ddl_safe(cur, ddl)

        else:
            # SQLite fallback for local development.
            cur.execute("""
                CREATE TABLE IF NOT EXISTS modem_inventory_current (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    cmts TEXT NOT NULL,
                    cmts_ip TEXT,
                    fiber_node TEXT,
                    cable_mac TEXT,
                    status TEXT,
                    docsis_version TEXT,
                    vendor TEXT,
                    model TEXT,
                    upstream_interface TEXT,
                    ofdm_enabled INTEGER,
                    ofdma_enabled INTEGER,
                    partial_service INTEGER,
                    ofdma_ifindex INTEGER,
                    upstream_ifindex INTEGER,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_poller TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS modem_rf_snapshot (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mac TEXT NOT NULL,
                    cmts TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    scqam_json TEXT,
                    rxmer_json TEXT,
                    poller_name TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS poller_setting (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    scope_type TEXT NOT NULL DEFAULT 'all_cmts',
                    scope_json TEXT,
                    collect_identity INTEGER NOT NULL DEFAULT 1,
                    collect_scqam INTEGER NOT NULL DEFAULT 0,
                    collect_rxmer INTEGER NOT NULL DEFAULT 0,
                    interval_minutes INTEGER NOT NULL DEFAULT 1440,
                    run_window_start TEXT,
                    run_window_end TEXT,
                    max_concurrency INTEGER NOT NULL DEFAULT 1,
                    max_agent_queue_depth INTEGER NOT NULL DEFAULT 20,
                    retention_days INTEGER NOT NULL DEFAULT 30,
                    heavy_window_start TEXT,
                    heavy_window_end TEXT,
                    heavy_max_modems INTEGER NOT NULL DEFAULT 300,
                    heavy_delay_ms INTEGER NOT NULL DEFAULT 0,
                    max_runtime_sec INTEGER NOT NULL DEFAULT 3600,
                    last_target_offset INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS poller_job (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poller_id INTEGER NOT NULL,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    rows_collected INTEGER NOT NULL DEFAULT 0,
                    modems_attempted INTEGER NOT NULL DEFAULT 0,
                    modems_succeeded INTEGER NOT NULL DEFAULT 0,
                    modems_failed INTEGER NOT NULL DEFAULT 0,
                    requested_by TEXT,
                    request_payload TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    error_text TEXT,
                    cmts_breakdown TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(poller_id) REFERENCES poller_setting(id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS modem_refresh_request (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mac TEXT NOT NULL,
                    cmts TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    requested_by TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error_text TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_decision_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tick_at TEXT NOT NULL,
                    poller_id INTEGER NULL,
                    poller_name TEXT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NULL,
                    effective_load INTEGER NULL,
                    threshold INTEGER NULL,
                    detail TEXT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS retention_cleanup_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    retention_days INTEGER NOT NULL,
                    deleted_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            try:
                cur.execute("ALTER TABLE poller_job ADD COLUMN rows_collected INTEGER NOT NULL DEFAULT 0")
            except Exception as exc:
                msg = str(exc).lower()
                if "duplicate" not in msg and "exists" not in msg and "duplicate column" not in msg:
                    raise
            for ddl in [
                "ALTER TABLE poller_setting ADD COLUMN heavy_window_start TEXT",
                "ALTER TABLE poller_setting ADD COLUMN heavy_window_end TEXT",
                "ALTER TABLE poller_setting ADD COLUMN heavy_max_modems INTEGER NOT NULL DEFAULT 300",
                "ALTER TABLE poller_setting ADD COLUMN heavy_delay_ms INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE poller_setting ADD COLUMN max_runtime_sec INTEGER NOT NULL DEFAULT 3600",
                "ALTER TABLE poller_setting ADD COLUMN last_target_offset INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_attempted INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_succeeded INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN modems_failed INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE poller_job ADD COLUMN cmts_breakdown TEXT",
            ]:
                try:
                    cur.execute(ddl)
                except Exception as exc:
                    msg = str(exc).lower()
                    if "duplicate" not in msg and "exists" not in msg and "duplicate column" not in msg:
                        raise
            for ddl in [
                "CREATE INDEX IF NOT EXISTS idx_inventory_cmts ON modem_inventory_current(cmts)",
                "CREATE INDEX IF NOT EXISTS idx_inventory_updated ON modem_inventory_current(updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_inventory_fiber ON modem_inventory_current(fiber_node)",
                "CREATE INDEX IF NOT EXISTS idx_inventory_status ON modem_inventory_current(status)",
                "CREATE INDEX IF NOT EXISTS idx_snapshot_mac_time ON modem_rf_snapshot(mac, collected_at)",
                "CREATE INDEX IF NOT EXISTS idx_snapshot_cmts_time ON modem_rf_snapshot(cmts, collected_at)",
                "CREATE INDEX IF NOT EXISTS idx_snapshot_collected ON modem_rf_snapshot(collected_at)",
                "CREATE INDEX IF NOT EXISTS idx_job_poller_status ON poller_job(poller_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_job_created ON poller_job(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_refresh_mac_created ON modem_refresh_request(mac, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_refresh_status_created ON modem_refresh_request(status, created_at)",
            ]:
                cur.execute(ddl)
            conn.commit()

        self._ensure_default_poller(cur)
        if self.backend != "mysql":
            conn.commit()

        try:
            conn.close()
        except Exception:
            pass

    def _ensure_default_poller(self, cur):
        now = self._now()
        if self.backend == "mysql":
            cur.execute("SELECT id FROM poller_setting WHERE name=%s", ("default-minimum",))
            row = cur.fetchone()
            if row:
                return
            cur.execute(
                """
                INSERT INTO poller_setting
                (name, enabled, scope_type, collect_identity, collect_scqam, collect_rxmer,
                 interval_minutes, max_concurrency, max_agent_queue_depth, retention_days,
                 heavy_window_start, heavy_window_end, heavy_max_modems, heavy_delay_ms, max_runtime_sec,
                 created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                ("default-minimum", 1, "all_cmts", 1, 0, 0, 1440, 4, 20, 30, "00:30", "05:30", 300, 0, 14400, now, now),
            )
            return

        cur.execute("SELECT id FROM poller_setting WHERE name=?", ("default-minimum",))
        row = cur.fetchone()
        if row:
            return
        cur.execute(
            """
            INSERT INTO poller_setting
            (name, enabled, scope_type, collect_identity, collect_scqam, collect_rxmer,
             interval_minutes, max_concurrency, max_agent_queue_depth, retention_days,
             heavy_window_start, heavy_window_end, heavy_max_modems, heavy_delay_ms, max_runtime_sec,
             created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("default-minimum", 1, "all_cmts", 1, 0, 0, 1440, 4, 20, 30, "00:30", "05:30", 300, 0, 14400, now, now),
        )

    def list_poller_settings(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM poller_setting ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        return [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]

    def upsert_poller_setting(self, payload):
        now = self._now()
        poller_id = payload.get("id")
        fields = {
            "name": payload.get("name", "default-minimum"),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "scope_type": payload.get("scope_type", "all_cmts"),
            "scope_json": payload.get("scope_json"),
            "collect_identity": 1 if payload.get("collect_identity", True) else 0,
            "collect_scqam": 1 if payload.get("collect_scqam", False) else 0,
            "collect_rxmer": 1 if payload.get("collect_rxmer", False) else 0,
            "interval_minutes": int(payload.get("interval_minutes", 1440)),
            "run_window_start": payload.get("run_window_start"),
            "run_window_end": payload.get("run_window_end"),
            "max_concurrency": int(payload.get("max_concurrency", 4)),
            "max_agent_queue_depth": int(payload.get("max_agent_queue_depth", 20)),
            "retention_days": int(payload.get("retention_days", 30)),
            "heavy_window_start": payload.get("heavy_window_start") or "00:30",
            "heavy_window_end": payload.get("heavy_window_end") or "05:30",
            "heavy_max_modems": int(payload.get("heavy_max_modems", 300)),
            "heavy_delay_ms": int(payload.get("heavy_delay_ms", 0)),
               "max_runtime_sec": int(payload.get("max_runtime_sec", 3600)),
        }

        conn = self._connect()
        cur = conn.cursor()
        if poller_id:
            if self.backend == "mysql":
                cur.execute(
                    """
                    UPDATE poller_setting SET
                        name=%s, enabled=%s, scope_type=%s, scope_json=%s,
                        collect_identity=%s, collect_scqam=%s, collect_rxmer=%s,
                        interval_minutes=%s, run_window_start=%s, run_window_end=%s,
                        max_concurrency=%s, max_agent_queue_depth=%s, retention_days=%s,
                        heavy_window_start=%s, heavy_window_end=%s, heavy_max_modems=%s, heavy_delay_ms=%s,
                           max_runtime_sec=%s,
                        updated_at=%s
                    WHERE id=%s
                    """,
                    (
                        fields["name"], fields["enabled"], fields["scope_type"], fields["scope_json"],
                        fields["collect_identity"], fields["collect_scqam"], fields["collect_rxmer"],
                        fields["interval_minutes"], fields["run_window_start"], fields["run_window_end"],
                        fields["max_concurrency"], fields["max_agent_queue_depth"], fields["retention_days"],
                        fields["heavy_window_start"], fields["heavy_window_end"], fields["heavy_max_modems"], fields["heavy_delay_ms"],
                           fields["max_runtime_sec"],
                        now, int(poller_id),
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE poller_setting SET
                        name=?, enabled=?, scope_type=?, scope_json=?,
                        collect_identity=?, collect_scqam=?, collect_rxmer=?,
                        interval_minutes=?, run_window_start=?, run_window_end=?,
                        max_concurrency=?, max_agent_queue_depth=?, retention_days=?,
                        heavy_window_start=?, heavy_window_end=?, heavy_max_modems=?, heavy_delay_ms=?,
                           max_runtime_sec=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        fields["name"], fields["enabled"], fields["scope_type"], fields["scope_json"],
                        fields["collect_identity"], fields["collect_scqam"], fields["collect_rxmer"],
                        fields["interval_minutes"], fields["run_window_start"], fields["run_window_end"],
                        fields["max_concurrency"], fields["max_agent_queue_depth"], fields["retention_days"],
                        fields["heavy_window_start"], fields["heavy_window_end"], fields["heavy_max_modems"], fields["heavy_delay_ms"],
                           fields["max_runtime_sec"],
                        now, int(poller_id),
                    ),
                )
                conn.commit()
            saved_id = int(poller_id)
        else:
            if self.backend == "mysql":
                cur.execute(
                    """
                    INSERT INTO poller_setting
                    (name, enabled, scope_type, scope_json, collect_identity, collect_scqam, collect_rxmer,
                     interval_minutes, run_window_start, run_window_end, max_concurrency,
                     max_agent_queue_depth, retention_days, heavy_window_start, heavy_window_end, heavy_max_modems, heavy_delay_ms,
                        max_runtime_sec,
                     created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        fields["name"], fields["enabled"], fields["scope_type"], fields["scope_json"],
                        fields["collect_identity"], fields["collect_scqam"], fields["collect_rxmer"],
                        fields["interval_minutes"], fields["run_window_start"], fields["run_window_end"],
                        fields["max_concurrency"], fields["max_agent_queue_depth"], fields["retention_days"],
                        fields["heavy_window_start"], fields["heavy_window_end"], fields["heavy_max_modems"], fields["heavy_delay_ms"],
                           fields["max_runtime_sec"],
                        now, now,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO poller_setting
                    (name, enabled, scope_type, scope_json, collect_identity, collect_scqam, collect_rxmer,
                     interval_minutes, run_window_start, run_window_end, max_concurrency,
                     max_agent_queue_depth, retention_days, heavy_window_start, heavy_window_end, heavy_max_modems, heavy_delay_ms,
                        max_runtime_sec,
                     created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fields["name"], fields["enabled"], fields["scope_type"], fields["scope_json"],
                        fields["collect_identity"], fields["collect_scqam"], fields["collect_rxmer"],
                        fields["interval_minutes"], fields["run_window_start"], fields["run_window_end"],
                        fields["max_concurrency"], fields["max_agent_queue_depth"], fields["retention_days"],
                        fields["heavy_window_start"], fields["heavy_window_end"], fields["heavy_max_modems"], fields["heavy_delay_ms"],
                           fields["max_runtime_sec"],
                        now, now,
                    ),
                )
                conn.commit()
            saved_id = int(cur.lastrowid)

        conn.close()
        return saved_id

    def delete_poller_setting(self, poller_id):
        """Hard-delete a poller setting and all related jobs.

        Active queued/running jobs are marked cancelled first, then all poller_job
        rows for this poller are removed so the setting can be deleted reliably.

        Returns dict: {deleted: bool, reason: str|None, active_jobs: int}
        """
        pid = int(poller_id)
        conn = self._connect()
        cur = conn.cursor()

        q_active = (
            "SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=%s AND status IN ('queued','running')"
            if self.backend == "mysql"
            else "SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=? AND status IN ('queued','running')"
        )
        cur.execute(q_active, (pid,))
        row = cur.fetchone()
        active = int((row["c"] if isinstance(row, sqlite3.Row) else row.get("c")) or 0)

        # Cancel active jobs first so deletion is deterministic for admins.
        if active > 0:
            now = self._now()
            q_cancel_active = (
                "UPDATE poller_job SET status=%s, finished_at=%s, error_text=%s WHERE poller_id=%s AND status IN ('queued','running')"
                if self.backend == "mysql"
                else "UPDATE poller_job SET status=?, finished_at=?, error_text=? WHERE poller_id=? AND status IN ('queued','running')"
            )
            cur.execute(q_cancel_active, ("cancelled", now, "Cancelled due to poller deletion", pid))

        # Remove all child rows first; FK on poller_job(poller_id)
        # blocks deleting poller_setting.
        q_del_jobs = (
            "DELETE FROM poller_job WHERE poller_id=%s"
            if self.backend == "mysql"
            else "DELETE FROM poller_job WHERE poller_id=?"
        )
        cur.execute(q_del_jobs, (pid,))

        q_del = (
            "DELETE FROM poller_setting WHERE id=%s"
            if self.backend == "mysql"
            else "DELETE FROM poller_setting WHERE id=?"
        )
        cur.execute(q_del, (pid,))
        deleted = int(cur.rowcount or 0)
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return {"deleted": deleted == 1, "reason": None if deleted == 1 else "not_found", "active_jobs": active}

    def enqueue_poller_run(self, poller_id, trigger_type="manual", requested_by=None, payload=None):
        now = self._now()
        payload_str = None
        if payload is not None:
            if isinstance(payload, str):
                # MySQL JSON columns require valid JSON text.
                try:
                    json.loads(payload)
                    payload_str = payload
                except Exception:
                    payload_str = json.dumps({"raw": payload})
            else:
                payload_str = json.dumps(payload)
        conn = self._connect()
        cur = conn.cursor()
        if self.backend == "mysql":
            cur.execute(
                """
                INSERT INTO poller_job
                (poller_id, trigger_type, status, requested_by, request_payload, created_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (int(poller_id), trigger_type, "queued", requested_by, payload_str, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO poller_job
                (poller_id, trigger_type, status, requested_by, request_payload, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (int(poller_id), trigger_type, "queued", requested_by, payload_str, now),
            )
            conn.commit()
        job_id = int(cur.lastrowid)
        conn.close()
        return job_id

    def list_jobs(self, status=None, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        conn = self._connect()
        cur = conn.cursor()
        if status:
            q = (
                "SELECT * FROM poller_job WHERE status=%s ORDER BY id DESC LIMIT %s"
                if self.backend == "mysql"
                else "SELECT * FROM poller_job WHERE status=? ORDER BY id DESC LIMIT ?"
            )
            cur.execute(q, (status, limit))
        else:
            q = (
                "SELECT * FROM poller_job ORDER BY id DESC LIMIT %s"
                if self.backend == "mysql"
                else "SELECT * FROM poller_job ORDER BY id DESC LIMIT ?"
            )
            cur.execute(q, (limit,))
        rows = cur.fetchall()
        conn.close()
        out = [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]
        for row in out:
            st = row.get("started_at")
            fn = row.get("finished_at")
            row["duration_seconds"] = None
            row["cmts_breakdown_obj"] = None
            if st and fn:
                try:
                    sdt = datetime.fromisoformat(str(st).replace("Z", ""))
                    fdt = datetime.fromisoformat(str(fn).replace("Z", ""))
                    row["duration_seconds"] = int((fdt - sdt).total_seconds())
                except Exception:
                    pass
            cbd = row.get("cmts_breakdown")
            if cbd:
                try:
                    row["cmts_breakdown_obj"] = json.loads(cbd) if isinstance(cbd, str) else cbd
                except Exception:
                    row["cmts_breakdown_obj"] = None
        return out

    def clear_finished_jobs(self):
        """Clear non-active terminal jobs, keep queued/running jobs."""
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "DELETE FROM poller_job WHERE status IN ('completed','done','failed','timed_out','cancelled')"
            if self.backend == "mysql"
            else "DELETE FROM poller_job WHERE status IN ('completed','done','failed','timed_out','cancelled')"
        )
        cur.execute(q)
        deleted = int(cur.rowcount or 0)
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return deleted

    def clear_inactive_jobs(self):
        """Clear all non-active jobs, keep queued/running jobs only."""
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "DELETE FROM poller_job WHERE status NOT IN ('queued','running')"
            if self.backend == "mysql"
            else "DELETE FROM poller_job WHERE status NOT IN ('queued','running')"
        )
        cur.execute(q)
        deleted = int(cur.rowcount or 0)
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return deleted

    def get_poller_setting_by_id(self, poller_id):
        conn = self._connect()
        cur = conn.cursor()
        q = "SELECT * FROM poller_setting WHERE id=%s" if self.backend == "mysql" else "SELECT * FROM poller_setting WHERE id=?"
        cur.execute(q, (int(poller_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return dict(row) if isinstance(row, sqlite3.Row) else row

    def advance_poller_target_offset(self, poller_id, total_targets, processed_targets):
        total_targets = int(total_targets or 0)
        if total_targets <= 0:
            return
        processed_targets = max(0, int(processed_targets or 0))

        conn = self._connect()
        cur = conn.cursor()
        sel = "SELECT last_target_offset FROM poller_setting WHERE id=%s" if self.backend == "mysql" else "SELECT last_target_offset FROM poller_setting WHERE id=?"
        cur.execute(sel, (int(poller_id),))
        row = cur.fetchone()
        current_offset = 0
        if row:
            current_offset = int((row["last_target_offset"] if isinstance(row, sqlite3.Row) else row.get("last_target_offset")) or 0)

        new_offset = (current_offset + processed_targets) % total_targets
        upd = "UPDATE poller_setting SET last_target_offset=%s WHERE id=%s" if self.backend == "mysql" else "UPDATE poller_setting SET last_target_offset=? WHERE id=?"
        cur.execute(upd, (new_offset, int(poller_id)))
        if self.backend != "mysql":
            conn.commit()
        conn.close()

    def claim_next_job(self):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        sel = "SELECT * FROM poller_job WHERE status=%s ORDER BY id ASC LIMIT 1" if self.backend == "mysql" else "SELECT * FROM poller_job WHERE status=? ORDER BY id ASC LIMIT 1"
        cur.execute(sel, ("queued",))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        job = dict(row) if isinstance(row, sqlite3.Row) else row
        upd = "UPDATE poller_job SET status=%s, started_at=%s WHERE id=%s AND status=%s" if self.backend == "mysql" else "UPDATE poller_job SET status=?, started_at=? WHERE id=? AND status=?"
        cur.execute(upd, ("running", now, int(job["id"]), "queued"))
        if self.backend != "mysql":
            conn.commit()
        # rowcount guard avoids double-claim in race conditions
        if getattr(cur, "rowcount", 0) != 1:
            conn.close()
            return None
        conn.close()
        job["status"] = "running"
        job["started_at"] = now
        return job

    def poller_has_active_job(self, poller_id):
        return self.get_active_job_for_poller(poller_id) is not None

    def get_active_job_for_poller(self, poller_id):
        """Return the most recent queued/running job for a poller, with age_sec."""
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "SELECT id, status, started_at, created_at FROM poller_job WHERE poller_id=%s AND status IN ('queued','running') ORDER BY id DESC LIMIT 1"
            if self.backend == "mysql"
            else "SELECT id, status, started_at, created_at FROM poller_job WHERE poller_id=? AND status IN ('queued','running') ORDER BY id DESC LIMIT 1"
        )
        cur.execute(q, (int(poller_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        job = dict(row) if isinstance(row, sqlite3.Row) else row
        ts_raw = job.get("started_at") or job.get("created_at")
        job["age_sec"] = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", ""))
                job["age_sec"] = int((datetime.now() - ts).total_seconds())
            except Exception:
                pass
        return job

    def get_active_job_count_for_poller(self, poller_id):
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=%s AND status IN ('queued','running')"
            if self.backend == "mysql"
            else "SELECT COUNT(*) AS c FROM poller_job WHERE poller_id=? AND status IN ('queued','running')"
        )
        cur.execute(q, (int(poller_id),))
        row = cur.fetchone()
        conn.close()
        return int((row["c"] if isinstance(row, sqlite3.Row) else row.get("c")) or 0)

    def get_running_heavy_job_count(self):
        conn = self._connect()
        cur = conn.cursor()
        q = (
            """
            SELECT COUNT(*) AS c
            FROM poller_job j
            JOIN poller_setting p ON p.id = j.poller_id
            WHERE j.status = 'running'
              AND (COALESCE(p.collect_scqam,0) = 1 OR COALESCE(p.collect_rxmer,0) = 1)
            """
        )
        cur.execute(q)
        row = cur.fetchone()
        conn.close()
        return int((row["c"] if isinstance(row, sqlite3.Row) else row.get("c")) or 0)

    def timeout_stale_jobs(self):
        """Mark running jobs as timed_out if they exceed their poller's max_runtime_sec.
        Returns list of job IDs that were timed out."""
        now_local = datetime.now()
        now_str = self._now()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("""
            SELECT cj.id, cj.started_at, cp.max_runtime_sec
            FROM poller_job cj
            JOIN poller_setting cp ON cp.id = cj.poller_id
            WHERE cj.status = 'running'
        """)
        rows = cur.fetchall()
        timed_out = []
        for row in rows:
            r = dict(row) if isinstance(row, sqlite3.Row) else row
            started_raw = r.get("started_at")
            if not started_raw:
                continue
            try:
                started = datetime.fromisoformat(str(started_raw).replace("Z", ""))
                # Compare as naive local — MySQL/SQLite store local time.
                if started.tzinfo is not None:
                    started = started.replace(tzinfo=None)
                elapsed = (now_local - started).total_seconds()
            except Exception:
                continue
            max_rt = max(60, int(r.get("max_runtime_sec") or 3600))
            if elapsed > max_rt:
                upd = (
                    "UPDATE poller_job SET status=%s, finished_at=%s, error_text=%s WHERE id=%s"
                    if self.backend == "mysql"
                    else "UPDATE poller_job SET status=?, finished_at=?, error_text=? WHERE id=?"
                )
                cur.execute(upd, ("timed_out", now_str, f"Timed out after {int(elapsed)}s (limit {max_rt}s)", int(r["id"])))
                timed_out.append(int(r["id"]))
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return timed_out

    def get_poller_last_job_created_at(self, poller_id):
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "SELECT created_at FROM poller_job WHERE poller_id=%s ORDER BY id DESC LIMIT 1"
            if self.backend == "mysql"
            else "SELECT created_at FROM poller_job WHERE poller_id=? ORDER BY id DESC LIMIT 1"
        )
        cur.execute(q, (int(poller_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return row["created_at"] if isinstance(row, sqlite3.Row) else row.get("created_at")

    def get_internal_queue_depth(self):
        conn = self._connect()
        cur = conn.cursor()
        if self.backend == "mysql":
            cur.execute("SELECT COUNT(*) AS c FROM poller_job WHERE status IN ('queued','running')")
            job_row = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c FROM modem_refresh_request WHERE status IN ('queued','running')")
            refresh_row = cur.fetchone()
        else:
            cur.execute("SELECT COUNT(*) AS c FROM poller_job WHERE status IN ('queued','running')")
            job_row = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS c FROM modem_refresh_request WHERE status IN ('queued','running')")
            refresh_row = cur.fetchone()
        conn.close()
        jc = int((job_row["c"] if isinstance(job_row, sqlite3.Row) else job_row.get("c")) or 0)
        rc = int((refresh_row["c"] if isinstance(refresh_row, sqlite3.Row) else refresh_row.get("c")) or 0)
        return jc + rc

    def complete_job(self, job_id, rows_collected=0, error_text=None, modems_attempted=0, modems_succeeded=0, modems_failed=0, cmts_breakdown=None, status_override=None):
        now = self._now()
        status = status_override or ("failed" if error_text else "completed")
        breakdown_str = json.dumps(cmts_breakdown) if cmts_breakdown else None
        conn = self._connect()
        cur = conn.cursor()
        upd = (
            "UPDATE poller_job SET status=%s, rows_collected=%s, modems_attempted=%s, modems_succeeded=%s, modems_failed=%s, finished_at=%s, error_text=%s, cmts_breakdown=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE poller_job SET status=?, rows_collected=?, modems_attempted=?, modems_succeeded=?, modems_failed=?, finished_at=?, error_text=?, cmts_breakdown=? WHERE id=?"
        )
        cur.execute(
            upd,
            (
                status,
                int(rows_collected or 0),
                int(modems_attempted or 0),
                int(modems_succeeded or 0),
                int(modems_failed or 0),
                now,
                error_text,
                breakdown_str,
                int(job_id),
            ),
        )
        if self.backend != "mysql":
            conn.commit()
        conn.close()

    def is_job_cancelled(self, job_id: int) -> bool:
        """Check if a job has been cancelled (e.g. by admin UI)."""
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "SELECT status FROM poller_job WHERE id=%s"
            if self.backend == "mysql"
            else "SELECT status FROM poller_job WHERE id=?"
        )
        cur.execute(q, (int(job_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return True  # job vanished — treat as cancelled
        status = row["status"] if isinstance(row, dict) else (row[0] if isinstance(row, tuple) else row["status"])
        return status == "cancelled"

    def cancel_poller_job(self, job_id, reason="Cancelled by admin"):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        upd = (
            "UPDATE poller_job SET status=%s, finished_at=%s, error_text=%s WHERE id=%s AND status IN ('queued','running')"
            if self.backend == "mysql"
            else "UPDATE poller_job SET status=?, finished_at=?, error_text=? WHERE id=? AND status IN ('queued','running')"
        )
        cur.execute(upd, ("cancelled", now, reason, int(job_id)))
        changed = int(cur.rowcount or 0)
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return changed == 1

    def upsert_inventory_rows(self, rows, source_poller=None):
        if not rows:
            return 0
        rows = [m for m in rows if not is_ignored_modem_ip((m or {}).get("ip_address"))]
        if not rows:
            # Keep DB clean from already persisted ignored ranges.
            self.purge_ignored_inventory_rows()
            return 0
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        written = 0
        if self.backend == "mysql":
            q = """
                INSERT INTO modem_inventory_current
                (mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version,
                 vendor, model, upstream_interface, ofdm_enabled, ofdma_enabled,
                 partial_service, ofdma_ifindex, upstream_ifindex,
                 first_seen_at, last_seen_at, updated_at, source_poller)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    ip=COALESCE(VALUES(ip), ip),
                    cmts=COALESCE(VALUES(cmts), cmts),
                    cmts_ip=COALESCE(VALUES(cmts_ip), cmts_ip),
                    fiber_node=COALESCE(VALUES(fiber_node), fiber_node),
                    cable_mac=COALESCE(VALUES(cable_mac), cable_mac),
                    status=COALESCE(VALUES(status), status),
                    docsis_version=COALESCE(VALUES(docsis_version), docsis_version),
                    vendor=COALESCE(VALUES(vendor), vendor),
                    model=COALESCE(VALUES(model), model),
                    upstream_interface=COALESCE(VALUES(upstream_interface), upstream_interface),
                    ofdm_enabled=COALESCE(VALUES(ofdm_enabled), ofdm_enabled),
                    ofdma_enabled=COALESCE(VALUES(ofdma_enabled), ofdma_enabled),
                    partial_service=COALESCE(VALUES(partial_service), partial_service),
                    ofdma_ifindex=COALESCE(VALUES(ofdma_ifindex), ofdma_ifindex),
                    upstream_ifindex=COALESCE(VALUES(upstream_ifindex), upstream_ifindex),
                    last_seen_at=VALUES(last_seen_at), updated_at=VALUES(updated_at),
                    source_poller=VALUES(source_poller)
            """
            for m in rows:
                cur.execute(
                    q,
                    (
                        m.get("mac_address"), m.get("ip_address"), m.get("cmts"), m.get("cmts_ip"),
                        m.get("fiber_node"), m.get("cable_mac"), m.get("status"), m.get("docsis_version"),
                        m.get("vendor"), m.get("model"), m.get("upstream_interface"),
                        m.get("ofdm_enabled"), m.get("ofdma_enabled"), m.get("partial_service"),
                        m.get("ofdma_ifindex"), m.get("upstream_ifindex"),
                        now, now, now, source_poller,
                    ),
                )
                written += 1
        else:
            q = """
                INSERT INTO modem_inventory_current
                (mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version,
                 vendor, model, upstream_interface, ofdm_enabled, ofdma_enabled,
                 partial_service, ofdma_ifindex, upstream_ifindex,
                 first_seen_at, last_seen_at, updated_at, source_poller)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(mac) DO UPDATE SET
                    ip=COALESCE(excluded.ip, ip),
                    cmts=COALESCE(excluded.cmts, cmts),
                    cmts_ip=COALESCE(excluded.cmts_ip, cmts_ip),
                    fiber_node=COALESCE(excluded.fiber_node, fiber_node),
                    cable_mac=COALESCE(excluded.cable_mac, cable_mac),
                    status=COALESCE(excluded.status, status),
                    docsis_version=COALESCE(excluded.docsis_version, docsis_version),
                    vendor=COALESCE(excluded.vendor, vendor),
                    model=COALESCE(excluded.model, model),
                    upstream_interface=COALESCE(excluded.upstream_interface, upstream_interface),
                    ofdm_enabled=COALESCE(excluded.ofdm_enabled, ofdm_enabled),
                    ofdma_enabled=COALESCE(excluded.ofdma_enabled, ofdma_enabled),
                    partial_service=COALESCE(excluded.partial_service, partial_service),
                    ofdma_ifindex=COALESCE(excluded.ofdma_ifindex, ofdma_ifindex),
                    upstream_ifindex=COALESCE(excluded.upstream_ifindex, upstream_ifindex),
                    last_seen_at=excluded.last_seen_at, updated_at=excluded.updated_at,
                    source_poller=excluded.source_poller
            """
            for m in rows:
                cur.execute(
                    q,
                    (
                        m.get("mac_address"), m.get("ip_address"), m.get("cmts"), m.get("cmts_ip"),
                        m.get("fiber_node"), m.get("cable_mac"), m.get("status"), m.get("docsis_version"),
                        m.get("vendor"), m.get("model"), m.get("upstream_interface"),
                        m.get("ofdm_enabled"), m.get("ofdma_enabled"), m.get("partial_service"),
                        m.get("ofdma_ifindex"), m.get("upstream_ifindex"),
                        now, now, now, source_poller,
                    ),
                )
                written += 1
            conn.commit()
        conn.close()
        self.purge_ignored_inventory_rows()
        return written

    def purge_ignored_inventory_rows(self):
        """Delete inventory rows whose IP falls inside MODEM_IGNORE_CIDRS/MODEM_IGNORE."""
        nets = get_modem_ignore_networks()
        if not nets:
            return 0

        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT mac, ip FROM modem_inventory_current WHERE COALESCE(ip,'') <> ''")
        rows = cur.fetchall()
        to_delete = []
        for row in rows:
            rec = dict(row) if isinstance(row, sqlite3.Row) else row
            ip_val = rec.get("ip")
            if is_ignored_modem_ip(ip_val):
                mac = rec.get("mac")
                if mac:
                    to_delete.append(mac)

        deleted = 0
        if to_delete:
            marker = "%s" if self.backend == "mysql" else "?"
            chunk_size = 500
            for i in range(0, len(to_delete), chunk_size):
                chunk = to_delete[i:i + chunk_size]
                placeholders = ",".join([marker] * len(chunk))
                cur.execute(f"DELETE FROM modem_inventory_current WHERE mac IN ({placeholders})", tuple(chunk))
                deleted += int(cur.rowcount or 0)

        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return deleted

    def insert_rf_snapshots(self, snapshots, poller_name):
        if not snapshots:
            return 0
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        written = 0
        if self.backend == "mysql":
            q = """
                INSERT INTO modem_rf_snapshot
                (mac, cmts, collected_at, scqam_json, rxmer_json, poller_name)
                VALUES (%s,%s,%s,%s,%s,%s)
            """
            for s in snapshots:
                cur.execute(
                    q,
                    (
                        s.get("mac"),
                        s.get("cmts"),
                        s.get("collected_at") or now,
                        s.get("scqam_json"),
                        s.get("rxmer_json"),
                        poller_name,
                    ),
                )
                written += 1
        else:
            q = """
                INSERT INTO modem_rf_snapshot
                (mac, cmts, collected_at, scqam_json, rxmer_json, poller_name)
                VALUES (?,?,?,?,?,?)
            """
            for s in snapshots:
                cur.execute(
                    q,
                    (
                        s.get("mac"),
                        s.get("cmts"),
                        s.get("collected_at") or now,
                        s.get("scqam_json"),
                        s.get("rxmer_json"),
                        poller_name,
                    ),
                )
                written += 1
            conn.commit()
        conn.close()
        return written

    def cleanup_old_snapshots(self, retention_days):
        days = max(1, int(retention_days or 30))
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        if self.backend == "mysql":
            cur.execute(
                "DELETE FROM modem_rf_snapshot WHERE collected_at < (NOW() - INTERVAL %s DAY)",
                (days,),
            )
            deleted = int(cur.rowcount or 0)
            try:
                cur.execute(
                    "INSERT INTO retention_cleanup_log (retention_days, deleted_count, created_at) VALUES (%s,%s,%s)",
                    (days, deleted, now),
                )
            except Exception:
                pass
        else:
            cur.execute(
                "DELETE FROM modem_rf_snapshot WHERE collected_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            deleted = int(cur.rowcount or 0)
            try:
                cur.execute(
                    "INSERT INTO retention_cleanup_log (retention_days, deleted_count, created_at) VALUES (?,?,?)",
                    (days, deleted, now),
                )
            except Exception:
                pass
            conn.commit()
        conn.close()
        return deleted

    def log_scheduler_decisions(self, tick_at, decisions):
        if not decisions:
            return
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        for d in decisions:
            if self.backend == "mysql":
                cur.execute(
                    "INSERT INTO scheduler_decision_log (tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (tick_at, d.get("poller_id"), d.get("poller_name"), d.get("decision"), d.get("reason"),
                     d.get("effective_load"), d.get("threshold"), d.get("detail"), now),
                )
            else:
                cur.execute(
                    "INSERT INTO scheduler_decision_log (tick_at, poller_id, poller_name, decision, reason, effective_load, threshold, detail, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tick_at, d.get("poller_id"), d.get("poller_name"), d.get("decision"), d.get("reason"),
                     d.get("effective_load"), d.get("threshold"), d.get("detail"), now),
                )
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        # Keep only the most recent 2000 rows to bound table size.
        try:
            conn2 = self._connect()
            cur2 = conn2.cursor()
            if self.backend == "mysql":
                cur2.execute("DELETE FROM scheduler_decision_log WHERE id <= (SELECT min_id FROM (SELECT MIN(id) AS min_id FROM (SELECT id FROM scheduler_decision_log ORDER BY id DESC LIMIT 2000) t) u)")
            else:
                cur2.execute("DELETE FROM scheduler_decision_log WHERE id NOT IN (SELECT id FROM scheduler_decision_log ORDER BY id DESC LIMIT 2000)")
            if self.backend != "mysql":
                conn2.commit()
            conn2.close()
        except Exception:
            pass

    def get_scheduler_decision_history(self, limit=100):
        limit = max(1, min(int(limit or 100), 500))
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "SELECT * FROM scheduler_decision_log ORDER BY id DESC LIMIT %s"
            if self.backend == "mysql"
            else "SELECT * FROM scheduler_decision_log ORDER BY id DESC LIMIT ?"
        )
        cur.execute(q, (limit,))
        rows = cur.fetchall()
        conn.close()
        return [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]

    def get_snapshot_counts_by_poller_day(self, lookback_days=14, limit=500):
        days = max(1, int(lookback_days or 14))
        limit = max(1, min(int(limit or 500), 5000))
        conn = self._connect()
        cur = conn.cursor()
        if self.backend == "mysql":
            cur.execute(
                """
                SELECT
                    DATE(collected_at) AS day,
                    poller_name,
                    COUNT(*) AS snapshots
                FROM modem_rf_snapshot
                WHERE collected_at >= (NOW() - INTERVAL %s DAY)
                GROUP BY DATE(collected_at), poller_name
                ORDER BY day DESC, poller_name ASC
                LIMIT %s
                """,
                (days, limit),
            )
        else:
            cur.execute(
                """
                SELECT
                    DATE(collected_at) AS day,
                    poller_name,
                    COUNT(*) AS snapshots
                FROM modem_rf_snapshot
                WHERE collected_at >= datetime('now', ?)
                GROUP BY DATE(collected_at), poller_name
                ORDER BY day DESC, poller_name ASC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) if isinstance(r, sqlite3.Row) else r for r in rows]

    def get_snapshot_analytics(self, lookback_days=14):
        days = max(1, int(lookback_days or 14))
        conn = self._connect()
        cur = conn.cursor()

        if self.backend == "mysql":
            cur.execute(
                """
                SELECT DATE(collected_at) AS day, COUNT(*) AS total
                FROM modem_rf_snapshot
                WHERE collected_at >= (NOW() - INTERVAL %s DAY)
                GROUP BY DATE(collected_at)
                ORDER BY day DESC
                """,
                (days,),
            )
        else:
            cur.execute(
                """
                SELECT DATE(collected_at) AS day, COUNT(*) AS total
                FROM modem_rf_snapshot
                WHERE collected_at >= datetime('now', ?)
                GROUP BY DATE(collected_at)
                ORDER BY day DESC
                """,
                (f"-{days} days",),
            )

        rows = [dict(r) if isinstance(r, sqlite3.Row) else r for r in cur.fetchall()]
        conn.close()

        daily_totals = [int(r.get("total") or 0) for r in rows]
        total = sum(daily_totals)
        avg_per_day = round(total / max(len(daily_totals), 1), 2)
        latest = daily_totals[0] if daily_totals else 0
        oldest = daily_totals[-1] if len(daily_totals) > 1 else latest
        growth_pct = 0.0
        if oldest > 0:
            growth_pct = round(((latest - oldest) / oldest) * 100.0, 2)

        deleted_last_24h = 0
        try:
            conn2 = self._connect()
            cur2 = conn2.cursor()
            if self.backend == "mysql":
                cur2.execute("SELECT COALESCE(SUM(deleted_count), 0) AS c FROM retention_cleanup_log WHERE created_at >= (NOW() - INTERVAL 1 DAY)")
            else:
                cur2.execute("SELECT COALESCE(SUM(deleted_count), 0) AS c FROM retention_cleanup_log WHERE created_at >= datetime('now', '-1 day')")
            row = cur2.fetchone()
            conn2.close()
            if row:
                deleted_last_24h = int((row["c"] if isinstance(row, sqlite3.Row) else row.get("c")) or 0)
        except Exception:
            deleted_last_24h = 0

        return {
            "total_snapshots_window": total,
            "avg_per_day": avg_per_day,
            "latest_day_total": latest,
            "oldest_day_total": oldest,
            "growth_pct": growth_pct,
            "deleted_last_24h": deleted_last_24h,
            "daily_series": list(reversed(rows)),
        }

    def enqueue_modem_refresh(self, mac, cmts, requested_by=None):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        if self.backend == "mysql":
            cur.execute(
                """
                INSERT INTO modem_refresh_request
                (mac, cmts, status, requested_by, created_at)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (mac, cmts, "queued", requested_by, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO modem_refresh_request
                (mac, cmts, status, requested_by, created_at)
                VALUES (?,?,?,?,?)
                """,
                (mac, cmts, "queued", requested_by, now),
            )
            conn.commit()
        req_id = int(cur.lastrowid)
        conn.close()
        return req_id

    def claim_next_refresh_request(self):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        sel = (
            "SELECT * FROM modem_refresh_request WHERE status=%s ORDER BY id ASC LIMIT 1"
            if self.backend == "mysql"
            else "SELECT * FROM modem_refresh_request WHERE status=? ORDER BY id ASC LIMIT 1"
        )
        cur.execute(sel, ("queued",))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None

        req = dict(row) if isinstance(row, sqlite3.Row) else row
        upd = (
            "UPDATE modem_refresh_request SET status=%s, started_at=%s WHERE id=%s AND status=%s"
            if self.backend == "mysql"
            else "UPDATE modem_refresh_request SET status=?, started_at=? WHERE id=? AND status=?"
        )
        cur.execute(upd, ("running", now, int(req["id"]), "queued"))
        if self.backend != "mysql":
            conn.commit()
        if getattr(cur, "rowcount", 0) != 1:
            conn.close()
            return None

        conn.close()
        req["status"] = "running"
        req["started_at"] = now
        return req

    def complete_refresh_request(self, request_id, error_text=None):
        now = self._now()
        status = "failed" if error_text else "completed"
        conn = self._connect()
        cur = conn.cursor()
        upd = (
            "UPDATE modem_refresh_request SET status=%s, finished_at=%s, error_text=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE modem_refresh_request SET status=?, finished_at=?, error_text=? WHERE id=?"
        )
        cur.execute(upd, (status, now, error_text, int(request_id)))
        if self.backend != "mysql":
            conn.commit()
        conn.close()

    def cancel_refresh_request(self, request_id, reason="Cancelled by admin"):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        upd = (
            "UPDATE modem_refresh_request SET status=%s, finished_at=%s, error_text=%s WHERE id=%s AND status IN ('queued','running')"
            if self.backend == "mysql"
            else "UPDATE modem_refresh_request SET status=?, finished_at=?, error_text=? WHERE id=? AND status IN ('queued','running')"
        )
        cur.execute(upd, ("cancelled", now, reason, int(request_id)))
        changed = int(cur.rowcount or 0)
        if self.backend != "mysql":
            conn.commit()
        conn.close()
        return changed == 1

    def get_latest_refresh_request(self, mac):
        conn = self._connect()
        cur = conn.cursor()
        marker = "%s" if self.backend == "mysql" else "?"
        q = (
            "SELECT id, mac, cmts, status, requested_by, created_at, started_at, finished_at, error_text "
            f"FROM modem_refresh_request WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = {marker} "
            "ORDER BY id DESC LIMIT 1"
        )
        mac_norm = (mac or "").lower().replace(":", "").replace("-", "")
        cur.execute(q, (mac_norm,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return dict(row) if isinstance(row, sqlite3.Row) else row

    def get_queue_heads(self):
        """Return queue head snapshots and counts for poller and modem refresh queues."""
        conn = self._connect()
        cur = conn.cursor()

        def _fetch_count(table, status):
            q = (
                f"SELECT COUNT(*) AS c FROM {table} WHERE status=%s"
                if self.backend == "mysql"
                else f"SELECT COUNT(*) AS c FROM {table} WHERE status=?"
            )
            cur.execute(q, (status,))
            row = cur.fetchone()
            return int((row["c"] if isinstance(row, sqlite3.Row) else row.get("c")) or 0)

        def _fetch_head(table, status):
            q = (
                f"SELECT * FROM {table} WHERE status=%s ORDER BY id ASC LIMIT 1"
                if self.backend == "mysql"
                else f"SELECT * FROM {table} WHERE status=? ORDER BY id ASC LIMIT 1"
            )
            cur.execute(q, (status,))
            row = cur.fetchone()
            if not row:
                return None
            rec = dict(row) if isinstance(row, sqlite3.Row) else row
            ts_raw = rec.get("started_at") or rec.get("created_at")
            rec["age_sec"] = None
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", ""))
                    rec["age_sec"] = int((datetime.now() - ts).total_seconds())
                except Exception:
                    pass
            return rec

        out = {
            "poller_job": {
                "queued_count": _fetch_count("poller_job", "queued"),
                "running_count": _fetch_count("poller_job", "running"),
                "queued_head": _fetch_head("poller_job", "queued"),
                "running_head": _fetch_head("poller_job", "running"),
            },
            "modem_refresh_request": {
                "queued_count": _fetch_count("modem_refresh_request", "queued"),
                "running_count": _fetch_count("modem_refresh_request", "running"),
                "queued_head": _fetch_head("modem_refresh_request", "queued"),
                "running_head": _fetch_head("modem_refresh_request", "running"),
            },
        }
        conn.close()
        return out

    def list_inventory_modems(self, cmts=None, search_type=None, search_value=None, interface_filter=None, limit=10000):
        """Return current modem inventory rows for API fallback reads."""
        limit = max(1, min(int(limit or 10000), 50000))
        conn = self._connect()
        cur = conn.cursor()

        where = []
        params = []

        if cmts:
            if self.backend == "mysql":
                where.append("cmts=%s")
            else:
                where.append("cmts=?")
            params.append(cmts)

        if search_value:
            sv = f"%{search_value.lower()}%"
            if search_type == "ip":
                where.append("LOWER(COALESCE(ip,'')) LIKE {}".format("%s" if self.backend == "mysql" else "?"))
                params.append(sv)
            elif search_type == "mac":
                expr = "LOWER(REPLACE(REPLACE(COALESCE(mac,''),':',''),'-',''))"
                where.append(f"{expr} LIKE {{}}".format("%s" if self.backend == "mysql" else "?"))
                params.append(search_value.lower().replace(":", "").replace("-", ""))
            elif search_type == "name":
                marker = "%s" if self.backend == "mysql" else "?"
                where.append(f"(LOWER(COALESCE(vendor,'')) LIKE {marker} OR LOWER(COALESCE(model,'')) LIKE {marker} OR LOWER(COALESCE(fiber_node,'')) LIKE {marker})")
                params.extend([sv, sv, sv])

        if interface_filter:
            marker = "%s" if self.backend == "mysql" else "?"
            where.append(f"(LOWER(COALESCE(upstream_interface,'')) LIKE {marker} OR LOWER(COALESCE(cable_mac,'')) LIKE {marker})")
            params.append(f"%{interface_filter.lower()}%")

        where_sql = f" WHERE {' AND '.join(where)}" if where else ""
        limit_marker = "%s" if self.backend == "mysql" else "?"
        q = (
            "SELECT mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model, "
            "upstream_interface, ofdm_enabled, ofdma_enabled, partial_service, ofdma_ifindex, upstream_ifindex, updated_at "
            "FROM modem_inventory_current"
            f"{where_sql} ORDER BY cmts ASC, mac ASC LIMIT {limit_marker}"
        )
        params.append(limit)
        cur.execute(q, tuple(params))
        rows = cur.fetchall()
        conn.close()

        out = []
        for r in rows:
            row = dict(r) if isinstance(r, sqlite3.Row) else r
            if is_ignored_modem_ip(row.get("ip")):
                continue
            out.append({
                "mac_address": row.get("mac"),
                "ip_address": row.get("ip"),
                "cmts": row.get("cmts"),
                "cmts_ip": row.get("cmts_ip"),
                "fiber_node": row.get("fiber_node"),
                "cable_mac": row.get("cable_mac"),
                "status": row.get("status"),
                "docsis_version": row.get("docsis_version"),
                "vendor": row.get("vendor"),
                "model": row.get("model"),
                "upstream_interface": row.get("upstream_interface"),
                "ofdm_enabled": row.get("ofdm_enabled"),
                "ofdma_enabled": row.get("ofdma_enabled"),
                "partial_service": row.get("partial_service"),
                "ofdma_ifindex": row.get("ofdma_ifindex"),
                "upstream_ifindex": row.get("upstream_ifindex"),
                "updated_at": row.get("updated_at"),
            })
        return out

    def get_inventory_modem_by_mac(self, mac_address):
        conn = self._connect()
        cur = conn.cursor()
        marker = "%s" if self.backend == "mysql" else "?"
        q = (
            "SELECT mac, ip, cmts, cmts_ip, fiber_node, cable_mac, status, docsis_version, vendor, model, "
            "upstream_interface, ofdm_enabled, ofdma_enabled, partial_service, ofdma_ifindex, upstream_ifindex, updated_at "
            f"FROM modem_inventory_current WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-','')) = {marker} LIMIT 1"
        )
        mac_norm = (mac_address or "").lower().replace(":", "").replace("-", "")
        cur.execute(q, (mac_norm,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        r = dict(row) if isinstance(row, sqlite3.Row) else row
        return {
            "mac_address": r.get("mac"),
            "ip_address": r.get("ip"),
            "cmts": r.get("cmts"),
            "cmts_ip": r.get("cmts_ip"),
            "fiber_node": r.get("fiber_node"),
            "cable_mac": r.get("cable_mac"),
            "status": r.get("status"),
            "docsis_version": r.get("docsis_version"),
            "vendor": r.get("vendor"),
            "model": r.get("model"),
            "upstream_interface": r.get("upstream_interface"),
            "ofdm_enabled": r.get("ofdm_enabled"),
            "ofdma_enabled": r.get("ofdma_enabled"),
            "partial_service": r.get("partial_service"),
            "ofdma_ifindex": r.get("ofdma_ifindex"),
            "upstream_ifindex": r.get("upstream_ifindex"),
            "updated_at": r.get("updated_at"),
        }

    def update_modem_channel_ifindices(self, mac_address, cmts_ip, ofdma_ifindex, upstream_ifindex=None):
        """Persist per-modem discovered channel ifindices. Called after a live SNMP poll.
        Only overwrites non-NULL discovered values; never nullifies existing data."""
        if not mac_address:
            return
        try:
            mac_norm = mac_address.lower().replace(":", "").replace("-", "")
            conn = self._connect()
            cur = conn.cursor()
            if self.backend == "mysql":
                cur.execute(
                    "UPDATE modem_inventory_current "
                    "SET ofdma_ifindex=COALESCE(%s, ofdma_ifindex), "
                    "upstream_ifindex=COALESCE(%s, upstream_ifindex), "
                    "updated_at=%s "
                    "WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-',''))=%s",
                    (ofdma_ifindex, upstream_ifindex, self._now(), mac_norm),
                )
            else:
                cur.execute(
                    "UPDATE modem_inventory_current "
                    "SET ofdma_ifindex=COALESCE(?,ofdma_ifindex), "
                    "upstream_ifindex=COALESCE(?,upstream_ifindex), "
                    "updated_at=? "
                    "WHERE LOWER(REPLACE(REPLACE(mac,':',''),'-',''))=?",
                    (ofdma_ifindex, upstream_ifindex, self._now(), mac_norm),
                )
                conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning(f"update_modem_channel_ifindices failed for {mac_address}: {exc}")


# singleton
_data_store_db = DataStoreDB()

data_store_db = _data_store_db
