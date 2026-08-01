// Shared engineering presentation and PNG export for PyPNM charts and canvases.
(() => {
    if (window.PyPnmCharts) return;

    const colors = Object.freeze({
        text: '#212529', muted: '#6c757d', grid: 'rgba(108,117,125,0.16)',
        border: 'rgba(108,117,125,0.35)', blue: '#2563eb', cyan: '#0891b2',
        green: '#198754', orange: '#f59e0b', red: '#dc3545', purple: '#8b5cf6', gray: '#6b7280'
    });
    const seriesColors = Object.freeze([
        colors.blue, colors.red, colors.green, colors.orange, colors.purple,
        colors.cyan, '#d946ef', '#84cc16', '#0f766e', '#9f1239'
    ]);
    const safeName = value => String(value || 'pypnm-chart').toLowerCase()
        .replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'pypnm-chart';
    const saveBlob = (blob, name) => {
        if (!blob) return;
        const link = document.createElement('a');
        link.download = `${safeName(name)}.png`;
        link.href = URL.createObjectURL(blob);
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    };
    const downloadPng = (canvas, name) => {
        if (!canvas) return;
        const output = document.createElement('canvas');
        output.width = canvas.width;
        output.height = canvas.height;
        const context = output.getContext('2d');
        context.fillStyle = '#fff';
        context.fillRect(0, 0, output.width, output.height);
        context.drawImage(canvas, 0, 0);
        output.toBlob(blob => saveBlob(blob, name), 'image/png');
    };
    const downloadBase64Png = (data, name) => {
        if (!data) return;
        const source = data.startsWith?.('data:') ? data : `data:image/png;base64,${data}`;
        fetch(source).then(response => response.blob()).then(blob => saveBlob(blob, name));
    };
    const normalizeOptions = options => {
        options.responsive = true;
        options.animation = false;
        options.interaction = { mode: 'nearest', intersect: false, ...(options.interaction || {}) };
        options.plugins = options.plugins || {};
        const title = options.plugins.title || {};
        options.plugins.title = { ...title, color: colors.text, font: { size: 14, weight: '600', ...(title.font || {}) }, padding: { top: 4, bottom: 12 } };
        const legend = options.plugins.legend || {};
        options.plugins.legend = { ...legend, labels: { usePointStyle: true, boxWidth: 10, boxHeight: 10, color: colors.text, padding: 14, ...(legend.labels || {}) } };
        const tooltip = options.plugins.tooltip || {};
        options.plugins.tooltip = { ...tooltip, backgroundColor: 'rgba(33,37,41,0.94)', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 4 };
        Object.values(options.scales || {}).forEach(scale => {
            scale.grid = { ...(scale.grid || {}), color: colors.grid };
            scale.border = { ...(scale.border || {}), color: colors.border };
            scale.ticks = { ...(scale.ticks || {}), color: colors.muted, padding: 6 };
            if (scale.title) scale.title = { ...scale.title, color: colors.text, font: { ...(scale.title.font || {}), size: 12, weight: '600' } };
        });
    };
    const attachButton = chart => {
        const canvas = chart.canvas;
        if (!canvas?.parentElement || chart.$pypnmDownload || canvas.dataset.noAutoExport === 'true') return;
        const parent = canvas.parentElement;
        if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
        const toolbar = document.createElement('div');
        toolbar.className = 'pypnm-chart-actions';
        toolbar.style.cssText = 'position:absolute;top:.25rem;right:.35rem;z-index:5';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-secondary';
        button.style.cssText = 'padding:.12rem .4rem;font-size:.72rem;line-height:1.25;background:#fff;color:#6c757d;border:1px solid #6c757d';
        button.innerHTML = '<i class="bi bi-download me-1"></i>PNG';
        button.title = 'Download chart as PNG';
        button.addEventListener('click', () => downloadPng(canvas, canvas.id || chart.options.plugins?.title?.text));
        toolbar.appendChild(button);
        parent.appendChild(toolbar);
        chart.$pypnmDownload = toolbar;
    };

    window.PyPnmCharts = Object.freeze({ colors, seriesColors, safeName, downloadPng, downloadBase64Png });
    if (!window.Chart) return;
    Chart.defaults.color = colors.text;
    Chart.defaults.font.family = 'system-ui,-apple-system,"Segoe UI",sans-serif';
    Chart.defaults.font.size = 12;
    Chart.defaults.animation = false;
    Chart.defaults.elements.line.borderWidth = 1;
    Chart.defaults.elements.point.radius = 0;
    Chart.defaults.scale.grid.color = colors.grid;
    Chart.defaults.scale.border.color = colors.border;
    Chart.defaults.scale.ticks.color = colors.muted;
    Chart.register({
        id: 'pypnmEngineeringTheme',
        beforeInit: chart => normalizeOptions(chart.config.options || {}),
        afterInit: chart => queueMicrotask(() => attachButton(chart)),
        afterDestroy: chart => chart.$pypnmDownload?.remove()
    });
})();