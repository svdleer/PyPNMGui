// SPDX-License-Identifier: Apache-2.0

(() => {
    'use strict';

    const tab = document.getElementById('inventory-tap-tab');
    const card = document.getElementById('ubee-bulk-refresh-card');
    if (!tab || !card) return;

    const basePath = window.BASE_PATH || '';
    const apiBase = `${basePath}/api/admin/inventory/modem-refresh-jobs`;
    const pollerJobsApi = `${basePath}/api/admin/data-jobs?limit=100`;
    const activeStatuses = new Set(['queued', 'running']);
    const elements = {
        alert: document.getElementById('ubee-refresh-alert'),
        status: document.getElementById('ubee-refresh-status'),
        detail: document.getElementById('ubee-refresh-detail'),
        concurrency: document.getElementById('ubee-refresh-concurrency'),
        queueDepth: document.getElementById('ubee-refresh-queue-depth'),
        start: document.getElementById('ubee-refresh-start-btn'),
        cancel: document.getElementById('ubee-refresh-cancel-btn'),
        refresh: document.getElementById('ubee-refresh-status-btn'),
        targeted: document.getElementById('ubee-refresh-targeted'),
        succeeded: document.getElementById('ubee-refresh-succeeded'),
        failed: document.getElementById('ubee-refresh-failed'),
        remaining: document.getElementById('ubee-refresh-remaining'),
    };

    let jobId = null;
    let refreshInFlight = false;
    let pollTimer = null;

    const integerInRange = (element, minimum, maximum, label) => {
        const value = Number(element?.value);
        if (!Number.isInteger(value) || value < minimum || value > maximum) {
            throw new Error(`${label} must be an integer from ${minimum} to ${maximum}.`);
        }
        return value;
    };

    const setAlert = (message, level = 'danger') => {
        if (!elements.alert) return;
        elements.alert.textContent = message || '';
        elements.alert.className = `alert alert-${level} py-2${message ? '' : ' d-none'}`;
    };

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, {
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
            ...options,
        });
        let body = {};
        try { body = await response.json(); } catch (_) {}
        if (!response.ok) throw new Error(body?.message || body?.detail || `HTTP ${response.status}`);
        return body || {};
    };

    const formatCount = (value) => Number(value || 0).toLocaleString();

    const renderJob = (job) => {
        const status = String(job?.status || 'unknown').toLowerCase();
        const active = activeStatuses.has(status);
        const colors = {
            queued: ['#dbeafe', '#1e40af'],
            running: ['#fef3c7', '#92400e'],
            done: ['#dcfce7', '#166534'],
            cancelled: ['#e2e8f0', '#334155'],
            failed: ['#fee2e2', '#991b1b'],
        };
        const [background, color] = colors[status] || ['#e2e8f0', '#334155'];
        if (elements.status) {
            elements.status.textContent = status;
            elements.status.style.background = background;
            elements.status.style.color = color;
        }
        const succeeded = Number(job?.modems_succeeded || 0);
        const failed = Number(job?.modems_failed || 0);
        const remaining = Number(job?.modems_remaining || 0);
        if (elements.targeted) elements.targeted.textContent = formatCount(succeeded + failed + remaining);
        if (elements.succeeded) elements.succeeded.textContent = formatCount(succeeded);
        if (elements.failed) elements.failed.textContent = formatCount(failed);
        if (elements.remaining) elements.remaining.textContent = formatCount(remaining);
        if (elements.detail) {
            const descriptor = [job?.vendor, job?.model].filter(Boolean).join(' ') || 'Ubee UBC1318ZG';
            elements.detail.textContent = `${descriptor} · ${job?.error_text || 'No additional status message.'}`;
        }
        if (elements.cancel) elements.cancel.disabled = !active;
        if (elements.start) elements.start.disabled = active;
        if (elements.concurrency) elements.concurrency.disabled = active;
        if (elements.queueDepth) elements.queueDepth.disabled = active;
        if (active) startPolling(); else stopPolling();
    };

    const discoverJob = async () => {
        if (refreshInFlight) return;
        refreshInFlight = true;
        if (elements.refresh) elements.refresh.disabled = true;
        try {
            const body = await requestJson(pollerJobsApi);
            const jobs = Array.isArray(body.jobs) ? body.jobs : [];
            const match = jobs.find((job) => String(job?.poller_name || '') === 'Bulk modem inventory refresh');
            if (!match) {
                jobId = null;
                renderJob({ status: 'not started' });
                if (elements.detail) elements.detail.textContent = 'No Ubee bulk refresh job has been created.';
                return;
            }
            jobId = Number(match.id);
            if (!Number.isInteger(jobId) || jobId <= 0) throw new Error('PyPNM returned an invalid bulk refresh job ID.');
            refreshInFlight = false;
            await refreshStatus();
        } catch (error) {
            setAlert(`Bulk refresh status discovery failed: ${error?.message || error}`);
        } finally {
            refreshInFlight = false;
            if (elements.refresh) elements.refresh.disabled = false;
        }
    };

    const refreshStatus = async () => {
        if (!jobId || refreshInFlight) return;
        refreshInFlight = true;
        if (elements.refresh) elements.refresh.disabled = true;
        try {
            const body = await requestJson(`${apiBase}/${encodeURIComponent(jobId)}`);
            renderJob(body.job || {});
        } catch (error) {
            setAlert(`Bulk refresh status failed: ${error?.message || error}`);
            stopPolling();
        } finally {
            refreshInFlight = false;
            if (elements.refresh) elements.refresh.disabled = false;
        }
    };

    const startRefresh = async () => {
        try {
            const maxInFlight = integerInRange(elements.concurrency, 1, 32, 'Concurrent requests');
            const queueDepth = integerInRange(elements.queueDepth, 16, 512, 'Queue depth');
            if (queueDepth < maxInFlight) throw new Error('Queue depth must be at least the concurrent request limit.');
            if (!window.confirm('Start the bounded Ubee UBC1318ZG inventory refresh? This sends live identity queries to the matched modem cohort.')) return;
            if (elements.start) elements.start.disabled = true;
            const body = await requestJson(apiBase, {
                method: 'POST',
                body: JSON.stringify({
                    vendor: 'Ubee',
                    model: 'UBC1318ZG',
                    max_in_flight: maxInFlight,
                    queue_depth: queueDepth,
                }),
            });
            const job = body.job || {};
            jobId = Number(job.id);
            if (!Number.isInteger(jobId) || jobId <= 0) throw new Error('PyPNM did not return a bulk refresh job ID.');
            setAlert(`Bulk Ubee refresh job ${jobId} queued.`, 'success');
            renderJob(job);
            await refreshStatus();
        } catch (error) {
            setAlert(`Could not start Ubee refresh: ${error?.message || error}`);
            if (elements.start) elements.start.disabled = false;
        }
    };

    const cancelRefresh = async () => {
        if (!jobId) return;
        if (!window.confirm(`Cancel Ubee bulk refresh job ${jobId}?`)) return;
        if (elements.cancel) elements.cancel.disabled = true;
        try {
            await requestJson(`${apiBase}/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', body: '{}' });
            setAlert('Bulk Ubee refresh cancellation requested.', 'success');
            await refreshStatus();
        } catch (error) {
            setAlert(`Could not cancel Ubee refresh: ${error?.message || error}`);
            if (elements.cancel) elements.cancel.disabled = false;
        }
    };

    const startPolling = () => {
        if (pollTimer || !tab.classList.contains('active')) return;
        pollTimer = window.setInterval(refreshStatus, 5000);
    };

    const stopPolling = () => {
        if (!pollTimer) return;
        window.clearInterval(pollTimer);
        pollTimer = null;
    };

    elements.start?.addEventListener('click', startRefresh);
    elements.cancel?.addEventListener('click', cancelRefresh);
    elements.refresh?.addEventListener('click', () => { if (jobId) refreshStatus(); else discoverJob(); });
    tab.addEventListener('shown.bs.tab', () => { if (jobId) refreshStatus(); else discoverJob(); });
    tab.addEventListener('hidden.bs.tab', stopPolling);
    window.addEventListener('beforeunload', stopPolling);
})();
