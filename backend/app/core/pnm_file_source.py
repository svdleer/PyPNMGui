"""
PNM file source abstraction.

By default (PNM_FILE_SOURCE=local) PyPNM reads capture files from a locally
mounted TFTP directory (e.g. /var/lib/tftpboot).

When PNM_FILE_SOURCE=ftp the container has no TFTP mount; capture files land
on an FTP server (same host as the TFTP server, or different).  Before calling
any PyPNM endpoint that uses tftp_path we pre-fetch matching files from FTP
into a local cache directory (/app/data/pnm_cache/) and pass that as tftp_path.

Environment variables:
    PNM_FILE_SOURCE     "local" (default) or "ftp"
    FTP_SERVER_IP       FTP server hostname/IP  (falls back to TFTP_IPV4)
    FTP_USER            FTP username             (default: ftpaccess)
    FTP_PASSWORD        FTP password             (default: ftpaccessftp)

    Vendor-specific FTP overrides (fall back to the generic vars above):
    FTP_SERVER_IP_COMMSCOPE / FTP_USER_COMMSCOPE / FTP_PASSWORD_COMMSCOPE
    FTP_SERVER_IP_CISCO     / FTP_USER_CISCO     / FTP_PASSWORD_CISCO
    FTP_SERVER_IP_CASA      / FTP_USER_CASA      / FTP_PASSWORD_CASA
    FTP_SERVER_IP_ALT       / FTP_USER_ALT       / FTP_PASSWORD_ALT
    FTP_TFTPBOOT_DIR    Remote directory on FTP server where CMTS files land
                        (default: /var/lib/tftpboot)
    TFTPBOOT_DIR        Local path used in 'local' mode
                        (default: /var/lib/tftpboot)
    PNM_CACHE_DIR       Local cache dir used in 'ftp' mode
                        (default: /app/data/pnm_cache)
    TFTP_DEST_PATH      Path component sent to CMTS in bulk-destination base URI
                        (default: ./)  Set to ./access/pnm/ when using FTP mode
                        with a sub-directory on the TFTP/FTP server.
"""
from __future__ import annotations

import ftplib
import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# ── configuration ──────────────────────────────────────────────────────────

def _env(key: str, default: str = '') -> str:
    return os.environ.get(key, default)

def is_ftp_mode() -> bool:
    return (_env('PNM_FILE_SOURCE', 'local').lower() in ('ftp', 'agent')
            or _env('CMTS_TFTP', '').lower() == 'ftp')

def get_tftp_dest_path() -> str:
    """Path component for CMTS bulk-destination base URI (e.g. './access/pnm/')."""
    return _env('TFTP_DEST_PATH', './')

def get_tftp_dest_path_for_vendor(vendor: str) -> str:
    """Return the TFTP upload root path for the given vendor.

    Lookup order:
      TFTP_ROOT_COMMSCOPE / TFTP_ROOT_CISCO / TFTP_ROOT_CASA / TFTP_ROOT_ALT
      → TFTP_DEST_PATH → './'
    """
    vendor = (vendor or '').lower()
    key_map = {
        'e6000':     'TFTP_ROOT_COMMSCOPE',
        'commscope': 'TFTP_ROOT_COMMSCOPE',
        'arris':     'TFTP_ROOT_COMMSCOPE',
        'cisco':     'TFTP_ROOT_CISCO',
        'casa':      'TFTP_ROOT_CASA',
    }
    key = key_map.get(vendor, 'TFTP_ROOT_ALT')
    return _env(key) or get_tftp_dest_path()

def get_ftp_config() -> dict:
    return {
        'host':    _env('FTP_SERVER_IP') or _env('TFTP_IPV4', '127.0.0.1'),
        'port':    int(_env('FTP_PORT', '21')),
        'user':    _env('FTP_USER', 'ftpaccess'),
        'password': _env('FTP_PASSWORD', 'ftpaccessftp'),
        'ftp_dir': _env('FTP_TFTPBOOT_DIR', '/var/lib/tftpboot'),
    }

def get_ftp_config_for_vendor(vendor: str) -> dict:
    """Return FTP config for the given vendor.

    Checks FTP_SERVER_IP_<VENDOR>, FTP_USER_<VENDOR>, FTP_PASSWORD_<VENDOR>
    first; falls back to the generic FTP_* vars.
    """
    vendor = (vendor or '').lower()
    suffix_map = {
        'e6000':     'COMMSCOPE',
        'commscope': 'COMMSCOPE',
        'arris':     'COMMSCOPE',
        'cisco':     'CISCO',
        'casa':      'CASA',
    }
    suffix = suffix_map.get(vendor, 'ALT')
    base = get_ftp_config()
    return {
        'host':     _env(f'FTP_SERVER_IP_{suffix}') or base['host'],
        'port':     int(_env(f'FTP_PORT_{suffix}') or base['port']),
        'user':     _env(f'FTP_USER_{suffix}') or base['user'],
        'password': _env(f'FTP_PASSWORD_{suffix}') or base['password'],
        'ftp_dir':  _env(f'FTP_TFTPBOOT_DIR_{suffix}') or base['ftp_dir'],
    }

