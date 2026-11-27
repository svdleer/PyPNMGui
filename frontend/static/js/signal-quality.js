/* Signal quality snapshots. The GUI talks only to the Flask BFF; the PyPNM API owns planning, agents and files. */
(function () {
    'use strict';
    const root = document.getElementById('signal-quality-app');
    if (!root) return;
    const basePath = root.dataset.basePath || '';
    const api = `${basePath}/api/admin/signal-quality`;
    const topologyEnabled = root.dataset.topologyScopesEnabled === 'true';
    const $ = id => document.getElementById(id);
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const when = iso => iso ? new Date(iso).toLocaleString() : '—';
    const FINAL = ['completed', 'completed_with_errors', 'failed', 'cancelled'];
    const ACTIVE = ['running', 'packaging', 'waiting_window'];
    const BADGES = {
        completed: 'bg-success', completed_with_errors: 'bg-warning text-dark', failed: 'bg-danger',
        running: 'bg-primary', packaging: 'bg-info text-dark', waiting_window: 'bg-secondary',
        scheduled: 'bg-secondary', cancelled: 'bg-dark', complete: 'bg-success', planned: 'bg-secondary',
    };
    let selectedJob = null;
    let pollTimer = null;

    async function request(method, path, body) {
        const options = { method, headers: { 'Content-Type': 'application/json' } };
        if (body !== undefined) options.body = JSON.stringify(body);
        const response = await fetch(`${api}${path}`, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
        return data;
    }

    const badge = status => `<span class="badge ${BADGES[status] || 'bg-secondary'}">${esc(String(status).replace(/_/g, ' '))}</span>`;
    const formatBytes = n => n == null ? '' : n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;

    function updateScope() {
        const fiberNode = $('sq-scope-type').value === 'fiber_node';
        $('sq-fn-wrap').classList.toggle('d-none', !(topologyEnabled && fiberNode));
        if (!topologyEnabled && fiberNode) $('sq-scope-type').value = 'cmts';
        if (topologyEnabled && fiberNode && loadedFor !== $('sq-cmts').value) loadFiberNodes();
    }

    // ── Fiber node picker: type part of a name, pick from the matches ─────
    const MENU_LIMIT = 50;
    let fiberNodes = [];          // [{name, modems_here, modems_total}] for the selected CMTS
    let selectedNodes = [];       // chosen names, in the order they were added
    let loadedFor = null;         // CMTS the list above belongs to
    let fnPollTimer = null;
    let fnLoadToken = 0;          // ignores answers for a CMTS that is no longer selected
    let activeIndex = -1;

    const nodeInfo = name => fiberNodes.find(n => n.name === name);

    function setFnStatus(html, cls = 'text-muted') {
        const el = $('sq-fn-status');
        el.className = `form-text ${cls}`;
        el.innerHTML = html;
    }

    function renderChips() {
        $('sq-fn-chips').innerHTML = selectedNodes.map(name => `
            <span class="badge text-bg-primary d-inline-flex align-items-center gap-1">${esc(name)}
                <button type="button" class="btn-close btn-close-white" style="font-size:.5rem" data-remove="${esc(name)}" aria-label="Remove ${esc(name)}"></button>
            </span>`).join('');
        const modems = selectedNodes.reduce((sum, name) => sum + (nodeInfo(name)?.modems_here || 0), 0);
        $('sq-fn-selected').textContent = selectedNodes.length
            ? `${selectedNodes.length} fiber node${selectedNodes.length === 1 ? '' : 's'} selected, about ${modems.toLocaleString()} online modems` : '';
    }

    function matches() {
        const term = $('sq-fn-search').value.trim().toLowerCase();
        return fiberNodes.filter(n => !selectedNodes.includes(n.name) && n.name.toLowerCase().includes(term));
    }

    function renderMenu() {
        const menu = $('sq-fn-menu');
        const term = $('sq-fn-search').value.trim();
        const found = matches();
        if (!fiberNodes.length) { menu.classList.add('d-none'); return; }
        const shown = found.slice(0, MENU_LIMIT);
        activeIndex = Math.min(activeIndex, shown.length - 1);
        const rows = shown.map((n, i) => `
            <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between ${i === activeIndex ? 'active' : ''}"
                    data-add="${esc(n.name)}" role="option">
                <span>${esc(n.name)}</span><span class="${i === activeIndex ? '' : 'text-muted'} ms-3">${n.modems_here.toLocaleString()} modems</span>
            </button>`);
        if (term && found.length > 1) {
            rows.unshift(`<button type="button" class="list-group-item list-group-item-action text-primary fw-semibold" data-add-all="1">
                Add all ${found.length} matches for “${esc(term)}”</button>`);
        }
        if (found.length > MENU_LIMIT) rows.push(`<div class="list-group-item text-muted small">${found.length - MENU_LIMIT} more, keep typing to narrow down</div>`);
        if (!found.length) rows.push(`<div class="list-group-item text-muted small">${term ? 'No fiber node matches' : 'All fiber nodes are selected'}</div>`);
        menu.innerHTML = rows.join('');
        menu.classList.remove('d-none');
    }

    function addNodes(names) {
        names.filter(n => !selectedNodes.includes(n)).forEach(n => selectedNodes.push(n));
        $('sq-fn-search').value = '';
        activeIndex = -1;
        renderChips();
        renderMenu();
        $('sq-fn-search').focus();
    }

    function removeNode(name) {
        selectedNodes = selectedNodes.filter(n => n !== name);
        renderChips();
        renderMenu();
    }

    function resetPicker(placeholder) {
        if (fnPollTimer) { clearTimeout(fnPollTimer); fnPollTimer = null; }
        fiberNodes = []; selectedNodes = []; loadedFor = null; activeIndex = -1;
        $('sq-fn-search').value = '';
        $('sq-fn-search').disabled = true;
        $('sq-fn-search').placeholder = placeholder;
        $('sq-fn-menu').classList.add('d-none');
        setFnStatus('');
        renderChips();
    }

    async function loadFiberNodes() {
        const cmts = $('sq-cmts').value;
        const token = ++fnLoadToken;
        resetPicker(cmts ? 'Loading fiber nodes...' : 'Select a CMTS first');
        if (!cmts || !topologyEnabled) return;
        const poll = async () => {
            let data;
            try {
                data = await request('GET', `/options/fiber-nodes?cmts=${encodeURIComponent(cmts)}&limit=10000`);
            } catch (error) {
                if (token === fnLoadToken) setFnStatus(esc(error.message), 'text-danger');
                return;
            }
            if (token !== fnLoadToken) return;   // another CMTS was selected meanwhile
            if (data.available === false) {
                $('sq-fn-search').placeholder = 'Not available';
                setFnStatus(esc(data.message || 'Fiber node data is not available in this environment'), 'text-danger');
                return;
            }
            fiberNodes = data.details || [];
            loadedFor = cmts;
            $('sq-fn-search').disabled = !fiberNodes.length;
            $('sq-fn-search').placeholder = fiberNodes.length ? 'Type part of a fiber node name' : 'No fiber nodes yet';
            renderChips();
            const snapshot = data.snapshot_date ? ` Topology snapshot ${esc(String(data.snapshot_date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3'))}.` : '';
            if (data.building) {
                const spinner = '<span class="spinner-border spinner-border-sm me-1"></span>';
                setFnStatus(fiberNodes.length
                    ? `${spinner}Refreshing the list in the background.${snapshot}`
                    : `${spinner}Building the fiber node list for this CMTS. The first time takes up to a minute...`);
                fnPollTimer = setTimeout(poll, 3000);
            } else if (data.error) {
                setFnStatus(`Could not build the list: ${esc(data.error)}. It will be retried in a few minutes.`, 'text-danger');
            } else {
                setFnStatus(`${fiberNodes.length} fiber nodes belong to this CMTS (it serves most of their online modems).${snapshot}`);
            }
        };
        await poll();
    }

    async function loadCmts() {
        const data = await request('GET', '/options/cmts?limit=5000');
        $('sq-cmts').innerHTML = '<option value="">— select CMTS —</option>' +
            (data.cmts || []).map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
    }

    function readPlan() {
        const type = $('sq-scope-type').value;
        const cmts = $('sq-cmts').value;
        const scope = { type, cmts };
        if (type === 'fiber_node') scope.fiber_nodes = [...selectedNodes];
        const start = $('sq-scheduled-start').value;
        return {
            scope,
            window_start: $('sq-window-start').value,
            window_end: $('sq-window-end').value,
            override_window: $('sq-override-window').checked,
            include_captures: $('sq-include-captures').checked,
            scheduled_start: start ? new Date(start).toISOString() : null,
            confirmation_password: $('sq-password').value,
        };
    }

    function validatePlan(plan) {
        if (!plan.confirmation_password) throw new Error('Confirmation password is required');
        if (!plan.scope.cmts) throw new Error('Select a CMTS');
        if (plan.scope.type === 'fiber_node' && !plan.scope.fiber_nodes.length) throw new Error('Select at least one fiber node');
        if (!plan.window_start || !plan.window_end) throw new Error('Set the window start and end');
        if (plan.window_start === plan.window_end) throw new Error('Window start and end must differ');
        if (plan.override_window && !confirm('Override is on: the snapshot will run at any time, including busy hours. Continue?')) throw new Error('Cancelled');
    }

    async function createJob(startNow) {
        const plan = readPlan();
        validatePlan(plan);
        const created = await request('POST', '/jobs/plan', plan);
        const id = created.job.public_id;
        if (startNow) {
            await request('POST', `/jobs/${id}/start`, { confirmation_password: plan.confirmation_password, override_window: plan.override_window });
        }
        $('sq-password').value = '';
        $('sq-plan-hint').textContent = `Planned ${created.job.targets_total} modems.`;
        await refreshJobs();
        await selectJob(id);
        startPolling();
    }

    async function run(action, label) {
        try { await action(); } catch (error) { if (error.message !== 'Cancelled') alert(`${label} failed: ${error.message}`); }
    }

    function jobRow(job) {
        const total = job.targets_total || 0;
        const done = job.targets_complete + job.targets_failed;
        const pct = total ? Math.round((done / total) * 100) : 0;
        const failPct = total ? Math.round((job.targets_failed / total) * 100) : 0;
        const scope = job.scope_type === 'fiber_node'
            ? `${esc(job.cmts)} / ${esc(job.fiber_nodes.join(', '))}` : esc(job.cmts);
        const next = job.override_window ? '<span class="text-danger">any time (override)</span>'
            : job.next_window_open ? esc(when(job.next_window_open)) : '—';
        const canStart = ['scheduled', 'waiting_window'].includes(job.status);
        const canCancel = ['scheduled', ...ACTIVE].includes(job.status);
        const canDelete = !ACTIVE.includes(job.status);
        const actions = [
            canStart ? `<button class="btn btn-sm btn-success sq-start" data-id="${esc(job.public_id)}">Start now</button>` : '',
            canCancel ? `<button class="btn btn-sm btn-outline-secondary sq-cancel" data-id="${esc(job.public_id)}">Cancel</button>` : '',
            canDelete ? `<button class="btn btn-sm btn-outline-danger sq-delete" data-id="${esc(job.public_id)}">Delete</button>` : '',
        ].join(' ');
        const pkg = job.package_ready
            ? `<a class="btn btn-sm btn-primary" href="${api}/jobs/${esc(job.public_id)}/download"><i class="bi bi-download me-1"></i>${esc(formatBytes(job.package_bytes))}</a>` : '—';
        return `<tr data-job="${esc(job.public_id)}" style="cursor:pointer">
            <td>${badge(job.status)}</td>
            <td>${job.scope_type === 'fiber_node' ? 'Fiber node' : 'CMTS'}: ${scope}</td>
            <td class="sq-code">${esc(job.window_start)}&ndash;${esc(job.window_end)}</td>
            <td class="small">${next}</td>
            <td><div class="sq-bar-wrap"><div class="sq-bar ${failPct > 20 ? 'sq-bar-fail' : ''}" style="width:${pct}%"></div></div>
                <div class="small text-muted">${job.targets_complete} ok, ${job.targets_failed} failed / ${total}</div></td>
            <td>${pkg}</td>
            <td class="text-nowrap">${actions}</td></tr>`;
    }

    async function refreshJobs() {
        const data = await request('GET', '/jobs?limit=50');
        const jobs = data.jobs || [];
        const body = $('sq-jobs-body');
        body.innerHTML = jobs.length ? jobs.map(jobRow).join('')
            : '<tr><td colspan="7" class="text-center text-muted py-3">No snapshots yet</td></tr>';
        body.querySelectorAll('tr[data-job]').forEach(row => row.addEventListener('click', event => {
            if (!event.target.closest('button, a')) selectJob(row.dataset.job);
        }));
        body.querySelectorAll('.sq-start').forEach(button => button.addEventListener('click', event => {
            event.stopPropagation();
            run(() => startJob(button.dataset.id), 'Start');
        }));
        body.querySelectorAll('.sq-cancel').forEach(button => button.addEventListener('click', event => {
            event.stopPropagation();
            run(async () => {
                if (!confirm('Cancel this snapshot? Data collected so far is discarded when deleted.')) return;
                await request('POST', `/jobs/${button.dataset.id}/cancel`);
                await refreshJobs();
            }, 'Cancel');
        }));
        body.querySelectorAll('.sq-delete').forEach(button => button.addEventListener('click', event => {
            event.stopPropagation();
            run(async () => {
                if (!confirm('Delete this snapshot and its package?')) return;
                await request('DELETE', `/jobs/${button.dataset.id}`);
                if (selectedJob === button.dataset.id) { selectedJob = null; $('sq-detail-card').classList.add('d-none'); }
                await refreshJobs();
            }, 'Delete');
        }));
        return jobs;
    }

    async function startJob(id) {
        const password = prompt('Enter confirmation password');
        if (!password) return;
        const override = confirm('Run now even outside the low-traffic window?\n\nOK = run now (override), Cancel = wait for the window.');
        await request('POST', `/jobs/${id}/start`, { confirmation_password: password, override_window: override });
        await refreshJobs();
        await selectJob(id);
        startPolling();
    }

    async function selectJob(id) {
        selectedJob = id;
        $('sq-detail-card').classList.remove('d-none');
        const { job } = await request('GET', `/jobs/${id}`);
        $('sq-detail-status').innerHTML = badge(job.status);
        const meta = [
            `Modems: <strong>${job.targets_total}</strong>`,
            `Complete: <strong>${job.targets_complete}</strong>`,
            `<span class="text-danger">Failed: <strong>${job.targets_failed}</strong></span>`,
            `Pending: <strong>${job.targets_pending}</strong>`,
            `Captures: <strong>${job.include_captures ? 'yes' : 'SNMP only'}</strong>`,
            `Started: ${esc(when(job.started_at))}`, `Finished: ${esc(when(job.finished_at))}`,
        ];
        $('sq-detail-meta').innerHTML = meta.map(m => `<span class="me-3">${m}</span>`).join('') +
            (job.error_text ? `<div class="text-danger mt-1">${esc(job.error_text)}</div>` : '');
        const filter = $('sq-target-filter').value;
        const targets = await request('GET', `/jobs/${id}/targets?limit=500${filter ? `&state=${filter}` : ''}`);
        $('sq-targets-body').innerHTML = (targets.targets || []).map(t => `<tr>
            <td class="sq-code">${esc(t.mac)}</td><td>${esc(t.modem_ip || '—')}</td><td>${esc(t.fiber_node || '—')}</td>
            <td>${badge(t.state)}</td><td class="text-danger small">${esc(t.error_text || '')}</td></tr>`).join('')
            || '<tr><td colspan="5" class="text-muted">No modems match</td></tr>';
        $('sq-targets-footer').textContent = targets.has_more ? 'Showing the first 500 modems of this view.' : '';
    }

    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
            if (document.hidden) return;
            try {
                await refreshJobs();
                if (selectedJob) await selectJob(selectedJob);
            } catch (error) { console.warn('Signal quality refresh failed', error); }
        }, 5000);
    }

    $('sq-scope-type').addEventListener('change', updateScope);
    // Changing the CMTS always clears the chosen nodes: a node name is only meaningful under its CMTS.
    $('sq-cmts').addEventListener('change', () => {
        if ($('sq-scope-type').value === 'fiber_node') loadFiberNodes(); else resetPicker('Select a CMTS first');
    });

    const search = $('sq-fn-search');
    $('sq-fn-box').addEventListener('click', () => { if (!search.disabled) { search.focus(); renderMenu(); } });
    search.addEventListener('focus', renderMenu);
    search.addEventListener('input', () => { activeIndex = -1; renderMenu(); });
    search.addEventListener('keydown', event => {
        const shown = matches().slice(0, MENU_LIMIT);
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!shown.length) return;
            activeIndex = (activeIndex + (event.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length;
            renderMenu();
            $('sq-fn-menu').querySelector('.active')?.scrollIntoView({ block: 'nearest' });
        } else if (event.key === 'Enter') {
            event.preventDefault();
            const pick = shown[activeIndex] || (shown.length === 1 || (search.value.trim() && shown.length) ? shown[0] : null);
            if (pick) addNodes([pick.name]);
        } else if (event.key === 'Escape') {
            $('sq-fn-menu').classList.add('d-none');
        } else if (event.key === 'Backspace' && !search.value && selectedNodes.length) {
            removeNode(selectedNodes[selectedNodes.length - 1]);
        }
    });
    $('sq-fn-menu').addEventListener('mousedown', event => event.preventDefault());   // keep focus in the input
    $('sq-fn-menu').addEventListener('click', event => {
        const single = event.target.closest('[data-add]');
        if (single) return addNodes([single.dataset.add]);
        if (event.target.closest('[data-add-all]')) addNodes(matches().map(n => n.name));
    });
    $('sq-fn-chips').addEventListener('click', event => {
        const button = event.target.closest('[data-remove]');
        if (button) { event.stopPropagation(); removeNode(button.dataset.remove); }
    });
    document.addEventListener('mousedown', event => {
        if (!event.target.closest('#sq-fn-box, #sq-fn-menu')) $('sq-fn-menu').classList.add('d-none');
    });
    $('sq-target-filter').addEventListener('change', () => selectedJob && selectJob(selectedJob));
    $('sq-refresh-btn').addEventListener('click', () => run(refreshJobs, 'Refresh'));
    $('sq-plan-btn').addEventListener('click', () => run(() => createJob(false), 'Schedule'));
    $('sq-run-btn').addEventListener('click', () => run(() => createJob(true), 'Start'));

    (async function init() {
        updateScope();
        await loadCmts();
        await refreshJobs();
        startPolling();
    })().catch(error => {
        console.error('Signal quality init failed', error);
        $('sq-jobs-body').innerHTML = `<tr><td colspan="7" class="text-danger">${esc(error.message)}</td></tr>`;
    });
})();
