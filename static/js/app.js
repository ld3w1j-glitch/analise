const fileInput = document.querySelector('#file');
const fileName = document.querySelector('#file-name');
const dropZones = document.querySelectorAll('.drop-zone, .reference-drop-zone');

function setFileName() {
    if (!fileInput || !fileName) return;
    if (fileInput.files.length) {
        fileName.textContent = fileInput.files[0].name;
    } else if (fileName.textContent.trim() === '') {
        fileName.textContent = 'Nenhum arquivo selecionado';
    }
}

if (fileInput && fileName) {
    fileInput.addEventListener('change', setFileName);
}

dropZones.forEach((zone) => {
    ['dragenter', 'dragover'].forEach((eventName) => {
        zone.addEventListener(eventName, (event) => {
            event.preventDefault();
            zone.classList.add('is-dragover');
        });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        zone.addEventListener(eventName, (event) => {
            event.preventDefault();
            zone.classList.remove('is-dragover');
        });
    });

    zone.addEventListener('drop', (event) => {
        const files = event.dataTransfer.files;
        if (files.length && fileInput) {
            fileInput.files = files;
            setFileName();
        }
    });
});

// Tooltip premium com delegação de eventos.
// Corrige páginas novas: qualquer elemento com data-tooltip passa a funcionar,
// mesmo quando o layout muda ou o elemento está dentro de SVG/containers.
let dashboardTooltip = null;
let activeTooltipElement = null;

function ensureDashboardTooltip() {
    if (!dashboardTooltip) {
        dashboardTooltip = document.createElement('div');
        dashboardTooltip.className = 'chart-tooltip';
        dashboardTooltip.setAttribute('role', 'tooltip');
        document.body.appendChild(dashboardTooltip);
    }
    return dashboardTooltip;
}

function moveDashboardTooltip(event) {
    const tip = ensureDashboardTooltip();
    const offset = 18;
    const margin = 12;
    const tooltipWidth = Math.min(280, window.innerWidth - margin * 2);

    let left = event.clientX;
    let top = event.clientY - offset;

    if (left < margin + tooltipWidth / 2) {
        left = margin + tooltipWidth / 2;
    }
    if (left > window.innerWidth - margin - tooltipWidth / 2) {
        left = window.innerWidth - margin - tooltipWidth / 2;
    }
    if (top < 80) {
        top = event.clientY + 58;
    }

    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
}

function showDashboardTooltip(element, event) {
    const text = element.getAttribute('data-tooltip');
    if (!text) return;

    const tip = ensureDashboardTooltip();
    activeTooltipElement = element;
    tip.textContent = text;
    moveDashboardTooltip(event);
    tip.classList.add('is-visible');
    element.classList.add('is-tooltip-active');
}

function hideDashboardTooltip() {
    if (dashboardTooltip) dashboardTooltip.classList.remove('is-visible');
    if (activeTooltipElement) activeTooltipElement.classList.remove('is-tooltip-active');
    activeTooltipElement = null;
}

document.addEventListener('pointermove', (event) => {
    const target = event.target.closest('[data-tooltip]');
    if (!target) {
        hideDashboardTooltip();
        return;
    }
    showDashboardTooltip(target, event);
});

document.addEventListener('pointerdown', hideDashboardTooltip);
document.addEventListener('scroll', hideDashboardTooltip, true);
window.addEventListener('blur', hideDashboardTooltip);

// Acessibilidade: mostra tooltip também ao navegar com TAB.
document.addEventListener('focusin', (event) => {
    const target = event.target.closest('[data-tooltip]');
    if (!target) return;
    const rect = target.getBoundingClientRect();
    showDashboardTooltip(target, {
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
    });
});

document.addEventListener('focusout', (event) => {
    if (event.target.closest('[data-tooltip]')) hideDashboardTooltip();
});

// Painel de detalhes ao clicar nos gráficos/cards.
// Qualquer item com data-tooltip pode abrir um painel com mais informações.
let detailOverlay = null;
let detailPanel = null;
let selectedDetailElement = null;
let selectionToast = null;