def get_all_ftp_configs() -> list[dict]:
    """Return list of all distinct FTP configs (generic + any vendor overrides).

    Used by fetch_pnm_files when no specific vendor is known — tries all servers.
    Deduplicates by (host, port, user) so the same server is not queried twice.
    """
    configs = []
    seen = set()
    for vendor in ('commscope', 'cisco', 'casa', 'alt', ''):
        cfg = get_ftp_config_for_vendor(vendor) if vendor else get_ftp_config()
        key = (cfg['host'], cfg['port'], cfg['user'])
        if key not in seen:
            seen.add(key)
            configs.append(cfg)
    return configs

def get_cache_dir() -> str:
    d = _env('PNM_CACHE_DIR', '/app/data/pnm_cache')
    os.makedirs(d, exist_ok=True)
    return d

# ── public helpers ──────────────────────────────────────────────────────────

def local_tftp_path() -> str:
    """
    Return the local filesystem path PyPNM should read from.

    - local mode: the mounted tftpboot dir (TFTPBOOT_DIR env, default /var/lib/tftpboot)
    - ftp mode:   the local cache dir where files were pre-fetched
    """
    if is_ftp_mode():
        return get_cache_dir()
    return _env('TFTPBOOT_DIR', '/var/lib/tftpboot')


def fetch_pnm_files(
    filename_prefix: str,
    *,
    ftp_cfg: dict | None = None,
    allow_when_local: bool = False,
) -> List[str]:
    """
    Download every file on the FTP server whose basename starts with
    *filename_prefix* into the local cache directory.

    Returns the list of local file paths that were downloaded, or [] on error.

    By default this is active only in ftp mode. Set ``allow_when_local=True``
    for mixed deployments where some captures are local (agent) while CMTS
    captures still need FTP prefetch.

    When *ftp_cfg* is None, all distinct vendor FTP servers are tried so that
    files from different vendors (Casa, CommScope, …) are all found.
    """
    if not is_ftp_mode() and not allow_when_local:
        return []

    configs = [ftp_cfg] if ftp_cfg is not None else get_all_ftp_configs()
    all_downloaded: List[str] = []
    for cfg in configs:
        all_downloaded.extend(_fetch_from_single_ftp(filename_prefix, cfg))
    return all_downloaded


def _fetch_from_single_ftp(filename_prefix: str, ftp_cfg: dict) -> List[str]:
    """Internal: fetch matching files from one FTP server."""
    cache_dir = get_cache_dir()
    downloaded: List[str] = []

    try:
        ftp = ftplib.FTP()
        ftp.connect(ftp_cfg['host'], ftp_cfg['port'], timeout=15)
        ftp.login(ftp_cfg['user'], ftp_cfg['password'])

        ftp_dir = ftp_cfg['ftp_dir']
        try:
            ftp.cwd(ftp_dir)
        except ftplib.error_perm as e:
            logger.warning(f"FTP: could not cd to {ftp_dir}: {e}")
            ftp.quit()
            return []

        # List files and filter by prefix
        try:
            all_files = ftp.nlst()
        except ftplib.error_perm:
            all_files = []

        prefix = os.path.basename(filename_prefix)
        matching = [f for f in all_files if os.path.basename(f).startswith(prefix)]

        if not matching:
            logger.debug(f"FTP: no files matching '{prefix}*' in {ftp_dir}")
        
        for remote_file in matching:
            basename = os.path.basename(remote_file)
            local_path = os.path.join(cache_dir, basename)
            if os.path.exists(local_path):
                continue
            try:
                with open(local_path, 'wb') as fp:
                    ftp.retrbinary(f'RETR {basename}', fp.write)
                downloaded.append(local_path)
                logger.debug(f"FTP: fetched {basename} -> {local_path}")
            except Exception as e:
                logger.warning(f"FTP: failed to download {basename}: {e}")

        ftp.quit()
        if downloaded:
            logger.info(f"FTP fetch: {len(downloaded)} file(s) for prefix '{prefix}'")
        else:
            logger.debug(f"FTP fetch: 0 file(s) for prefix '{prefix}'")

    except Exception as e:
        logger.warning(f"FTP fetch error (host={ftp_cfg.get('host')}): {e}")

    return downloaded


def ensure_pnm_files_local(filename: str, tftp_path: str = '/var/lib/tftpboot') -> str:
    """
    Ensure that PNM capture files for *filename* are accessible locally.

    - local mode: returns *tftp_path* unchanged (mount is expected to be there)
    - ftp mode:   downloads matching files from FTP, returns the local cache dir

    Use this in any route that passes tftp_path to a PyPNM endpoint, e.g.:

        resolved_path = ensure_pnm_files_local(filename, tftp_path)
        payload['tftp_path'] = resolved_path
    """
    if not is_ftp_mode():
        return tftp_path

    fetch_pnm_files(os.path.basename(filename))
    return get_cache_dir()


def delete_pnm_files(filename_prefix: str, *, ftp_cfg: dict | None = None) -> int:
    """
    Delete files whose basename starts with *filename_prefix* from the local
    cache directory only.  FTP cleanup is left to the PyPNM API.

    Call this after a file has been successfully processed (housekeeping).
    Returns total number of deleted files.
    """
    prefix = os.path.basename(filename_prefix)
    deleted = 0

    cache_dir = get_cache_dir()
    for p in Path(cache_dir).glob(f"{prefix}*"):
        try:
            p.unlink()
            deleted += 1
            logger.debug(f"Cache housekeeping: deleted {p.name}")
        except Exception as e:
            logger.warning(f"Cache housekeeping: {p.name}: {e}")

    if deleted:
        logger.info(f"Housekeeping: removed {deleted} file(s) for prefix '{prefix}'")
    return deleted
