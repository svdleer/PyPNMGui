# SPDX-License-Identifier: Apache-2.0

import logging

from app.core.auth_db import auth_db

logger = logging.getLogger(__name__)
NETWORK_RXMER_ANALYTICS_SETTING = "network_rxmer_analytics_enabled"


def is_network_rxmer_analytics_enabled() -> bool:
    """Return the persisted admin feature flag, disabled on absence or DB failure."""
    try:
        return auth_db.get_bool_setting(NETWORK_RXMER_ANALYTICS_SETTING, default=False)
    except Exception as exc:
        logger.error("Unable to read Network RxMER Analytics feature flag: %s", exc)
        return False