function ensureDetailPanel() {
    if (detailOverlay && detailPanel) return { overlay: detailOverlay, panel: detailPanel };

    detailOverlay = document.createElement('div');
    detailOverlay.className = 'detail-overlay';
    detailOverlay.setAttribute('aria-hidden', 'true');

    detailPanel = document.createElement('section');
    detailPanel.className = 'detail-panel';
    detailPanel.setAttribute('role', 'dialog');
    detailPanel.setAttribute('aria-modal', 'true');
    detailPanel.innerHTML = `
        <button class="detail-close" type="button" aria-label="Fechar detalhes">×</button>
        <div class="detail-top">
            <div>
                <div class="detail-kicker">Item selecionado</div>
                <h2 class="detail-title">Detalhes</h2>
            </div>
            <span class="detail-status">Análise</span>
        </div>
        <p class="detail-body"></p>
        <div class="detail-grid"></div>
        <div class="detail-related">
            <strong>Leitura recomendada</strong>
            <ul class="detail-related-list"></ul>
        </div>
        <div class="detail-actions">
            <button class="detail-copy" type="button">Copiar resumo</button>
            <a class="detail-open-table" href="#">Ver tabela</a>
        </div>
        <div class="detail-help">Dica: clique em barras, pontos, cards ou linhas para trocar rapidamente o item detalhado.</div>
    `;

    document.body.appendChild(detailOverlay);
    document.body.appendChild(detailPanel);

    detailOverlay.addEventListener('click', closeDetailPanel);
    detailPanel.querySelector('.detail-close').addEventListener('click', closeDetailPanel);
    detailPanel.querySelector('.detail-copy').addEventListener('click', copyCurrentDetailSummary);

    return { overlay: detailOverlay, panel: detailPanel };
}

function closeDetailPanel() {
    if (!detailOverlay || !detailPanel) return;
    detailOverlay.classList.remove('is-open');
    detailPanel.classList.remove('is-open');
    detailOverlay.setAttribute('aria-hidden', 'true');
    if (selectedDetailElement) selectedDetailElement.classList.remove('is-selected-detail');
    selectedDetailElement = null;
}

