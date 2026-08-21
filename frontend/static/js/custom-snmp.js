/* Custom SNMP Query — admin tool */
(function () {
    'use strict';

    const root = document.getElementById('custom-snmp-app');
    const basePath = (root && root.dataset.basePath) || '';
    const apiBase = `${basePath}/api/admin/custom-snmp`;

    function byId(id) { return document.getElementById(id); }

    async function request(method, path, body) {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const resp = await fetch(`${apiBase}${path}`, opts);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || err.message || `HTTP ${resp.status}`);
        }
        return resp.json();
    }

    // ── State ───────────────────────────────────────────────

    let selectedJobId = null;
    let pollTimer = null;

    // ── OID builder ─────────────────────────────────────────

    const oidContainer = byId('oid-list-container');

    function createOidRow(oid = '', label = '') {
        const row = document.createElement('div');
        row.className = 'oid-row';
        row.innerHTML = `
            <input type="text" class="form-control form-control-sm snmp-code" placeholder="OID (e.g. sysUpTime.0)" data-field="oid" value="${oid}">
            <input type="text" class="form-control form-control-sm" placeholder="Label" style="max-width:120px;" data-field="label" value="${label}">
            <button class="btn btn-sm btn-outline-success oid-verify-btn" title="Verify OID"><i class="bi bi-check-circle"></i></button>
            <button class="btn btn-sm btn-outline-danger oid-remove-btn" title="Remove"><i class="bi bi-dash"></i></button>
        `;
        row.querySelector('.oid-remove-btn').addEventListener('click', () => {
            if (oidContainer.querySelectorAll('.oid-row').length > 1) {
                row.remove();
                updateOidCount();
            }
        });
        row.querySelector('.oid-verify-btn').addEventListener('click', async () => {
            const cmts = byId('snmp-cmts').value;
            if (!cmts) { alert('Select a CMTS first to verify OIDs'); return; }
            const oidInput = row.querySelector('[data-field="oid"]');
            const oidVal = oidInput.value.trim();
            if (!oidVal) return;
            const btn = row.querySelector('.oid-verify-btn');
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                const data = await request('POST', '/verify-oid', { oid: oidVal, cmts });
                if (data.success) {
                    btn.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
                    btn.title = `OK: ${data.value} (tested on ${data.modem_ip})`;
                    oidInput.classList.remove('is-invalid');
                    oidInput.classList.add('is-valid');
                } else {
                    btn.innerHTML = '<i class="bi bi-x-circle-fill text-danger"></i>';
                    btn.title = data.error || 'Verification failed';
                    oidInput.classList.remove('is-valid');
                    oidInput.classList.add('is-invalid');
                }
            } catch (e) {
                btn.innerHTML = '<i class="bi bi-x-circle-fill text-danger"></i>';
                btn.title = e.message;
                oidInput.classList.add('is-invalid');
            }
            btn.disabled = false;
        });
        return row;
    }

    function updateOidCount() {
        const count = oidContainer.querySelectorAll('.oid-row').length;
        byId('oid-count').textContent = `${count} OID${count !== 1 ? 's' : ''}`;
    }

    byId('oid-add-btn').addEventListener('click', () => {
        oidContainer.appendChild(createOidRow());
        updateOidCount();
    });

    // Wire up initial remove button
    oidContainer.querySelector('.oid-remove-btn').addEventListener('click', function () {
        if (oidContainer.querySelectorAll('.oid-row').length > 1) {
            this.closest('.oid-row').remove();
            updateOidCount();
        }
    });
    // Replace initial row with dynamic version that has verify button
    const initialRow = oidContainer.querySelector('.oid-row');
    if (initialRow) {
        const newRow = createOidRow();
        initialRow.replaceWith(newRow);
    }

    function getOids() {
        const rows = oidContainer.querySelectorAll('.oid-row');
        const oids = [];
        rows.forEach(row => {
            const oid = row.querySelector('[data-field="oid"]').value.trim();
            const label = row.querySelector('[data-field="label"]').value.trim();
            if (oid) oids.push({ oid, label: label || null });
        });
        return oids;
    }

    function setOids(oids) {
        oidContainer.innerHTML = '';
        (oids || []).forEach(entry => {
            oidContainer.appendChild(createOidRow(entry.oid || '', entry.label || ''));
        });
        if (!oidContainer.children.length) oidContainer.appendChild(createOidRow());
        updateOidCount();
    }

    // ── Templates ───────────────────────────────────────────

    async function loadTemplates() {
        try {
            const data = await request('GET', '/templates');
            const sel = byId('snmp-template-select');
            sel.innerHTML = '<option value="">— templates —</option>' +
                (data.templates || []).map(t => `<option value="${t.id}">${t.name} (${t.oids.length} OIDs)</option>`).join('');
        } catch (e) { console.warn('Templates load failed:', e); }
    }

    byId('snmp-load-template').addEventListener('click', async () => {
        const id = byId('snmp-template-select').value;
        if (!id) return;
        try {
            const data = await request('GET', '/templates');
            const tmpl = (data.templates || []).find(t => String(t.id) === id);
            if (tmpl) setOids(tmpl.oids);
        } catch (e) { alert(`Load failed: ${e.message}`); }
    });

    byId('snmp-save-template').addEventListener('click', async () => {
        const oids = getOids();
        if (!oids.length) return alert('Add at least one OID first');
        const name = prompt('Template name:');
        if (!name) return;
        try {
            await request('POST', '/templates', { name, oids, description: null });
            await loadTemplates();
            alert('Template saved');
        } catch (e) { alert(`Save failed: ${e.message}`); }
    });

    // ── Scope ───────────────────────────────────────────────

    const scopeType = byId('snmp-scope-type');
    const cmtsWrap = byId('snmp-cmts-wrap');
    const fnWrap = byId('snmp-fn-wrap');

    function updateScopeUI() {
        const type = scopeType.value;
        cmtsWrap.classList.toggle('d-none', type === 'all_network');
        fnWrap.classList.toggle('d-none', type !== 'fiber_node');
    }
    scopeType.addEventListener('change', updateScopeUI);

    async function loadCmtsOptions() {
        try {
            const data = await request('GET', '/options/cmts?limit=5000');
            const sel = byId('snmp-cmts');
            sel.innerHTML = '<option value="">— select —</option>' +
                (data.cmts || []).map(c => `<option value="${c}">${c}</option>`).join('');
        } catch (e) { console.warn('CMTS options:', e); }
    }

    byId('snmp-cmts').addEventListener('change', async function () {
        const cmts = this.value;
        const fnSel = byId('snmp-fiber-node');
        if (!cmts) { fnSel.innerHTML = '<option value="">Select CMTS</option>'; fnSel.disabled = true; return; }
        fnSel.disabled = false;
        fnSel.innerHTML = '<option value="">Loading...</option>';
        try {
            const data = await request('GET', `/options/fiber-nodes?cmts=${encodeURIComponent(cmts)}`);
            fnSel.innerHTML = '<option value="">— all —</option>' +
                (data.fiber_nodes || []).map(fn => `<option value="${fn}">${fn}</option>`).join('');
        } catch (e) { fnSel.innerHTML = '<option value="">Error</option>'; }
    });

    // ── Create plan ─────────────────────────────────────────

    byId('snmp-plan-btn').addEventListener('click', async function () {
        const oids = getOids();
        if (!oids.length) return alert('Add at least one OID');

        const type = scopeType.value;
        const scope = { type };
        if (type === 'cmts') {
            const cmts = byId('snmp-cmts').value;
            if (!cmts) return alert('Select a CMTS');
            scope.cmts = [cmts];
        } else if (type === 'fiber_node') {
            const cmts = byId('snmp-cmts').value;
            const fn = byId('snmp-fiber-node').value;
            if (!cmts) return alert('Select a CMTS');
            if (!fn) return alert('Select a fiber node');
            scope.cmts = cmts;
            scope.fiber_nodes = [fn];
        }

        const maxModems = parseInt(byId('snmp-max-modems').value) || 100;
        this.disabled = true;
        try {
            await request('POST', '/jobs/plan', { scope, oids, max_modems: maxModems });
            await refreshJobs();
        } catch (e) { alert(`Plan failed: ${e.message}`); }
        finally { this.disabled = false; }
    });

    // ── Job list ────────────────────────────────────────────

    function statusBadge(status) {
        const map = { planned: 'bg-secondary', running: 'bg-primary', completed: 'bg-success', completed_with_errors: 'bg-warning text-dark', failed: 'bg-danger' };
        return `<span class="badge ${map[status] || 'bg-secondary'}">${status}</span>`;
    }

    async function refreshJobs() {
        try {
            const data = await request('GET', '/jobs?limit=30');
            const body = byId('snmp-jobs-body');
            const jobs = data.jobs || [];
            if (!jobs.length) { body.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3">No jobs</td></tr>'; return; }
            body.innerHTML = jobs.map(job => `
                <tr data-job-id="${job.public_id}" style="cursor:pointer">
                    <td>${statusBadge(job.status)}</td>
                    <td><small>${job.scope_type || '—'}</small></td>
                    <td><small>${(job.oids || []).length}</small></td>
                    <td><small>${job.targets_succeeded + job.targets_failed}/${job.targets_total}</small></td>
                    <td><small>${job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</small></td>
                    <td>
                        ${job.status === 'planned' ? `<button class="btn btn-sm btn-success snmp-start-btn" data-id="${job.public_id}"><i class="bi bi-play-fill"></i></button>` : ''}
                        ${job.status === 'running' ? `<button class="btn btn-sm btn-outline-danger snmp-cancel-btn" data-id="${job.public_id}"><i class="bi bi-stop-fill"></i></button>` : ''}
                        ${['completed','completed_with_errors','failed','planned'].includes(job.status) ? `<button class="btn btn-sm btn-outline-secondary snmp-delete-btn" data-id="${job.public_id}"><i class="bi bi-trash"></i></button>` : ''}
                    </td>
                </tr>
            `).join('');

            body.querySelectorAll('tr[data-job-id]').forEach(row => {
                row.addEventListener('click', (e) => { if (!e.target.closest('button')) selectJob(row.dataset.jobId); });
            });
            body.querySelectorAll('.snmp-start-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => { e.stopPropagation(); await request('POST', `/jobs/${btn.dataset.id}/start`, { max_concurrency: 10 }); await refreshJobs(); startPolling(); });
            });
            body.querySelectorAll('.snmp-cancel-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => { e.stopPropagation(); await request('POST', `/jobs/${btn.dataset.id}/cancel`); await refreshJobs(); });
            });
            body.querySelectorAll('.snmp-delete-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => { e.stopPropagation(); if (!confirm('Delete?')) return; await request('DELETE', `/jobs/${btn.dataset.id}`); await refreshJobs(); if (selectedJobId === btn.dataset.id) { byId('snmp-detail-card').classList.add('d-none'); selectedJobId = null; } });
            });
        } catch (e) { console.error('Jobs refresh:', e); }
    }

    // ── Job detail + results ────────────────────────────────

    async function selectJob(publicId) {
        selectedJobId = publicId;
        const card = byId('snmp-detail-card');
        card.classList.remove('d-none');

        // Export links
        const csvLink = byId('snmp-export-csv');
        const jsonLink = byId('snmp-export-json');
        csvLink.href = `${apiBase}/jobs/${publicId}/report?format=csv`;
        csvLink.classList.remove('disabled');
        jsonLink.href = `${apiBase}/jobs/${publicId}/report?format=json`;
        jsonLink.classList.remove('disabled');

        try {
            const data = await request('GET', `/jobs/${publicId}/targets?limit=200`);
            const targets = data.targets || [];
            const head = byId('snmp-results-head');
            const body = byId('snmp-results-body');

            if (!targets.length) {
                head.innerHTML = '<tr><th>No results yet</th></tr>';
                body.innerHTML = '';
                return;
            }

            // Determine columns from first target's results
            const resultKeys = targets[0].results ? Object.keys(targets[0].results) : [];
            head.innerHTML = `<tr><th>MAC</th><th>IP</th><th>State</th>${resultKeys.map(k => `<th class="snmp-code">${k}</th>`).join('')}</tr>`;
            body.innerHTML = targets.map(t => {
                const vals = resultKeys.map(k => `<td class="snmp-code"><small>${t.results?.[k] ?? '—'}</small></td>`).join('');
                return `<tr><td class="snmp-code">${t.mac}</td><td><small>${t.modem_ip || '—'}</small></td><td><span class="badge ${t.state === 'complete' ? 'bg-success' : t.state === 'failed' ? 'bg-danger' : 'bg-secondary'}">${t.state}</span></td>${vals}</tr>`;
            }).join('');
        } catch (e) { console.error('Results load:', e); }
    }

    // ── Polling ─────────────────────────────────────────────

    function startPolling() {
        stopPolling();
        pollTimer = setInterval(async () => {
            await refreshJobs();
            if (selectedJobId) await selectJob(selectedJobId);
        }, 5000);
    }
    function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

    byId('snmp-refresh-btn').addEventListener('click', async () => { await refreshJobs(); if (selectedJobId) await selectJob(selectedJobId); });

    // ── Init ────────────────────────────────────────────────

    async function init() {
        updateScopeUI();
        await Promise.all([loadCmtsOptions(), loadTemplates(), refreshJobs()]);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
