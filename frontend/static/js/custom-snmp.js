/* Custom SNMP Query — admin tool */
(function () {
    'use strict';

    const root = document.getElementById('custom-snmp-app');
    const basePath = (root && root.dataset.basePath) || '';
    const topologyScopesEnabled = Boolean(root) && root.dataset.topologyScopesEnabled === 'true';
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
        row.style.position = 'relative';
        row.innerHTML = `
            <div style="position:relative;flex:1">
                <input type="text" class="form-control form-control-sm snmp-code" placeholder="OID (e.g. sysUpTime.0 or 1.3.6.1.2.1.1.3.0)" data-field="oid" value="${oid}" autocomplete="off">
                <div class="list-group position-absolute w-100 shadow-sm" style="z-index:100;max-height:150px;overflow-y:auto;display:none" data-role="suggestions"></div>
            </div>
            <input type="text" class="form-control form-control-sm" placeholder="Label" style="max-width:120px;" data-field="label" value="${label}">
            <button class="btn btn-sm btn-outline-success oid-verify-btn" title="Verify OID"><i class="bi bi-check-circle"></i></button>
            <button class="btn btn-sm btn-outline-danger oid-remove-btn" title="Remove"><i class="bi bi-dash"></i></button>
        `;
        // Autocomplete
        const oidInput = row.querySelector('[data-field="oid"]');
        const sugBox = row.querySelector('[data-role="suggestions"]');
        oidInput.addEventListener('input', () => clearRowVerification(row));
        let debounceTimer = null;
        oidInput.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const val = oidInput.value.trim();
            if (val.length < 2 || /^\d/.test(val)) { sugBox.style.display = 'none'; return; }
            debounceTimer = setTimeout(async () => {
                try {
                    const data = await request('GET', `/mib-search?q=${encodeURIComponent(val)}&limit=10`);
                    const results = data.results || [];
                    if (!results.length) { sugBox.style.display = 'none'; return; }
                    sugBox.innerHTML = results.map(r =>
                        `<a href="#" class="list-group-item list-group-item-action py-1 px-2 small"><strong>${r.name}</strong> <span class="text-muted">${r.oid}</span></a>`
                    ).join('');
                    sugBox.style.display = 'block';
                    sugBox.querySelectorAll('a').forEach((a, i) => {
                        a.addEventListener('mousedown', (e) => {
                            e.preventDefault();
                            oidInput.value = results[i].name;
                            clearRowVerification(row);
                            const labelInput = row.querySelector('[data-field="label"]');
                            if (!labelInput.value) labelInput.value = results[i].name.split('.')[0];
                            sugBox.style.display = 'none';
                        });
                    });
                } catch(e) { sugBox.style.display = 'none'; }
            }, 250);
        });
        oidInput.addEventListener('blur', () => { setTimeout(() => { sugBox.style.display = 'none'; }, 200); });

        row.querySelector('.oid-remove-btn').addEventListener('click', () => {
            if (oidContainer.querySelectorAll('.oid-row').length > 1) {
                row.remove();
                updateOidCount();
            }
        });
        row.querySelector('.oid-verify-btn').addEventListener('click', async () => {
            const cmts = byId('snmp-cmts').value;
            const affiliate = byId('snmp-affiliate').value;
            const requestedScope = byId('snmp-scope-type').value;
            if (!affiliate || (requestedScope !== 'all_network' && !cmts)) {
                alert('Select an affiliate and CMTS first to verify OIDs');
                return;
            }
            const oidInput = row.querySelector('[data-field="oid"]');
            const oidVal = oidInput.value.trim();
            if (!oidVal) return;
            const btn = row.querySelector('.oid-verify-btn');
            const targetMode = byId('snmp-verify-modem').checked ? 'modem' : 'cmts';
            const allCmts = requestedScope === 'all_network' || isAffiliateAllCmtsSelected();
            const payload = {
                oid: oidVal,
                target_mode: targetMode,
                affiliate,
                cmts: allCmts ? null : cmts,
                modem_vendor: byId('snmp-modem-vendor').value || null,
                modem_type: byId('snmp-modem-type').value || null,
            };
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                const data = await request('POST', '/verify-oid', payload);
                if (data.success) {
                    const target = data.target || {};
                    const receipt = data.verification_receipt || {};
                    const targetLabel = target.role === 'cmts'
                        ? `${target.cmts || 'CMTS'} (${target.ip || 'unknown IP'})`
                        : `${target.modem_ip || target.ip || 'modem'} behind ${target.cmts || 'CMTS'}`;
                    if (targetMode === 'modem' && receipt.receipt_id) {
                        row.dataset.verificationReceipt = receipt.receipt_id;
                        row.dataset.verifiedOid = oidVal;
                        btn.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i>';
                        btn.title = `Verified: ${data.value} (tested on ${targetLabel}; attempt ${data.attempts_used || 1})`;
                        oidInput.classList.remove('is-invalid');
                        oidInput.classList.add('is-valid');
                    } else {
                        clearRowVerification(row);
                        btn.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-warning"></i>';
                        btn.title = `Valid only on ${targetLabel}. Modem verification is required before planning a modem query task.`;
                    }
                } else {
                    clearRowVerification(row);
                    btn.innerHTML = '<i class="bi bi-x-circle-fill text-danger"></i>';
                    btn.title = `${data.error || 'Verification failed'} (${data.attempts_used || 0}/${data.attempts_limit || 0} attempts)`;
                    oidInput.classList.add('is-invalid');
                }
            } catch (e) {
                clearRowVerification(row);
                btn.innerHTML = '<i class="bi bi-x-circle-fill text-danger"></i>';
                btn.title = e.message;
                oidInput.classList.add('is-invalid');
            }
            btn.disabled = false;
        });
        return row;
    }

    function clearRowVerification(row) {
        delete row.dataset.verificationReceipt;
        delete row.dataset.verifiedOid;
        const oidInput = row.querySelector('[data-field="oid"]');
        oidInput.classList.remove('is-valid', 'is-invalid');
    }

    function invalidateOidVerifications() {
        oidContainer.querySelectorAll('.oid-row').forEach(row => {
            clearRowVerification(row);
            const btn = row.querySelector('.oid-verify-btn');
            btn.innerHTML = '<i class="bi bi-check-circle"></i>';
            btn.title = 'Verify OID';
        });
    }

    function getVerificationReceipts() {
        const receipts = [];
        const unverified = [];
        oidContainer.querySelectorAll('.oid-row').forEach(row => {
            const oid = row.querySelector('[data-field="oid"]').value.trim();
            if (!oid) return;
            if (row.dataset.verifiedOid !== oid || !row.dataset.verificationReceipt) {
                unverified.push(oid);
                return;
            }
            receipts.push(row.dataset.verificationReceipt);
        });
        if (unverified.length) {
            throw new Error(`Verify every OID on a cable modem before planning: ${unverified.join(', ')}`);
        }
        return receipts;
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
    const affiliateSelect = byId('snmp-affiliate');
    const cmtsSelect = byId('snmp-cmts');
    const modemVendorSelect = byId('snmp-modem-vendor');
    const modemTypeSelect = byId('snmp-modem-type');
    const cmtsWrap = byId('snmp-cmts-wrap');
    const fnWrap = byId('snmp-fn-wrap');
    const affiliateAllCmtsValue = '__affiliate_all_cmts__';

    function isAffiliateAllCmtsSelected() {
        return cmtsSelect.value === affiliateAllCmtsValue;
    }

    function updateScopeUI() {
        if (!topologyScopesEnabled && scopeType.value === 'fiber_node') {
            scopeType.value = 'cmts';
        }
        const type = scopeType.value;
        cmtsWrap.classList.toggle('d-none', type === 'all_network');
        fnWrap.classList.toggle('d-none', !topologyScopesEnabled || type !== 'fiber_node');
    }
    scopeType.addEventListener('change', () => {
        updateScopeUI();
        invalidateOidVerifications();
    });

    function escapeHtml(value) {
        return String(value).replace(/[&<>'"]/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
        }[char]));
    }

    function facetOptions(items, placeholder) {
        return `<option value="">${placeholder}</option>` + (items || []).map(item => {
            const value = String(item.value || '');
            const count = Number(item.count || 0);
            return `<option value="${escapeHtml(value)}">${escapeHtml(value)} (${count})</option>`;
        }).join('');
    }

    function resetModemFacetSelectors(placeholder = 'Select CMTS') {
        modemVendorSelect.disabled = true;
        modemVendorSelect.innerHTML = `<option value="">${placeholder}</option>`;
        modemTypeSelect.disabled = true;
        modemTypeSelect.innerHTML = `<option value="">${placeholder}</option>`;
    }

    async function loadCmtsOptions() {
        const affiliate = affiliateSelect.value;
        if (!affiliate) {
            cmtsSelect.disabled = true;
            cmtsSelect.innerHTML = '<option value="">Select affiliate</option>';
            return;
        }
        cmtsSelect.disabled = true;
        cmtsSelect.innerHTML = '<option value="">Loading...</option>';
        try {
            const params = new URLSearchParams({ affiliate, limit: '5000' });
            const data = await request('GET', `/options/cmts?${params.toString()}`);
            const aggregate = data.aggregate || {};
            const modemCount = Number(aggregate.modem_count);
            const aggregateOption = aggregate.kind === 'affiliate_all' && Number.isFinite(modemCount)
                ? `<option value="${affiliateAllCmtsValue}">All CMTS (${modemCount.toLocaleString()} active modems)</option>`
                : '';
            cmtsSelect.innerHTML = '<option value="">— select —</option>' + aggregateOption +
                (data.cmts || []).map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
            cmtsSelect.disabled = false;
        } catch (e) {
            cmtsSelect.innerHTML = '<option value="">Error loading CMTSs</option>';
            console.warn('CMTS options:', e);
        }
    }

    async function loadFiberNodeOptions() {
        const cmts = cmtsSelect.value;
        const affiliate = affiliateSelect.value;
        const fnSel = byId('snmp-fiber-node');
        if (!topologyScopesEnabled) {
            fnSel.innerHTML = '<option value="">Topology scopes disabled</option>';
            fnSel.disabled = true;
            return;
        }
        if (!affiliate) {
            fnSel.innerHTML = '<option value="">Select affiliate</option>';
            fnSel.disabled = true;
            return;
        }
        if (!cmts) {
            fnSel.innerHTML = '<option value="">Select CMTS</option>';
            fnSel.disabled = true;
            return;
        }
        if (isAffiliateAllCmtsSelected()) {
            fnSel.innerHTML = '<option value="">All CMTS does not support Fiber Node</option>';
            fnSel.disabled = true;
            return;
        }
        fnSel.disabled = false;
        fnSel.innerHTML = '<option value="">Loading...</option>';
        try {
            const params = new URLSearchParams({ cmts, affiliate, limit: '5000' });
            const data = await request('GET', `/options/fiber-nodes?${params.toString()}`);
            fnSel.innerHTML = '<option value="">— select —</option>' +
                (data.fiber_nodes || []).map(fn => `<option value="${escapeHtml(fn)}">${escapeHtml(fn)}</option>`).join('');
        } catch (e) {
            fnSel.innerHTML = '<option value="">Error loading FiberNodes</option>';
            fnSel.disabled = true;
        }
    }

    async function loadModemVendorOptions() {
        const affiliate = affiliateSelect.value;
        const cmts = cmtsSelect.value;
        if (!affiliate) {
            resetModemFacetSelectors('Select affiliate');
            return;
        }
        if (!cmts) {
            resetModemFacetSelectors();
            return;
        }
        const params = new URLSearchParams({ affiliate, limit: '5000' });
        if (!isAffiliateAllCmtsSelected()) params.set('cmts', cmts);
        modemVendorSelect.disabled = true;
        modemVendorSelect.innerHTML = '<option value="">Loading...</option>';
        try {
            const data = await request('GET', `/options/modem-vendors?${params.toString()}`);
            modemVendorSelect.innerHTML = facetOptions(data.modem_vendors, 'All vendors');
            modemVendorSelect.disabled = false;
        } catch (e) {
            modemVendorSelect.innerHTML = '<option value="">Error loading vendors</option>';
            console.warn('Modem vendor options:', e);
        }
        await loadModemTypeOptions();
    }

    async function loadModemTypeOptions() {
        const affiliate = affiliateSelect.value;
        const cmts = cmtsSelect.value;
        if (!affiliate) {
            modemTypeSelect.disabled = true;
            modemTypeSelect.innerHTML = '<option value="">Select affiliate</option>';
            return;
        }
        if (!cmts) {
            modemTypeSelect.disabled = true;
            modemTypeSelect.innerHTML = '<option value="">Select CMTS</option>';
            return;
        }
        const params = new URLSearchParams({ affiliate, limit: '5000' });
        if (!isAffiliateAllCmtsSelected()) params.set('cmts', cmts);
        if (modemVendorSelect.value) params.set('modem_vendor', modemVendorSelect.value);
        modemTypeSelect.disabled = true;
        modemTypeSelect.innerHTML = '<option value="">Loading...</option>';
        try {
            const data = await request('GET', `/options/modem-types?${params.toString()}`);
            modemTypeSelect.innerHTML = facetOptions(data.modem_types, 'All types / models');
            modemTypeSelect.disabled = false;
        } catch (e) {
            modemTypeSelect.innerHTML = '<option value="">Error loading types / models</option>';
            console.warn('Modem type options:', e);
        }
    }

    cmtsSelect.addEventListener('change', async () => {
        invalidateOidVerifications();
        if (!affiliateSelect.value) return;
        await Promise.all([loadFiberNodeOptions(), loadModemVendorOptions()]);
    });
    affiliateSelect.addEventListener('change', async () => {
        invalidateOidVerifications();
        resetModemFacetSelectors();
        await Promise.all([loadCmtsOptions(), loadFiberNodeOptions()]);
    });
    modemVendorSelect.addEventListener('change', () => {
        invalidateOidVerifications();
        return loadModemTypeOptions();
    });
    modemTypeSelect.addEventListener('change', invalidateOidVerifications);
    byId('snmp-verify-modem').addEventListener('change', invalidateOidVerifications);

    // ── Create plan ─────────────────────────────────────────

    byId('snmp-plan-btn').addEventListener('click', async function () {
        const oids = getOids();
        if (!oids.length) return alert('Add at least one OID');

        const requestedType = scopeType.value;
        const affiliate = affiliateSelect.value;
        const affiliateAllCmts = isAffiliateAllCmtsSelected();
        if (!affiliate) return alert('Select an affiliate first');
        if (affiliateAllCmts && requestedType === 'fiber_node') {
            return alert('All CMTS cannot be used with a Fiber Node scope');
        }
        if (requestedType === 'fiber_node' && !topologyScopesEnabled) {
            return alert('Fiber Node scope is disabled by the administrator');
        }
        const type = affiliateAllCmts ? 'all_network' : requestedType;
        const scope = { type, affiliate };
        if (modemVendorSelect.value) scope.modem_vendor = modemVendorSelect.value;
        if (modemTypeSelect.value) scope.modem_type = modemTypeSelect.value;
        if (type === 'cmts') {
            const cmts = cmtsSelect.value;
            if (!cmts) return alert('Select a CMTS');
            scope.cmts = [cmts];
        } else if (type === 'fiber_node') {
            const cmts = cmtsSelect.value;
            const fn = byId('snmp-fiber-node').value;
            if (!cmts) return alert('Select a CMTS');
            if (!fn) return alert('Select a fiber node');
            scope.cmts = cmts;
            scope.fiber_nodes = [fn];
        }

        let verificationReceipts;
        try {
            verificationReceipts = getVerificationReceipts();
        } catch (e) {
            return alert(e.message);
        }
        const maxModems = parseInt(byId('snmp-max-modems').value) || 100;
        this.disabled = true;
        try {
            await request('POST', '/jobs/plan', {
                scope,
                oids,
                verification_receipts: verificationReceipts,
                max_modems: maxModems,
            });
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
            body.innerHTML = jobs.map(job => {
                const total = job.targets_total || 1;
                const done = (job.targets_succeeded || 0) + (job.targets_failed || 0);
                const pct = Math.round(done * 100 / total);
                const progressHtml = job.status === 'running' || done > 0
                    ? `<div class="progress" style="height:4px"><div class="progress-bar ${job.targets_failed ? 'bg-warning' : 'bg-success'}" style="width:${pct}%"></div></div><small class="text-muted">${done}/${total}</small>`
                    : `<small class="text-muted">${total} targets</small>`;
                return `
                <tr data-job-id="${job.public_id}" style="cursor:pointer">
                    <td>${statusBadge(job.status)}</td>
                    <td><small>${job.scope_type || '—'}</small></td>
                    <td><small>${(job.oids || []).length}</small></td>
                    <td>${progressHtml}</td>
                    <td><small>${job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</small></td>
                    <td>
                        ${job.status === 'planned' && (topologyScopesEnabled || String(job.scope_type || '').toLowerCase() !== 'fiber_node') ? `<button class="btn btn-sm btn-success snmp-start-btn" data-id="${job.public_id}"><i class="bi bi-play-fill"></i></button>` : ''}
                        ${job.status === 'running' ? `<button class="btn btn-sm btn-outline-danger snmp-cancel-btn" data-id="${job.public_id}"><i class="bi bi-stop-fill"></i></button>` : ''}
                        ${['completed','completed_with_errors','failed','planned'].includes(job.status) ? `<button class="btn btn-sm btn-outline-secondary snmp-delete-btn" data-id="${job.public_id}"><i class="bi bi-trash"></i></button>` : ''}
                    </td>
                </tr>`;
            }).join('');

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

    byId('snmp-delete-all-btn').addEventListener('click', async () => {
        if (!confirm('Delete ALL completed/failed/planned custom SNMP jobs?')) return;
        try {
            const data = await request('DELETE', '/jobs');
            alert(`Deleted ${data.deleted || 0} job(s)`);
            selectedJobId = null;
            byId('snmp-detail-card').classList.add('d-none');
            await refreshJobs();
        } catch (e) { alert(`Delete failed: ${e.message}`); }
    });

    // ── Init ────────────────────────────────────────────────

    async function init() {
        updateScopeUI();
        await Promise.all([loadTemplates(), refreshJobs()]);
        // Auto-poll if any job is running
        const body = byId('snmp-jobs-body');
        if (body && body.innerHTML.includes('bg-primary')) startPolling();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
