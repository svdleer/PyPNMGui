(() => {
    'use strict';

    const root = document.getElementById('network-rxmer-app');
    if (!root) return;

    const basePath = root.dataset.basePath || '';
    const apiBase = `${basePath}/api/admin/rxmer-analytics`;
    const terminalStates = new Set(['completed', 'completed_with_errors', 'partial', 'failed', 'cancelled']);
    const startableStates = new Set(['planned', 'interrupted', 'failed']);
    const cancellableStates = new Set(['queued', 'running', 'cancelling']);
    const activeStates = new Set(['queued', 'running', 'cancelling']);
    let selectedJobId = null;
    let selectedJobStatus = null;
    let pollTimer = null;
    let progressPollCount = 0;
    let spectrumPollTimer = null;
    let spectrumChart = null;
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
            const actionGroup = document.createElement('div');
            actionGroup.className = 'btn-group btn-group-sm';
            actionGroup.appendChild(actionButton('Open', 'btn-outline-primary', () => selectJob(job.public_id)));
            const clearResults = actionButton('Clear results', 'btn-outline-warning', () => deleteJobResults(job.public_id));
            const deleteButton = actionButton('Delete job', 'btn-outline-danger', () => deleteAnalyticsJob(job.public_id));
            const destructiveDisabled = activeStates.has(job.status);
            clearResults.disabled = destructiveDisabled;
            deleteButton.disabled = destructiveDisabled;
            if (destructiveDisabled) {
                clearResults.title = 'Cancel the active job before deleting results.';
                deleteButton.title = 'Cancel the active job before deleting it.';
            }
            actionGroup.append(clearResults, deleteButton);
            actions.appendChild(actionGroup);
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
        selectedJobStatus = job.status;
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
        byId('rxmer-concurrency').disabled = !startableStates.has(job.status);
        byId('rxmer-cancel-job').classList.toggle('d-none', !cancellableStates.has(job.status));
        const error = byId('rxmer-job-error');
        error.textContent = job.error_text || '';
        error.classList.toggle('d-none', !job.error_text);
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

    function formatFrequencyHz(value) {
        if (value == null) return '—';
        const frequencyHz = Number(value);
        if (!Number.isFinite(frequencyHz)) return '—';
        return `${(frequencyHz / 1_000_000).toFixed(3)} MHz`;
    }

    const ofdmChannelBandsPlugin = {
        id: 'rxmerOfdmChannelBands',
        beforeDatasetsDraw(chart, _args, options) {
            const spans = options && Array.isArray(options.spans) ? options.spans : [];
            const xScale = chart.scales.x;
            const area = chart.chartArea;
            if (!xScale || !area || !spans.length) return;
            const context = chart.ctx;
            context.save();
            context.beginPath();
            context.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
            context.clip();
            spans.forEach((span, index) => {
                const left = xScale.getPixelForValue(Number(span.start_frequency_hz) / 1_000_000);
                const right = xScale.getPixelForValue(Number(span.end_frequency_hz) / 1_000_000);
                const x = Math.min(left, right);
                const width = Math.max(1, Math.abs(right - left));
                context.fillStyle = index % 2
                    ? 'rgba(8, 145, 178, 0.055)'
                    : 'rgba(37, 99, 235, 0.055)';
                context.fillRect(x, area.top, width, area.bottom - area.top);
                context.strokeStyle = 'rgba(71, 85, 105, 0.18)';
                context.beginPath();
                context.moveTo(x, area.top);
                context.lineTo(x, area.bottom);
                context.stroke();
                if (width >= 48) {
                    context.save();
                    context.fillStyle = 'rgba(71, 85, 105, 0.72)';
                    context.font = '10px system-ui, sans-serif';
                    context.fillText(`OFDM ${span.channel_id}`, x + 4, area.top + 12);
                    context.restore();
                }
            });
            context.restore();
        },
    };

    function clearSpectrumPolling() {
        if (spectrumPollTimer) window.clearTimeout(spectrumPollTimer);
        spectrumPollTimer = null;
    }

    function destroySpectrumChart() {
        if (spectrumChart) spectrumChart.destroy();
        spectrumChart = null;
        byId('rxmer-spectrum-wrap').classList.add('d-none');
    }

    function setSpectrumStatus(message, kind = 'muted') {
        const status = byId('rxmer-spectrum-status');
        status.textContent = message;
        status.className = `small text-${kind} mb-2`;
    }

    function scheduleSpectrumPolling() {
        clearSpectrumPolling();
        spectrumPollTimer = window.setTimeout(() => loadSpectrum(), 3000);
    }

    function renderSpectrum(payload) {
        clearSpectrumPolling();
        const points = Array.isArray(payload.points) ? payload.points : [];
        if (!points.length) {
            destroySpectrumChart();
            setSpectrumStatus(payload.message || 'No successful channel vectors are available.');
            byId('rxmer-spectrum-rebuild').classList.remove('d-none');
            return;
        }
        if (!window.Chart) {
            destroySpectrumChart();
            setSpectrumStatus('Chart.js is unavailable; the spectrum cannot be rendered.', 'danger');
            return;
        }
        if (spectrumChart) spectrumChart.destroy();
        const toSeries = (key) => points.map((point) => ({
            x: Number(point.frequency_hz) / 1_000_000,
            y: point[key] == null ? null : Number(point[key]),
        }));
        const colors = window.PyPnmCharts?.colors || {
            blue: '#2563eb', green: '#198754', red: '#dc3545',
        };
        byId('rxmer-spectrum-wrap').classList.remove('d-none');
        spectrumChart = new Chart(byId('rxmer-spectrum-chart'), {
            type: 'line',
            plugins: [ofdmChannelBandsPlugin],
            data: {
                datasets: [
                    {label: 'Average RxMER', data: toSeries('average_db'), borderColor: colors.blue, backgroundColor: colors.blue, spanGaps: false},
                    {label: 'Maximum RxMER', data: toSeries('max_db'), borderColor: colors.green, backgroundColor: colors.green, spanGaps: false},
                    {label: 'Worst RxMER', data: toSeries('worst_db'), borderColor: colors.red, backgroundColor: colors.red, spanGaps: false},
                ],
            },
            options: {
                maintainAspectRatio: false,
                parsing: false,
                normalized: true,
                interaction: {mode: 'index', intersect: false},
                plugins: {
                    rxmerOfdmChannelBands: {spans: payload.channel_spans || []},
                    tooltip: {
                        callbacks: {
                            title: (items) => items.length ? `${Number(items[0].parsed.x).toFixed(3)} MHz` : '',
                            afterBody: (items) => {
                                if (!items.length) return '';
                                const point = points[items[0].dataIndex];
                                return `${Number(point.sample_count || 0).toLocaleString()} samples`;
                            },
                        },
                    },
                },
                scales: {
                    x: {type: 'linear', title: {display: true, text: 'Frequency (MHz)'}},
                    y: {title: {display: true, text: 'RxMER (dB)'}},
                },
            },
        });
        const omitted = Number(payload.span_groups_omitted || 0);
        const detail = omitted ? `; ${omitted} additional channel plan omitted` : '';
        setSpectrumStatus(
            `${Number(payload.source_modems || 0).toLocaleString()} modems, `
            + `${Number(payload.source_channels || 0).toLocaleString()} channels, `
            + `${points.length.toLocaleString()} plotted bins at ${formatFrequencyHz(payload.bin_width_hz)}${detail}.`,
        );
        byId('rxmer-spectrum-rebuild').classList.add('d-none');
    }

    async function loadSpectrum(forceBuild = false) {
        clearSpectrumPolling();
        const publicId = selectedJobId;
        if (!publicId) return;
        if (!terminalStates.has(selectedJobStatus)) {
            destroySpectrumChart();
            setSpectrumStatus('The spectrum can be built after collection stops.');
            byId('rxmer-spectrum-rebuild').classList.add('d-none');
            return;
        }
        try {
            if (forceBuild) {
                await request(`/jobs/${encodeURIComponent(publicId)}/spectrum/materialize`, {method: 'POST'});
            }
            const payload = await request(`/jobs/${encodeURIComponent(publicId)}/spectrum?max_points=1600`);
            if (publicId !== selectedJobId) return;
            if (payload.state === 'missing' || payload.state === 'stale') {
                destroySpectrumChart();
                setSpectrumStatus(`${payload.message || 'Spectrum profile is not available.'} Click Build spectrum.`);
                byId('rxmer-spectrum-rebuild').classList.remove('d-none');
                return;
            }
            if (payload.state === 'building') {
                destroySpectrumChart();
                setSpectrumStatus(payload.message || 'Building spectrum from stored RxMER vectors…', 'primary');
                byId('rxmer-spectrum-rebuild').classList.add('d-none');
                scheduleSpectrumPolling();
                return;
            }
            if (payload.state === 'failed') {
                destroySpectrumChart();
                setSpectrumStatus(payload.message || 'Spectrum build failed.', 'danger');
                byId('rxmer-spectrum-rebuild').classList.remove('d-none');
                return;
            }
            renderSpectrum(payload);
        } catch (error) {
            destroySpectrumChart();
            setSpectrumStatus(error.message, 'danger');
            byId('rxmer-spectrum-rebuild').classList.remove('d-none');
        }
    }

    function renderModems(targets) {
        const card = byId('rxmer-modems-card');
        const body = byId('rxmer-modems-body');
        body.replaceChildren();
        card.classList.remove('d-none');
        if (!targets.length) {
            const row = document.createElement('tr');
            const cell = textCell(row, 'No target rows available.', 'text-center text-muted py-3');
            cell.colSpan = 9;
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
            const frequencyCell = textCell(row, formatFrequencyHz(target.best_frequency_hz));
            if (target.best_frequency_hz != null && Number.isFinite(Number(target.best_frequency_hz))) {
                const subcarrier = target.best_subcarrier_index == null
                    ? ''
                    : `; subcarrier ${target.best_subcarrier_index}`;
                frequencyCell.title = `${Math.round(Number(target.best_frequency_hz))} Hz${subcarrier}`;
            }
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
            await loadSpectrum();
            schedulePolling(jobResponse.job.status);
        } catch (error) {
            showAlert(error.message);
        }
    }

    async function selectJob(publicId) {
        clearSpectrumPolling();
        destroySpectrumChart();
        selectedJobId = publicId;
        selectedJobStatus = null;
        progressPollCount = 0;
        setSpectrumStatus('Loading spectrum status…');
        clearAlert();
        await refreshSelectedJob();
        await loadJobs();
    }

    async function pollSelectedJob() {
        const publicId = selectedJobId;
        if (!publicId) return;
        try {
            progressPollCount += 1;
            if (progressPollCount % 5 === 0) {
                await refreshSelectedJob();
                await loadJobs();
                return;
            }
            const response = await request(`/jobs/${encodeURIComponent(publicId)}`);
            if (publicId !== selectedJobId) return;
            renderJob(response.job);
            if (terminalStates.has(response.job.status)) {
                await refreshSelectedJob();
                await loadJobs();
                return;
            }
            schedulePolling(response.job.status);
        } catch (error) {
            showAlert(error.message);
            schedulePolling(selectedJobStatus);
        }
    }

    function schedulePolling(status) {
        if (pollTimer) window.clearTimeout(pollTimer);
        pollTimer = null;
        if (!selectedJobId || terminalStates.has(status) || status === 'planned') return;
        pollTimer = window.setTimeout(pollSelectedJob, 2000);
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

    async function deleteJobResults(publicId) {
        if (!window.confirm(
            'Delete all collected RxMER results for this job? The 50,000-target plan will be retained and reset to planned. External PNM files are not deleted.'
        )) return;
        if (publicId === selectedJobId) {
            if (pollTimer) window.clearTimeout(pollTimer);
            pollTimer = null;
            clearSpectrumPolling();
        }
        try {
            const response = await request(`/jobs/${encodeURIComponent(publicId)}/results`, {method: 'DELETE'});
            showAlert(response.message || 'Collected results deleted.', 'success');
            if (publicId === selectedJobId) {
                destroySpectrumChart();
                await refreshSelectedJob();
            }
            await loadJobs();
        } catch (error) {
            showAlert(error.message);
        }
    }

    async function deleteAnalyticsJob(publicId) {
        if (!window.confirm(
            'Permanently delete this RxMER job, its plan, collected vectors, aggregates, and spectrum results? External PNM files are not deleted.'
        )) return;
        if (publicId === selectedJobId) {
            if (pollTimer) window.clearTimeout(pollTimer);
            pollTimer = null;
            clearSpectrumPolling();
        }
        try {
            const response = await request(`/jobs/${encodeURIComponent(publicId)}`, {method: 'DELETE'});
            if (publicId === selectedJobId) {
                selectedJobId = null;
                selectedJobStatus = null;
                destroySpectrumChart();
                byId('rxmer-detail-card').classList.add('d-none');
                byId('rxmer-modems-card').classList.add('d-none');
            }
            showAlert(response.message || 'RxMER job deleted.', 'success');
            await loadJobs();
        } catch (error) {
            showAlert(error.message);
        }
    }

    async function startSelectedJob() {
        if (!selectedJobId) return;
        const concurrency = Math.max(1, Math.min(20, Number(byId('rxmer-concurrency').value) || 10));
        byId('rxmer-concurrency').value = String(concurrency);
        if (!window.confirm(
            `Start network RxMER collection with ${concurrency} modems in parallel? This will contact every planned modem and capture downstream OFDM RxMER.`
        )) return;
        try {
            const response = await request(`/jobs/${encodeURIComponent(selectedJobId)}/start`, {
                method: 'POST',
                body: JSON.stringify({max_concurrency: concurrency}),
            });
            showAlert(response.message || 'Collection queued.', 'success');
            renderJob(response.job);
            schedulePolling(response.job.status);
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
            schedulePolling(response.job.status);
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
    byId('rxmer-spectrum-rebuild').addEventListener('click', () => loadSpectrum(true));
    window.addEventListener('pagehide', () => {
        if (pollTimer) window.clearTimeout(pollTimer);
        clearSpectrumPolling();
        if (spectrumChart) spectrumChart.destroy();
    });

    loadJobs();
})();