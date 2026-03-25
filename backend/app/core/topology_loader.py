import csv
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.topology_db import topology_db


def _normalize_mac_address(mac: str) -> str:
    """
    Normalize MAC address to xx:xx:xx:xx:xx:xx format.
    
    Handles various formats:
    - aabbccddeeff (no separators)
    - aa:bb:cc:dd:ee:ff (colon)
    - aa-bb-cc-dd-ee-ff (hyphen)
    - aabb.ccdd.eeff (cisco)
    
    Returns empty string if invalid.
    """
    if not mac:
        return ""
    
    # Remove all common separators
    clean = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    
    # Must be exactly 12 hex characters
    if not re.fullmatch(r"[0-9a-fA-F]{12}", clean):
        return mac  # Return original if invalid
    
    # Format as lowercase colon-separated
    return ":".join(clean.lower()[i:i+2] for i in range(0, 12, 2))


@dataclass
class TopologyFiles:
    topology_file: str | None
    modemlocation_file: str | None
    image_files: list[str]
    pair_date: str | None
    warnings: list[str]
    available_pair_dates: list[str]


def _repo_topology_dir() -> str:
    # backend/app/core -> backend -> project root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base_dir, "topology")


def _pick_latest(files: list[str], prefix: str) -> str | None:
    candidates = [f for f in files if os.path.basename(f).startswith(prefix)]
    if not candidates:
        return None
    # Filenames include date suffix, lexical sort works.
    return sorted(candidates)[-1]


def _extract_date(name: str) -> str | None:
    m = re.search(r"_(\d{8})$", name)
    return m.group(1) if m else None


def _scan_topology_inventory() -> tuple[dict[str, str], dict[str, str], list[str], str]:
    topo_dir = _repo_topology_dir()
    if not os.path.isdir(topo_dir):
        return {}, {}, [], topo_dir

    all_files = [
        os.path.join(topo_dir, name)
        for name in os.listdir(topo_dir)
        if os.path.isfile(os.path.join(topo_dir, name))
    ]

    image_files = [
        os.path.basename(f)
        for f in all_files
        if os.path.basename(f).lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]

    topo_by_date: dict[str, str] = {}
    modem_by_date: dict[str, str] = {}
    for f in all_files:
        name = os.path.basename(f)
        if name.startswith("NL_topology_"):
            d = _extract_date(name)
            if d:
                topo_by_date[d] = f
        elif name.startswith("NL_modemlocation_"):
            d = _extract_date(name)
            if d:
                modem_by_date[d] = f

    return topo_by_date, modem_by_date, sorted(image_files), topo_dir


def discover_topology_files(selected_date: str | None = None) -> TopologyFiles:
    topo_by_date, modem_by_date, image_files, _topo_dir = _scan_topology_inventory()
    if not topo_by_date and not modem_by_date:
        return TopologyFiles(None, None, [], None, ["topology directory not found or empty"], [])

    warnings: list[str] = []
    paired_dates = sorted(set(topo_by_date.keys()) & set(modem_by_date.keys()))

    if selected_date and selected_date in paired_dates:
        for only_topo in sorted(set(topo_by_date.keys()) - set(modem_by_date.keys())):
            warnings.append(f"unpaired topology file date: {only_topo}")
        for only_modem in sorted(set(modem_by_date.keys()) - set(topo_by_date.keys())):
            warnings.append(f"unpaired modemlocation file date: {only_modem}")
        return TopologyFiles(
            topology_file=topo_by_date[selected_date],
            modemlocation_file=modem_by_date[selected_date],
            image_files=image_files,
            pair_date=selected_date,
            warnings=warnings,
            available_pair_dates=paired_dates,
        )

    if paired_dates:
        d = paired_dates[-1]
        for only_topo in sorted(set(topo_by_date.keys()) - set(modem_by_date.keys())):
            warnings.append(f"unpaired topology file date: {only_topo}")
        for only_modem in sorted(set(modem_by_date.keys()) - set(topo_by_date.keys())):
            warnings.append(f"unpaired modemlocation file date: {only_modem}")
        return TopologyFiles(
            topology_file=topo_by_date[d],
            modemlocation_file=modem_by_date[d],
            image_files=image_files,
            pair_date=d,
            warnings=warnings,
            available_pair_dates=paired_dates,
        )

    topo_files = list(topo_by_date.values())
    modem_files = list(modem_by_date.values())
    latest_topo = _pick_latest(topo_files, "NL_topology_")
    latest_modem = _pick_latest(modem_files, "NL_modemlocation_")
    if latest_topo and latest_modem:
        warnings.append("topology/modemlocation dates do not match; modem file not joined")
    elif latest_topo and not latest_modem:
        warnings.append("no modemlocation file found")
    elif latest_modem and not latest_topo:
        warnings.append("no topology file found")

    return TopologyFiles(
        topology_file=latest_topo,
        modemlocation_file=None,
        image_files=image_files,
        pair_date=None,
        warnings=warnings,
        available_pair_dates=paired_dates,
    )


