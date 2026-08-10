# PNM File Acquisition Migration

Status: **implemented locally; validation pending commit**

PyPNM is the sole owner of CMTS PNM file-source selection, vendor FTP/TFTP/agent policy, cache paths, capture housekeeping, and UTSC binary parsing. PyPNMGui retains browser presentation and `/ws/utsc/<mac>`, consuming normalized PyPNM samples.

## Completed work

- [x] Added PyPNM capture listing, retrieval, deletion, age-housekeeping, and normalized UTSC sample APIs.
- [x] Centralized vendor source mode, FTP routing, TFTP destination, cache, and safe-prefix deletion policy in PyPNM.
- [x] Made RxMER analysis resolve and retrieve capture files inside PyPNM rather than from GUI paths.
- [x] Moved `pypnm_routes.py` UTSC/RxMER fetching, path decisions, destination policy, and capture housekeeping behind PyPNM APIs.
- [x] Moved `/ws/utsc` file polling and binary amplitude parsing to PyPNM.
- [x] Preserved `/ws/utsc/<mac>` start/retrigger/stop ownership and browser spectrum envelope.
- [x] Removed `backend/app/core/pnm_file_source.py` after all active imports were removed.

## Resulting ownership

- **PyPNM:** local/FTP/agent selection, vendor configuration, atomic retrieval, cache, deletion, housekeeping, UTSC decoding, and RxMER file resolution.
- **PyPNMGui:** authenticated HTTP adapters, optional plot generation, Redis-backed presentation frequency settings, and browser WebSocket buffering.
- **pyPNMAgent:** remote file listing/retrieval plus default-disabled exact deletion and bounded age-housekeeping when PyPNM selects agent mode. Destructive capabilities require an explicit writable root and independent opt-ins; they never use discovered read fallbacks.

## Compatibility

- Existing GUI UTSC REST responses retain `frequencies`, `amplitudes`, and plot support.
- Browser messages retain `type: spectrum` and the existing `raw_data` frequency/bin fields.
- Legacy PyPNM `tftp_path` request fields remain accepted but GUI callers no longer send cross-container paths.
- The normalized parser preserves the deployed GUI behavior: Cisco files use big-endian centi-dB samples; other current CMTS files use little-endian centi-dB samples after the 328-byte header.
