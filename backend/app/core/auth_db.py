import os
import secrets
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash


class AuthDB:
    REQUIRED_ENV = (
        "AUTH_DB_HOST",
        "AUTH_DB_USER",
        "AUTH_DB_PASSWORD",
        "AUTH_DB_NAME",
    )

    def __init__(self):
        self.backend = "mysql"
        missing = [name for name in self.REQUIRED_ENV if not os.environ.get(name)]
        if missing:
            raise RuntimeError(
                "MySQL auth database configuration missing: " + ", ".join(missing)
            )

    def _connect(self):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("pymysql is required for the auth database") from exc
        return pymysql.connect(
            host=os.environ["AUTH_DB_HOST"],
            port=int(os.environ.get("AUTH_DB_PORT", "3306")),
            user=os.environ["AUTH_DB_USER"],
            password=os.environ["AUTH_DB_PASSWORD"],
            database=os.environ["AUTH_DB_NAME"],
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def init_db(self):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    language_preference VARCHAR(16) NOT NULL DEFAULT 'en-US',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    name VARCHAR(128) NOT NULL,
                    key_hash VARCHAR(255) NOT NULL,
                    key_prefix VARCHAR(16) NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    description VARCHAR(255),
                    created_by BIGINT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
            try:
                cur.execute(
                    "ALTER TABLE users ADD COLUMN language_preference "
                    "VARCHAR(16) NOT NULL DEFAULT 'en-US'"
                )
            except Exception:
                pass
        finally:
            conn.close()

    def _fetchone(self, query, params=()):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            return cur.fetchone()
        finally:
            conn.close()

    def _fetchall(self, query, params=()):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            return list(cur.fetchall())
        finally:
            conn.close()

    def ensure_bootstrap_admin(self):
        """Create the first internal administrator exactly once across workers."""
        conn = self._connect()
        cur = conn.cursor()
        database = os.environ["AUTH_DB_NAME"]
        lock_name = f"pypnmgui.bootstrap_admin.{database}"[:64]
        lock_acquired = False
        try:
            cur.execute("SELECT GET_LOCK(%s, %s) AS acquired", (lock_name, 10))
            lock_row = cur.fetchone()
            acquired = lock_row.get("acquired") if lock_row else None
            if acquired != 1:
                raise RuntimeError("Timed out waiting for auth bootstrap lock")
            lock_acquired = True

            cur.execute("SELECT id FROM users LIMIT 1")
            if cur.fetchone():
                return False

            username = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USER", "admin")
            password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASS", "admin")
            now = self._now()
            cur.execute(
                "INSERT INTO users "
                "(username, password_hash, role, language_preference, is_active, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    username,
                    generate_password_hash(password),
                    "admin",
                    "en-US",
                    1,
                    now,
                    now,
                ),
            )
            return True
        finally:
            if lock_acquired:
                try:
                    cur.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                except Exception:
                    pass
            conn.close()

    def get_user_by_username(self, username):
        return self._fetchone("SELECT * FROM users WHERE username = %s", (username,))

    def get_user_by_id(self, user_id):
        return self._fetchone("SELECT * FROM users WHERE id = %s", (user_id,))

    def verify_user(self, username, password):
        user = self.get_user_by_username(username)
        if not user or not user.get("is_active"):
            return None
        if not check_password_hash(user["password_hash"], password):
            return None
        return user

    def list_users(self):
        users = self._fetchall("SELECT id, username, role, language_preference, is_active, created_at, updated_at FROM users ORDER BY username")
        return users

    def create_user(self, username, password, role="user", is_active=True):
        now = self._now()
        password_hash = generate_password_hash(password)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO users "
                "(username, password_hash, role, language_preference, is_active, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (username, password_hash, role, "en-US", 1 if is_active else 0, now, now),
            )
            return cur.lastrowid
        finally:
            conn.close()

    def update_user(self, user_id, role, is_active):
        now = self._now()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET role=%s, is_active=%s, updated_at=%s WHERE id=%s",
                (role, 1 if is_active else 0, now, user_id),
            )
        finally:
            conn.close()

    def set_language_preference(self, user_id, locale):
        now = self._now()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET language_preference=%s, updated_at=%s WHERE id=%s",
                (locale, now, user_id),
            )
        finally:
            conn.close()

    def delete_user(self, user_id):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        finally:
            conn.close()

    def change_password(self, user_id, current_password, new_password):
        user = self.get_user_by_id(user_id)
        if not user:
            return False, "User not found"
        if not check_password_hash(user["password_hash"], current_password):
            return False, "Current password is incorrect"
        self.set_password(user_id, new_password)
        return True, "Password updated"

    def set_password(self, user_id, new_password):
        now = self._now()
        password_hash = generate_password_hash(new_password)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET password_hash=%s, updated_at=%s WHERE id=%s",
                (password_hash, now, user_id),
            )
        finally:
            conn.close()

    def admin_count(self):
        row = self._fetchone("SELECT COUNT(*) AS c FROM users WHERE role='admin' AND is_active=1")
        return int(row["c"]) if row else 0

    def list_api_keys(self):
        return self._fetchall(
            "SELECT id, name, key_prefix, role, is_active, description, created_by, created_at, updated_at FROM api_keys ORDER BY id DESC"
        )

    def create_api_key(self, name, role, description, created_by):
        now = self._now()
        plain = f"pk_{secrets.token_urlsafe(32)}"
        key_hash = generate_password_hash(plain)
        key_prefix = plain[:12]
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO api_keys "
                "(name, key_hash, key_prefix, role, is_active, description, created_by, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (name, key_hash, key_prefix, role, 1, description, created_by, now, now),
            )
            return cur.lastrowid, plain
        finally:
            conn.close()

    def update_api_key(self, key_id, name, role, is_active, description):
        now = self._now()
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE api_keys SET name=%s, role=%s, is_active=%s, description=%s, updated_at=%s WHERE id=%s",
                (name, role, 1 if is_active else 0, description, now, key_id),
            )
        finally:
            conn.close()


auth_db = AuthDB()
