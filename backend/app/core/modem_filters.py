import ipaddress
import os
import re
from functools import lru_cache


def _raw_modem_ignore_value() -> str:
    # Backward-compatible aliases: MODEM_IGNORE_CIDRS preferred, MODEM_IGNORE fallback.
    return str(os.environ.get("MODEM_IGNORE_CIDRS") or os.environ.get("MODEM_IGNORE") or "").strip()


@lru_cache(maxsize=1)
def get_modem_ignore_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = _raw_modem_ignore_value()
    if not raw:
        return ()

    tokens = [t for t in re.split(r"[\s,;]+", raw) if t]
    nets = []
    for token in tokens:
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except Exception:
            # Ignore invalid entries so one bad token does not break runtime.
            continue
    return tuple(nets)


def is_ignored_modem_ip(ip_value: str | None) -> bool:
    if not ip_value:
        return False
    try:
        addr = ipaddress.ip_address(str(ip_value).strip())
    except Exception:
        return False

    for net in get_modem_ignore_networks():
        if addr.version == net.version and addr in net:
            return True
    return False


def filter_ignored_modems(modems: list[dict], ip_field: str = "ip_address") -> list[dict]:
    if not modems:
        return modems
    nets = get_modem_ignore_networks()
    if not nets:
        return modems
    def _extract_ip(modem: dict) -> str | None:
        if not modem:
            return None
        for key in (ip_field, "ip_address", "ip", "modem_ip"):
            value = modem.get(key)
            if value:
                return str(value).strip()
        return None

    return [m for m in modems if not is_ignored_modem_ip(_extract_ip(m or {}))]