function inferDetailTitle(element) {
    if (element.dataset.detailTitle) return element.dataset.detailTitle;
    const titleNode = element.querySelector('h2, h3, strong, .kpi-label, .panel-label');
    if (titleNode && titleNode.textContent.trim()) return titleNode.textContent.trim();
    if (element.getAttribute('aria-label')) return element.getAttribute('aria-label');
    return 'Detalhes do item selecionado';
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function metricFromPart(part) {
    const index = part.indexOf(':');
    if (index === -1) return null;
    const label = part.slice(0, index).trim();
    const value = part.slice(index + 1).trim();
    if (!label || !value) return null;
    return { label, value };
}

function buildDetailGrid(element) {
    const raw = element.dataset.detailMetrics || '';
    if (raw.trim()) {
        return raw.split('|').map(metricFromPart).filter(Boolean).map((metric) => {
            return `<div class="detail-metric"><span>${escapeHtml(metric.label)}</span><strong>${escapeHtml(metric.value)}</strong></div>`;
        }).join('');
    }

    const tooltip = element.dataset.tooltip || '';
    const parts = tooltip.split('•').map((v) => v.trim()).filter(Boolean);
    if (parts.length > 1) {
        return parts.map((part, index) => `<div class="detail-metric"><span>${index === 0 ? 'Item' : 'Informação ' + index}</span><strong>${escapeHtml(part)}</strong></div>`).join('');
    }

    return `
        <div class="detail-metric"><span>Tipo</span><strong>Análise visual</strong></div>
        <div class="detail-metric"><span>Ação</span><strong>Selecionar e detalhar</strong></div>
    `;
}

function inferStatus(element) {
    const statusText = (element.dataset.tooltip || element.dataset.detailMetrics || '').toLowerCase();
    if (element.classList.contains('negativo') || statusText.includes('negativ') || statusText.includes('falta') || statusText.includes('perda')) return 'Atenção';
    if (element.classList.contains('positivo') || statusText.includes('positiv') || statusText.includes('sobra') || statusText.includes('ganho')) return 'Positivo';
    return 'Análise';
}

function buildRelatedList(element) {
    const status = inferStatus(element);
    const base = [];
    if (status === 'Atenção') {
        base.push('Priorize os maiores valores negativos no ranking por impacto.');
        base.push('Compare o período selecionado com os meses anteriores.');
        base.push('Abra Detalhes & Exportação para conferir a linha completa.');
    } else if (status === 'Positivo') {
        base.push('Verifique se a sobra/ganho está ligada a ajuste ou lançamento duplicado.');
        base.push('Compare com o resumo positivo e com o saldo líquido.');
        base.push('Use a exportação para compartilhar a lista com a equipe.');
    } else {
        base.push('Use esta seleção para interpretar o comportamento geral.');
        base.push('Clique em outro ponto ou barra para trocar o contexto.');
        base.push('Acesse a tabela para conferir os registros originais.');
    }
    return base.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
}

function copyCurrentDetailSummary() {
    if (!detailPanel) return;
    const title = detailPanel.querySelector('.detail-title')?.textContent || '';
    const body = detailPanel.querySelector('.detail-body')?.textContent || '';
    const metrics = Array.from(detailPanel.querySelectorAll('.detail-metric')).map((metric) => {
        const label = metric.querySelector('span')?.textContent || '';
        const value = metric.querySelector('strong')?.textContent || '';
        return `${label}: ${value}`;
    });
    const text = [title, body, ...metrics].filter(Boolean).join('\n');
    navigator.clipboard?.writeText(text).then(() => showSelectionToast('Resumo copiado')).catch(() => showSelectionToast('Resumo selecionado'));
}

function showSelectionToast(message) {
    if (!selectionToast) {
        selectionToast = document.createElement('div');
        selectionToast.className = 'selection-toast';
        document.body.appendChild(selectionToast);
    }
    selectionToast.textContent = message;
    selectionToast.classList.add('is-visible');
    clearTimeout(selectionToast._timer);
    selectionToast._timer = setTimeout(() => selectionToast.classList.remove('is-visible'), 1800);
}

function openDetailPanel(element) {
    const { overlay, panel } = ensureDetailPanel();
    const title = inferDetailTitle(element);
    const body = element.dataset.detail || element.dataset.tooltip || 'Informações relacionadas ao item selecionado.';
    const grid = buildDetailGrid(element);
    const status = inferStatus(element);

    if (selectedDetailElement && selectedDetailElement !== element) selectedDetailElement.classList.remove('is-selected-detail');
    selectedDetailElement = element;
    selectedDetailElement.classList.add('is-selected-detail');

    panel.querySelector('.detail-title').textContent = title;
    panel.querySelector('.detail-body').textContent = body;
    panel.querySelector('.detail-grid').innerHTML = grid;
    panel.querySelector('.detail-status').textContent = status;
    panel.querySelector('.detail-status').className = `detail-status ${status === 'Atenção' ? 'is-negative' : status === 'Positivo' ? 'is-positive' : ''}`;
    panel.querySelector('.detail-related-list').innerHTML = buildRelatedList(element);

    const detailsUrl = document.querySelector('a[href*="detalhes"]')?.getAttribute('href');
    const tableLink = panel.querySelector('.detail-open-table');
    if (detailsUrl) tableLink.setAttribute('href', detailsUrl);

    overlay.classList.add('is-open');
    panel.classList.add('is-open');
    overlay.setAttribute('aria-hidden', 'false');
    showSelectionToast('Detalhes abertos');
}

document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-tooltip]');
    if (!target) return;

    const ignored = event.target.closest('a, button, input, label, select, textarea');
    const isInteractiveChartPoint = target.matches('.trend-point, .evo-point, .mini-bar-item, .impact-strip-row, .chart-hover, .hover-info');
    if (ignored && !isInteractiveChartPoint) return;

    event.preventDefault();
    openDetailPanel(target);
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDetailPanel();
    if ((event.key === 'Enter' || event.key === ' ') && document.activeElement?.matches?.('[data-tooltip]')) {
        event.preventDefault();
        openDetailPanel(document.activeElement);
    }
});