def _read_csv(path: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        # Skip preamble lines like: %%% COMPLETE fZIGGO
        while True:
            pos = fh.tell()
            line = fh.readline()
            if not line:
                return rows
            if not line.startswith("%%"):
                fh.seek(pos)
                break

        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _to_float(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return float(val)
    except Exception:
        return None


def _desc_to_map(desc: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not desc:
        return out
    for part in desc.split(";"):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def _file_stamp(path: str | None) -> float:
    if not path or not os.path.exists(path):
        return 0.0
    return os.path.getmtime(path)


@lru_cache(maxsize=4)
def _load_cached(topo_path: str, modem_path: str, topo_stamp: float, modem_stamp: float) -> dict[str, Any]:
    topo_rows = _read_csv(topo_path) if topo_path else []
    modem_rows = _read_csv(modem_path) if modem_path else []

    node_type_counts: dict[str, int] = {}
    by_linkid: dict[str, dict[str, Any]] = {}
    fn_counts: dict[str, int] = {}

    edges: list[dict[str, str]] = []
    topo_nodes: list[dict[str, Any]] = []
    for r in topo_rows:
        node_id = r.get("ID", "")
        parent = r.get("PARENTID", "")
        fnid = r.get("FNID", "")
        ntype = r.get("NODETYPE", "Unknown") or "Unknown"
        linkid = r.get("LINKID", "")
        lat = _to_float(r.get("LAT"))
        lon = _to_float(r.get("LON"))
        md = _desc_to_map(r.get("DESCRIPTION", ""))

        node = {
            "id": node_id,
            "parent_id": parent,
            "fnid": fnid,
            "node_type": ntype,
            "link_id": linkid,
            "lat": lat,
            "lon": lon,
            "description": r.get("DESCRIPTION", ""),
            "metadata": md,
        }
        topo_nodes.append(node)
        if linkid:
            by_linkid[linkid] = node
        if fnid:
            fn_counts[fnid] = fn_counts.get(fnid, 0) + 1

        node_type_counts[ntype] = node_type_counts.get(ntype, 0) + 1
        if parent:
            edges.append({"from": parent, "to": node_id})

    modem_joined: list[dict[str, Any]] = []
    matched_link = 0
    for r in modem_rows:
        linkid = r.get("TOPOLOGYLINKID", "")
        fnid = r.get("FIBERNODE", "")
        linked_node = by_linkid.get(linkid)
        if linked_node:
            matched_link += 1

        modem_joined.append(
            {
                "mac": _normalize_mac_address(r.get("MACADDRESS", "")),
                "fibernode": fnid,
                "topology_link_id": linkid,
                "lat": _to_float(r.get("LAT")),
                "lon": _to_float(r.get("LON")),
                "address": " ".join(
                    p for p in [r.get("ADDRESS1", ""), r.get("ADDRESS2", ""), r.get("POSTALCODE", ""), r.get("LOCALITY", "")]
                    if p
                ).strip(),
                "customer_id": r.get("CUSTOMERID", ""),
                "linked_node_id": linked_node.get("id") if linked_node else None,
                "linked_node_type": linked_node.get("node_type") if linked_node else None,
                "link_match": bool(linked_node),
            }
        )

    amp_nodes = 0
    tap_nodes = 0
    for node_type, count in node_type_counts.items():
        nt = (node_type or "").strip().lower()
        if nt == "amp":
            amp_nodes += count
        elif nt == "tap":
            tap_nodes += count

    fiber_nodes_count = len(fn_counts)
    avg_amp_per_node = (amp_nodes / fiber_nodes_count) if fiber_nodes_count else 0.0
    avg_tap_per_node = (tap_nodes / fiber_nodes_count) if fiber_nodes_count else 0.0

    return {
        "topology_nodes": topo_nodes,
        "topology_edges": edges,
        "modems": modem_joined,
        "stats": {
            "topology_nodes": len(topo_nodes),
            "topology_edges": len(edges),
            "modems": len(modem_rows),
            "fiber_nodes": fiber_nodes_count,
            "matched_by_linkid": matched_link,
            "potential_fibernode_match": 0,
            "unmatched_modems": max(0, len(modem_rows) - matched_link),
            "amp_nodes": amp_nodes,
            "tap_nodes": tap_nodes,
            "avg_amp_per_node": avg_amp_per_node,
            "avg_tap_per_node": avg_tap_per_node,
            "node_type_counts": dict(sorted(node_type_counts.items(), key=lambda kv: kv[0].lower())),
        },
    }


def load_topology_data(selected_date: str | None = None) -> dict[str, Any]:
    files = discover_topology_files(selected_date=selected_date)
    if not files.topology_file:
        return {
            "files": {
                "topology_file": None,
                "modemlocation_file": files.modemlocation_file,
                "image_files": files.image_files,
                "pair_date": files.pair_date,
                "warnings": files.warnings,
                "available_pair_dates": files.available_pair_dates,
                "selected_date": selected_date,
                "topology_dir": _repo_topology_dir(),
            },
            "topology_nodes": [],
            "topology_edges": [],
            "modems": [],
            "stats": {
                "topology_nodes": 0,
                "topology_edges": 0,
                "modems": 0,
                "fiber_nodes": 0,
                "matched_by_linkid": 0,
                "potential_fibernode_match": 0,
                "unmatched_modems": 0,
                "node_type_counts": {},
            },
        }

    payload: dict[str, Any]
    db_warning: str | None = None

    if topology_db.enabled:
        try:
            topology_db.init_db()
            snapshot_date = files.pair_date or _extract_date(os.path.splitext(os.path.basename(files.topology_file))[0])
            if snapshot_date:
                db_payload = topology_db.load_snapshot_payload(snapshot_date=snapshot_date, sample_limit=200)
                if db_payload is None:
                    raw_payload = _load_cached(
                        files.topology_file or "",
                        files.modemlocation_file or "",
                        _file_stamp(files.topology_file),
                        _file_stamp(files.modemlocation_file),
                    )
                    topology_db.upsert_snapshot_payload(
                        snapshot_date=snapshot_date,
                        topology_file=os.path.basename(files.topology_file) if files.topology_file else None,
                        modemlocation_file=os.path.basename(files.modemlocation_file) if files.modemlocation_file else None,
                        payload=raw_payload,
                    )
                    db_payload = topology_db.load_snapshot_payload(snapshot_date=snapshot_date, sample_limit=200)
                payload = db_payload or {
                    "topology_nodes": [],
                    "topology_edges": [],
                    "modems": [],
                    "stats": {
                        "topology_nodes": 0,
                        "topology_edges": 0,
                        "modems": 0,
                        "fiber_nodes": 0,
                        "matched_by_linkid": 0,
                        "potential_fibernode_match": 0,
                        "unmatched_modems": 0,
                        "node_type_counts": {},
                    },
                }
            else:
                payload = _load_cached(
                    files.topology_file or "",
                    files.modemlocation_file or "",
                    _file_stamp(files.topology_file),
                    _file_stamp(files.modemlocation_file),
                )
        except Exception as exc:
            db_warning = f"topology mysql fallback to file parsing: {exc}"
            payload = _load_cached(
                files.topology_file or "",
                files.modemlocation_file or "",
                _file_stamp(files.topology_file),
                _file_stamp(files.modemlocation_file),
            )
    else:
        payload = _load_cached(
            files.topology_file or "",
            files.modemlocation_file or "",
            _file_stamp(files.topology_file),
            _file_stamp(files.modemlocation_file),
        )

    warnings = list(files.warnings)
    if db_warning:
        warnings.append(db_warning)

    payload["files"] = {
        "topology_file": os.path.basename(files.topology_file) if files.topology_file else None,
        "modemlocation_file": os.path.basename(files.modemlocation_file) if files.modemlocation_file else None,
        "image_files": files.image_files,
        "pair_date": files.pair_date,
        "warnings": warnings,
        "available_pair_dates": files.available_pair_dates,
        "selected_date": selected_date,
        "topology_dir": _repo_topology_dir(),
        "storage_backend": "mysql" if topology_db.enabled else "file",
    }
    return payload
