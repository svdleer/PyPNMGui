(() => {
    'use strict';

    const root = document.getElementById('network-rxmer-app');
    if (!root) return;

    const basePath = root.dataset.basePath || '';
    const apiBase = `${basePath}/api/admin/rxmer-analytics`;
    const terminalStates = new Set(['completed', 'partial', 'failed', 'cancelled']);
    const startableStates = new Set(['planned', 'interrupted', 'failed']);
    const cancellableStates = new Set(['queued', 'running', 'cancel_requested']);
    let selectedJobId = null;
    let pollTimer = null;
    let pendingPlanKey = null;
    let pendingPlanFingerprint = null;
    const pendingPlanStorageKey = 'networkRxmerPendingPlan';

    try {
        const pending = JSON.parse(window.sessionStorage.getItem(pendingPlanStorageKey) || 'null');
        pendingPlanKey = pending && pending.key ? pending.key : null;
        pendingPlanFingerprint = pending && pending.fingerprint ? pending.fingerprint : null;
    } catch (_) {
        window.sessionStorage.removeItem(pendingPlanStorageKey);
    }

    const byId = (id) => document.getElementById(id);
    const alertBox = byId('rxmer-alert');

    function showAlert(message, kind = 'danger') {
        alertBox.textContent = message;
        alertBox.className = `alert alert-${kind}`;
    }

    function clearAlert() {
        alertBox.textContent = '';
        alertBox.className = 'alert d-none';
    }

    async function request(path, options = {}) {
        const response = await fetch(`${apiBase}${path}`, {
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', ...(options.headers || {})},
            ...options,
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(body.detail || body.message || `Request failed (${response.status})`);
        }
        return body;
    }

    function textCell(row, value, className = '') {
        const cell = document.createElement('td');
        cell.textContent = value == null || value === '' ? '—' : String(value);
        if (className) cell.className = className;
        row.appendChild(cell);
        return cell;
    }

    function scopeLabel(scope) {
        if (!scope || scope.type === 'all_network') return 'Entire network';
        return (scope.cmts || []).join(', ') || 'Selected CMTS';
    }

    function completedTargets(job) {
        return Number(job.targets_succeeded || 0) + Number(job.targets_partial || 0) + Number(job.targets_failed || 0);
    }

    function progressPercent(job) {
        const total = Number(job.targets_total || 0);
        return total ? Math.min(100, Math.round((completedTargets(job) / total) * 100)) : 0;
    }

    function actionButton(label, className, handler) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `btn btn-sm ${className}`;
        button.textContent = label;
        button.addEventListener('click', handler);
        return button;
    }

    function renderJobs(jobs) {
        const body = byId('rxmer-jobs-body');
        body.replaceChildren();
        if (!jobs.length) {
            const row = document.createElement('tr');
            const cell = textCell(row, 'No analytics jobs have been planned.', 'text-center text-muted py-4');
            cell.colSpan = 7;
            body.appendChild(row);
            return;
        }
        jobs.forEach((job) => {
            const row = document.createElement('tr');
            if (job.public_id === selectedJobId) row.classList.add('table-primary');
            textCell(row, job.created_at ? new Date(job.created_at).toLocaleString() : '—');
            textCell(row, job.status);
            textCell(row, scopeLabel(job.scope));
            textCell(row, job.targets_total || 0);
            textCell(row, `${completedTargets(job)} / ${job.targets_total || 0}`);
            textCell(row, `${job.channels_succeeded || 0} ok / ${job.channels_failed || 0} failed`);
            const actions = document.createElement('td');
            actions.className = 'text-end';
            actions.appendChild(actionButton('Open', 'btn-outline-primary', () => selectJob(job.public_id)));
            row.appendChild(actions);
            body.appendChild(row);
        });
    }

    async function loadJobs() {
        try {
            const response = await request('/jobs?limit=100');
            renderJobs(response.jobs || []);
        } catch (error) {
            showAlert(error.message);
        }
    }

    function metric(label, value) {
        const element = document.createElement('div');
        element.className = 'rxmer-metric';
        const strong = document.createElement('strong');
        strong.textContent = String(value ?? 0);
        const caption = document.createElement('span');
        caption.className = 'small text-muted';
        caption.textContent = label;
        element.append(strong, caption);
        return element;
    }

    function renderJob(job) {
        byId('rxmer-detail-card').classList.remove('d-none');
        byId('rxmer-job-id').textContent = job.public_id;
        const metrics = byId('rxmer-metrics');
        metrics.replaceChildren(
            metric('Status', job.status),
            metric('Targets', job.targets_total),
            metric('Succeeded', job.targets_succeeded),
            metric('Partial', job.targets_partial),
            metric('Failed', job.targets_failed),
            metric('Channels OK', job.channels_succeeded),
            metric('Channels failed', job.channels_failed),
        );
        const percent = progressPercent(job);
        const progress = byId('rxmer-progress');
        progress.style.width = `${percent}%`;
        progress.textContent = `${percent}%`;
        progress.setAttribute('aria-valuenow', String(percent));
        byId('rxmer-start-job').classList.toggle('d-none', !startableStates.has(job.status));
        byId('rxmer-cancel-job').classList.toggle('d-none', !cancellableStates.has(job.status));
        const error = byId('rxmer-job-error');
        error.textContent = job.error_text || '';
        error.classList.toggle('d-none', !job.error_text);
        schedulePolling(job.status);
    }

    function renderHistogram(elementId, bins) {
        const container = byId(elementId);
        container.replaceChildren();
        if (!bins || !bins.length) {
            const empty = document.createElement('div');
            empty.className = 'text-muted small';
            empty.textContent = 'No completed modem results yet.';
            container.appendChild(empty);
            return;
        }
        const maximum = Math.max(...bins.map((bin) => Number(bin.modem_count || 0)), 1);
        bins.forEach((bin) => {
            const row = document.createElement('div');
            row.className = 'rxmer-bin';
            const label = document.createElement('span');
            label.textContent = `${Number(bin.rxmer_db).toFixed(2)} dB`;
            const track = document.createElement('div');
            track.className = 'rxmer-bar-track';
            const bar = document.createElement('div');
            bar.className = 'rxmer-bar';
            bar.style.width = `${(Number(bin.modem_count || 0) / maximum) * 100}%`;
            track.appendChild(bar);
            const count = document.createElement('span');
            count.className = 'text-end';
            count.textContent = String(bin.modem_count || 0);
            row.append(label, track, count);
            container.appendChild(row);
        });
    }

    function renderModems(targets) {
        const card = byId('rxmer-modems-card');
        const body = byId('rxmer-modems-body');
        body.replaceChildren();
        card.classList.remove('d-none');
        if (!targets.length) {
            const row = document.createElement('tr');
            const cell = textCell(row, 'No target rows available.', 'text-center text-muted py-3');
            cell.colSpan = 8;
            body.appendChild(row);
            return;
        }
        targets.forEach((target) => {
            const row = document.createElement('tr');
            textCell(row, target.mac, 'rxmer-code');
            textCell(row, target.cmts);
            textCell(row, target.fiber_node);
            textCell(row, target.state);
            textCell(row, target.completeness);
            textCell(row, target.avg_db == null ? '—' : `${Number(target.avg_db).toFixed(2)} dB`);
            textCell(row, target.best_db == null ? '—' : `${Number(target.best_db).toFixed(2)} dB`);
            textCell(row, target.sample_count || 0);
            body.appendChild(row);
        });
    }

    async function refreshSelectedJob() {
        if (!selectedJobId) return;
        try {
            const [jobResponse, aggregateResponse, modemResponse] = await Promise.all([
                request(`/jobs/${encodeURIComponent(selectedJobId)}`),
                request(`/jobs/${encodeURIComponent(selectedJobId)}/aggregates?bucket_db=0.5`),
                request(`/jobs/${encodeURIComponent(selectedJobId)}/modems?cursor=0&limit=200`),
            ]);
            renderJob(jobResponse.job);
            renderHistogram('rxmer-average-histogram', aggregateResponse.average_rxmer || []);
            renderHistogram('rxmer-best-histogram', aggregateResponse.best_subcarrier_rxmer || []);
            renderModems(modemResponse.targets || []);
        } catch (error) {
            showAlert(error.message);
        }
    }

    async function selectJob(publicId) {
        selectedJobId = publicId;
        clearAlert();
        await refreshSelectedJob();
        await loadJobs();
    }

    function schedulePolling(status) {
        if (pollTimer) window.clearTimeout(pollTimer);
        pollTimer = null;
        if (!selectedJobId || terminalStates.has(status) || status === 'planned') return;
        pollTimer = window.setTimeout(async () => {
            await refreshSelectedJob();
            await loadJobs();
        }, 5000);
    }

    function selectedCmts() {
        return [...new Set(byId('rxmer-cmts').value.split(/[\n,]+/).map((value) => value.trim()).filter(Boolean))].sort();
    }

    async function createPlan(event) {
        event.preventDefault();
        clearAlert();
        const scopeType = byId('rxmer-scope-type').value;
        const cmts = scopeType === 'cmts' ? selectedCmts() : [];
        if (scopeType === 'cmts' && !cmts.length) {
            showAlert('Enter at least one CMTS for selected-CMTS scope.', 'warning');
            return;
        }
        const planPayload = {
            scope: {type: scopeType, cmts},
            online_only: byId('rxmer-online-only').checked,
            raw_retention_days: Number(byId('rxmer-raw-retention').value),
            aggregate_retention_days: Number(byId('rxmer-aggregate-retention').value),
        };
        const fingerprint = JSON.stringify(planPayload);
        if (!pendingPlanKey || pendingPlanFingerprint !== fingerprint) {
            pendingPlanKey = window.crypto && window.crypto.randomUUID
                ? window.crypto.randomUUID()
                : `gui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            pendingPlanFingerprint = fingerprint;
            window.sessionStorage.setItem(
                pendingPlanStorageKey,
                JSON.stringify({key: pendingPlanKey, fingerprint}),
            );
        }
        planPayload.idempotency_key = pendingPlanKey;

        const button = byId('rxmer-plan-button');
        button.disabled = true;
        try {
            const response = await request('/jobs/plan', {
                method: 'POST',
                body: JSON.stringify(planPayload),
            });
            pendingPlanKey = null;
            pendingPlanFingerprint = null;
            window.sessionStorage.removeItem(pendingPlanStorageKey);
            showAlert(response.reused ? 'Existing matching plan selected.' : 'Plan created. No collection has started.', 'success');
            selectedJobId = response.job.public_id;
            await refreshSelectedJob();
            await loadJobs();
        } catch (error) {
            const ambiguous = error.message.includes('may still complete');
            showAlert(
                ambiguous
                    ? `${error.message}. Refresh the job list before retrying; a retry will reuse the same request key.`
                    : error.message,
                ambiguous ? 'warning' : 'danger',
            );
        } finally {
            button.disabled = false;
        }
    }

    async function startSelectedJob() {
        if (!selectedJobId) return;
        if (!window.confirm('Start network RxMER collection for this plan? This will contact every planned modem and capture downstream OFDM RxMER.')) return;
        try {
            const response = await request(`/jobs/${encodeURIComponent(selectedJobId)}/start`, {
                method: 'POST',
                body: JSON.stringify({max_concurrency: 2}),
            });
            showAlert(response.message || 'Collection queued.', 'success');
            renderJob(response.job);
            await loadJobs();
        } catch (error) {
            showAlert(error.message);
        }
    }

    async function cancelSelectedJob() {
        if (!selectedJobId) return;
        if (!window.confirm('Request cooperative cancellation of this RxMER collection?')) return;
        try {
            const response = await request(`/jobs/${encodeURIComponent(selectedJobId)}/cancel`, {method: 'POST'});
            showAlert(response.message || 'Cancellation requested.', 'warning');
            renderJob(response.job);
            await loadJobs();
        } catch (error) {
            showAlert(error.message);
        }
    }

    byId('rxmer-scope-type').addEventListener('change', (event) => {
        byId('rxmer-cmts-field').hidden = event.target.value !== 'cmts';
    });
    byId('rxmer-plan-form').addEventListener('submit', createPlan);
    byId('rxmer-refresh-jobs').addEventListener('click', loadJobs);
    byId('rxmer-start-job').addEventListener('click', startSelectedJob);
    byId('rxmer-cancel-job').addEventListener('click', cancelSelectedJob);
    window.addEventListener('pagehide', () => {
        if (pollTimer) window.clearTimeout(pollTimer);
    });

    loadJobs();
})();