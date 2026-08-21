/* CM Bulk Reset — admin tool */
(function () {
    'use strict';

    const root = document.querySelector('.container-fluid');
    const basePath = (root && root.dataset.basePath) || '';
    const apiBase = `${basePath}/api/admin/cm-reset`;

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

    // ── State ───────────────────────────────────────────────────

    let selectedJobId = null;
    let pollTimer = null;
    let cmtsOptions = [];

    // ── Scope UI ────────────────────────────────────────────────

    const scopeType = byId('reset-scope-type');
    const singleWrap = byId('scope-single-wrap');
    const cmtsWrap = byId('scope-cmts-wrap');
    const fnWrap = byId('scope-fn-wrap');
    const fileWrap = byId('scope-file-wrap');

    function updateScopeUI() {
        const type = scopeType.value;
        singleWrap.classList.toggle('d-none', type !== 'single');
        cmtsWrap.classList.toggle('d-none', type !== 'cmts' && type !== 'fiber_node');
        fnWrap.classList.toggle('d-none', type !== 'fiber_node');
        fileWrap.classList.toggle('d-none', type !== 'file');
    }
    scopeType.addEventListener('change', updateScopeUI);

    // ── CMTS / Fiber-node options ───────────────────────────────

    async function loadCmtsOptions() {
        try {
            const data = await request('GET', '/options/cmts?limit=5000');
            cmtsOptions = data.cmts || [];
            const sel = byId('reset-cmts');
            sel.innerHTML = '<option value="">— select CMTS —</option>' +
                cmtsOptions.map(c => `<option value="${c}">${c}</option>`).join('');
        } catch (e) {
            console.warn('Failed to load CMTS options:', e);
        }
    }

    byId('reset-cmts').addEventListener('change', async function () {
        const cmts = this.value;
        const fnSel = byId('reset-fiber-node');
        if (!cmts) {
            fnSel.innerHTML = '<option value="">Select CMTS first</option>';
            fnSel.disabled = true;
            return;
        }
        fnSel.disabled = false;
        fnSel.innerHTML = '<option value="">Loading...</option>';
        try {
            const data = await request('GET', `/options/fiber-nodes?cmts=${encodeURIComponent(cmts)}`);
            const fns = data.fiber_nodes || [];
            fnSel.innerHTML = '<option value="">— all fiber nodes —</option>' +
                fns.map(fn => `<option value="${fn}">${fn}</option>`).join('');
        } catch (e) {
            fnSel.innerHTML = '<option value="">Failed to load</option>';
        }
    });

    // ── Create plan ─────────────────────────────────────────────

    byId('reset-plan-btn').addEventListener('click', async function () {
        const type = scopeType.value;
        let scope = { type };

        if (type === 'single') {
            const mac = byId('reset-mac').value.trim();
            if (!mac) return alert('Enter a MAC address');
            scope.mac = mac;
        } else if (type === 'cmts') {
            const cmts = byId('reset-cmts').value;
            if (!cmts) return alert('Select a CMTS');
            scope.cmts = [cmts];
        } else if (type === 'fiber_node') {
            const cmts = byId('reset-cmts').value;
            const fn = byId('reset-fiber-node').value;
            if (!cmts) return alert('Select a CMTS');
            scope.cmts = cmts;
            scope.fiber_nodes = fn ? [fn] : [];
            if (!fn) return alert('Select a fiber node');
        } else if (type === 'file') {
            const text = byId('reset-mac-list').value.trim();
            if (!text) return alert('Paste or upload MAC addresses');
            const macs = text.split(/[\n,;]+/).map(m => m.trim()).filter(Boolean);
            if (!macs.length) return alert('No valid MAC addresses found');
            scope.mac_list = macs;
        }

        this.disabled = true;
        try {
            await request('POST', '/jobs/plan', { scope, requested_by: 'admin' });
            await refreshJobs();
        } catch (e) {
            alert(`Plan failed: ${e.message}`);
        } finally {
            this.disabled = false;
        }
    });

    // ── Job list ────────────────────────────────────────────────

    function statusBadge(status) {
        const map = {
            planned: 'bg-secondary', queued: 'bg-info',
            running: 'bg-primary', completed: 'bg-success',
            completed_with_errors: 'bg-warning text-dark',
            failed: 'bg-danger', cancelled: 'bg-dark',
        };
        return `<span class="badge ${map[status] || 'bg-secondary'}">${status}</span>`;
    }

    function progressBar(job) {
        const total = job.targets_total || 1;
        const done = (job.targets_succeeded || 0) + (job.targets_failed || 0);
        const pct = Math.round(done * 100 / total);
        const failPct = Math.round((job.targets_failed || 0) * 100 / total);
        return `<div class="reset-bar-wrap">
            <div class="reset-bar" style="width:${pct - failPct}%"></div>
            <div class="reset-bar reset-bar-fail" style="width:${failPct}%"></div>
        </div><small class="text-muted">${done}/${total}</small>`;
    }

    async function refreshJobs() {
        try {
            const data = await request('GET', '/jobs?limit=50');
            const body = byId('reset-jobs-body');
            const jobs = data.jobs || [];
            if (!jobs.length) {
                body.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">No reset jobs</td></tr>';
                return;
            }
            body.innerHTML = jobs.map(job => `
                <tr class="cursor-pointer" data-job-id="${job.public_id}" style="cursor:pointer">
                    <td>${statusBadge(job.status)}</td>
                    <td><small>${job.scope_type || '—'}</small></td>
                    <td>${job.targets_total}</td>
                    <td>${progressBar(job)}</td>
                    <td><small>${job.scheduled_start ? new Date(job.scheduled_start).toLocaleString() : '—'}</small></td>
                    <td><small>${job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</small></td>
                    <td>
                        ${job.status === 'planned' ? `<button class="btn btn-sm btn-success reset-start-btn" data-id="${job.public_id}" data-total="${job.targets_total}"><i class="bi bi-play-fill"></i></button>` : ''}
                        ${job.status === 'running' ? `<button class="btn btn-sm btn-outline-danger reset-cancel-btn" data-id="${job.public_id}"><i class="bi bi-stop-fill"></i></button>` : ''}
                        ${['completed', 'completed_with_errors', 'failed', 'cancelled', 'planned'].includes(job.status) ? `<button class="btn btn-sm btn-outline-secondary reset-delete-btn" data-id="${job.public_id}"><i class="bi bi-trash"></i></button>` : ''}
                    </td>
                </tr>
            `).join('');

            // Event delegation
            body.querySelectorAll('tr[data-job-id]').forEach(row => {
                row.addEventListener('click', (e) => {
                    if (e.target.closest('button')) return;
                    selectJob(row.dataset.jobId);
                });
            });
            body.querySelectorAll('.reset-start-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showConfirmModal(btn.dataset.id, btn.dataset.total);
                });
            });
            body.querySelectorAll('.reset-cancel-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await request('POST', `/jobs/${btn.dataset.id}/cancel`);
                    await refreshJobs();
                });
            });
            body.querySelectorAll('.reset-delete-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm('Delete this job and all its targets?')) return;
                    await request('DELETE', `/jobs/${btn.dataset.id}`);
                    await refreshJobs();
                    if (selectedJobId === btn.dataset.id) {
                        byId('reset-detail-card').classList.add('d-none');
                        selectedJobId = null;
                    }
                });
            });
        } catch (e) {
            console.error('Failed to refresh jobs:', e);
        }
    }

    // ── Job detail ──────────────────────────────────────────────

    async function selectJob(publicId) {
        selectedJobId = publicId;
        const card = byId('reset-detail-card');
        card.classList.remove('d-none');
        try {
            const data = await request('GET', `/jobs/${publicId}`);
            const job = data.job;
            byId('reset-detail-status').className = `badge ${job.status === 'running' ? 'bg-primary' : job.status === 'completed' ? 'bg-success' : 'bg-secondary'}`;
            byId('reset-detail-status').textContent = job.status;
            byId('reset-detail-meta').innerHTML = `
                <div class="col-auto"><small class="text-muted">Scope:</small> <strong>${job.scope_type}</strong></div>
                <div class="col-auto"><small class="text-muted">Total:</small> <strong>${job.targets_total}</strong></div>
                <div class="col-auto"><small class="text-muted">Done:</small> <strong>${job.targets_succeeded}</strong></div>
                <div class="col-auto"><small class="text-muted">Failed:</small> <strong class="text-danger">${job.targets_failed}</strong></div>
                <div class="col-auto"><small class="text-muted">Pending:</small> <strong>${job.targets_pending}</strong></div>
            `;

            // Load targets
            const targets = await request('GET', `/jobs/${publicId}/targets?limit=200`);
            const tbody = byId('reset-targets-body');
            const rows = targets.targets || [];
            if (!rows.length) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">No targets</td></tr>';
                return;
            }
            tbody.innerHTML = rows.map(t => `
                <tr>
                    <td class="reset-code">${t.mac}</td>
                    <td><small>${t.modem_ip || '—'}</small></td>
                    <td><small>${t.cmts || '—'}</small></td>
                    <td><small>${t.fiber_node || '—'}</small></td>
                    <td><span class="badge ${t.state === 'complete' ? 'bg-success' : t.state === 'failed' ? 'bg-danger' : t.state === 'running' ? 'bg-primary' : 'bg-secondary'}">${t.state}</span></td>
                    <td><small>${t.reset_at ? new Date(t.reset_at).toLocaleTimeString() : '—'}</small></td>
                    <td><small class="text-danger">${t.error_text || ''}</small></td>
                </tr>
            `).join('');
        } catch (e) {
            console.error('Failed to load job detail:', e);
        }
    }

    // ── Confirmation modal ──────────────────────────────────────

    let pendingStartId = null;

    function showConfirmModal(publicId, targetCount) {
        pendingStartId = publicId;
        byId('confirm-target-count').textContent = targetCount;
        byId('confirm-passphrase').value = '';
        byId('confirm-start-btn').disabled = true;
        const modal = new bootstrap.Modal(byId('resetConfirmModal'));
        modal.show();
    }

    byId('confirm-passphrase').addEventListener('input', function () {
        const match = this.value.trim().toLowerCase() === 'have you tried turning it on and off again?';
        byId('confirm-start-btn').disabled = !match;
    });

    byId('confirm-start-btn').addEventListener('click', async function () {
        if (!pendingStartId) return;
        const passphrase = byId('confirm-passphrase').value.trim();
        this.disabled = true;
        try {
            await request('POST', `/jobs/${pendingStartId}/start`, {
                max_concurrency: 5,
                confirmation_passphrase: passphrase,
            });
            bootstrap.Modal.getInstance(byId('resetConfirmModal')).hide();
            await refreshJobs();
            selectJob(pendingStartId);
            startPolling();
        } catch (e) {
            alert(`Start failed: ${e.message}`);
        } finally {
            this.disabled = false;
        }
    });

    // ── Auto-refresh polling ────────────────────────────────────

    function startPolling() {
        stopPolling();
        pollTimer = setInterval(async () => {
            await refreshJobs();
            if (selectedJobId) await selectJob(selectedJobId);
        }, 5000);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    byId('reset-refresh-btn').addEventListener('click', async () => {
        await refreshJobs();
        if (selectedJobId) await selectJob(selectedJobId);
    });

    // ── Init ────────────────────────────────────────────────────

    async function init() {
        updateScopeUI();
        await loadCmtsOptions();
        await refreshJobs();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
