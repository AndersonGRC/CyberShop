/*
 * Módulo Restaurante — diseño 1.5 (design_handoff_modulo_restaurante).
 *
 * Dos pantallas sobre el MISMO lienzo lógico de 1436×640 (constructor, plano de
 * Atender y minimapa), escalado al ancho de cada contenedor. La base de datos
 * guarda la posición en porcentaje (pos_x 0–96, pos_y 0–92, ancho/alto 8–30,
 * rotacion): aquí se convierte, sin cambiar el esquema que también replica el
 * POS de escritorio.
 *
 * Reglas que NO cambian (las hace cumplir el servidor):
 *  - Nunca se envía `estado` al guardar el plano: el servidor conserva el actual.
 *  - Una mesa con cuenta abierta o con historial no se elimina.
 *  - Mesero no cobra ni anula; caja cerrada ⇒ se ofrece abrirla; la factura
 *    electrónica pide los datos del adquiriente; un consumo servido no se resta.
 */
(function () {
    'use strict';

    const P = window.RM_PAGE || {};
    const E = P.endpoints || {};
    const SIMPLE = !!P.simple;
    const CSRF = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    const root = document.getElementById('rmRoot');
    if (!root) return;

    const CW = 1436, CH = 640, SNAP = 24, MARGIN = 48;
    const SH = {
        round: { label: 'Redonda', w: 120, h: 120, cap: 2 },
        square: { label: 'Cuadrada', w: 144, h: 144, cap: 4 },
        rectangle: { label: 'Rectangular', w: 264, h: 132, cap: 6 },
    };
    const ST = {
        libre: 'Disponible', ocupada: 'Ocupada', cobrar: 'Pendiente de cobro', reservada: 'Reservada',
    };
    const COCINA = { pendiente: 'Pendiente', preparando: 'Preparando', servido: 'Servido' };
    const SIG_COCINA = { pendiente: 'preparando', preparando: 'servido' };
    const PAGO_ICON = { EFECTIVO: 'money-bill-wave', TARJETA: 'credit-card', TRANSFERENCIA: 'mobile-alt', MIXTO: 'coins' };
    const MAX_CAP = 30;

    const S = {
        view: P.view === 'builder' ? 'builder' : 'service',
        tables: [],
        salones: [],
        salon: null,
        // Crear mesas
        sel: null, drag: null, pal: null, saving: 0, saveError: false,
        // Atender
        mesa: null, filtro: 'todas', q: '', cat: 'Todos', metodo: 'EFECTIVO',
        fe: false, feDatos: {}, conNota: false, libre: false, menu: false, ops: Promise.resolve(), busy: 0,
    };
    let tempId = -1;

    /* ── Utilidades ─────────────────────────────────────────── */
    const esc = (v) => String(v == null ? '' : v)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const money = (n) => '$' + Math.round(Number(n) || 0).toLocaleString('es-CO');
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    const snap = (v) => Math.round(v / SNAP) * SNAP;
    const r2 = (v) => Math.round(v * 100) / 100;
    const conId = (tpl, key, id) => String(tpl || '').replace(key, String(id));
    const byId = (id) => S.tables.find((t) => t.id === id) || null;
    const store = {
        get(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
        set(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } },
    };

    async function api(url, payload, method) {
        const res = await fetch(url, {
            method: method || 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': CSRF },
            body: method === 'GET' || method === 'DELETE' ? undefined : JSON.stringify(payload || {}),
            credentials: 'same-origin',
        });
        const tipo = res.headers.get('content-type') || '';
        if (!tipo.includes('application/json')) {
            throw new Error(res.status === 401 || res.redirected
                ? 'Tu sesión expiró. Recarga la página e inicia sesión.'
                : 'El servidor respondió algo inesperado. Recarga la página.');
        }
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.success === false) {
            const err = new Error(data.error || 'No se pudo completar la operación.');
            err.data = data;
            throw err;
        }
        return data;
    }

    let toastTimer = null;
    function toast(msg, tipo) {
        const el = document.getElementById('rmToast');
        if (!el) return;
        el.querySelector('span').textContent = msg;
        el.className = 'rm-toast' + (tipo === 'error' ? ' is-error' : '');
        el.querySelector('i').className = 'fas fa-' + (tipo === 'error' ? 'exclamation-circle' : 'check-circle');
        // Abajo a la izquierda del MÓDULO (no encima del menú lateral de la plantilla).
        const app = document.getElementById('rmApp');
        const izq = app ? app.getBoundingClientRect().left + 24 : 24;
        el.style.left = Math.max(16, Math.min(izq, window.innerWidth - 200)) + 'px';
        el.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.hidden = true; }, tipo === 'error' ? 3600 : 1800);
    }

    function alerta(msg, icon) {
        if (window.Swal) {
            return Swal.fire({ icon: icon || 'info', text: msg, confirmButtonText: 'Aceptar',
                confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94' });
        }
        window.alert(msg);
        return Promise.resolve();
    }

    /* ── Datos ──────────────────────────────────────────────── */
    function setData(floor, salones) {
        // Las mesas que se reemplazan no deben seguir guardando lo que tenían en cola.
        S.tables.forEach((t) => { t._obsoleta = true; clearTimeout(t._timer); });
        S.tables = (floor && Array.isArray(floor.tables) ? floor.tables : []).map((t) => ({
            ...t, _codigoGuardado: t.codigo, _nombreGuardado: t.nombre,
        }));
        if (Array.isArray(salones) && salones.length) S.salones = salones;
        const nombres = S.salones.map((s) => s.nombre);
        if (!S.salon || !nombres.includes(S.salon)) {
            const guardado = store.get('rm-salon');
            S.salon = nombres.includes(guardado) ? guardado : (nombres[0] || 'Salon principal');
        }
    }

    async function recargar() {
        const data = await api(E.data, null, 'GET');
        setData(data, data.salones);
    }

    function enSalon() { return S.tables.filter((t) => (t.area || 'Salon principal') === S.salon); }

    /* Geometría en el lienzo lógico (px) a partir de los % guardados. */
    function vertical(t) { return t.forma === 'rectangle' && (Number(t.rotacion) === 90 || Number(t.rotacion) === 270); }
    function geo(t) {
        if (t._g) return t._g;
        const d = SH[t.forma] || SH.square;
        const w = vertical(t) ? d.h : d.w;
        const h = vertical(t) ? d.w : d.h;
        const x = clamp(Math.round((Number(t.pos_x) || 0) / 100 * CW), 0, CW - w);
        const y = clamp(Math.round((Number(t.pos_y) || 0) / 100 * CH), 0, CH - h);
        t._g = { x, y, w, h };
        return t._g;
    }
    function ajustar(g) { g.x = clamp(g.x, 0, CW - g.w); g.y = clamp(g.y, 0, CH - g.h); return g; }

    /* Estado que se ve (derivado de la cuenta, como pide el diseño). */
    function est(t) {
        const items = t.open_order ? Number(t.open_order.total_items || 0) : 0;
        if (items > 0) return t.estado === 'cuenta_solicitada' ? 'cobrar' : 'ocupada';
        if (t.estado === 'reservada') return 'reservada';
        if (t.estado === 'ocupada' && !t.open_order) return 'ocupada';
        return 'libre';
    }
    const total = (t) => (t.open_order ? Number(t.open_order.total_acumulado || 0) : 0);

    function stats() {
        const ocup = S.tables.filter((t) => est(t) === 'ocupada' || est(t) === 'cobrar');
        const a = document.getElementById('rmStatOcupadas');
        const b = document.getElementById('rmStatTotal');
        if (a) a.textContent = `${ocup.length} de ${S.tables.length}`;
        if (b) b.textContent = money(ocup.reduce((s, t) => s + total(t), 0));
    }

    /* ── Lienzo escalado ────────────────────────────────────── */
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => fit()) : null;
    function fit() {
        root.querySelectorAll('.rm-canvas-wrap').forEach((wrap) => {
            const s = wrap.clientWidth / CW;
            if (!s) return;
            wrap.style.height = (CH * s) + 'px';
            const c = wrap.querySelector('.rm-canvas');
            if (c) c.style.transform = `scale(${s})`;
            wrap.dataset.s = String(s);
        });
        posicionarBarra();
    }
    function observar() {
        if (!ro) { fit(); return; }
        ro.disconnect();
        root.querySelectorAll('.rm-canvas-wrap').forEach((w) => ro.observe(w));
        fit();
    }
    window.addEventListener('resize', fit);

    function chairs(t, g) {
        const S_ = 30, G = 10, n = Math.min(Number(t.capacidad) || 1, MAX_CAP), out = [];
        if (t.forma === 'round') {
            const r = g.w / 2 + G + S_ / 2;
            for (let i = 0; i < n; i++) {
                const a = -Math.PI / 2 + i * 2 * Math.PI / n;
                out.push([g.w / 2 + r * Math.cos(a) - S_ / 2, g.h / 2 + r * Math.sin(a) - S_ / 2]);
            }
            return out;
        }
        const lados = t.forma === 'square' ? ['t', 'b', 'l', 'r'] : (g.w >= g.h ? ['t', 'b'] : ['l', 'r']);
        const cnt = { t: 0, b: 0, l: 0, r: 0 };
        for (let i = 0; i < n; i++) cnt[lados[i % lados.length]]++;
        ['t', 'b', 'l', 'r'].forEach((sd) => {
            for (let k = 0; k < cnt[sd]; k++) {
                if (sd === 't' || sd === 'b') out.push([(k + 1) * g.w / (cnt[sd] + 1) - S_ / 2, sd === 't' ? -G - S_ : g.h + G]);
                else out.push([sd === 'l' ? -G - S_ : g.w + G, (k + 1) * g.h / (cnt[sd] + 1) - S_ / 2]);
            }
        });
        return out;
    }

    function chipsSalon(conConteo) {
        return S.salones.map((s) => {
            const n = S.tables.filter((t) => (t.area || 'Salon principal') === s.nombre).length;
            return `<button type="button" class="rm-chip${s.nombre === S.salon ? ' is-on' : ''}" data-act="salon" data-salon="${esc(s.nombre)}">${esc(s.nombre)}${conConteo ? `<span class="rm-chip-n">${n}</span>` : ''}</button>`;
        }).join('');
    }

    /* ═════════════════════ CREAR MESAS ═════════════════════ */
    function renderBuilder() {
        const mesas = enSalon();
        const sel = S.sel != null ? byId(S.sel) : null;
        const visibleSel = sel && mesas.includes(sel) ? sel : null;
        const puestos = mesas.reduce((a, t) => a + (Number(t.capacidad) || 0), 0);
        const borrarSalon = !mesas.length && S.salones.length > 1;

        root.innerHTML = `
        <div class="rm-grid rm-grid-build">
            <section class="rm-main">
                <div class="rm-row">
                    ${chipsSalon(true)}
                    <button type="button" class="rm-add-salon" data-act="add-salon"><i class="fas fa-plus"></i>Agregar salón</button>
                    <span class="rm-row-meta">${mesas.length} mesas · ${puestos} puestos</span>
                </div>
                <div class="rm-scroll">
                    <div class="rm-canvas-wrap rm-canvas-build" id="rmBld" data-act="bg">
                        <div class="rm-canvas rm-dots">
                            ${mesas.map((t) => nodoPlano(t, visibleSel === t)).join('')}
                        </div>
                        ${mesas.length ? '' : `
                        <div class="rm-empty">
                            <i class="fas fa-mouse-pointer"></i>
                            <b>Este salón está vacío</b>
                            <span>Arrastra una mesa desde el panel derecho.</span>
                        </div>`}
                        ${visibleSel ? barra(visibleSel) : ''}
                    </div>
                </div>
                <div class="rm-hints">
                    <span>Arrastra para mover · se ajusta a la cuadrícula</span>
                    <span>Flechas para mover fino</span><span>Supr para eliminar</span>
                </div>
            </section>
            <div class="rm-side">
                <section class="rm-side-sec">
                    <h2 class="rm-h">Agregar mesa</h2>
                    <div class="rm-palette">
                        ${Object.entries(SH).map(([k, d]) => `
                        <button type="button" class="rm-pal" data-pal="${k}" aria-label="Agregar mesa ${d.label.toLowerCase()} de ${d.cap} puestos">
                            <span class="rm-pal-prev"><span class="rm-pal-shape is-${k}" style="width:${d.w / 4.4}px;height:${d.h / 4.4}px"></span></span>
                            <span class="rm-pal-txt"><b>${d.label}</b><span>${d.cap} puestos</span></span>
                        </button>`).join('')}
                    </div>
                    <span class="rm-note">Arrástrala al plano o tócala para ubicarla en un espacio libre.</span>
                </section>
                ${visibleSel ? panelMesa(visibleSel) : panelSalon(borrarSalon)}
            </div>
        </div>`;
        observar();
    }

    function nodoPlano(t, on) {
        const g = geo(t);
        return `
        <div class="rm-bnode${on ? ' is-on' : ''}" data-node="${t.id}" style="left:${g.x}px;top:${g.y}px;width:${g.w}px;height:${g.h}px">
            ${chairs(t, g).map(([x, y]) => `<span class="rm-chair" style="left:${x}px;top:${y}px"></span>`).join('')}
            <div class="rm-bnode-body is-${esc(t.forma)}">
                <b>${t.codigo ? esc(t.codigo) : '…'}</b>
                <span>${Number(t.capacidad) || 0} puestos</span>
            </div>
        </div>`;
    }

    function barra(t) {
        const g = geo(t);
        const btns = [];
        if (t.forma === 'rectangle') btns.push(['rotate', 'redo', 'Girar']);
        btns.push(['cap-dec', 'minus', 'Menos puestos'], ['cap-inc', 'plus', 'Más puestos'],
            ['dup', 'copy', 'Duplicar'], ['del', 'trash-alt', 'Eliminar']);
        return `<div class="rm-float" id="rmFloat" data-x="${g.x}" data-y="${g.y}" data-w="${g.w}" data-h="${g.h}">
            ${btns.map(([a, i, l]) => `<button type="button" data-act="${a}" title="${l}" aria-label="${l}"${a === 'del' ? ' class="is-danger"' : ''}><i class="fas fa-${i}"></i></button>`).join('')}
        </div>`;
    }

    function posicionarBarra() {
        const f = document.getElementById('rmFloat');
        const wrap = document.getElementById('rmBld');
        if (!f || !wrap) return;
        const s = Number(wrap.dataset.s) || 1;
        const x = Number(f.dataset.x), y = Number(f.dataset.y), w = Number(f.dataset.w), h = Number(f.dataset.h);
        const arriba = y * s > 56;
        f.style.left = ((x + w / 2) * s) + 'px';
        f.style.top = (arriba ? y * s - 14 : (y + h) * s + 14) + 'px';
        f.style.transform = arriba ? 'translate(-50%,-100%)' : 'translate(-50%,0)';
    }

    function guardadoTxt() {
        if (S.saveError) return '<span class="rm-saved is-error"><i class="fas fa-exclamation-circle"></i>Sin guardar</span>';
        if (S.saving > 0) return '<span class="rm-saved is-busy"><i class="fas fa-circle-notch fa-spin"></i>Guardando…</span>';
        return '<span class="rm-saved"><i class="fas fa-check"></i>Guardado</span>';
    }
    function pintarGuardado() {
        const el = document.getElementById('rmSaved');
        if (el) el.innerHTML = guardadoTxt();
    }

    function panelMesa(t) {
        return `
        <section class="rm-side-sec rm-form">
            <div class="rm-form-head">
                <h2 class="rm-h">Mesa ${t.codigo ? esc(t.codigo) : '…'}</h2>
                <span id="rmSaved">${guardadoTxt()}</span>
            </div>
            <label class="rm-field">Código
                <input id="rmCodigo" type="text" maxlength="30" value="${esc(t.codigo)}" autocomplete="off" ${t.id < 0 ? 'disabled' : ''}>
            </label>
            <div class="rm-field">Forma
                <div class="rm-seg">
                    ${Object.entries(SH).map(([k, d]) => `
                    <button type="button" class="${t.forma === k ? 'is-on' : ''}" data-act="forma" data-forma="${k}">
                        <span class="rm-seg-ico is-${k}"></span>${d.label}
                    </button>`).join('')}
                </div>
            </div>
            <div class="rm-field rm-field-row">Puestos
                <div class="rm-stepper">
                    <button type="button" class="rm-ibtn" data-act="cap-dec" aria-label="Menos puestos"><i class="fas fa-minus"></i></button>
                    <b>${Number(t.capacidad) || 0}</b>
                    <button type="button" class="rm-ibtn" data-act="cap-inc" aria-label="Más puestos"><i class="fas fa-plus"></i></button>
                </div>
            </div>
            <label class="rm-field">Salón
                <select id="rmSalonMesa">
                    ${S.salones.map((s) => `<option value="${esc(s.nombre)}"${s.nombre === t.area ? ' selected' : ''}>${esc(s.nombre)}</option>`).join('')}
                </select>
            </label>
            <div class="rm-two">
                <button type="button" class="rm-btn rm-btn-sec rm-btn-sm" data-act="dup"><i class="fas fa-copy"></i>Duplicar</button>
                <button type="button" class="rm-btn rm-btn-danger rm-btn-sm" data-act="del"><i class="fas fa-trash-alt"></i>Eliminar</button>
            </div>
        </section>`;
    }

    function panelSalon(borrar) {
        return `
        <section class="rm-side-sec rm-form">
            <h2 class="rm-h">Salón</h2>
            <label class="rm-field">Nombre
                <input id="rmSalonNombre" type="text" maxlength="100" value="${esc(S.salon)}" autocomplete="off">
            </label>
            <span class="rm-note">Toca una mesa del plano para editarla.</span>
            ${borrar ? '<button type="button" class="rm-btn rm-btn-ghost rm-btn-sm" data-act="del-salon"><i class="fas fa-trash-alt"></i>Eliminar salón vacío</button>' : ''}
        </section>`;
    }

    /* Espacio libre: primera posición de la cuadrícula sin chocar (margen 48). */
    function espacioLibre(w, h, excluir) {
        const otras = enSalon().filter((t) => t !== excluir).map(geo);
        for (let y = MARGIN; y <= CH - h - MARGIN / 2; y += SNAP) {
            for (let x = MARGIN; x <= CW - w - MARGIN / 2; x += SNAP) {
                const choca = otras.some((o) => x < o.x + o.w + MARGIN && x + w + MARGIN > o.x
                    && y < o.y + o.h + MARGIN && y + h + MARGIN > o.y);
                if (!choca) return { x, y };
            }
        }
        return { x: MARGIN, y: MARGIN };
    }

    function payloadMesa(t) {
        const g = geo(t);
        const d = SH[t.forma] || SH.square;
        // Nombre por defecto «Mesa CÓDIGO»: si nunca se personalizó, sigue al código.
        const nombrePorDefecto = !t._nombreGuardado || t._nombreGuardado === `Mesa ${t._codigoGuardado}`;
        return {
            table_id: t.id > 0 ? t.id : null,
            codigo: t.codigo || '',
            nombre: nombrePorDefecto ? '' : t._nombreGuardado,
            area: t.area || S.salon,
            capacidad: clamp(Number(t.capacidad) || 1, 1, MAX_CAP),
            forma: t.forma,
            pos_x: clamp(r2(g.x / CW * 100), 0, 96),
            pos_y: clamp(r2(g.y / CH * 100), 0, 92),
            ancho: clamp(r2(d.w / CW * 100), 8, 30),
            alto: clamp(r2(d.h / CH * 100), 8, 30),
            rotacion: vertical(t) ? 90 : 0,
        };
    }

    /* Autoguardado: 400 ms de pausa y una cola por mesa (nunca dos envíos a la vez). */
    function programar(t) {
        t._sucia = true;
        clearTimeout(t._timer);
        t._timer = setTimeout(() => encolar(t), 400);
    }
    function encolar(t) {
        clearTimeout(t._timer);
        t._q = (t._q || Promise.resolve()).then(() => persistir(t)).catch(() => {});
        return t._q;
    }
    async function persistir(t) {
        if (t._borrada || t._obsoleta) return;
        t._sucia = false;
        S.saving++; S.saveError = false; pintarGuardado();
        try {
            const r = await api(E.layout, payloadMesa(t));
            const antes = t.id;
            if (t.id < 0) t.id = r.table_id;
            if (S.sel === antes) S.sel = t.id;
            if (r.codigo) t.codigo = r.codigo;
            t._codigoGuardado = t.codigo;
            if (!t._nombreGuardado || t._nombreGuardado.startsWith('Mesa ')) t._nombreGuardado = `Mesa ${t.codigo}`;
            if (antes < 0) { toast(`Mesa ${t.codigo} agregada`); renderBuilder(); }
        } catch (e) {
            S.saveError = true;
            toast(e.message, 'error');
            try { await recargar(); } catch (e2) { /* se queda lo local */ }
            S.sel = null;
            renderBuilder();
        } finally {
            S.saving--; pintarGuardado();
        }
    }

    function agregarMesa(forma, pos) {
        const d = SH[forma];
        const p = pos || espacioLibre(d.w, d.h);
        const t = {
            id: tempId--, codigo: '', nombre: '', area: S.salon, capacidad: d.cap, forma, rotacion: 0,
            estado: 'disponible', open_order: null, _nombreGuardado: '', _codigoGuardado: '',
            _g: ajustar({ x: snap(p.x), y: snap(p.y), w: d.w, h: d.h }),
        };
        S.tables.push(t);
        S.sel = t.id;
        renderBuilder();
        encolar(t);
    }

    function duplicar(t) {
        const g = geo(t);
        const p = espacioLibre(g.w, g.h);
        const n = {
            id: tempId--, codigo: '', nombre: '', area: t.area, capacidad: t.capacidad, forma: t.forma,
            rotacion: vertical(t) ? 90 : 0, estado: 'disponible', open_order: null,
            _nombreGuardado: '', _codigoGuardado: '', _g: { x: p.x, y: p.y, w: g.w, h: g.h },
        };
        S.tables.push(n);
        S.sel = n.id;
        renderBuilder();
        encolar(n);
    }

    async function eliminar(t) {
        if (!t) return;
        if (t.open_order) { toast('No puedes eliminar una mesa con cuenta abierta', 'error'); return; }
        if (t._q) await t._q;              // espera su creación/guardado pendiente
        if (t.id < 0) return;
        try {
            await api(conId(E.deleteTableBase, '__TABLE_ID__', t.id), null, 'DELETE');
            t._borrada = true;
            S.tables = S.tables.filter((x) => x !== t);
            S.sel = null;
            toast(`Mesa ${t.codigo} eliminada`);
            renderBuilder();
        } catch (e) {
            toast(e.message, 'error');
        }
    }

    function cambiar(t, fn) {
        fn(t);
        renderBuilder();
        programar(t);
    }

    async function salonApi(payload, okMsg) {
        try {
            const r = await api(E.salones, payload);
            S.salones = r.salones || S.salones;
            if (okMsg) toast(okMsg);
            return true;
        } catch (e) {
            toast(e.message, 'error');
            return false;
        }
    }

    async function agregarSalon() {
        const usados = S.salones.map((s) => s.nombre.toLowerCase());
        let i = S.salones.length + 1;
        while (usados.includes(`salón ${i}`)) i++;
        const nombre = `Salón ${i}`;
        if (await salonApi({ accion: 'crear', nombre }, `${nombre} creado · ponle nombre en el panel`)) {
            S.salon = nombre; S.sel = null; store.set('rm-salon', nombre);
            renderBuilder();
            const inp = document.getElementById('rmSalonNombre');
            if (inp) { inp.focus(); inp.select(); }
        }
    }

    async function renombrarSalon(nuevo) {
        const actual = S.salon;
        nuevo = String(nuevo || '').replace(/\s+/g, ' ').trim();
        if (!nuevo || nuevo === actual) { renderBuilder(); return; }
        // Que no haya guardados en vuelo con el nombre viejo.
        await Promise.all(S.tables.map((t) => t._q).filter(Boolean));
        if (await salonApi({ accion: 'renombrar', nombre: actual, nuevo }, 'Salón renombrado')) {
            S.tables.forEach((t) => { if (t.area === actual) t.area = nuevo; });
            S.salon = nuevo; store.set('rm-salon', nuevo);
        }
        renderBuilder();
    }

    async function eliminarSalon() {
        if (await salonApi({ accion: 'eliminar', nombre: S.salon }, 'Salón eliminado')) {
            S.salon = S.salones[0] ? S.salones[0].nombre : 'Salon principal';
            store.set('rm-salon', S.salon);
        }
        renderBuilder();
    }

    /* Arrastre de mesas del plano y de la paleta. */
    function escalaPlano() { return Number(document.getElementById('rmBld')?.dataset.s) || 1; }

    root.addEventListener('pointerdown', (ev) => {
        if (S.view !== 'builder') return;
        const pal = ev.target.closest('[data-pal]');
        if (pal) {
            ev.preventDefault();
            S.pal = { forma: pal.dataset.pal, sx: ev.clientX, sy: ev.clientY, moved: false };
            return;
        }
        if (ev.target.closest('#rmFloat')) return;
        const nodo = ev.target.closest('[data-node]');
        if (nodo) {
            const t = byId(Number(nodo.dataset.node));
            if (!t) return;
            ev.preventDefault();
            const g = geo(t);
            S.drag = { t, sx: ev.clientX, sy: ev.clientY, ox: g.x, oy: g.y, moved: false, el: nodo };
            if (S.sel !== t.id) { S.sel = t.id; renderBuilder(); S.drag.el = root.querySelector(`[data-node="${t.id}"]`); }
            return;
        }
        if (ev.target.closest('[data-act="bg"]') && S.sel != null) {
            S.sel = null;
            renderBuilder();
        }
    });

    window.addEventListener('pointermove', (ev) => {
        if (S.drag) {
            const d = S.drag, s = escalaPlano();
            const dx = (ev.clientX - d.sx) / s, dy = (ev.clientY - d.sy) / s;
            if (!d.moved && Math.hypot(dx, dy) < 4) return;
            d.moved = true;
            const g = geo(d.t);
            g.x = snap(d.ox + dx); g.y = snap(d.oy + dy); ajustar(g);
            if (d.el) { d.el.style.left = g.x + 'px'; d.el.style.top = g.y + 'px'; d.el.classList.add('is-drag'); }
            const f = document.getElementById('rmFloat');
            if (f) f.hidden = true;
        }
        if (S.pal) {
            const p = S.pal;
            if (!p.moved && Math.hypot(ev.clientX - p.sx, ev.clientY - p.sy) < 6) return;
            p.moved = true;
            const s = escalaPlano(), d = SH[p.forma], gh = document.getElementById('rmGhost');
            if (gh) {
                gh.hidden = false;
                gh.style.left = ev.clientX + 'px'; gh.style.top = ev.clientY + 'px';
                gh.style.width = (d.w * s) + 'px'; gh.style.height = (d.h * s) + 'px';
                gh.style.borderRadius = p.forma === 'round' ? '50%' : '12px';
            }
        }
    });

    window.addEventListener('pointerup', (ev) => {
        if (S.drag) {
            const d = S.drag;
            S.drag = null;
            if (d.moved) { renderBuilder(); programar(d.t); }
        }
        if (S.pal) {
            const p = S.pal;
            S.pal = null;
            const gh = document.getElementById('rmGhost');
            if (gh) gh.hidden = true;
            if (!p.moved) { agregarMesa(p.forma); return; }
            const wrap = document.getElementById('rmBld');
            const r = wrap?.getBoundingClientRect();
            if (!r || ev.clientX < r.left || ev.clientX > r.right || ev.clientY < r.top || ev.clientY > r.bottom) return;
            const s = escalaPlano(), dd = SH[p.forma];
            agregarMesa(p.forma, { x: (ev.clientX - r.left) / s - dd.w / 2, y: (ev.clientY - r.top) / s - dd.h / 2 });
        }
    });

    /* ═════════════════════ ATENDER ═════════════════════ */
    function renderService() {
        if (S.mesa != null && byId(S.mesa)) renderMesa();
        else { S.mesa = null; renderPlano(); }
    }

    function tarjeta(t, mini) {
        const g = geo(t), e = est(t), o = t.open_order;
        const coincide = S.filtro === 'todas' || e === S.filtro;
        const on = mini && t.id === S.mesa;
        const cocina = !SIMPLE && o ? (Number(o.pending_count || 0) + Number(o.preparing_count || 0)) : 0;
        if (mini) {
            return `<button type="button" class="rm-mnode is-${e}${on ? ' is-on' : ''}" data-act="open" data-id="${t.id}" title="Mesa ${esc(t.codigo)}"
                style="left:${g.x}px;top:${g.y}px;width:${Math.max(g.w, 200)}px">${esc(t.codigo)}</button>`;
        }
        return `<button type="button" class="rm-card is-${e}" data-act="open" data-id="${t.id}"
            style="left:${g.x}px;top:${g.y}px;width:${Math.max(g.w, 200)}px;opacity:${coincide ? 1 : 0.3}"
            aria-label="Mesa ${esc(t.codigo)}, ${ST[e]}">
            <span class="rm-card-strip"></span>
            <span class="rm-card-body">
                <span class="rm-card-top"><b>${esc(t.codigo)}</b><span class="rm-badge is-${e}">${ST[e]}</span></span>
                <span class="rm-card-meta">
                    <span><i class="fas fa-users"></i>${Number(t.capacidad) || 0}</span>
                    ${cocina ? `<span class="rm-card-cocina"><i class="fas fa-fire-alt"></i>${cocina}</span>` : ''}
                    <b class="rm-num">${o && Number(o.total_items) ? money(total(t)) : 'Sin cuenta'}</b>
                </span>
            </span>
        </button>`;
    }

    function renderPlano() {
        const mesas = enSalon();
        const cuenta = (k) => mesas.filter((t) => est(t) === k).length;
        const filtros = [['todas', 'Todas', mesas.length], ['libre', ST.libre, cuenta('libre')],
            ['ocupada', ST.ocupada, cuenta('ocupada')], ['cobrar', ST.cobrar, cuenta('cobrar')]];
        if (cuenta('reservada')) filtros.push(['reservada', ST.reservada, cuenta('reservada')]);
        root.innerHTML = `
        <section class="rm-main rm-main-full">
            <div class="rm-row">
                ${chipsSalon(false)}
                <div class="rm-filters">
                    ${filtros.map(([k, l, n]) => `<button type="button" class="rm-filter${S.filtro === k ? ' is-on' : ''}" data-act="filtro" data-f="${k}">
                        <span class="rm-dot is-${k}"></span>${l}<span class="rm-filter-n">${n}</span></button>`).join('')}
                </div>
            </div>
            <div class="rm-scroll">
                <div class="rm-canvas-wrap rm-canvas-big">
                    <div class="rm-canvas rm-lines">${mesas.map((t) => tarjeta(t, false)).join('')}</div>
                    ${mesas.length ? '' : `<div class="rm-empty"><i class="fas fa-chair"></i><b>Este salón no tiene mesas</b>
                        ${P.canBuild ? `<a class="rm-btn rm-btn-sec rm-btn-sm" href="${esc(E.builder)}"><i class="fas fa-drafting-compass"></i>Crear mesas</a>` : '<span>Pide a un administrador que las cree.</span>'}</div>`}
                </div>
            </div>
            <div class="rm-hints"><span>Toca una mesa para abrir su cuenta.</span></div>
        </section>`;
        observar();
    }

    function productosFiltrados() {
        const q = S.q.trim().toLowerCase();
        return (P.products || []).filter((p) => (S.cat === 'Todos' || (p.genero_nombre || 'Sin categoría') === S.cat)
            && (!q || String(p.nombre || '').toLowerCase().includes(q) || String(p.referencia || '').toLowerCase().includes(q)
                || String(p.barcode || '').toLowerCase().includes(q)));
    }

    /* ── Lector de código de barras (mismo criterio que el POS) ──
       La pistola USB escribe como un teclado muy rápido y termina con Enter.
       El código se compara con la referencia o el barcode del producto, sin
       distinguir mayúsculas ni espacios. A diferencia del POS no se exige stock:
       en el restaurante la venta nunca se bloquea por inventario. */
    const normCodigo = (v) => String(v == null ? '' : v).replace(/[ -]/g, '').trim().toUpperCase();
    function productoPorCodigo(codigo) {
        const c = normCodigo(codigo);
        if (!c) return null;
        return (P.products || []).find((p) => normCodigo(p.referencia) === c || (p.barcode && normCodigo(p.barcode) === c)) || null;
    }
    function bip(ok) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator(), gain = ctx.createGain();
            osc.connect(gain); gain.connect(ctx.destination);
            osc.frequency.value = ok ? 1200 : 400; osc.type = 'sine'; gain.gain.value = 0.3;
            osc.start(); osc.stop(ctx.currentTime + (ok ? 0.15 : 0.3));
        } catch (e) { /* sin audio */ }
    }
    const ultimoEscaneo = { codigo: '', t: 0 };
    function escanear(codigo) {
        const c = normCodigo(codigo);
        if (c.length < 3) return false;
        const ahora = Date.now();
        if (c === ultimoEscaneo.codigo && ahora - ultimoEscaneo.t < 500) return true;   // rebote del lector
        ultimoEscaneo.codigo = c; ultimoEscaneo.t = ahora;
        const mesa = S.view === 'service' && S.mesa != null ? byId(S.mesa) : null;
        if (!mesa) { bip(false); toast('Abre una mesa para agregar con el lector', 'error'); return true; }
        const p = productoPorCodigo(c);
        if (!p) { bip(false); toast(`No encontré el código ${c}. Usa Ítem libre si no está en el catálogo.`, 'error'); return true; }
        bip(true);
        S.q = '';
        operar(() => agregar(mesa, { product_id: p.id, cantidad: 1, merge: true }, p.nombre));
        return true;
    }
    // Lector con el foco fuera de un campo: se acumula la ráfaga de teclas.
    const lector = { buffer: '', ultima: 0, timer: null };
    document.addEventListener('keydown', (ev) => {
        if (S.view !== 'service' || document.querySelector('.swal2-container')) return;
        const foco = document.activeElement;
        if (foco && /INPUT|SELECT|TEXTAREA/.test(foco.tagName)) return;     // el buscador tiene su propio manejo
        const ahora = Date.now(), dt = ahora - lector.ultima;
        if ((ev.key === 'Enter' || ev.key === 'Tab') && lector.buffer.length >= 3) {
            ev.preventDefault();
            const cod = lector.buffer; lector.buffer = ''; clearTimeout(lector.timer);
            escanear(cod);
            return;
        }
        if (ev.key.length !== 1 || ev.ctrlKey || ev.altKey || ev.metaKey) return;
        lector.ultima = ahora;
        if (dt > 50 && lector.buffer.length) lector.buffer = '';
        if (lector.buffer.length && dt <= 50) ev.preventDefault();
        lector.buffer += ev.key;
        clearTimeout(lector.timer);
        lector.timer = setTimeout(() => {
            if (lector.buffer.length >= 3) escanear(lector.buffer);
            lector.buffer = '';
        }, 200);
    }, true);
    function gridProductos() {
        const lista = productosFiltrados();
        if (!lista.length) return '<div class="rm-prods-empty">No hay productos con ese filtro. Usa <b>Ítem libre</b> para vender algo que no está en el catálogo.</div>';
        return lista.map((p) => `
            <button type="button" class="rm-prod" data-act="add" data-pid="${p.id}">
                <span class="rm-prod-name">${esc(p.nombre)}</span>
                <span class="rm-prod-foot"><b class="rm-num">${money(p.precio)}</b><span class="rm-prod-plus"><i class="fas fa-plus"></i></span></span>
            </button>`).join('');
    }

    function renderMesa() {
        const t = byId(S.mesa);
        const e = est(t), o = t.open_order;
        const lineas = o ? (o.consumptions || []) : [];
        const tot = total(t);
        const cats = ['Todos', ...Array.from(new Set((P.products || []).map((p) => p.genero_nombre || 'Sin categoría')))];
        const pasos = [['libre', 'Disponible'], ['ocupada', 'Ocupada'], ['cobrar', 'Pendiente de cobro']];
        const idx = Math.max(0, pasos.findIndex(([k]) => k === e));
        const cobrando = e === 'cobrar';
        const salonMesa = t.area || 'Salon principal';
        const mini = S.tables.filter((x) => (x.area || 'Salon principal') === salonMesa);
        const opciones = menuMesa(t, e);

        root.innerHTML = `
        <div class="rm-grid rm-grid-sale">
            <section class="rm-main">
                <div class="rm-sale-head">
                    <button type="button" class="rm-ibtn rm-ibtn-lg" data-act="close-mesa" aria-label="Ver todas las mesas"><i class="fas fa-arrow-left"></i></button>
                    <div class="rm-sale-id">
                        <div class="rm-sale-title">Mesa ${esc(t.codigo)}<span class="rm-badge is-${e}">${ST[e]}</span></div>
                        <div class="rm-sale-sub">${Number(t.capacidad) || 0} personas · ${esc(t.area || 'Salon principal')}</div>
                    </div>
                    <div class="rm-steps" aria-label="Estado de la mesa">
                        ${pasos.map(([k, l], i) => `<span class="rm-step${i === idx && e !== 'reservada' ? ' is-on' : ''}${i < idx ? ' is-done' : ''}"><span class="rm-dot is-${k}"></span>${l}</span>${i < pasos.length - 1 ? '<span class="rm-step-sep"></span>' : ''}`).join('')}
                    </div>
                    ${opciones ? `<div class="rm-more">
                        <button type="button" class="rm-ibtn" data-act="menu" aria-haspopup="true" aria-expanded="${S.menu}" aria-label="Más opciones de la mesa"><i class="fas fa-ellipsis-h"></i></button>
                        ${S.menu ? `<div class="rm-menu" role="menu">${opciones}</div>` : ''}
                    </div>` : ''}
                </div>
                <div class="rm-search">
                    <i class="fas fa-barcode"></i>
                    <input id="rmQ" type="search" placeholder="Buscar producto o escanear código…" value="${esc(S.q)}"
                        autocomplete="off" aria-label="Buscar producto o escanear su código de barras">
                </div>
                <div class="rm-cats">
                    ${cats.map((c) => `<button type="button" class="rm-chip rm-chip-pill${S.cat === c ? ' is-on' : ''}" data-act="cat" data-cat="${esc(c)}">${esc(c)}</button>`).join('')}
                    <button type="button" class="rm-chip rm-chip-pill rm-chip-libre${S.libre ? ' is-on' : ''}" data-act="libre"><i class="fas fa-pen"></i>Ítem libre</button>
                    ${SIMPLE ? '' : `<button type="button" class="rm-chip rm-chip-pill rm-chip-nota${S.conNota ? ' is-on' : ''}" data-act="nota" aria-pressed="${S.conNota}" title="Pide una nota para cocina antes de agregar"><i class="fas fa-comment-alt"></i>Con nota</button>`}
                </div>
                ${S.libre ? `
                <form class="rm-libre" id="rmLibre" autocomplete="off">
                    <input id="rmLibreDesc" type="text" maxlength="200" placeholder="¿Qué vendes? (ej. Almuerzo del día)" required>
                    <input id="rmLibrePrecio" type="number" min="0" step="any" inputmode="decimal" placeholder="Precio" required>
                    <input id="rmLibreCant" type="number" min="1" max="100" value="1" inputmode="numeric" aria-label="Cantidad">
                    ${SIMPLE ? '' : '<input id="rmLibreNota" type="text" maxlength="300" placeholder="Nota para cocina (opcional)">'}
                    <button type="submit" class="rm-btn rm-btn-primary rm-btn-sm"><i class="fas fa-plus"></i>Agregar</button>
                </form>` : ''}
                <div class="rm-prods" id="rmProds">${gridProductos()}</div>
            </section>
            <div class="rm-side rm-side-sale" id="rmCuenta">
                <div class="rm-mini-head">
                    <span>Cambiar de mesa</span>
                    <button type="button" class="rm-btn rm-btn-sec rm-btn-sm" data-act="close-mesa"><i class="fas fa-th-large"></i>Ver todas</button>
                </div>
                <div class="rm-canvas-wrap rm-canvas-mini">
                    <div class="rm-canvas rm-minigrid">${mini.map((x) => tarjeta(x, true)).join('')}</div>
                </div>
                <div class="rm-lines-list">
                    ${lineas.length ? lineas.map(linea).join('') : '<div class="rm-lines-empty">Aún no hay consumos. Toca un producto para agregarlo.</div>'}
                </div>
                <div class="rm-pay">
                    <div class="rm-total"><span>Total</span><b class="rm-num">${money(tot)}</b></div>
                    ${cobrando ? bloqueCobro(t, tot) : `
                    <button type="button" class="rm-btn rm-btn-cta" data-act="pedir" ${lineas.length ? '' : 'disabled'}>
                        <i class="fas fa-receipt"></i>Pedir cuenta · ${money(tot)}</button>`}
                </div>
            </div>
        </div>
        <button type="button" class="rm-ver-cuenta" data-act="ver-cuenta"><i class="fas fa-receipt"></i>Ver cuenta · ${money(tot)}</button>`;
        observar();
    }

    function linea(c) {
        const servido = c.estado === 'servido';
        const qty = Number(c.cantidad) || 0;
        const bloqueo = servido ? ' disabled title="Ya se sirvió: no se puede cambiar"' : '';
        return `
        <div class="rm-line">
            <div class="rm-line-info">
                <b>${esc(c.descripcion)}</b>
                <span>${money(c.precio_unitario)} c/u${c.notas ? ' · ' + esc(c.notas) : ''}</span>
                ${SIMPLE ? '' : `<button type="button" class="rm-kitchen is-${esc(c.estado)}" data-act="cocina" data-cid="${c.id}" ${SIG_COCINA[c.estado] ? `title="Pasar a ${COCINA[SIG_COCINA[c.estado]]}"` : 'disabled'}>${COCINA[c.estado] || esc(c.estado)}</button>`}
            </div>
            <div class="rm-stepper">
                <button type="button" class="rm-ibtn rm-ibtn-sm" data-act="dec" data-cid="${c.id}" data-q="${qty}" aria-label="Quitar uno"${bloqueo}><i class="fas fa-${qty === 1 ? 'trash-alt' : 'minus'}"></i></button>
                <b class="rm-num">${qty}</b>
                <button type="button" class="rm-ibtn rm-ibtn-sm" data-act="inc" data-cid="${c.id}" data-q="${qty}" aria-label="Agregar uno"${bloqueo}><i class="fas fa-plus"></i></button>
            </div>
            <b class="rm-line-sub rm-num">${money(c.subtotal)}</b>
        </div>`;
    }

    function bloqueCobro(t, tot) {
        if (!P.canCharge) {
            return `<div class="rm-wait"><i class="fas fa-hourglass-half"></i>Esperando el cobro en caja.</div>
                <button type="button" class="rm-btn rm-btn-ghost rm-btn-full" data-act="seguir">Seguir agregando</button>`;
        }
        const metodos = Array.isArray(P.paymentMethods) && P.paymentMethods.length
            ? P.paymentMethods : Object.entries(P.paymentMethods || { EFECTIVO: 'Efectivo' });
        const fd = S.feDatos;
        return `
            <div class="rm-methods" role="radiogroup" aria-label="Medio de pago" style="grid-template-columns:repeat(${Math.min(metodos.length, 4)},1fr)">
                ${metodos.map(([k, l]) => `<button type="button" role="radio" aria-checked="${S.metodo === k}" class="rm-method${S.metodo === k ? ' is-on' : ''}" data-act="metodo" data-m="${k}">
                    <i class="fas fa-${PAGO_ICON[k] || 'wallet'}"></i>${esc(l)}</button>`).join('')}
            </div>
            ${P.feHabilitada ? `
            <div class="rm-fe">
                <span>¿Factura electrónica?</span>
                <div class="rm-seg rm-seg-sm">
                    <button type="button" class="${S.fe ? '' : 'is-on'}" data-act="fe" data-v="0">No</button>
                    <button type="button" class="${S.fe ? 'is-on' : ''}" data-act="fe" data-v="1"><i class="fas fa-file-invoice"></i>Sí</button>
                </div>
            </div>
            ${S.fe ? `
            <div class="rm-fe-form">
                <input data-fe="cliente_nombre" type="text" placeholder="Nombre o razón social" value="${esc(fd.cliente_nombre)}">
                <div class="rm-fe-row">
                    <select data-fe="cliente_tipo_doc" aria-label="Tipo de documento">
                        ${['CC', 'NIT', 'CE', 'PASS'].map((k) => `<option value="${k}"${(fd.cliente_tipo_doc || 'CC') === k ? ' selected' : ''}>${{ CC: 'C.C.', NIT: 'NIT', CE: 'C.E.', PASS: 'Pasaporte' }[k]}</option>`).join('')}
                    </select>
                    <input data-fe="cliente_documento" type="text" inputmode="numeric" placeholder="Número de documento" value="${esc(fd.cliente_documento)}">
                </div>
                <input data-fe="cliente_email" type="email" placeholder="Correo (donde llega la factura)" value="${esc(fd.cliente_email)}">
                <input data-fe="cliente_telefono" type="tel" placeholder="Teléfono (opcional)" value="${esc(fd.cliente_telefono)}">
            </div>` : ''}` : ''}
            <button type="button" class="rm-btn rm-btn-ghost rm-btn-full" data-act="seguir">Seguir agregando</button>
            <button type="button" class="rm-btn rm-btn-cta" data-act="pagar"><i class="fas fa-check"></i>Confirmar pago ${money(tot)}</button>`;
    }

    function menuMesa(t, e) {
        const items = [];
        if (!t.open_order && e === 'libre') items.push(['reservar', 'bookmark', 'Marcar como reservada']);
        if (!t.open_order && e === 'reservada') items.push(['liberar', 'check-circle', 'Quitar la reserva']);
        if (P.canCancel && t.open_order) items.push(['anular', 'ban', 'Anular la cuenta']);
        return items.map(([a, i, l]) => `<button type="button" role="menuitem" data-act="${a}"${a === 'anular' ? ' class="is-danger"' : ''}><i class="fas fa-${i}"></i>${l}</button>`).join('');
    }

    /* Operaciones de la cuenta: en serie, y siempre se vuelve a leer del servidor. */
    function operar(fn) {
        S.ops = S.ops.then(async () => {
            S.busy++;
            try { await fn(); } catch (e) { toast(e.message, 'error'); }
            finally { S.busy--; }
            try { await recargar(); } catch (e) { /* conserva la vista */ }
            stats();
            if (S.view === 'service') { renderService(); listoParaEscanear(); }
        });
        return S.ops;
    }

    /* En PC el buscador queda enfocado para el siguiente escaneo (como el POS),
       salvo que la persona esté escribiendo en otro campo. */
    function listoParaEscanear() {
        if (S.mesa == null || !window.matchMedia('(pointer: fine)').matches) return;
        const foco = document.activeElement;
        if (foco && foco !== document.body && root.contains(foco) && /INPUT|SELECT|TEXTAREA/.test(foco.tagName)) return;
        document.getElementById('rmQ')?.focus({ preventScroll: true });
    }

    async function estadoMesa(t, estado) {
        await api(conId(E.tableStateBase, '__TABLE_ID__', t.id), { estado });
    }

    async function agregar(t, cuerpo, nombre) {
        const antes = est(t);
        await api(conId(E.addConsumptionBase, '__TABLE_ID__', t.id), cuerpo);
        // Agregar algo en «Pendiente de cobro» vuelve a «Ocupada» (diseño).
        if (antes === 'cobrar') await estadoMesa(t, 'ocupada');
        toast(antes === 'ocupada' || antes === 'cobrar' ? `Agregado: ${nombre}` : `Mesa ${t.codigo} ahora está Ocupada`);
    }

    async function pedirNota(nombre) {
        if (!window.Swal) return window.prompt(`Nota para cocina (${nombre})`) || '';
        const r = await Swal.fire({
            title: nombre, input: 'text', inputPlaceholder: 'Nota para cocina: sin cebolla, término medio…',
            showCancelButton: true, confirmButtonText: 'Agregar', cancelButtonText: 'Cancelar',
            confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
        });
        return r.isConfirmed ? (r.value || '').trim() : null;
    }

    async function abrirCaja() {
        if (!window.Swal || !E.abrirCaja) { await alerta('Abre la caja desde el Punto de Venta para poder cobrar.', 'warning'); return false; }
        const r = await Swal.fire({
            icon: 'info', title: 'Abre la caja para cobrar',
            text: 'Las ventas de mesas hacen parte del arqueo del turno. Indica la base en efectivo.',
            input: 'number', inputLabel: 'Base inicial en efectivo', inputValue: 0,
            showCancelButton: true, confirmButtonText: 'Abrir caja', cancelButtonText: 'Cancelar',
            confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
            inputValidator: (v) => (v === '' || Number(v) < 0 ? 'Escribe la base (0 o más).' : null),
        });
        if (!r.isConfirmed) return false;
        try {
            await api(E.abrirCaja, { base: r.value });
            const chip = document.getElementById('rmCaja');
            if (chip) { chip.className = 'rm-caja is-open'; chip.innerHTML = '<i class="fas fa-cash-register"></i>Caja abierta'; }
            return true;
        } catch (e) {
            await alerta(e.message || 'No se pudo abrir la caja.', 'error');
            return false;
        }
    }

    async function cobrar(t) {
        const cuerpo = { payment_method: S.metodo, facturar_electronicamente: !!(P.feHabilitada && S.fe) };
        if (cuerpo.facturar_electronicamente) {
            const f = S.feDatos, faltan = [];
            if (!(f.cliente_nombre || '').trim()) faltan.push('nombre o razón social');
            if (!(f.cliente_documento || '').trim()) faltan.push('número de documento');
            if (String(f.cliente_email || '').indexOf('@') === -1) faltan.push('correo válido');
            if (faltan.length) {
                toast('Para la factura falta: ' + faltan.join(', '), 'error');
                root.querySelector(`[data-fe="${!(f.cliente_nombre || '').trim() ? 'cliente_nombre' : (!(f.cliente_documento || '').trim() ? 'cliente_documento' : 'cliente_email')}"]`)?.focus();
                return;
            }
            Object.assign(cuerpo, {
                cliente_nombre: f.cliente_nombre.trim(), cliente_tipo_doc: f.cliente_tipo_doc || 'CC',
                cliente_documento: f.cliente_documento.trim(), cliente_email: f.cliente_email.trim(),
                cliente_telefono: (f.cliente_telefono || '').trim(),
            });
        }
        const url = conId(E.closeAccountBase, '__TABLE_ID__', t.id);
        await operar(async () => {
            try {
                await api(url, cuerpo);
            } catch (e) {
                if (!(e.data && e.data.caja_cerrada)) throw e;
                if (!(await abrirCaja())) return;
                await api(url, cuerpo);
            }
            toast(`Pago registrado · Mesa ${t.codigo} disponible`);
            S.mesa = null; S.fe = false; S.feDatos = {}; S.metodo = 'EFECTIVO';
        });
    }

    async function anular(t) {
        if (!window.Swal) return;
        const r = await Swal.fire({
            icon: 'warning', text: `¿Anular la cuenta de la mesa ${t.codigo}? Se devuelve al inventario lo que no se sirvió.`,
            input: 'text', inputPlaceholder: 'Motivo de la anulación', showCancelButton: true,
            confirmButtonText: 'Anular cuenta', cancelButtonText: 'Volver',
            confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
            inputValidator: (v) => (!v || !v.trim() ? 'Escribe el motivo.' : null),
        });
        if (!r.isConfirmed) return;
        await operar(async () => {
            await api(conId(E.cancelOpenBase, '__TABLE_ID__', t.id), { motivo: r.value.trim() });
            toast(`Cuenta de la mesa ${t.codigo} anulada`);
        });
    }

    /* ── Eventos ────────────────────────────────────────────── */
    root.addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-act]');
        if (!b || b.disabled) return;
        const act = b.dataset.act;
        if (act === 'bg') return;

        if (act === 'salon') {
            S.salon = b.dataset.salon; S.sel = null; store.set('rm-salon', S.salon);
            S.view === 'builder' ? renderBuilder() : renderService();
            return;
        }

        if (S.view === 'builder') {
            const t = S.sel != null ? byId(S.sel) : null;
            if (act === 'add-salon') agregarSalon();
            else if (act === 'del-salon') eliminarSalon();
            else if (!t) return;
            else if (act === 'rotate') cambiar(t, (m) => { const g = geo(m); m.rotacion = vertical(m) ? 0 : 90; [g.w, g.h] = [g.h, g.w]; ajustar(g); });
            else if (act === 'cap-dec') cambiar(t, (m) => { m.capacidad = Math.max(1, (Number(m.capacidad) || 1) - 1); });
            else if (act === 'cap-inc') cambiar(t, (m) => { m.capacidad = Math.min(MAX_CAP, (Number(m.capacidad) || 0) + 1); });
            else if (act === 'forma') cambiar(t, (m) => { const d = SH[b.dataset.forma]; const g = geo(m); m.forma = b.dataset.forma; m.rotacion = 0; g.w = d.w; g.h = d.h; ajustar(g); });
            else if (act === 'dup') duplicar(t);
            else if (act === 'del') eliminar(t);
            return;
        }

        const mesa = S.mesa != null ? byId(S.mesa) : null;
        if (act === 'filtro') { S.filtro = b.dataset.f; renderPlano(); }
        else if (act === 'open') {
            S.mesa = Number(b.dataset.id); S.q = ''; S.libre = false; S.menu = false; S.fe = false; S.feDatos = {};
            const t = byId(S.mesa);
            if (t && t.area) S.salon = t.area;
            renderService();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            if (window.matchMedia('(pointer: fine)').matches) document.getElementById('rmQ')?.focus({ preventScroll: true });
        }
        else if (act === 'close-mesa') { S.mesa = null; S.menu = false; renderService(); }
        else if (!mesa) return;
        else if (act === 'cat') { S.cat = b.dataset.cat; renderMesa(); }
        else if (act === 'libre') { S.libre = !S.libre; renderMesa(); if (S.libre) document.getElementById('rmLibreDesc')?.focus(); }
        else if (act === 'nota') { S.conNota = !S.conNota; renderMesa(); }
        else if (act === 'menu') { S.menu = !S.menu; renderMesa(); }
        else if (act === 'ver-cuenta') document.getElementById('rmCuenta')?.scrollIntoView({ behavior: 'smooth' });
        else if (act === 'add') {
            const p = (P.products || []).find((x) => String(x.id) === b.dataset.pid);
            if (!p) return;
            b.classList.remove('is-pulse'); void b.offsetWidth; b.classList.add('is-pulse');
            (async () => {
                let nota = '';
                if (!SIMPLE && S.conNota) { nota = await pedirNota(p.nombre); if (nota === null) return; }
                operar(() => agregar(mesa, nota
                    ? { product_id: p.id, cantidad: 1, notas: nota }
                    : { product_id: p.id, cantidad: 1, merge: true }, p.nombre));
            })();
        }
        else if (act === 'inc' || act === 'dec') {
            const q = Number(b.dataset.q) || 0, cid = b.dataset.cid;
            operar(async () => {
                if (act === 'dec' && q <= 1) await api(conId(E.consumptionRemoveBase, '__CONSUMPTION_ID__', cid), {});
                else await api(conId(E.consumptionQtyBase, '__CONSUMPTION_ID__', cid), { cantidad: act === 'inc' ? q + 1 : q - 1 });
            });
        }
        else if (act === 'cocina') {
            const c = (mesa.open_order?.consumptions || []).find((x) => String(x.id) === b.dataset.cid);
            const sig = c && SIG_COCINA[c.estado];
            if (sig) operar(() => api(conId(E.consumptionStateBase, '__CONSUMPTION_ID__', c.id), { estado: sig }));
        }
        else if (act === 'pedir') operar(async () => { await estadoMesa(mesa, 'cuenta_solicitada'); toast(`Mesa ${mesa.codigo} pendiente de cobro`); });
        else if (act === 'seguir') operar(() => estadoMesa(mesa, 'ocupada'));
        else if (act === 'metodo') { S.metodo = b.dataset.m; renderMesa(); }
        else if (act === 'fe') { S.fe = b.dataset.v === '1'; renderMesa(); }
        else if (act === 'pagar') cobrar(mesa);
        else if (act === 'reservar') { S.menu = false; operar(async () => { await estadoMesa(mesa, 'reservada'); toast(`Mesa ${mesa.codigo} reservada`); }); }
        else if (act === 'liberar') { S.menu = false; operar(async () => { await estadoMesa(mesa, 'disponible'); toast(`Mesa ${mesa.codigo} disponible`); }); }
        else if (act === 'anular') { S.menu = false; renderMesa(); anular(mesa); }
    });

    root.addEventListener('input', (ev) => {
        if (ev.target.id === 'rmQ') {
            S.q = ev.target.value;
            const g = document.getElementById('rmProds');
            if (g) g.innerHTML = gridProductos();
        } else if (ev.target.dataset.fe) {
            S.feDatos[ev.target.dataset.fe] = ev.target.value;
        }
    });

    root.addEventListener('change', (ev) => {
        const t = S.sel != null ? byId(S.sel) : null;
        if (ev.target.id === 'rmCodigo' && t) {
            const v = ev.target.value.replace(/\s+/g, ' ').trim().toUpperCase();
            if (!v) { ev.target.value = t.codigo; return; }
            cambiar(t, (m) => { m.codigo = v; });
        } else if (ev.target.id === 'rmSalonMesa' && t) {
            const v = ev.target.value;
            t.area = v; S.sel = null;
            const g = geo(t);
            const p = espacioLibreEn(v, g, t);
            g.x = p.x; g.y = p.y;
            renderBuilder(); programar(t);
            toast(`Mesa ${t.codigo} movida a ${v}`);
        } else if (ev.target.id === 'rmSalonNombre') {
            renombrarSalon(ev.target.value);
        } else if (ev.target.dataset.fe) {
            S.feDatos[ev.target.dataset.fe] = ev.target.value;
        }
    });

    function espacioLibreEn(salon, g, excluir) {
        const actual = S.salon;
        S.salon = salon;
        const p = espacioLibre(g.w, g.h, excluir);
        S.salon = actual;
        return p;
    }

    root.addEventListener('submit', (ev) => {
        if (ev.target.id !== 'rmLibre') return;
        ev.preventDefault();
        const mesa = byId(S.mesa);
        const desc = document.getElementById('rmLibreDesc').value.trim();
        const precio = Number(document.getElementById('rmLibrePrecio').value);
        const cant = Math.max(1, Math.min(100, parseInt(document.getElementById('rmLibreCant').value, 10) || 1));
        const nota = (document.getElementById('rmLibreNota')?.value || '').trim();
        if (!mesa || !desc || !(precio >= 0)) return;
        S.libre = false;
        operar(() => agregar(mesa, { descripcion: desc, precio_unitario: precio, cantidad: cant, notas: nota || undefined }, desc));
    });

    root.addEventListener('keydown', (ev) => {
        if (ev.target.id !== 'rmQ' || ev.key !== 'Enter') return;
        ev.preventDefault();
        const valor = ev.target.value;
        if (productoPorCodigo(valor)) { ev.target.value = ''; escanear(valor); return; }
        const lista = productosFiltrados();
        if (valor.trim() && lista.length === 1) {
            const p = lista[0];
            ev.target.value = ''; S.q = '';
            operar(() => agregar(byId(S.mesa), { product_id: p.id, cantidad: 1, merge: true }, p.nombre));
        } else if (valor.trim() && !lista.length) {
            escanear(valor);            // avisa «No encontré el código…»
        }
    });

    document.addEventListener('keydown', (ev) => {
        const enCampo = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || '');
        if (S.view === 'builder' && S.sel != null && !enCampo) {
            const t = byId(S.sel);
            const d = { ArrowLeft: [-SNAP, 0], ArrowRight: [SNAP, 0], ArrowUp: [0, -SNAP], ArrowDown: [0, SNAP] }[ev.key];
            if (t && d) { ev.preventDefault(); cambiar(t, (m) => { const g = geo(m); g.x += d[0]; g.y += d[1]; ajustar(g); }); return; }
            if (t && (ev.key === 'Delete' || ev.key === 'Backspace')) { ev.preventDefault(); eliminar(t); return; }
        }
        if (ev.key === 'Escape' && !document.querySelector('.swal2-container')) {
            if (S.view === 'builder' && S.sel != null) { S.sel = null; renderBuilder(); }
            else if (S.view === 'service' && S.menu) { S.menu = false; renderMesa(); }
            else if (S.view === 'service' && S.mesa != null) { S.mesa = null; renderService(); }
        }
    });

    document.addEventListener('click', (ev) => {
        if (S.menu && !ev.target.closest('.rm-more')) { S.menu = false; if (S.mesa != null) renderMesa(); }
    });

    /* Otros meseros: el plano de Atender se relee cada 20 s mientras la pestaña
       está visible, sin interrumpir a quien escribe o tiene una operación en curso. */
    setInterval(async () => {
        if (S.view !== 'service' || document.visibilityState !== 'visible' || S.busy) return;
        const foco = document.activeElement;
        const buscadorVacio = foco && foco.id === 'rmQ' && !foco.value;
        if (foco && root.contains(foco) && /INPUT|SELECT|TEXTAREA/.test(foco.tagName) && !buscadorVacio) return;
        if (S.menu || document.querySelector('.swal2-container')) return;
        try {
            await recargar(); stats(); renderService();
            if (buscadorVacio) document.getElementById('rmQ')?.focus({ preventScroll: true });
        } catch (e) { /* reintenta en el próximo ciclo */ }
    }, 20000);

    window.addEventListener('beforeunload', (ev) => {
        const pendiente = S.saving > 0 || S.tables.some((t) => t._sucia);
        if (S.view === 'builder' && pendiente) { ev.preventDefault(); ev.returnValue = ''; }
    });

    /* ── Inicio ─────────────────────────────────────────────── */
    S.salones = Array.isArray(P.salones) && P.salones.length ? P.salones : [{ nombre: 'Salon principal', mesas: 0 }];
    setData(P.floor, P.salones);
    stats();
    if (S.view === 'builder') renderBuilder(); else renderService();
})();
