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
let detailSpotlight = null;
let selectedDetailElement = null;
let selectionToast = null;

function ensureDetailPanel() {
    if (detailOverlay && detailPanel && detailSpotlight) return { overlay: detailOverlay, panel: detailPanel, spotlight: detailSpotlight };

    detailOverlay = document.createElement('div');
    detailOverlay.className = 'detail-overlay';
    detailOverlay.setAttribute('aria-hidden', 'true');

    detailSpotlight = document.createElement('section');
    detailSpotlight.className = 'detail-spotlight';
    detailSpotlight.setAttribute('aria-hidden', 'true');
    detailSpotlight.innerHTML = `
        <div class="spotlight-kicker">Análise do item selecionado</div>
        <div class="spotlight-head">
            <div>
                <h2 class="spotlight-title">Gráfico detalhado</h2>
                <p class="spotlight-body">Clique em qualquer elemento do dashboard para atualizar esta visualização.</p>
            </div>
            <span class="spotlight-status">Análise</span>
        </div>
        <div class="detail-visual spotlight-visual" aria-label="Animação visual ampliada do item selecionado">
            <div class="detail-visual-head">
                <span>Composição visual</span>
                <strong class="detail-visual-total">--</strong>
            </div>
            <div class="detail-visual-stage">
                <div class="detail-visual-bars"></div>
                <div class="detail-line-wrap">
                    <svg class="detail-visual-line" viewBox="0 0 220 82" preserveAspectRatio="none">
                        <path class="detail-visual-area" d=""></path>
                        <polyline class="detail-visual-path" points=""></polyline>
                    </svg>
                    <div class="detail-visual-points"></div>
                </div>
                <div class="detail-visual-donut" data-tooltip="Indicador: 0%"><span>0%</span></div>
            </div>
            <div class="detail-visual-caption">Esta área mostra o gráfico animado do item que você clicou.</div>
        </div>
    `;

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
    document.body.appendChild(detailSpotlight);
    document.body.appendChild(detailPanel);

    detailOverlay.addEventListener('click', closeDetailPanel);
    detailPanel.querySelector('.detail-close').addEventListener('click', closeDetailPanel);
    detailPanel.querySelector('.detail-copy').addEventListener('click', copyCurrentDetailSummary);

    return { overlay: detailOverlay, panel: detailPanel, spotlight: detailSpotlight };
}

