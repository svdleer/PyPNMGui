# Post-Mortem: Lab Bulk CM Write Schema Failure

**Date:** 2026-10-03  
**Environment:** Lab  
**Severity:** P1 deployment regression  
**Status:** Resolved

## Summary

The lab PyPNM API remained available but the Bulk CM write scheduler repeatedly failed while initializing its database schema. The failure was caused by new foreign-key DDL requiring the application database user to have the MySQL `REFERENCES` privilege. The lab user `pypnm_app` does not have that privilege.

The API health endpoint stayed green because the failing work ran in a background scheduler. This made the deployment appear healthy while Bulk CM write scheduling was unavailable.

## Impact

- Bulk CM write scheduling could not initialize its schema.
- The scheduler logged the same database error repeatedly.
- The API health endpoint continued returning HTTP success.
- The GUI and agent containers were not the cause of this incident and were not restarted for the fix.
- No device operation or configuration change was performed as part of this incident.

## Immediate Cause

The new `cm_snmp_write_target` and `cm_snmp_write_result` table definitions included foreign keys referencing `cm_snmp_write_job` and `cm_snmp_write_target`:

```text
REFERENCES command denied to user 'pypnm_app'@'localhost'
```

The lab database account can create and use the application tables but cannot create those foreign-key relationships. Schema initialization therefore failed when the scheduler called `ensure_schema()`.

## Contributing Factors

### Deployment into a dirty source checkout

The lab PyPNM checkout already contained unrelated local state before deployment:

- Deleted tracked files under `src/pypnm/settings/`
- An untracked `src/pypnm/settings/` path

The deployment used a fast-forward pull and preserved those artifacts. They were not cleaned, reset, overwritten, or deleted. The feature change did not modify configuration files, so the dirty state was not the direct cause of the schema failure. It did increase deployment uncertainty and made broad cleanup unsafe.

### Background scheduler failure was not part of health status

The scheduler exception was logged repeatedly while `/health` continued to report `{"status":"ok"}`. The health endpoint did not expose the readiness of the Bulk CM write scheduler or its schema initialization state.

### Schema privileges were not checked before deployment

The new DDL was reviewed as application code but not exercised against the lab database account before deployment. The privilege mismatch was therefore detected only after the scheduler started in lab.

## Timeline

1. The OFDM 6 MHz API and GUI changes were pulled into lab source-mounted containers.
2. The API restart initially exposed a separate recovery-table compatibility issue, which was guarded by commit `efb88308`.
3. The API then started successfully but logged repeated Bulk CM write schema failures.
4. The error was traced to foreign-key creation in `cm_snmp_write/service.py`.
5. Commit `521ce1dd` removed the three foreign-key constraints from the new DDL while retaining all columns and indexes.
6. Because child rows no longer cascade automatically, the same commit changed job deletion to delete result rows, target rows, and the job in one transaction.
7. The commit was pushed to `origin/main`, pulled into `/home/svdleer/docker/PyPNM`, and only `pypnm-api` was restarted.

## Resolution

Commit `521ce1dd` made the Bulk CM write schema compatible with the lab application database privileges:

- Removed foreign-key definitions from `cm_snmp_write_target` and `cm_snmp_write_result`.
- Retained `job_id`, `target_id`, primary keys, unique keys, and secondary indexes.
- Added transactional child-first cleanup for job deletion so removing the foreign keys does not leave target or result orphans.

No database grants were changed. No configuration files were changed.

## Verification

After deployment:

- Lab PyPNM revision: `521ce1d`
- `pypnm-api`: running and healthy
- `/health`: returned `{"status":"ok","version":"1.0.55.0"}`
- Running container source contained no `FOREIGN KEY` definitions in the Bulk CM write DDL.
- No new `CM write scheduler failed` messages appeared after the API restart.
- No new `REFERENCES command denied` messages appeared after the API restart.
- `pypnm-gui-lab`, `pypnm-agent-lab`, and Redis were left running and were not restarted.
- The pre-existing dirty PyPNM checkout artifacts remained unchanged.

The old error lines visible in the combined recent log window were from the period before the restart. Fresh post-restart logs showed normal API startup and scheduler operation without the Bulk CM write schema error.

## Prevention Actions

- Keep schema DDL compatible with the privileges granted to the application DB user. Do not require `REFERENCES` unless the deployment explicitly grants it.
- Add a schema smoke test that runs as the real application DB account before deployment.
- Make background scheduler readiness visible through health or readiness status, including the last schema initialization failure.
- Keep source-only deployments narrow: pull with `--ff-only`, preserve unrelated dirty artifacts, and restart only the affected source-mounted service.
- Record and verify the running container revision and changed source content after every deployment.
- Continue using explicit transactional cleanup when database-enforced cascade behavior is unavailable.

## Architecture Compliance

The fix stayed within the required GUI → PyPNM API → agent boundary. It changed only API-owned schema and job cleanup behavior. No GUI-to-agent path, direct device access, shared-file bypass, or agent configuration change was introduced.
