import json
import os
from datetime import datetime, timezone
from typing import Any


class TopologyDB:
    def __init__(self):
        self.backend = (os.environ.get("TOPOLOGY_DB_BACKEND") or "mysql").lower()

    @property
    def enabled(self) -> bool:
        return (os.environ.get("ENABLE_TOPOLOGY_DB", "true").lower() in {"1", "true", "yes", "on"})

    def _connect(self):
        if self.backend != "mysql":
            raise RuntimeError("Topology DB backend must be mysql")
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("pymysql is required for topology mysql backend") from exc

        host = os.environ.get("TOPOLOGY_DB_HOST") or os.environ.get("AUTH_DB_HOST", "127.0.0.1")
        port = int(os.environ.get("TOPOLOGY_DB_PORT") or os.environ.get("AUTH_DB_PORT", "3306"))
        user = os.environ.get("TOPOLOGY_DB_USER") or os.environ.get("AUTH_DB_USER", "pypnm")
        password = os.environ.get("TOPOLOGY_DB_PASSWORD") or os.environ.get("AUTH_DB_PASSWORD", "pypnm")
        database = os.environ.get("TOPOLOGY_DB_NAME", "pypnm_topology")

        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def init_db(self):
        conn = self._connect()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS topology_snapshots (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                snapshot_date CHAR(8) NOT NULL UNIQUE,
                topology_file VARCHAR(255),
                modemlocation_file VARCHAR(255),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS topology_nodes (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                snapshot_id BIGINT NOT NULL,
                node_id VARCHAR(255) NOT NULL,
                parent_id VARCHAR(255),
                fnid VARCHAR(255),
                node_type VARCHAR(64),
                link_id VARCHAR(64),
                lat DOUBLE,
                lon DOUBLE,
                description TEXT,
                metadata_json JSON,
                UNIQUE KEY uq_snapshot_node (snapshot_id, node_id),
                KEY idx_nodes_snapshot_type (snapshot_id, node_type),
                KEY idx_nodes_snapshot_fnid (snapshot_id, fnid),
                KEY idx_nodes_snapshot_link (snapshot_id, link_id),
                KEY idx_nodes_snapshot_parent (snapshot_id, parent_id),
                CONSTRAINT fk_nodes_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS topology_edges (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                snapshot_id BIGINT NOT NULL,
                from_node_id VARCHAR(255) NOT NULL,
                to_node_id VARCHAR(255) NOT NULL,
                KEY idx_edges_snapshot_from (snapshot_id, from_node_id),
                KEY idx_edges_snapshot_to (snapshot_id, to_node_id),
                CONSTRAINT fk_edges_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS topology_modems (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                snapshot_id BIGINT NOT NULL,
                mac VARCHAR(32),
                fibernode VARCHAR(255),
                topology_link_id VARCHAR(64),
                lat DOUBLE,
                lon DOUBLE,
                address TEXT,
                customer_id VARCHAR(128),
                linked_node_id VARCHAR(255),
                linked_node_type VARCHAR(64),
                link_match TINYINT(1) NOT NULL DEFAULT 0,
                KEY idx_modems_snapshot_mac (snapshot_id, mac),
                KEY idx_modems_snapshot_link (snapshot_id, topology_link_id),
                KEY idx_modems_snapshot_fn (snapshot_id, fibernode),
                KEY idx_modems_snapshot_match (snapshot_id, link_match),
                CONSTRAINT fk_modems_snapshot FOREIGN KEY (snapshot_id) REFERENCES topology_snapshots(id) ON DELETE CASCADE
            )
            """
        )

        conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def get_snapshot_id(self, snapshot_date: str) -> int | None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (snapshot_date,))
        row = cur.fetchone()
        conn.close()
        return int(row["id"]) if row else None

    def upsert_snapshot_payload(
        self,
        snapshot_date: str,
        topology_file: str | None,
        modemlocation_file: str | None,
        payload: dict[str, Any],
    ) -> int:
        conn = self._connect()
        cur = conn.cursor()
        now = self._now()

        cur.execute(
            """
            INSERT INTO topology_snapshots (snapshot_date, topology_file, modemlocation_file, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                topology_file=VALUES(topology_file),
                modemlocation_file=VALUES(modemlocation_file),
                updated_at=VALUES(updated_at)
            """,
            (snapshot_date, topology_file, modemlocation_file, now, now),
        )
        cur.execute("SELECT id FROM topology_snapshots WHERE snapshot_date=%s", (snapshot_date,))
        snapshot_id = int(cur.fetchone()["id"])

        cur.execute("DELETE FROM topology_edges WHERE snapshot_id=%s", (snapshot_id,))
        cur.execute("DELETE FROM topology_modems WHERE snapshot_id=%s", (snapshot_id,))
        cur.execute("DELETE FROM topology_nodes WHERE snapshot_id=%s", (snapshot_id,))

        nodes = payload.get("topology_nodes") or []
        if nodes:
            node_sql = (
                "INSERT INTO topology_nodes (snapshot_id, node_id, parent_id, fnid, node_type, link_id, lat, lon, description, metadata_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            node_rows = [
                (
                    snapshot_id,
                    n.get("id"),
                    n.get("parent_id"),
                    n.get("fnid"),
                    n.get("node_type"),
                    n.get("link_id"),
                    n.get("lat"),
                    n.get("lon"),
                    n.get("description"),
                    json.dumps(n.get("metadata") or {}, ensure_ascii=True),
                )
                for n in nodes
            ]
            for i in range(0, len(node_rows), 3000):
                cur.executemany(node_sql, node_rows[i : i + 3000])

        edges = payload.get("topology_edges") or []
        if edges:
            edge_sql = "INSERT INTO topology_edges (snapshot_id, from_node_id, to_node_id) VALUES (%s,%s,%s)"
            edge_rows = [(snapshot_id, e.get("from"), e.get("to")) for e in edges]
            for i in range(0, len(edge_rows), 5000):
                cur.executemany(edge_sql, edge_rows[i : i + 5000])

        modems = payload.get("modems") or []
        if modems:
            modem_sql = (
                "INSERT INTO topology_modems (snapshot_id, mac, fibernode, topology_link_id, lat, lon, address, customer_id, linked_node_id, linked_node_type, link_match) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            modem_rows = [
                (
                    snapshot_id,
                    m.get("mac"),
                    m.get("fibernode"),
                    m.get("topology_link_id"),
                    m.get("lat"),
                    m.get("lon"),
                    m.get("address"),
                    m.get("customer_id"),
                    m.get("linked_node_id"),
                    m.get("linked_node_type"),
                    1 if m.get("link_match") else 0,
                )
                for m in modems
            ]
            for i in range(0, len(modem_rows), 5000):
                cur.executemany(modem_sql, modem_rows[i : i + 5000])

        conn.close()
        return snapshot_id

    def load_snapshot_payload(self, snapshot_date: str, sample_limit: int = 200) -> dict[str, Any] | None:
        snapshot_id = self.get_snapshot_id(snapshot_date)
        if not snapshot_id:
            return None

        conn = self._connect()
        cur = conn.cursor()

        cur.execute("SELECT topology_file, modemlocation_file FROM topology_snapshots WHERE id=%s", (snapshot_id,))
        snap_row = cur.fetchone() or {}

        cur.execute("SELECT COUNT(*) AS c FROM topology_nodes WHERE snapshot_id=%s", (snapshot_id,))
        nodes_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute("SELECT COUNT(*) AS c FROM topology_edges WHERE snapshot_id=%s", (snapshot_id,))
        edges_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute("SELECT COUNT(*) AS c FROM topology_modems WHERE snapshot_id=%s", (snapshot_id,))
        modems_count = int((cur.fetchone() or {}).get("c", 0))
        cur.execute("SELECT COUNT(DISTINCT fnid) AS c FROM topology_nodes WHERE snapshot_id=%s", (snapshot_id,))
        fiber_nodes = int((cur.fetchone() or {}).get("c", 0))
        cur.execute("SELECT COUNT(*) AS c FROM topology_modems WHERE snapshot_id=%s AND link_match=1", (snapshot_id,))
        matched_link = int((cur.fetchone() or {}).get("c", 0))
        cur.execute("SELECT COUNT(*) AS c FROM topology_modems WHERE snapshot_id=%s AND link_match=0", (snapshot_id,))
        unmatched = int((cur.fetchone() or {}).get("c", 0))

        cur.execute(
            "SELECT node_type, COUNT(*) AS c FROM topology_nodes WHERE snapshot_id=%s GROUP BY node_type ORDER BY node_type ASC",
            (snapshot_id,),
        )
        node_type_counts = {row["node_type"] or "Unknown": int(row["c"]) for row in cur.fetchall() or []}

        cur.execute(
            "SELECT COUNT(*) AS c FROM topology_nodes WHERE snapshot_id=%s AND LOWER(TRIM(COALESCE(node_type,'')))='amp'",
            (snapshot_id,),
        )
        amp_nodes = int((cur.fetchone() or {}).get("c", 0))
        cur.execute(
            "SELECT COUNT(*) AS c FROM topology_nodes WHERE snapshot_id=%s AND LOWER(TRIM(COALESCE(node_type,'')))='tap'",
            (snapshot_id,),
        )
        tap_nodes = int((cur.fetchone() or {}).get("c", 0))
        avg_amp_per_node = (amp_nodes / fiber_nodes) if fiber_nodes else 0.0
        avg_tap_per_node = (tap_nodes / fiber_nodes) if fiber_nodes else 0.0

        cur.execute(
            "SELECT node_id AS id, parent_id, fnid, node_type, link_id, lat, lon, description, metadata_json FROM topology_nodes WHERE snapshot_id=%s LIMIT %s",
            (snapshot_id, int(sample_limit)),
        )
        sample_nodes = []
        for row in cur.fetchall() or []:
            md_raw = row.get("metadata_json")
            try:
                metadata = json.loads(md_raw) if isinstance(md_raw, str) and md_raw else (md_raw or {})
            except Exception:
                metadata = {}
            sample_nodes.append(
                {
                    "id": row.get("id"),
                    "parent_id": row.get("parent_id"),
                    "fnid": row.get("fnid"),
                    "node_type": row.get("node_type"),
                    "link_id": row.get("link_id"),
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "description": row.get("description") or "",
                    "metadata": metadata,
                }
            )

        cur.execute(
            "SELECT mac, fibernode, topology_link_id, lat, lon, address, customer_id, linked_node_id, linked_node_type, link_match FROM topology_modems WHERE snapshot_id=%s LIMIT %s",
            (snapshot_id, int(sample_limit)),
        )
        sample_modems = []
        for row in cur.fetchall() or []:
            sample_modems.append(
                {
                    "mac": row.get("mac") or "",
                    "fibernode": row.get("fibernode") or "",
                    "topology_link_id": row.get("topology_link_id") or "",
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "address": row.get("address") or "",
                    "customer_id": row.get("customer_id") or "",
                    "linked_node_id": row.get("linked_node_id"),
                    "linked_node_type": row.get("linked_node_type"),
                    "link_match": bool(row.get("link_match")),
                }
            )

        conn.close()

        return {
            "files": {
                "topology_file": snap_row.get("topology_file"),
                "modemlocation_file": snap_row.get("modemlocation_file"),
            },
            "topology_nodes": sample_nodes,
            "topology_edges": [],
            "modems": sample_modems,
            "stats": {
                "topology_nodes": nodes_count,
                "topology_edges": edges_count,
                "modems": modems_count,
                "fiber_nodes": fiber_nodes,
                "matched_by_linkid": matched_link,
                "potential_fibernode_match": 0,
                "unmatched_modems": unmatched,
                "amp_nodes": amp_nodes,
                "tap_nodes": tap_nodes,
                "avg_amp_per_node": avg_amp_per_node,
                "avg_tap_per_node": avg_tap_per_node,
                "node_type_counts": node_type_counts,
            },
        }


topology_db = TopologyDB()
