/**
 * app.js - Frontend logic for Inspecciones Predictivas Dashboard
 * 
 * Handles:
 *  - Plan generation & display
 *  - KPI auto-refresh
 *  - Gantt chart rendering
 *  - OT table with pagination
 *  - Simulation panel (new OT, absences, log)
 *  - Status updates & modal detail
 */

// ═══════════════════════════════════════
// STATE
// ═══════════════════════════════════════
let currentPage = 1;
const perPage = 20;
let logEntries = [];
let kpiInterval = null;

// ═══════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════

function getGrupo() {
    return document.getElementById('grupo-select').value;
}

function getFechaInicio() {
    return document.getElementById('semana-input').value;
}

function getFechaFin() {
    const start = new Date(getFechaInicio());
    start.setDate(start.getDate() + 6);
    return start.toISOString().split('T')[0];
}

function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function addLog(msg) {
    const now = new Date();
    const time = now.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' });
    logEntries.unshift({ time, msg });
    if (logEntries.length > 10) logEntries.pop();
    renderLog();
}

function renderLog() {
    const list = document.getElementById('log-list');
    if (logEntries.length === 0) {
        list.innerHTML = '<div class="log-entry">Sin actividad reciente</div>';
        return;
    }
    list.innerHTML = logEntries.map(e =>
        `<div class="log-entry"><span class="log-time">${e.time}</span>${e.msg}</div>`
    ).join('');
}

async function apiFetch(url, options = {}) {
    try {
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `Error ${res.status}`);
        }
        return await res.json();
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}

// ═══════════════════════════════════════
// PLAN GENERATION
// ═══════════════════════════════════════

async function generarPlan() {
    const btn = document.getElementById('btn-generar');
    btn.disabled = true;
    btn.textContent = 'Generando...';

    try {
        const data = await apiFetch('/api/generar-plan', {
            method: 'POST',
            body: JSON.stringify({
                grupo: getGrupo(),
                fecha_inicio: getFechaInicio(),
                fecha_fin: getFechaFin(),
            }),
        });

        showToast(`Plan generado: ${data.total_asignadas} OTs asignadas, ${data.total_pendientes} pendientes`, 'success');
        addLog(`Plan generado para ${getGrupo()}: ${data.total_asignadas} asignadas`);

        // Refresh all sections
        await Promise.all([loadKPIs(), loadGantt(), loadOrdenes()]);
    } catch (e) {
        // error already shown by apiFetch
    } finally {
        btn.disabled = false;
        btn.textContent = '\u26A1 Generar Plan';
    }
}

async function resetData() {
    if (!confirm('Esto borrara todas las asignaciones. Continuar?')) return;

    try {
        await apiFetch('/api/reset', { method: 'DELETE' });
        showToast('Datos reseteados', 'info');
        addLog('Reset completo');
        await Promise.all([loadKPIs(), loadGantt(), loadOrdenes()]);
    } catch (e) { }
}

// ═══════════════════════════════════════
// KPIs
// ═══════════════════════════════════════

async function loadKPIs() {
    try {
        const params = new URLSearchParams({
            grupo: getGrupo(),
            fecha_inicio: getFechaInicio(),
            fecha_fin: getFechaFin(),
        });
        const data = await apiFetch(`/api/indicadores?${params}`);

        document.getElementById('kpi-total-val').textContent = data.total_ots;
        document.getElementById('kpi-cumpl-val').textContent = data.cumplimiento_pct + '%';
        document.getElementById('kpi-cumpl-bar').style.width = data.cumplimiento_pct + '%';
        document.getElementById('kpi-pend-val').textContent = data.pendientes_backlog;
        document.getElementById('kpi-util-val').textContent = data.utilizacion_promedio_pct + '%';
        document.getElementById('kpi-util-bar').style.width = data.utilizacion_promedio_pct + '%';
        document.getElementById('kpi-trasl-val').textContent = data.tiempo_traslados_horas + ' h';

        // Color pendientes orange if > 0
        const pendCard = document.getElementById('kpi-pendientes');
        if (data.pendientes_backlog > 0) {
            pendCard.style.borderColor = 'rgba(249,115,22,0.5)';
        } else {
            pendCard.style.borderColor = '';
        }
    } catch (e) { }
}

