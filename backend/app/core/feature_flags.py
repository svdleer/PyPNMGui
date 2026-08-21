# SPDX-License-Identifier: Apache-2.0

import logging

from app.core.auth_db import auth_db

logger = logging.getLogger(__name__)
NETWORK_RXMER_ANALYTICS_SETTING = "network_rxmer_analytics_enabled"
CM_BULK_RESET_SETTING = "cm_bulk_reset_enabled"
CUSTOM_SNMP_SETTING = "custom_snmp_enabled"


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
