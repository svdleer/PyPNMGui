# PyPNM Web GUI - CMTS Data Provider
# SPDX-License-Identifier: Apache-2.0
#
# Fetches CMTS inventory from appdb.oss.local API with caching

import requests
import time
import logging
from typing import Optional, List, Dict, Any
from functools import lru_cache
import os

logger = logging.getLogger(__name__)

# Check if running in LAB mode
LAB_MODE = os.environ.get('FLASK_ENV') == 'lab' or os.environ.get('PYPNM_MODE') == 'lab'

if LAB_MODE:
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
        from config_lab import LAB_CMTS_SYSTEMS
        logger.info(f"LAB MODE: Loaded {len(LAB_CMTS_SYSTEMS)} CMTS systems from config_lab.py")
    except ImportError as e:
        logger.error(f"LAB MODE: Failed to load config_lab.py: {e}")
        LAB_CMTS_SYSTEMS = []


class CMTSProvider:
    """Provides CMTS data from appdb.oss.local with caching."""
    
    # API Configuration
    API_URL = os.environ.get('APPDB_API_URL', 'https://appdb.oss.local/isw/api')
    API_USER = os.environ.get('APPDB_API_USER', 'isw')
    API_PASS = os.environ.get('APPDB_API_PASS', 'Spyem_OtGheb4')
    
    # Cache settings
    CACHE_TTL = 300  # 5 minutes cache
    
    # Instance variables
    _cache: Optional[Dict[str, Any]] = None
    _cache_time: float = 0
    
    @classmethod
    def _fetch_from_api(cls) -> Dict[str, Any]:
        """Fetch CMTS data from appdb API."""
        try:
            url = f"{cls.API_URL}/search?type=hostname&q=*"
            response = requests.get(
                url,
                auth=(cls.API_USER, cls.API_PASS),
                verify=False,  # Self-signed cert
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch CMTS data from appdb: {e}")
            return {"status": 500, "count": 0, "data": []}
    
    @classmethod
    def get_all_cmts(cls, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get all CMTS systems from appdb with caching (or LAB config in LAB mode).
        
        Args:
            force_refresh: If True, bypass cache and fetch fresh data
            
        Returns:
            List of CMTS dictionaries with fields:
            - HostName, IPAddress, Vendor, Type, Alias
        """
        # LAB MODE: Return static config
        if LAB_MODE:
            logger.debug("LAB MODE: Returning CMTS from config_lab.py")
            # Convert LAB config format to appdb format
            return [{
                'HostName': cmts['name'],
                'IPAddress': cmts['ip'],
                'Vendor': cmts.get('vendor', 'Casa'),  # Use vendor from config
                'Type': cmts.get('type', 'CCAP'),
                'Alias': cmts.get('location', ''),
                'snmp_community': cmts.get('snmp_community', 'oss1nf0')
            } for cmts in LAB_CMTS_SYSTEMS]
        
        current_time = time.time()
        
        # Check if cache is valid
        if not force_refresh and cls._cache is not None:
            if (current_time - cls._cache_time) < cls.CACHE_TTL:
                logger.debug("Returning cached CMTS data")
                return cls._cache.get('data', [])
        
        # Fetch fresh data
        logger.info("Fetching fresh CMTS data from appdb")
        data = cls._fetch_from_api()
        
        if data.get('status') == 200:
            cls._cache = data
            cls._cache_time = current_time
            logger.info(f"Cached {data.get('count', 0)} CMTS systems")
        
        return data.get('data', [])
    
    @classmethod
    def get_cmts_count(cls) -> int:
        """Get total number of CMTS systems."""
        cmts_list = cls.get_all_cmts()
        return len(cmts_list)
    
    @classmethod
    def get_cmts_by_vendor(cls, vendor: str) -> List[Dict[str, Any]]:
        """Filter CMTS systems by vendor (Arris, Casa, Cisco)."""
        cmts_list = cls.get_all_cmts()
        return [c for c in cmts_list if c.get('Vendor', '').lower() == vendor.lower()]
    
    @classmethod
    def get_cmts_by_type(cls, cmts_type: str) -> List[Dict[str, Any]]:
        """Filter CMTS systems by type (E6000, C100G, cBR-8)."""
        cmts_list = cls.get_all_cmts()
        return [c for c in cmts_list if c.get('Type', '').lower() == cmts_type.lower()]
    
    @classmethod
    def get_cmts_by_hostname(cls, hostname: str) -> Optional[Dict[str, Any]]:
        """Get a specific CMTS by hostname."""
        cmts_list = cls.get_all_cmts()
        for cmts in cmts_list:
            if cmts.get('HostName', '').lower() == hostname.lower():
                return cmts
        return None
    
    @classmethod
    def search_cmts(cls, query: str) -> List[Dict[str, Any]]:
        """
        Search CMTS by hostname, alias, or IP address.
        
        Args:
            query: Search string (case-insensitive)
            
        Returns:
            List of matching CMTS systems
        """
        cmts_list = cls.get_all_cmts()
        query = query.lower()
        
        results = []
        for cmts in cmts_list:
            hostname = cmts.get('HostName', '').lower()
            alias = cmts.get('Alias', '').lower()
            ip = cmts.get('IPAddress', '').lower()
            
            if query in hostname or query in alias or query in ip:
                results.append(cmts)
        
        return results
    
    @classmethod
    def get_vendors_summary(cls) -> Dict[str, int]:
        """Get count of CMTS systems by vendor."""
        cmts_list = cls.get_all_cmts()
        vendors: Dict[str, int] = {}
        
        for cmts in cmts_list:
            vendor = cmts.get('Vendor', 'Unknown')
            vendors[vendor] = vendors.get(vendor, 0) + 1
        
        return vendors
    
    @classmethod
    def get_types_summary(cls) -> Dict[str, int]:
        """Get count of CMTS systems by type."""
        cmts_list = cls.get_all_cmts()
        types: Dict[str, int] = {}
        
        for cmts in cmts_list:
            cmts_type = cmts.get('Type', 'Unknown')
            types[cmts_type] = types.get(cmts_type, 0) + 1
        
        return types
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the CMTS cache."""
        cls._cache = None
        cls._cache_time = 0
        logger.info("CMTS cache cleared")
    
    @classmethod
    def get_cache_info(cls) -> Dict[str, Any]:
        """Get cache status information."""
        current_time = time.time()
        cache_age = current_time - cls._cache_time if cls._cache_time > 0 else None
        
        return {
            "cached": cls._cache is not None,
            "cache_age_seconds": cache_age,
            "cache_ttl_seconds": cls.CACHE_TTL,
            "cache_expires_in": cls.CACHE_TTL - cache_age if cache_age else None,
            "cached_count": len(cls._cache.get('data', [])) if cls._cache else 0
        }


# Suppress SSL warnings for self-signed certs
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