// ═══════════════════════════════════════
// GANTT CHART
// ═══════════════════════════════════════

async function loadGantt() {
    const container = document.getElementById('gantt-container');

    try {
        const params = new URLSearchParams({
            grupo: getGrupo(),
            fecha_inicio: getFechaInicio(),
            fecha_fin: getFechaFin(),
        });
        const data = await apiFetch(`/api/plan-semanal?${params}`);

        if (!data.tecnicos || Object.keys(data.tecnicos).length === 0) {
            container.innerHTML = '<div class="gantt-placeholder">No hay tecnicos en este grupo o no hay plan generado</div>';
            return;
        }

        // Build dates array
        const dates = [];
        let d = new Date(data.fecha_inicio);
        const end = new Date(data.fecha_fin);
        while (d <= end) {
            dates.push(d.toISOString().split('T')[0]);
            d.setDate(d.getDate() + 1);
        }

        const dayNames = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab'];

        // Build table
        let html = '<table class="gantt-table"><thead><tr><th>Tecnico</th>';
        for (const date of dates) {
            const dt = new Date(date + 'T12:00:00');
            const dayName = dayNames[dt.getDay()];
            const dayNum = dt.getDate();
            const turno = data.calendario[date] || 'Descanso';
            const turnoClass = turno === 'Dia' ? 'turno-dia' : turno === 'Noche' ? 'turno-noche' : 'turno-descanso';
            const turnoLabel = turno === 'Dia' ? '☀️' : turno === 'Noche' ? '🌙' : '💤';
            html += `<th class="${turnoClass}">${dayName} ${dayNum}<br>${turnoLabel} ${turno}</th>`;
        }
        html += '</tr></thead><tbody>';

        // Rows per technician
        for (const [tid, tdata] of Object.entries(data.tecnicos)) {
            html += `<tr><td class="gantt-tech-name">${tdata.nombre}</td>`;

            for (const date of dates) {
                const turno = data.calendario[date] || 'Descanso';
                const isDescanso = turno === 'Descanso';
                const cellClass = isDescanso ? 'gantt-cell descanso' : 'gantt-cell';

                html += `<td class="${cellClass}">`;

                if (!isDescanso && tdata.dias[date]) {
                    for (const task of tdata.dias[date]) {
                        const statusClass = task.estado.replace(' ', '_');
                        html += `<div class="gantt-block ${statusClass}" 
                                      onclick="showOTDetail('${task.ot_id}')"
                                      onmouseenter="showTooltip(event, this)"
                                      onmouseleave="hideTooltip()"
                                      data-ot="${task.ot_id}"
                                      data-equipo="${escapeHtml(task.equipo)}"
                                      data-tecnica="${escapeHtml(task.tecnica)}"
                                      data-ubicacion="${escapeHtml(task.ubicacion)}"
                                      data-inicio="${task.hora_inicio}"
                                      data-fin="${task.hora_fin}"
                                      data-pareja="${escapeHtml(task.pareja)}">
                                    <span>${task.ot_id}</span>
                                    <span class="block-time">${task.hora_inicio}-${task.hora_fin}</span>
                                 </div>`;
                    }
                } else if (isDescanso) {
                    html += '<span style="color:var(--text-muted);font-size:0.65rem">Descanso</span>';
                }

                html += '</td>';
            }
            html += '</tr>';
        }

        html += '</tbody></table>';
        container.innerHTML = html;

    } catch (e) {
        container.innerHTML = '<div class="gantt-placeholder">Error cargando el Gantt</div>';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Tooltip
let tooltipEl = null;

function showTooltip(event, el) {
    if (!tooltipEl) {
        tooltipEl = document.createElement('div');
        tooltipEl.className = 'tooltip';
        document.body.appendChild(tooltipEl);
    }

    const ot = el.dataset.ot;
    const equipo = el.dataset.equipo;
    const tecnica = el.dataset.tecnica;
    const ubicacion = el.dataset.ubicacion;
    const inicio = el.dataset.inicio;
    const fin = el.dataset.fin;
    const pareja = el.dataset.pareja;

    let html = `
        <div class="tooltip-row"><span class="tooltip-label">OT</span><span class="tooltip-value">${ot}</span></div>
        <div class="tooltip-row"><span class="tooltip-label">Equipo</span><span class="tooltip-value">${equipo}</span></div>
        <div class="tooltip-row"><span class="tooltip-label">Tecnica</span><span class="tooltip-value">${tecnica}</span></div>
        <div class="tooltip-row"><span class="tooltip-label">Ubicacion</span><span class="tooltip-value">${ubicacion}</span></div>
        <div class="tooltip-row"><span class="tooltip-label">Horario</span><span class="tooltip-value">${inicio} - ${fin}</span></div>
    `;
    if (pareja) {
        html += `<div class="tooltip-row"><span class="tooltip-label">Pareja</span><span class="tooltip-value">${pareja}</span></div>`;
    }

    tooltipEl.innerHTML = html;
    tooltipEl.classList.add('visible');

    const rect = el.getBoundingClientRect();
    tooltipEl.style.left = (rect.right + 8) + 'px';
    tooltipEl.style.top = rect.top + 'px';

    // Keep tooltip in viewport
    const tr = tooltipEl.getBoundingClientRect();
    if (tr.right > window.innerWidth) {
        tooltipEl.style.left = (rect.left - tr.width - 8) + 'px';
    }
    if (tr.bottom > window.innerHeight) {
        tooltipEl.style.top = (window.innerHeight - tr.height - 8) + 'px';
    }
}

function hideTooltip() {
    if (tooltipEl) tooltipEl.classList.remove('visible');
}

// ═══════════════════════════════════════
// OT TABLE
// ═══════════════════════════════════════

async function loadOrdenes() {
    const estado = document.getElementById('filter-estado').value;
    const tecnica = document.getElementById('filter-tecnica').value;

    const params = new URLSearchParams({ page: currentPage, per_page: perPage });
    if (estado) params.set('estado', estado);
    if (tecnica) params.set('tecnica', tecnica);

    try {
        const data = await apiFetch(`/api/ordenes?${params}`);
        renderOTTable(data.ordenes);
        renderPagination(data.total, data.page, data.per_page);
    } catch (e) {
        document.getElementById('ot-tbody').innerHTML =
            '<tr><td colspan="9" class="empty-msg">Error cargando ordenes</td></tr>';
    }
}

function renderOTTable(ordenes) {
    const tbody = document.getElementById('ot-tbody');

    if (!ordenes || ordenes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-msg">No hay ordenes con estos filtros</td></tr>';
        return;
    }

    tbody.innerHTML = ordenes.map(ot => {
        const asig = ot.asignacion;
        const tecnicoStr = asig
            ? (asig.tecnico_nombre + (asig.tecnico2_nombre ? ', ' + asig.tecnico2_nombre : ''))
            : '-';
        const horarioStr = asig ? `${asig.hora_inicio}-${asig.hora_fin}` : '-';

        const actionsHTML = ot.estado === 'programada' || ot.estado === 'en_ejecucion' ? `
            <div class="actions-cell">
                <button class="btn-status btn-fin" onclick="updateEstado('${ot.ot_id}','finalizada')">&#9989;</button>
                <button class="btn-status btn-ejec" onclick="updateEstado('${ot.ot_id}','en_ejecucion')">&#9654;&#65039;</button>
                <button class="btn-status btn-noejec" onclick="updateEstado('${ot.ot_id}','no_ejecutada')">&#10060;</button>
            </div>
        ` : '';

        return `<tr>
            <td><strong>${ot.ot_id}</strong></td>
            <td>${ot.equipo}</td>
            <td>${ot.tecnica_requerida}</td>
            <td>${ot.duracion_horas}h</td>
            <td>${ot.ubicacion}${ot.requiere_pareja ? ' &#128101;' : ''}</td>
            <td>${tecnicoStr}</td>
            <td>${horarioStr}</td>
            <td><span class="status-badge status-${ot.estado}">${ot.estado}</span></td>
            <td>${actionsHTML}</td>
        </tr>`;
    }).join('');
}

function renderPagination(total, page, perPage) {
    const container = document.getElementById('pagination');
    const totalPages = Math.ceil(total / perPage);

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    let html = '';
    for (let i = 1; i <= totalPages; i++) {
        html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }
    container.innerHTML = html;
}

function goToPage(page) {
    currentPage = page;
    loadOrdenes();
}

// ═══════════════════════════════════════
// STATUS UPDATES
// ═══════════════════════════════════════

async function updateEstado(otId, estado) {
    try {
        await apiFetch('/api/actualizar-estado', {
            method: 'PUT',
            body: JSON.stringify({ ot_id: otId, estado }),
        });

        showToast(`${otId} → ${estado}`, 'success');
        addLog(`${otId} marcada como ${estado}`);
        await Promise.all([loadKPIs(), loadOrdenes(), loadGantt()]);
    } catch (e) { }
}

// ═══════════════════════════════════════
// MODAL
// ═══════════════════════════════════════

async function showOTDetail(otId) {
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');
    const title = document.getElementById('modal-title');

    title.textContent = `Detalle - ${otId}`;

    try {
        const data = await apiFetch(`/api/ordenes?per_page=200`);
        const ot = data.ordenes.find(o => o.ot_id === otId);

        if (!ot) {
            body.innerHTML = '<p>OT no encontrada</p>';
        } else {
            const asig = ot.asignacion;
            body.innerHTML = `
                <div class="detail-row"><span class="detail-label">OT</span><span class="detail-value">${ot.ot_id}</span></div>
                <div class="detail-row"><span class="detail-label">Equipo</span><span class="detail-value">${ot.equipo}</span></div>
                <div class="detail-row"><span class="detail-label">Flota</span><span class="detail-value">${ot.flota}</span></div>
                <div class="detail-row"><span class="detail-label">Tarea</span><span class="detail-value">${ot.tarea}</span></div>
                <div class="detail-row"><span class="detail-label">Tecnica</span><span class="detail-value">${ot.tecnica_requerida}</span></div>
                <div class="detail-row"><span class="detail-label">Duracion</span><span class="detail-value">${ot.duracion_horas}h</span></div>
                <div class="detail-row"><span class="detail-label">Ubicacion</span><span class="detail-value">${ot.ubicacion}</span></div>
                <div class="detail-row"><span class="detail-label">Pareja</span><span class="detail-value">${ot.requiere_pareja ? 'Si' : 'No'}</span></div>
                <div class="detail-row"><span class="detail-label">Fecha Solicitud</span><span class="detail-value">${ot.fecha_solicitud}</span></div>
                <div class="detail-row"><span class="detail-label">Estado</span><span class="detail-value"><span class="status-badge status-${ot.estado}">${ot.estado}</span></span></div>
                ${asig ? `
                    <hr style="border-color:var(--border); margin:0.75rem 0">
                    <div class="detail-row"><span class="detail-label">Tecnico</span><span class="detail-value">${asig.tecnico_nombre}</span></div>
                    ${asig.tecnico2_nombre ? `<div class="detail-row"><span class="detail-label">Tecnico 2</span><span class="detail-value">${asig.tecnico2_nombre}</span></div>` : ''}
                    <div class="detail-row"><span class="detail-label">Fecha</span><span class="detail-value">${asig.fecha}</span></div>
                    <div class="detail-row"><span class="detail-label">Horario</span><span class="detail-value">${asig.hora_inicio} - ${asig.hora_fin}</span></div>
                    <div class="detail-row"><span class="detail-label">Turno</span><span class="detail-value">${asig.turno}</span></div>
                ` : ''}
            `;
        }
    } catch (e) {
        body.innerHTML = '<p>Error cargando detalle</p>';
    }

    overlay.classList.remove('hidden');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
}

// ═══════════════════════════════════════
// SIMULATION PANEL
// ═══════════════════════════════════════

function togglePanel() {
    document.getElementById('sim-panel').classList.toggle('hidden');
}

function switchTab(tabId) {
    document.querySelectorAll('.sim-tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.sim-tab').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    // Activate the right tab button
    const tabs = document.querySelectorAll('.sim-tab');
    const tabMap = { 'tab-nueva-ot': 0, 'tab-ausencia': 1, 'tab-log': 2 };
    if (tabMap[tabId] !== undefined) tabs[tabMap[tabId]].classList.add('active');
}

async function agregarOT() {
    const equipo = document.getElementById('new-equipo').value.trim();
    const tecnica = document.getElementById('new-tecnica').value;
    const duracion = parseFloat(document.getElementById('new-duracion').value);
    const ubicacion = document.getElementById('new-ubicacion').value;

    if (!equipo) { showToast('Ingresa un equipo', 'error'); return; }

    try {
        const data = await apiFetch('/api/nueva-ot', {
            method: 'POST',
            body: JSON.stringify({
                equipo,
                tarea: `INSPECCION ${tecnica.toUpperCase()} ${equipo.toUpperCase()}`,
                tecnica_requerida: tecnica,
                duracion_horas: duracion,
                ubicacion,
                flota: 'General',
            }),
        });

        showToast(`Nueva OT creada: ${data.ot_id}`, 'success');
        addLog(`Nueva OT ${data.ot_id}: ${equipo} - ${tecnica}`);
        document.getElementById('new-equipo').value = '';
        await Promise.all([loadKPIs(), loadOrdenes()]);
    } catch (e) { }
}

async function registrarAusencia() {
    const tecnico = document.getElementById('aus-tecnico').value;
    const fecha = document.getElementById('aus-fecha').value;

    if (!tecnico) { showToast('Selecciona un tecnico', 'error'); return; }

    try {
        const data = await apiFetch('/api/ausencia-tecnico', {
            method: 'POST',
            body: JSON.stringify({
                tecnico_id: tecnico,
                fecha,
                grupo: getGrupo(),
                fecha_inicio: getFechaInicio(),
                fecha_fin: getFechaFin(),
            }),
        });

        const liberadas = data.ots_liberadas ? data.ots_liberadas.length : 0;
        showToast(`Ausencia registrada. ${liberadas} OTs liberadas.`, 'info');
        addLog(`Ausencia: ${tecnico} el ${fecha} (${liberadas} OTs liberadas)`);
        await Promise.all([loadKPIs(), loadGantt(), loadOrdenes()]);
    } catch (e) { }
}

async function loadTecnicosForPanel() {
    try {
        const tecnicos = await apiFetch(`/api/tecnicos?grupo=${encodeURIComponent(getGrupo())}`);
        const select = document.getElementById('aus-tecnico');
        select.innerHTML = tecnicos
            .filter(t => t.habilidades.length > 0)
            .map(t => `<option value="${t.id}">${t.nombre}</option>`)
            .join('');
    } catch (e) { }
}

// ═══════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════

document.addEventListener('DOMContentLoaded', async () => {
    // Load initial data
    await loadKPIs();
    await loadOrdenes();
    await loadTecnicosForPanel();

    // Auto-refresh KPIs every 30 seconds
    kpiInterval = setInterval(loadKPIs, 30000);

    // Refresh technician list when group changes
    document.getElementById('grupo-select').addEventListener('change', async () => {
        await loadTecnicosForPanel();
        await Promise.all([loadKPIs(), loadGantt(), loadOrdenes()]);
    });

    document.getElementById('semana-input').addEventListener('change', async () => {
        await Promise.all([loadKPIs(), loadGantt()]);
    });
});