function closeDetailPanel() {
    if (!detailOverlay || !detailPanel) return;
    detailOverlay.classList.remove('is-open');
    detailPanel.classList.remove('is-open');
    if (detailSpotlight) {
        detailSpotlight.classList.remove('is-open');
        detailSpotlight.setAttribute('aria-hidden', 'true');
    }
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

function parseBrazilianNumber(raw) {
    const text = String(raw || '').trim();
    if (!text) return null;

    const multiplier = /[0-9.,]\s*K\b/i.test(text) ? 1000 : /[0-9.,]\s*M\b/i.test(text) ? 1000000 : 1;
    const cleaned = text
        .replace(/R\$/gi, '')
        .replace(/%/g, '')
        .replace(/\s/g, '')
        .replace(/\./g, '')
        .replace(',', '.')
        .replace(/[^0-9.\-+]/g, '');

    if (!cleaned || cleaned === '-' || cleaned === '+') return null;
    const value = Number(cleaned) * multiplier;
    return Number.isFinite(value) ? value : null;
}

function extractNumbersFromText(text, options = {}) {
    const matches = String(text || '').match(/[-+]?R?\$?\s*[0-9.]+(?:,[0-9]+)?\s*[KM]?|[-+]?[0-9]+(?:,[0-9]+)?%?/gi) || [];
    return matches.map((raw) => {
        const value = parseBrazilianNumber(raw);
        if (!Number.isFinite(value)) return 0;
        return options.absolute ? Math.abs(value) : value;
    }).filter((value) => Number.isFinite(value) && value !== 0);
}

function uniqueVisualValues(values) {
    const seen = new Set();
    return values.filter((value) => {
        const key = Math.round(Math.abs(value) * 100) / 100;
        if (!Number.isFinite(key) || key <= 0 || seen.has(key)) return false;
        seen.add(key);
        return true;
    });
}

function firstValueMatching(text, pattern) {
    const match = String(text || '').match(pattern);
    return match ? parseBrazilianNumber(match[0]) : null;
}

function getPrimaryVisualValue(element) {
    // Prioridade 1: métricas detalhadas. Em linhas/tabelas, evita pegar números
    // da descrição ou da posição da linha antes do valor de divergência.
    const metrics = String(element.dataset.detailMetrics || '')
        .split('|')
        .map(metricFromPart)
        .filter(Boolean);
    for (const metric of metrics) {
        if (/R\$|%|valor|saldo|total|índice|indice|score/i.test(`${metric.label} ${metric.value}`)) {
            const value = parseBrazilianNumber(metric.value);
            if (Number.isFinite(value)) return value;
        }
    }

    const source = [element.dataset.tooltip, element.dataset.detail, element.textContent].filter(Boolean).join(' • ');

    // Prioridade 2: primeiro valor monetário explícito. Corrige o caso do card
    // "Divergência líquida", que repetia o mesmo R$ no tooltip e no card.
    const currencyValue = firstValueMatching(source, /[-+]?R\$\s*[0-9.]+(?:,[0-9]+)?/i);
    if (Number.isFinite(currencyValue)) return currencyValue;

    // Prioridade 3: valor principal visível no componente, quando não há R$.
    const primaryNode = element.querySelector(':scope > strong, .rank-value, .bar-value, .gauge-center strong, .summary-metric strong');
    const primaryValue = parseBrazilianNumber(primaryNode?.textContent);
    if (Number.isFinite(primaryValue)) return primaryValue;

    // Prioridade 4: percentual explícito, útil para score, acuracidade e índice.
    const percentValue = firstValueMatching(source, /[-+]?[0-9]+(?:,[0-9]+)?%/);
    if (Number.isFinite(percentValue)) return percentValue;

    // Prioridade 5: primeiro número encontrado no tooltip ou no texto de detalhe.
    const values = extractNumbersFromText(source);
    return values.length ? values[0] : null;
}

function buildDetailVisualData(element) {
    const source = [
        element.dataset.detailTitle,
        element.dataset.detail,
        element.dataset.tooltip,
        element.dataset.detailMetrics,
        element.textContent,
    ].filter(Boolean).join(' • ');

    const primaryValue = getPrimaryVisualValue(element);
    let values = uniqueVisualValues(extractNumbersFromText(source, { absolute: true })).slice(0, 7);

    // Quando o item clicado tem um valor principal claro, use somente esse valor
    // como base do gráfico ampliado. Assim "Divergência líquida" mostra o saldo
    // líquido real, e não a soma duplicada entre tooltip + card + textos auxiliares.
    if (Number.isFinite(primaryValue)) {
        values = [Math.abs(primaryValue)];
    }

    if (!values.length) values = [18, 34, 52, 46, 72, 64, 88];
    if (values.length === 1) {
        const base = values[0];
        values = [base * .22, base * .48, base * .7, base, base * .58, base * .86];
    }
    while (values.length < 5) {
        const last = values[values.length - 1] || 10;
        values.push(Math.max(4, last * (0.72 + values.length * 0.08)));
    }

    const max = Math.max(...values, 1);
    const visualTotal = Number.isFinite(primaryValue) ? primaryValue : values.reduce((sum, value) => sum + value, 0);
    const first = values[0] || 0;
    const last = values[values.length - 1] || 0;
    const intensity = Math.max(6, Math.min(94, Math.round((Math.abs(visualTotal) / max) * 100)));
    const status = inferStatus(element);
    return { values, max, total: visualTotal, first, last, intensity, status };
}

function formatCompactVisualValue(value) {
    if (!Number.isFinite(value)) return '--';
    const sign = value < 0 ? '-' : '';
    const absValue = Math.abs(value);
    if (absValue >= 1000000) return `${sign}R$ ${(absValue / 1000000).toFixed(1).replace('.', ',')}M`;
    if (absValue >= 1000) return `${sign}R$ ${(absValue / 1000).toFixed(1).replace('.', ',')}K`;
    return `${sign}${String(Math.round(absValue)).replace('.', ',')}`;
}

function renderDetailVisual(element, panel) {
    const visual = panel.querySelector('.detail-visual');
    if (!visual) return;

    const { values, max, total, intensity, status } = buildDetailVisualData(element);
    const bars = visual.querySelector('.detail-visual-bars');
    const totalNode = visual.querySelector('.detail-visual-total');
    const pathNode = visual.querySelector('.detail-visual-path');
    const areaNode = visual.querySelector('.detail-visual-area');
    const pointsNode = visual.querySelector('.detail-visual-points');
    const donut = visual.querySelector('.detail-visual-donut');
    const donutLabel = donut?.querySelector('span');

    visual.classList.remove('is-positive', 'is-negative', 'is-neutral', 'is-animating');
    visual.classList.add(status === 'Positivo' ? 'is-positive' : status === 'Atenção' ? 'is-negative' : 'is-neutral');
    void visual.offsetWidth;
    visual.classList.add('is-animating');

    totalNode.textContent = formatCompactVisualValue(total);
    bars.innerHTML = values.map((value, index) => {
        const height = Math.max(12, Math.round((value / max) * 100));
        const label = `Barra ${index + 1}: ${formatCompactVisualValue(value)}`;
        return `<i tabindex="0" role="button" class="detail-visual-bar-point" data-tooltip="${escapeHtml(label)}" data-detail-title="${escapeHtml(label)}" data-detail="Barra ${index + 1} da composição visual. Valor: ${escapeHtml(formatCompactVisualValue(value))}. Clique para ver esta parte isolada no painel de informações." data-detail-metrics="Elemento:Barra ${index + 1}|Valor:${escapeHtml(formatCompactVisualValue(value))}|Participação:${Math.round((value / Math.max(Math.abs(total), 1)) * 100)}%|Contexto:${escapeHtml(inferDetailTitle(element))}" style="--h:${height}%; --delay:${index * 70}ms"></i>`;
    }).join('');

    const width = 220;
    const height = 82;
    const pad = 8;
    const coordinates = values.map((value, index) => {
        const x = pad + index * ((width - pad * 2) / Math.max(values.length - 1, 1));
        const y = height - pad - (value / max) * (height - pad * 2);
        return { x, y, value, index };
    });
    const points = coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ');
    const area = `M${points.split(' ')[0]} L${points.split(' ').slice(1).join(' L')} L${width - pad},${height - pad} L${pad},${height - pad} Z`;
    pathNode.setAttribute('points', points);
    areaNode.setAttribute('d', area);

    if (pointsNode) {
        pointsNode.innerHTML = coordinates.map((point) => {
            const left = (point.x / width) * 100;
            const top = (point.y / height) * 100;
            const label = `Ponto ${point.index + 1}: ${formatCompactVisualValue(point.value)}`;
            return `<button type="button" class="detail-visual-point" style="--x:${left}%; --y:${top}%; --delay:${point.index * 85}ms" data-tooltip="${escapeHtml(label)}" data-detail-title="${escapeHtml(label)}" data-detail="Ponto ${point.index + 1} da linha animada. Valor: ${escapeHtml(formatCompactVisualValue(point.value))}. Este ponto ajuda a comparar a evolução visual do item selecionado." data-detail-metrics="Elemento:Ponto ${point.index + 1}|Valor:${escapeHtml(formatCompactVisualValue(point.value))}|Percentual:${Math.round((point.value / max) * 100)}%|Contexto:${escapeHtml(inferDetailTitle(element))}"></button>`;
        }).join('');
    }

    if (donut) {
        donut.style.setProperty('--value', `${intensity}%`);
        donut.setAttribute('data-tooltip', `Indicador circular: ${intensity}%`);
        donut.setAttribute('data-detail-title', `Indicador circular ${intensity}%`);
        donut.setAttribute('data-detail', `Indicador circular do item selecionado. Percentual calculado: ${intensity}%. Clique para manter este indicador no painel lateral.`);
        donut.setAttribute('data-detail-metrics', `Elemento:Indicador circular|Percentual:${intensity}%|Total visual:${formatCompactVisualValue(total)}|Contexto:${inferDetailTitle(element)}`);
        if (donutLabel) donutLabel.textContent = `${intensity}%`;
    }
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
    const { overlay, panel, spotlight } = ensureDetailPanel();
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
    renderDetailVisual(element, panel);

    if (spotlight) {
        spotlight.querySelector('.spotlight-title').textContent = title;
        spotlight.querySelector('.spotlight-body').textContent = body;
        const statusNode = spotlight.querySelector('.spotlight-status');
        statusNode.textContent = status;
        statusNode.className = `spotlight-status ${status === 'Atenção' ? 'is-negative' : status === 'Positivo' ? 'is-positive' : ''}`;
        renderDetailVisual(element, spotlight);
    }

    const detailsUrl = document.querySelector('a[href*="detalhes"]')?.getAttribute('href');
    const tableLink = panel.querySelector('.detail-open-table');
    if (detailsUrl) tableLink.setAttribute('href', detailsUrl);

    overlay.classList.add('is-open');
    panel.classList.add('is-open');
    if (spotlight) {
        spotlight.classList.add('is-open');
        spotlight.setAttribute('aria-hidden', 'false');
    }
    overlay.setAttribute('aria-hidden', 'false');
    showSelectionToast('Detalhes abertos');
}

document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-tooltip]');
    if (!target) return;

    const ignored = event.target.closest('a, button, input, label, select, textarea');
    const isInteractiveChartPoint = target.matches('.trend-point, .evo-point, .mini-bar-item, .impact-strip-row, .chart-hover, .hover-info, .detail-visual-point, .detail-visual-bar-point, .detail-visual-donut') || target.closest('.detail-visual-bars');
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

// Abas da página de divergências: Visão Geral / Por Categoria / Por Fornecedor.
function initDivergenceTabs() {
    const shell = document.querySelector('.divergence-reference-shell');
    if (!shell) return;

    const buttons = Array.from(shell.querySelectorAll('[data-divergence-tab]'));
    const panels = Array.from(shell.querySelectorAll('[data-divergence-panel]'));
    if (!buttons.length || !panels.length) return;

    buttons.forEach((button) => {
        button.addEventListener('click', () => {
            const selectedTab = button.dataset.divergenceTab;

            buttons.forEach((item) => {
                const isActive = item.dataset.divergenceTab === selectedTab;
                item.classList.toggle('active', isActive);
                item.setAttribute('aria-selected', isActive ? 'true' : 'false');
            });

            panels.forEach((panel) => {
                const isActive = panel.dataset.divergencePanel === selectedTab;
                panel.hidden = !isActive;
                panel.classList.toggle('is-active', isActive);
            });

            if (typeof hideDashboardTooltip === 'function') hideDashboardTooltip();
        });
    });
}

initDivergenceTabs();
