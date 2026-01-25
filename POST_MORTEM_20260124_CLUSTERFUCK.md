# POST-MORTEM: 2026-01-24 CLUSTERFUCK

## Summary
Another major clusterfuck occurred during UTSC integration and testing. All available SKUs were burned and rendered useless due to repeated infrastructure failures, misconfiguration, and build errors. The agent lost focus, built the wrong Docker images, and failed to use the correct PyPNM fork. Multiple reminders were required to point out the correct build path and configuration.

## Timeline
- Attempted to deploy UTSC trigger fix and test continuous spectrum capture
- Initial builds used the wrong PyPNM source (old/original, not fork)
- Healthchecks and agent ports were misconfigured
- Agent and API containers repeatedly unhealthy, causing endless restarts
- SNMP traffic was not sent; PyPNM API failed to initiate UTSC
- User had to repeatedly point out the correct PyPNM fork and build path
- After hours of troubleshooting, the environment was still unable to generate new UTSC files

## Root Causes
- Docker-compose pointed to the wrong PyPNM source directory (later discovered BOTH paths had the fork)
- Agent and API healthchecks were broken (python vs python3)
- Agent was connecting to wrong port (5051 vs 5050)
- GUI missing ipv6 field in TFTP config
- Multiple rebuilds degraded the environment beyond recovery
- UTSC worked at 21:10 with same fork code but stopped working after rebuilds
- Lack of clear ownership and focus in the agent's actions
- User intervention required multiple times to correct build path and configuration
- **Critical discovery**: Both /home/svdleer/docker/PyPNM and /opt/pypnm/PyPNM are the SAME fork
- **Environment degradation**: Same code that generated files at 21:10 fails after multiple rebuilds
- SNMP connectivity confirmed working, but UTSC capture fails with generic error

## Impact
- All SKUs for the day were burned and rendered useless
- No new UTSC data generated
- Significant time wasted on infrastructure and build issues
- User frustration and loss of productivity

## Lessons Learned
- Always verify Docker build context and source before deploying
- Ensure healthchecks and agent ports are correct before testing
- Document and automate build steps to avoid repeated manual intervention
- Maintain clear focus and ownership during troubleshooting

## Action Items
- Update documentation to clarify build paths and fork usage
- Automate healthcheck and agent port validation
- Implement post-build verification to ensure correct code is deployed
- Schedule infrastructure review to prevent future clusterfucks

---
**Filed by GitHub Copilot on behalf of user after repeated infrastructure failures and wasted SKUs.**
