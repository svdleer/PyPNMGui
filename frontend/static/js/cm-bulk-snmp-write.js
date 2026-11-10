/* Bulk CM SNMP write operations. GUI talks only to the Flask BFF. */
(function () {
    'use strict';
    const root = document.getElementById('cm-write-app');
    if (!root) return;
    const pageRoot = document.getElementById('cm-bulk-reset-app');
    const basePath = (pageRoot && pageRoot.dataset.basePath) || '';
    const api = `${basePath}/api/admin/cm-snmp-write`;
    const topologyEnabled = pageRoot?.dataset.topologyScopesEnabled === 'true';
    const $ = id => document.getElementById(id);
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function request(method, path, body) {
        const options = { method, headers: {'Content-Type': 'application/json'} };
        if (body !== undefined) options.body = JSON.stringify(body);
        const response = await fetch(`${api}${path}`, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
        return data;
    }

    let operations = [];
    let selectedJob = null;
    let pollTimer = null;

    function updateScope() {
        const type = $('write-scope-type').value;
        $('write-single-wrap').classList.toggle('d-none', type !== 'single');
        $('write-cmts-wrap').classList.toggle('d-none', type !== 'cmts' && type !== 'fiber_node');
        $('write-fn-wrap').classList.toggle('d-none', !topologyEnabled || type !== 'fiber_node');
        $('write-file-wrap').classList.toggle('d-none', type !== 'file');
        if (!topologyEnabled && type === 'fiber_node') $('write-scope-type').value = 'single';
    }

    function renderOperations() {
        $('write-operations').innerHTML = operations.map((op, index) => `
            <div class="row g-2 mb-2 write-operation" data-index="${index}">
                <div class="col-md-4"><input class="form-control form-control-sm write-oid" placeholder="OID or MIB name" value="${esc(op.oid)}"></div>
                <div class="col-md-3"><input class="form-control form-control-sm write-value" placeholder="Value" value="${esc(op.value)}"></div>
                <div class="col-md-2"><select class="form-select form-select-sm write-type">${[['i','Integer32'],['s','String'],['x','Hex'],['u','Unsigned32'],['c','Counter32'],['g','Gauge32'],['t','TimeTicks'],['a','IpAddress']].map(([v,l]) => `<option value="${v}" ${op.type === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
                <div class="col-md-2"><input type="number" min="0" max="300" step="0.1" class="form-control form-control-sm write-delay" placeholder="Delay" value="${esc(op.delay)}"></div>
                <div class="col-md-1"><button class="btn btn-sm btn-outline-danger write-remove" title="Remove">&times;</button></div>
            </div>`).join('');
    }

    function readOperations() {
        return [...document.querySelectorAll('.write-operation')].map(row => ({
            oid: row.querySelector('.write-oid').value.trim(),
            value: row.querySelector('.write-value').value,
            type: row.querySelector('.write-type').value,
            delay: Number(row.querySelector('.write-delay').value || 0),
        }));
    }

    function readScope() {
        const type = $('write-scope-type').value;
        const scope = { type };
        if (type === 'single') scope.mac = $('write-mac').value.trim();
        if (type === 'cmts') scope.cmts = [$('write-cmts').value];
        if (type === 'fiber_node') { scope.cmts = $('write-cmts').value; scope.fiber_nodes = [$('write-fiber-node').value]; }
        if (type === 'file') scope.mac_list = $('write-mac-list').value.split(/[\n,;]+/).map(x => x.trim()).filter(Boolean);
        return scope;
    }

    async function loadOptions() {
        const data = await request('GET', '/options/cmts?limit=5000');
        $('write-cmts').innerHTML = '<option value="">— select CMTS —</option>' + (data.cmts || []).map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
    }

    $('write-scope-type').addEventListener('change', updateScope);
    $('write-cmts').addEventListener('change', async () => {
        const cmts = $('write-cmts').value;
        const select = $('write-fiber-node');
        if (!cmts || !topologyEnabled) return;
        select.disabled = true; select.innerHTML = '<option>Loading...</option>';
        try {
            const data = await request('GET', `/options/fiber-nodes?cmts=${encodeURIComponent(cmts)}`);
            select.innerHTML = '<option value="">— select fiber node —</option>' + (data.fiber_nodes || []).map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
            select.disabled = false;
        } catch (error) { select.innerHTML = `<option>${esc(error.message)}</option>`; }
    });
    $('write-add-operation').addEventListener('click', () => { operations.push({oid:'', value:'', type:'i', delay:0}); renderOperations(); });
    $('write-operations').addEventListener('click', event => {
        const button = event.target.closest('.write-remove');
        if (!button) return;
        const index = Number(button.closest('.write-operation').dataset.index);
        operations.splice(index, 1); renderOperations();
    });

    async function createJob(runNow) {
        const scope = readScope();
        const ops = readOperations();
        const password = $('write-plan-password').value;
        const delay = Math.max(0, Math.min(Number($('write-delay-seconds').value || 0), 86400));
        if (!password) throw new Error('Confirmation password is required');
        if (!ops.length || ops.some(op => !op.oid || op.value === '')) throw new Error('Every operation needs an OID and value');
        if (scope.type === 'single' && !scope.mac) throw new Error('Enter a MAC address');
        if (scope.type === 'cmts' && !scope.cmts[0]) throw new Error('Select a CMTS');
        if (scope.type === 'fiber_node' && (!scope.cmts || !scope.fiber_nodes[0])) throw new Error('Select a CMTS and fiber node');
        if (scope.type === 'file' && !scope.mac_list.length) throw new Error('Enter at least one MAC');
        const data = await request('POST', '/jobs/plan', {scope, operations: ops, delay_seconds: runNow ? 0 : delay, confirmation_password: password});
        const id = data.job.public_id;
        if (runNow) await request('POST', `/jobs/${id}/start`, {confirmation_password: password, max_concurrency: 5});
        $('write-plan-password').value = '';
        await refreshJobs(); selectJob(id); startPolling();
    }

    $('write-plan-btn').addEventListener('click', async () => { try { await createJob(false); } catch (e) { alert(`Schedule failed: ${e.message}`); } });
    $('write-run-btn').addEventListener('click', async () => { try { await createJob(true); } catch (e) { alert(`Start failed: ${e.message}`); } });

    function status(status) { const classes={completed:'bg-success',completed_with_errors:'bg-warning text-dark',failed:'bg-danger',running:'bg-primary',queued:'bg-info',scheduled:'bg-secondary',planned:'bg-secondary',cancelled:'bg-dark'}; return `<span class="badge ${classes[status] || 'bg-secondary'}">${esc(status)}</span>`; }
    async function refreshJobs() {
        const data = await request('GET', '/jobs?limit=50');
        const jobs = data.jobs || [];
        $('write-jobs-body').innerHTML = jobs.length ? jobs.map(j => `<tr data-write-job="${esc(j.public_id)}"><td>${status(j.status)}</td><td>${esc(j.scope_type)}</td><td>${j.targets_total}</td><td>${j.operations_succeeded}/${j.operations_total} ok, ${j.operations_failed} failed</td><td>${j.scheduled_start ? esc(new Date(j.scheduled_start).toLocaleString()) : 'now'}</td><td>${['planned','scheduled'].includes(j.status) ? `<button class="btn btn-sm btn-success write-start" data-id="${esc(j.public_id)}">Start</button>` : ''} ${['completed','completed_with_errors','failed','cancelled','planned','scheduled'].includes(j.status) ? `<button class="btn btn-sm btn-outline-danger write-delete" data-id="${esc(j.public_id)}">Delete</button>` : ''}</td></tr>`).join('') : '<tr><td colspan="6" class="text-center text-muted py-3">No write jobs</td></tr>';
        $('write-jobs-body').querySelectorAll('tr[data-write-job]').forEach(row => row.addEventListener('click', e => { if (!e.target.closest('button')) selectJob(row.dataset.writeJob); }));
        $('write-jobs-body').querySelectorAll('.write-start').forEach(button => button.addEventListener('click', async e => { e.stopPropagation(); const password=prompt('Enter confirmation password'); if (!password) return; try { await request('POST', `/jobs/${button.dataset.id}/start`, {confirmation_password:password,max_concurrency:5}); await refreshJobs(); selectJob(button.dataset.id); startPolling(); } catch (error) { alert(error.message); } }));
        $('write-jobs-body').querySelectorAll('.write-delete').forEach(button => button.addEventListener('click', async e => { e.stopPropagation(); if (confirm('Delete this write job and its results?')) { await request('DELETE', `/jobs/${button.dataset.id}`); await refreshJobs(); } }));
    }
    async function selectJob(id) {
        selectedJob=id; $('write-detail-card').classList.remove('d-none');
        const data=await request('GET', `/jobs/${id}`); const job=data.job;
        $('write-detail-status').innerHTML=status(job.status); $('write-detail-meta').innerHTML=`<div class="col-auto">Targets: <strong>${job.targets_total}</strong></div><div class="col-auto">Succeeded: <strong>${job.operations_succeeded}</strong></div><div class="col-auto text-danger">Failed: <strong>${job.operations_failed}</strong></div><div class="col-auto">Pending: <strong>${job.operations_pending}</strong></div>`;
        const results=await request('GET', `/jobs/${id}/results?limit=1000`); $('write-results-body').innerHTML=(results.results||[]).map(r=>`<tr><td class="reset-code">${esc(r.mac)}</td><td>${esc(r.modem_ip||'—')}</td><td>${Number(r.operation_index)+1}</td><td>${esc(r.oid)}</td><td>${esc(r.type)}</td><td>${status(r.state)}</td><td>${r.duration_ms ?? '—'} ms</td><td class="text-danger">${esc(r.error_text||'')}</td></tr>`).join('') || '<tr><td colspan="8" class="text-muted">No results yet</td></tr>';
    }
    function startPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer=setInterval(async()=>{ try { await refreshJobs(); if(selectedJob) await selectJob(selectedJob); } catch(e) { console.warn(e); } },5000); }
    $('write-refresh-btn').addEventListener('click', refreshJobs);
    async function init() { operations.push({oid:'',value:'',type:'i',delay:0}); renderOperations(); updateScope(); await loadOptions(); await refreshJobs(); }
    init().catch(error => console.error('Bulk CM write init failed', error));
})();
