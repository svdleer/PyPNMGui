# PNM File Acquisition Migration — High Priority

Status: **ASAP architecture remediation**

PyPNM must become the sole owner of PNM file-source selection, FTP/TFTP/agent retrieval, cache policy, housekeeping, and binary parsing. PyPNMGui may retain browser presentation and the `/ws/utsc/<mac>` spectrum stream, but it must consume normalized PyPNM results rather than acquire or parse capture files itself.

## Required work

- [ ] Define complete PyPNM APIs for capture listing, retrieval, deletion, and normalized sample responses.
- [ ] Keep vendor-specific source selection and FTP/TFTP/agent policy inside PyPNM.
- [ ] Move active `pypnm_routes.py` file fetching, cache-path decisions, and housekeeping to those APIs.
- [ ] Move `/ws/utsc` file polling and binary amplitude parsing to PyPNM.
- [ ] Stream normalized UTSC samples from PyPNM to the GUI browser stream.
- [ ] Remove `backend/app/core/pnm_file_source.py` only after all active imports are gone.

## Current active GUI dependencies

- `backend/app/routes/pypnm_routes.py` uses the GUI file-source module for RxMER and other capture flows.
- `backend/app/routes/ws_routes.py` uses it for UTSC file acquisition and currently parses UTSC binary samples.

## Completion criteria

- PyPNMGui contains no FTP credentials, vendor file-source policy, capture cache policy, or PNM binary parser.
- PyPNM is authoritative for file acquisition and returns normalized data or explicit file metadata.
- `/ws/utsc/<mac>` remains operational as a browser-facing presentation stream.
- Existing local, FTP, and agent deployment modes continue to work without GUI-side transport decisions.
