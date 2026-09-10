// SPDX-License-Identifier: Apache-2.0

(() => {
    'use strict';

    const pane = document.getElementById('inventory-backfill-pane');
    if (!pane) return;

    const basePath = window.BASE_PATH || '';
    const apiBase = `${basePath}/api/admin/inventory/mysql-backfill`;
    const activeStatuses = new Set(['queued', 'running', 'finalizing']);
    const elements = {
        tab: document.getElementById('inventory-backfill-tab'),
        lockChip: document.getElementById('backfill-lock-chip'),
        alert: document.getElementById('backfill-alert'),
        password: document.getElementById('backfill-password'),
        unlock: document.getElementById('backfill-unlock-btn'),
        pageSize: document.getElementById('backfill-page-size'),
        queue: document.getElementById('backfill-queue-btn'),
        refresh: document.getElementById('backfill-refresh-btn'),
        agentsBody: document.getElementById('backfill-agents-body'),
        jobsBody: document.getElementById('backfill-jobs-body'),
    };

    let initialized = false;
    let controlPassword = '';
    let agents = [];
    let jobs = [];
    let selectedAgents = new Set();
    let refreshInFlight = false;

    const setAlert = (message, level = 'danger') => {
        if (!elements.alert) return;
        elements.alert.textContent = message || '';
        elements.alert.className = `alert alert-${level} py-2${message ? '' : ' d-none'}`;
    };

    const requestJson = async (url, options = {}) => {
        const response = await fetch(url, {
            credentials: 'same-origin',
            ...options,
        });
        let body = null;
        try {
            body = await response.json();
        } catch (_error) {
            body = {};
        }
        if (!response.ok) {
            throw new Error(body?.message || body?.detail || `HTTP ${response.status}`);
        }
        return body || {};
    };

    const appendTextCell = (row, value, className = '') => {
        const cell = document.createElement('td');
        cell.textContent = value;
        if (className) cell.className = className;
        row.appendChild(cell);
        return cell;
    };

    const activeJobByAgent = () => {
        const result = new Map();
        jobs.forEach((job) => {
            if (activeStatuses.has(String(job?.status || '').toLowerCase())) {
                result.set(String(job.agent_id || ''), job);
            }
        });
        return result;
    };

    const updateQueueButton = () => {
        if (!elements.queue) return;
        elements.queue.disabled = !controlPassword || selectedAgents.size === 0;
    };

    const renderAgents = () => {
        if (!elements.agentsBody) return;
        elements.agentsBody.replaceChildren();
        const active = activeJobByAgent();
        const availableIds = new Set(agents.map((agent) => String(agent.agent_id || '')));
        selectedAgents = new Set(
            [...selectedAgents].filter((agentId) => availableIds.has(agentId) && !active.has(agentId))
        );

        if (!agents.length) {
            const row = document.createElement('tr');
            appendTextCell(row, 'No connected agent advertises cm_poller_inventory.', 'text-muted small');
            row.firstChild.colSpan = 4;
            elements.agentsBody.appendChild(row);
            updateQueueButton();
            return;
        }

        agents.forEach((agent) => {
            const agentId = String(agent.agent_id || '');
            const activeJob = active.get(agentId);
            const row = document.createElement('tr');
            const selectCell = document.createElement('td');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input';
            checkbox.checked = selectedAgents.has(agentId);
            checkbox.disabled = Boolean(activeJob);
            checkbox.setAttribute('aria-label', `Select ${agentId}`);
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) selectedAgents.add(agentId);
                else selectedAgents.delete(agentId);
                updateQueueButton();
            });
            selectCell.appendChild(checkbox);
            row.appendChild(selectCell);
            appendTextCell(row, agentId, 'small font-monospace');
            appendTextCell(row, String(agent.bulk_free_slots ?? 0), 'small');
            appendTextCell(
                row,
                activeJob ? `${activeJob.status} · ${activeJob.public_id}` : '—',
                'small'
            );
            elements.agentsBody.appendChild(row);
        });
        updateQueueButton();
    };

    const renderJobs = () => {
        if (!elements.jobsBody) return;
        elements.jobsBody.replaceChildren();
        if (!jobs.length) {
            const row = document.createElement('tr');
            appendTextCell(row, 'No MySQL inventory backfill jobs.', 'text-muted small');
            row.firstChild.colSpan = 8;
            elements.jobsBody.appendChild(row);
            return;
        }

        jobs.forEach((job) => {
            const row = document.createElement('tr');
            const status = String(job.status || 'unknown');
            const percent = job.percent === null || job.percent === undefined
                ? '—'
                : `${Number(job.percent).toFixed(2)}%`;
            appendTextCell(row, String(job.agent_id || '—'), 'small font-monospace');
            appendTextCell(row, status, 'small');
            appendTextCell(row, percent, 'small');
            appendTextCell(row, Number(job.rows_received || 0).toLocaleString(), 'small');
            appendTextCell(
                row,
                `${Number(job.rows_matched || 0).toLocaleString()} / ${Number(job.rows_updated || 0).toLocaleString()}`,
                'small'
            );
            appendTextCell(row, String(job.cursor || '—'), 'small font-monospace');
            appendTextCell(
                row,
                [job.error_code, job.error_text].filter(Boolean).join(': ') || '—',
                job.error_text ? 'small text-danger' : 'small text-muted'
            );

            const actionCell = document.createElement('td');
            if (['queued', 'running'].includes(status)) {
                const cancel = document.createElement('button');
                cancel.type = 'button';
                cancel.className = 'btn btn-outline-danger btn-sm';
                cancel.textContent = 'Cancel';
                cancel.disabled = !controlPassword;
                cancel.addEventListener('click', async () => {
                    if (!window.confirm(`Cancel backfill ${job.public_id} for ${job.agent_id}?`)) return;
                    cancel.disabled = true;
                    try {
                        await requestJson(`${apiBase}/${encodeURIComponent(job.public_id)}/cancel`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ control_password: controlPassword }),
                        });
                        setAlert('Cancellation requested.', 'success');
                        await refreshState();
                    } catch (error) {
                        setAlert(`Cancel failed: ${error?.message || error}`);
                        cancel.disabled = !controlPassword;
                    }
                });
                actionCell.appendChild(cancel);
            } else {
                actionCell.textContent = '—';
                actionCell.className = 'small text-muted';
            }
            row.appendChild(actionCell);
            elements.jobsBody.appendChild(row);
        });
    };

    const refreshState = async () => {
        if (refreshInFlight) return;
        refreshInFlight = true;
        if (elements.refresh) elements.refresh.disabled = true;
        try {
            const [agentsBody, jobsBody] = await Promise.all([
                requestJson(`${apiBase}/agents`),
                requestJson(`${apiBase}?limit=100`),
            ]);
            agents = Array.isArray(agentsBody.agents) ? agentsBody.agents : [];
            jobs = Array.isArray(jobsBody.jobs) ? jobsBody.jobs : [];
            renderJobs();
            renderAgents();
        } catch (error) {
            setAlert(`Backfill status refresh failed: ${error?.message || error}`);
        } finally {
            refreshInFlight = false;
            if (elements.refresh) elements.refresh.disabled = false;
        }
    };

    const unlock = async () => {
        const supplied = String(elements.password?.value || '');
        if (!supplied) {
            setAlert('Enter the control password.');
            return;
        }
        if (elements.unlock) elements.unlock.disabled = true;
        try {
            await requestJson(`${apiBase}/verify`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ control_password: supplied }),
            });
            controlPassword = supplied;
            if (elements.password) elements.password.value = '';
            if (elements.lockChip) {
                elements.lockChip.textContent = 'Unlocked for this page';
                elements.lockChip.style.background = '#dcfce7';
                elements.lockChip.style.color = '#166534';
            }
            setAlert('Inventory backfill controls unlocked for this page.', 'success');
            renderJobs();
            updateQueueButton();
        } catch (error) {
            controlPassword = '';
            setAlert(error?.message || 'Unlock failed.');
        } finally {
            if (elements.unlock) elements.unlock.disabled = false;
        }
    };

    const queueSelected = async () => {
        if (!controlPassword || !selectedAgents.size) return;
        const pageSize = Number(elements.pageSize?.value || 1000);
        if (!Number.isInteger(pageSize) || pageSize < 100 || pageSize > 5000) {
            setAlert('Page size must be an integer from 100 to 5000.');
            return;
        }
        const sourceIds = [...selectedAgents];
        if (!window.confirm(`Queue inventory backfill for ${sourceIds.length} source agent(s)?`)) return;
        if (elements.queue) elements.queue.disabled = true;
        const failures = [];
        let queued = 0;
        for (const agentId of sourceIds) {
            try {
                await requestJson(apiBase, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent_id: agentId,
                        page_size: pageSize,
                        control_password: controlPassword,
                    }),
                });
                queued += 1;
                selectedAgents.delete(agentId);
            } catch (error) {
                failures.push(`${agentId}: ${error?.message || error}`);
            }
        }
        if (failures.length) {
            setAlert(`Queued ${queued}; failed ${failures.length}. ${failures.join(' | ')}`);
        } else {
            setAlert(`Queued ${queued} source backfill job(s).`, 'success');
        }
        await refreshState();
        updateQueueButton();
    };

    elements.unlock?.addEventListener('click', unlock);
    elements.password?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            unlock();
        }
    });
    elements.queue?.addEventListener('click', queueSelected);
    elements.refresh?.addEventListener('click', refreshState);
    elements.tab?.addEventListener('shown.bs.tab', async () => {
        if (!initialized) initialized = true;
        await refreshState();
    });

    if (elements.tab?.classList.contains('active')) {
        initialized = true;
        refreshState();
    }
    window.setInterval(() => {
        if (initialized && elements.tab?.classList.contains('active')) refreshState();
    }, 5000);
})();
