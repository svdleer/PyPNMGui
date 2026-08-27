# SPDX-License-Identifier: Apache-2.0

import logging
import os

from app.core.auth_db import auth_db

logger = logging.getLogger(__name__)

_IS_LAB = (
    os.environ.get("FLASK_ENV") == "lab"
    or os.environ.get("PYPNM_MODE") == "lab"
)


def _environment_setting_key(name: str) -> str:
    return f"lab.{name}" if _IS_LAB else name


# Existing feature switches remain deployment-agnostic for backward compatibility.
NETWORK_RXMER_ANALYTICS_SETTING = "network_rxmer_analytics_enabled"
CM_BULK_RESET_SETTING = "cm_bulk_reset_enabled"
CUSTOM_SNMP_SETTING = "custom_snmp_enabled"
# Only topology-dependent scopes need a lab-specific override.
TOPOLOGY_SCOPES_SETTING = _environment_setting_key("topology_scopes_enabled")
FEATURE_FLAG_DEFAULTS = {
    NETWORK_RXMER_ANALYTICS_SETTING: "false",
    CM_BULK_RESET_SETTING: "false",
    CUSTOM_SNMP_SETTING: "false",
    TOPOLOGY_SCOPES_SETTING: "false" if _IS_LAB else "true",
}


def is_network_rxmer_analytics_enabled() -> bool:
    """Return the persisted admin feature flag, disabled on absence or DB failure."""
    try:
        return auth_db.get_bool_setting(NETWORK_RXMER_ANALYTICS_SETTING, default=False)
    except Exception as exc:
        logger.error("Unable to read Network RxMER Analytics feature flag: %s", exc)
        return False


def is_cm_bulk_reset_enabled() -> bool:
    """Return the persisted admin feature flag for CM Bulk Reset."""
    try:
        return auth_db.get_bool_setting(CM_BULK_RESET_SETTING, default=False)
    except Exception as exc:
        logger.error("Unable to read CM Bulk Reset feature flag: %s", exc)
        return False


def is_custom_snmp_enabled() -> bool:
    """Return the persisted admin feature flag for Custom SNMP queries."""
    try:
        return auth_db.get_bool_setting(CUSTOM_SNMP_SETTING, default=False)
    except Exception as exc:
        logger.error("Unable to read Custom SNMP feature flag: %s", exc)
        return False


def is_topology_scopes_enabled() -> bool:
    """Return whether topology-dependent scopes are available in this environment."""
    try:
        return auth_db.get_bool_setting(
            TOPOLOGY_SCOPES_SETTING,
            default=not _IS_LAB,
        )
    except Exception as exc:
        logger.error("Unable to read topology scopes feature flag: %s", exc)
        return not _IS_LAB
