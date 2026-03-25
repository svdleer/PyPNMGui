import os
import secrets
import sqlite3
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash


class AuthDB:
    def __init__(self):
        self.backend = self._detect_backend()
        self.sqlite_path = os.environ.get("AUTH_SQLITE_PATH", "/app/data/auth.db")

    def _detect_backend(self):
        if os.environ.get("AUTH_DB_BACKEND", "").lower() == "mysql":
            return "mysql"
        if os.environ.get("AUTH_DB_HOST"):
            return "mysql"
        return "sqlite"

    def _connect(self):
        if self.backend == "mysql":
            try:
                import pymysql
            except ImportError as exc:
                raise RuntimeError("MySQL backend selected but pymysql is not installed") from exc
            return pymysql.connect(
                host=os.environ.get("AUTH_DB_HOST", "127.0.0.1"),
                port=int(os.environ.get("AUTH_DB_PORT", "3306")),
                user=os.environ.get("AUTH_DB_USER", "pypnm"),
                password=os.environ.get("AUTH_DB_PASSWORD", "pypnm"),
                database=os.environ.get("AUTH_DB_NAME", "pypnm_auth"),
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )

        os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def init_db(self):
        conn = self._connect()
        cur = conn.cursor()

        if self.backend == "mysql":
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
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    language_preference TEXT NOT NULL DEFAULT 'en-US',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    description TEXT,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

        try:
            if self.backend == "mysql":
                cur.execute("ALTER TABLE users ADD COLUMN language_preference VARCHAR(16) NOT NULL DEFAULT 'en-US'")
            else:
                cur.execute("ALTER TABLE users ADD COLUMN language_preference TEXT NOT NULL DEFAULT 'en-US'")
                conn.commit()
        except Exception:
            pass

        try:
            conn.close()
        except Exception:
            pass

    def _fetchone(self, query, params=()):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        conn.close()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        return row

    def _fetchall(self, query, params=()):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        conn.close()
        out = []
        for row in rows:
            out.append(dict(row) if isinstance(row, sqlite3.Row) else row)
        return out

    def ensure_bootstrap_admin(self):
        row = self._fetchone("SELECT id FROM users LIMIT 1")
        if row:
            return
        username = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USER", "admin")
        password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASS", "admin")
        self.create_user(username=username, password=password, role="admin", is_active=True)

    def get_user_by_username(self, username):
        return self._fetchone("SELECT * FROM users WHERE username = %s" if self.backend == "mysql" else "SELECT * FROM users WHERE username = ?", (username,))

    def get_user_by_id(self, user_id):
        return self._fetchone("SELECT * FROM users WHERE id = %s" if self.backend == "mysql" else "SELECT * FROM users WHERE id = ?", (user_id,))

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
        cur = conn.cursor()
        q = (
            "INSERT INTO users (username, password_hash, role, language_preference, is_active, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            if self.backend == "mysql"
            else "INSERT INTO users (username, password_hash, role, language_preference, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,?)"
        )
        cur.execute(q, (username, password_hash, role, "en-US", 1 if is_active else 0, now, now))
        if self.backend != "mysql":
            conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return user_id

    def update_user(self, user_id, role, is_active):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "UPDATE users SET role=%s, is_active=%s, updated_at=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE users SET role=?, is_active=?, updated_at=? WHERE id=?"
        )
        cur.execute(q, (role, 1 if is_active else 0, now, user_id))
        if self.backend != "mysql":
            conn.commit()
        conn.close()

    def set_language_preference(self, user_id, locale):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "UPDATE users SET language_preference=%s, updated_at=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE users SET language_preference=?, updated_at=? WHERE id=?"
        )
        cur.execute(q, (locale, now, user_id))
        if self.backend != "mysql":
            conn.commit()
        conn.close()

    def delete_user(self, user_id):
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "DELETE FROM users WHERE id=%s"
            if self.backend == "mysql"
            else "DELETE FROM users WHERE id=?"
        )
        cur.execute(q, (user_id,))
        if self.backend != "mysql":
            conn.commit()
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
        cur = conn.cursor()
        q = (
            "UPDATE users SET password_hash=%s, updated_at=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE users SET password_hash=?, updated_at=? WHERE id=?"
        )
        cur.execute(q, (password_hash, now, user_id))
        if self.backend != "mysql":
            conn.commit()
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
        cur = conn.cursor()
        q = (
            "INSERT INTO api_keys (name, key_hash, key_prefix, role, is_active, description, created_by, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            if self.backend == "mysql"
            else "INSERT INTO api_keys (name, key_hash, key_prefix, role, is_active, description, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)"
        )
        cur.execute(q, (name, key_hash, key_prefix, role, 1, description, created_by, now, now))
        if self.backend != "mysql":
            conn.commit()
        key_id = cur.lastrowid
        conn.close()
        return key_id, plain

    def update_api_key(self, key_id, name, role, is_active, description):
        now = self._now()
        conn = self._connect()
        cur = conn.cursor()
        q = (
            "UPDATE api_keys SET name=%s, role=%s, is_active=%s, description=%s, updated_at=%s WHERE id=%s"
            if self.backend == "mysql"
            else "UPDATE api_keys SET name=?, role=?, is_active=?, description=?, updated_at=? WHERE id=?"
        )
        cur.execute(q, (name, role, 1 if is_active else 0, description, now, key_id))
        if self.backend != "mysql":
            conn.commit()
        conn.close()


auth_db = AuthDB()
