# SPDX-License-Identifier: Apache-2.0

import logging
import os

from app.core.auth_db import auth_db

logger = logging.getLogger(__name__)

_IS_LAB = (
    os.environ.get("FLASK_ENV") == "lab"
    or os.environ.get("PYPNM_MODE") == "lab"
)
_SETTING_PREFIX = "lab." if _IS_LAB else ""


def _setting_key(name: str) -> str:
    return f"{_SETTING_PREFIX}{name}"


NETWORK_RXMER_ANALYTICS_SETTING = _setting_key("network_rxmer_analytics_enabled")
CM_BULK_RESET_SETTING = _setting_key("cm_bulk_reset_enabled")
CUSTOM_SNMP_SETTING = _setting_key("custom_snmp_enabled")
FEATURE_FLAG_DEFAULTS = {
    NETWORK_RXMER_ANALYTICS_SETTING: "false",
    CM_BULK_RESET_SETTING: "false",
    CUSTOM_SNMP_SETTING: "false",
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
