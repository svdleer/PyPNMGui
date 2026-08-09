#!/usr/bin/env python3
"""Initialize and verify the mandatory MySQL auth database.

Usage:
  AUTH_DB_HOST=... AUTH_DB_USER=... AUTH_DB_PASSWORD=... AUTH_DB_NAME=... \
    python backend/scripts/init_auth_db.py

This script:
  1) creates/updates auth tables
  2) ensures a bootstrap admin exists
  3) prints backend + user/admin counts
"""

import os
import sys
import importlib.util


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
AUTH_DB_PATH = os.path.join(BACKEND_DIR, "app", "core", "auth_db.py")

spec = importlib.util.spec_from_file_location("auth_db_module", AUTH_DB_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load auth DB module from {AUTH_DB_PATH}")
auth_db_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth_db_module)
auth_db = auth_db_module.auth_db


def main() -> int:
    try:
        auth_db.init_db()
        auth_db.ensure_bootstrap_admin()
        users = auth_db.list_users()
        admins = auth_db.admin_count()
        print(
            f"AUTH_DB_OK backend={auth_db.backend} users={len(users)} admins={admins}"
        )
        if users:
            print("USERS:")
            for u in users:
                print(
                    f"- id={u['id']} username={u['username']} role={u['role']} active={u['is_active']}"
                )
        return 0
    except Exception as exc:
        print(f"AUTH_DB_ERROR {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
