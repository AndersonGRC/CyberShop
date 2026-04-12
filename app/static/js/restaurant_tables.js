(function () {
    const page = window.RESTAURANT_PAGE || {};
    const bootstrap = page.floorData || { tables: [], summary: {} };
    const products = page.products || [];
    const endpoints = page.endpoints || {};
    const viewMode = page.viewMode || 'service';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    const state = {
        viewMode,
        data: bootstrap,
        products,
        selectedTableId: bootstrap.tables && bootstrap.tables.length ? bootstrap.tables[0].id : null,
        selectedArea: 'all',
        selectedProduct: null,
        layoutMode: viewMode === 'builder',
        snapMode: true,
        drag: null,
        builderPlacement: false,
        builderPreset: {
            forma: 'square',
            capacidad: 4,
            ancho: 16,
            alto: 16,
        },
    };

    const elements = {
        shell: document.querySelector('.rt-shell'),
        floor: document.getElementById('restaurantFloor'),
        refreshButton: document.getElementById('rtRefreshButton'),
        layoutModeButton: document.getElementById('rtLayoutModeButton'),
        newTableButton: document.getElementById('rtNewTableButton'),
        placeTableButton: document.getElementById('rtPlaceTableButton'),
        placementBadge: document.getElementById('rtPlacementBadge'),
        saveTableButton: document.getElementById('rtSaveTableButton'),
        resetSelectionButton: document.getElementById('rtResetSelectionButton'),
        closeAccountButton: document.getElementById('rtCloseAccountButton'),
        cancelAccountButton: document.getElementById('rtCancelAccountButton'),
        summaryValues: document.querySelectorAll('[data-summary]'),
        selectedStateBadge: document.getElementById('rtSelectedStateBadge'),
        openTotal: document.getElementById('rtOpenTotal'),
        openMinutes: document.getElementById('rtOpenMinutes'),
        pendingCount: document.getElementById('rtPendingCount'),
        orderMeta: document.getElementById('rtOrderMeta'),
        activeOrderStatus: document.getElementById('rtActiveOrderStatus'),
        queueCount: document.getElementById('rtQueueCount'),
        tableQueue: document.getElementById('rtTableQueue'),
        areaSwitcher: document.getElementById('rtAreaSwitcher'),
        chargeTotal: document.getElementById('rtChargeTotal'),
        chargeKitchen: document.getElementById('rtChargeKitchen'),
        chargeOrderCode: document.getElementById('rtChargeOrderCode'),
        productSearch: document.getElementById('productSearchInput'),
        productGrid: document.getElementById('productQuickGrid'),
        selectedProductName: document.getElementById('selectedProductName'),
        consumptionQuantity: document.getElementById('consumptionQuantity'),
        consumptionNotes: document.getElementById('consumptionNotes'),
        addConsumptionButton: document.getElementById('rtAddConsumptionButton'),
        consumptionList: document.getElementById('rtConsumptionList'),
        quickStateButtons: Array.from(document.querySelectorAll('.rt-quick-state')),
        reportActionButtons: Array.from(document.querySelectorAll('.rt-report-action')),
        presetButtons: Array.from(document.querySelectorAll('.rt-preset-card')),
        form: document.getElementById('tableEditorForm'),
        orderClientName: document.getElementById('orderClientName'),
        orderDinings: document.getElementById('orderDinings'),
        orderNotes: document.getElementById('orderNotes'),
        closePaymentMethod: document.getElementById('closePaymentMethod'),
        serviceAreaReference: document.getElementById('serviceAreaReference'),
        builderAreaInput: document.getElementById('builderAreaInput'),
        builderRotationInput: document.getElementById('builderRotationInput'),
    };

    const formFields = [
        'table_id', 'codigo', 'nombre', 'area', 'capacidad', 'forma',
        'estado', 'pos_x', 'pos_y', 'ancho', 'alto', 'rotacion',
    ].reduce((acc, id) => {
        acc[id] = document.getElementById(id);
        return acc;
    }, {});

    function notify(message, icon) {
        if (window.Swal) {
            Swal.fire({
                icon: icon || 'info',
                text: message,
                confirmButtonText: 'Aceptar',
                confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
            });
            return;
        }
        window.alert(message);
    }

    async function confirmAction(message, options) {
        if (window.Swal) {
            const result = await Swal.fire({
                icon: options?.icon || 'question',
                text: message,
                input: options?.input || undefined,
                inputPlaceholder: options?.inputPlaceholder || '',
                inputValidator: options?.input ? (value) => (!value ? 'Este campo es obligatorio.' : null) : undefined,
                showCancelButton: true,
                confirmButtonText: options?.confirmText || 'Continuar',
                cancelButtonText: 'Cancelar',
                confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
            });
            return result;
        }
        const confirmed = window.confirm(message);
        return { isConfirmed: confirmed, value: '' };
    }

    function money(value) {
        return new Intl.NumberFormat('es-CO', {
            style: 'currency',
            currency: 'COP',
            maximumFractionDigits: 0,
        }).format(Number(value || 0));
    }

    function endpointForTable(template, tableId) {
        return template.replace('__TABLE_ID__', String(tableId));
    }

    function endpointForConsumption(template, consumptionId) {
        return template.replace('__CONSUMPTION_ID__', String(consumptionId));
    }

    function endpointForOrder(template, orderId) {
        return template.replace('__ORDER_ID__', String(orderId));
    }

    function getSelectedTable() {
        return state.data.tables.find((table) => table.id === state.selectedTableId) || null;
    }

    function getVisibleTables() {
        if (!Array.isArray(state.data.tables)) {
            return [];
        }
        if (!state.selectedArea || state.selectedArea === 'all') {
            return state.data.tables;
        }
        return state.data.tables.filter((table) => table.area === state.selectedArea);
    }

    function getKitchenStatus(order) {
        if (!order) {
            return 'Sin orden';
        }
        if (order.pending_count > 0) {
            return `${order.pending_count} pendientes`;
        }
        if (order.preparing_count > 0) {
            return `${order.preparing_count} en cocina`;
        }
        if (order.total_items > 0) {
            return 'Lista para cobro';
        }
        return 'Sin orden';
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function snap(value, step) {
        const safeStep = step || 2;
        return Math.round(value / safeStep) * safeStep;
    }

    function resolveProductImage(imagePath) {
        const value = String(imagePath || '').trim();
        if (!value) {
            return '';
        }
        if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('//')) {
            return value;
        }
        if (value.startsWith('/static/')) {
            return value;
        }
        if (value.startsWith('static/')) {
            return `/${value}`;
        }
        if (value.startsWith('/media/')) {
            return `/static${value}`;
        }
        return `/static/media/${value.replace(/^\/+/, '')}`;
    }

    function getTableSizeClass(table) {
        const width = Number(table?.ancho || 0);
        const height = Number(table?.alto || 0);
        const footprint = width * height;
        const minSide = Math.min(width || 0, height || 0);

        if (footprint < 240 || minSide < 14) {
            return 'rt-table-compact';
        }
        if (footprint < 360 || minSide < 18) {
            return 'rt-table-medium';
        }
        return 'rt-table-large';
    }

    async function jsonRequest(url, payload) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(payload || {}),
        });

        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            if (response.status === 401 || response.redirected) {
                throw new Error('Sesión expirada. Recarga la página e inicia sesión.');
            }
            throw new Error('El servidor respondió con un formato inesperado. Recarga la página.');
        }

        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.success === false) {
            throw new Error(data.error || 'Operación no disponible.');
        }
        return data;
    }

    function renderSummary() {
        elements.summaryValues.forEach((node) => {
            const key = node.dataset.summary;
            node.textContent = state.data.summary[key] || 0;
        });
    }

    function renderFloor() {
        if (!elements.floor) {
            return;
        }

        const inPlacement = state.viewMode === 'builder' && state.builderPlacement;
        elements.floor.classList.toggle('is-placement', inPlacement);
        elements.floor.innerHTML = '';
        const visibleTables = getVisibleTables();

        // Hint de placement visible sobre el plano
        if (inPlacement) {
            const hint = document.createElement('div');
            hint.className = 'rt-placement-hint';
            hint.innerHTML = '<i class="fas fa-mouse-pointer"></i> Clic en cualquier punto para colocar la mesa';
            elements.floor.appendChild(hint);
        }

        if (!visibleTables.length) {
            const empty = document.createElement('div');
            empty.className = 'rt-floor-empty';
            const imgSrc = document.querySelector('meta[name="static-root"]')
                ? document.querySelector('meta[name="static-root"]').content + '/img/restaurant_empty.png'
                : '/static/img/restaurant_empty.png';
            empty.innerHTML = inPlacement
                ? '<div><img src="' + imgSrc + '" alt="Plano vacío" class="rt-empty-illustration"><strong>Plano vacío.</strong><br>Haz clic en cualquier punto del plano para crear la primera mesa.</div>'
                : '<div><img src="' + imgSrc + '" alt="Sin mesas" class="rt-empty-illustration"><strong>No hay mesas creadas.</strong><br>Selecciona un preset en la barra lateral para comenzar.</div>';
            elements.floor.appendChild(empty);
            return;
        }

        visibleTables.forEach((table) => {
            const button = document.createElement('button');
            const order = table.open_order;
            const selected = table.id === state.selectedTableId;

            button.type = 'button';
            button.className = [
                'rt-table-node',
                table.forma,
                table.estado,
                getTableSizeClass(table),
                selected ? 'selected' : '',
                state.layoutMode ? 'layout-mode' : '',
            ].join(' ').trim();
            button.style.left = `${table.pos_x}%`;
            button.style.top = `${table.pos_y}%`;
            button.style.width = `${table.ancho}%`;
            button.style.height = `${table.alto}%`;
            button.style.transform = `rotate(${table.rotacion || 0}deg)`;
            button.dataset.tableId = table.id;
            button.title = `${table.nombre} · ${table.codigo} · ${table.estado_label}`;
            button.innerHTML = `
                <div class="rt-table-topline">
                    <span class="rt-table-code">${table.codigo}</span>
                    <span class="rt-table-state">${table.estado_label}</span>
                </div>
                <div class="rt-table-name">${table.nombre}</div>
                <div class="rt-table-meta">
                    <span><i class="fas fa-users"></i> ${table.capacidad}</span>
                    <span>${order ? money(order.total_acumulado) : 'Sin cuenta'}</span>
                </div>
                <div class="rt-table-signal">
                    <div class="rt-signal">
                        <span>Pendientes</span>
                        <strong>${order ? order.pending_count : 0}</strong>
                    </div>
                    <div class="rt-signal">
                        <span>Abierta</span>
                        <strong>${order ? `${order.minutes_open} min` : '0 min'}</strong>
                    </div>
                </div>
                <div class="rt-wait-track">
                    <div class="rt-wait-fill" style="width:${order ? order.wait_progress : 0}%"></div>
                </div>
            `;

            button.addEventListener('click', function () {
                selectTable(table.id);
            });

            if (state.layoutMode) {
                button.addEventListener('pointerdown', startDrag);
            }

            elements.floor.appendChild(button);
        });
    }

    function fillFormFromTable(table) {
        if (!elements.form) {
            return;
        }
        if (!table) {
            formFields.table_id.value = '';
            formFields.codigo.value = '';
            formFields.nombre.value = '';
            formFields.area.value = elements.builderAreaInput?.value || 'Salon principal';
            formFields.capacidad.value = state.builderPreset.capacidad || 4;
            formFields.forma.value = state.builderPreset.forma || 'square';
            formFields.estado.value = 'disponible';
            if (formFields.pos_x) formFields.pos_x.value = 8;
            if (formFields.pos_y) formFields.pos_y.value = 10;
            if (formFields.ancho) formFields.ancho.value = state.builderPreset.ancho || 16;
            if (formFields.alto) formFields.alto.value = state.builderPreset.alto || 16;
            if (formFields.rotacion) formFields.rotacion.value = elements.builderRotationInput?.value || 0;
            return;
        }

        formFields.table_id.value = table.id;
        formFields.codigo.value = table.codigo || '';
        formFields.nombre.value = table.nombre || '';
        formFields.area.value = table.area || 'Salon principal';
        formFields.capacidad.value = table.capacidad || 4;
        formFields.forma.value = table.forma || 'square';
        formFields.estado.value = table.estado || 'disponible';
        if (formFields.pos_x) formFields.pos_x.value = Number(table.pos_x || 0).toFixed(1);
        if (formFields.pos_y) formFields.pos_y.value = Number(table.pos_y || 0).toFixed(1);
        if (formFields.ancho) formFields.ancho.value = Number(table.ancho || 16).toFixed(1);
        if (formFields.alto) formFields.alto.value = Number(table.alto || 16).toFixed(1);
        if (formFields.rotacion) formFields.rotacion.value = table.rotacion || 0;
    }

    function renderAreaSwitcher() {
        if (!elements.areaSwitcher) {
            return;
        }
        const areaButtons = elements.areaSwitcher.querySelectorAll('[data-area]');
        // Show the area switcher when there are areas beyond "all"
        elements.areaSwitcher.hidden = areaButtons.length <= 1;
        areaButtons.forEach((button) => {
            button.classList.toggle('is-active', button.dataset.area === state.selectedArea);
        });
    }

    function setSelectedArea(area) {
        state.selectedArea = area || 'all';
        const visibleTables = getVisibleTables();
        if (!visibleTables.some((table) => table.id === state.selectedTableId)) {
            state.selectedTableId = visibleTables[0]?.id || null;
        }
        renderAreaSwitcher();
        renderFloor();
        renderSelectionPanel();
    }

    function renderQueue() {
        if (!elements.tableQueue) {
            return;
        }
        const visibleTables = getVisibleTables().slice().sort((left, right) => {
            const leftOpen = left.open_order?.minutes_open || 0;
            const rightOpen = right.open_order?.minutes_open || 0;
            if ((right.open_order ? 1 : 0) !== (left.open_order ? 1 : 0)) {
                return (right.open_order ? 1 : 0) - (left.open_order ? 1 : 0);
            }
            return rightOpen - leftOpen;
        });

        if (elements.queueCount) {
            elements.queueCount.textContent = visibleTables.length;
        }

        if (!visibleTables.length) {
            elements.tableQueue.innerHTML = '<div class="rt-consumption-empty">No hay mesas visibles en esta zona.</div>';
            return;
        }

        elements.tableQueue.innerHTML = visibleTables.map((table) => {
            const order = table.open_order;
            const orderTotal = order ? money(order.total_acumulado) : '$0';
            const canCharge = Boolean(order);
            const actionLabel = canCharge ? 'Cobrar' : 'Abrir';
            return `
                <article class="rt-queue-item ${table.id === state.selectedTableId ? 'is-active' : ''}" data-table-id="${table.id}">
                    <div class="rt-queue-item-head">
                        <div>
                            <strong>${table.nombre}</strong>
                            <small>${table.codigo} · ${table.area}</small>
                        </div>
                        <span class="rt-state-badge ${table.estado}">${table.estado_label}</span>
                    </div>
                    <div class="rt-queue-item-metrics">
                        <div>
                            <span>Total</span>
                            <strong>${orderTotal}</strong>
                        </div>
                        <div>
                            <span>Espera</span>
                            <strong>${order ? `${order.minutes_open} min` : 'Libre'}</strong>
                        </div>
                        <div>
                            <span>Cocina</span>
                            <strong>${getKitchenStatus(order)}</strong>
                        </div>
                    </div>
                    <div class="rt-queue-item-actions">
                        <span>${order ? `${order.total_items} ítems` : 'Sin cuenta'}</span>
                        <button class="rt-queue-action" type="button" data-action="${canCharge ? 'charge' : 'select'}" data-table-id="${table.id}">
                            ${actionLabel}
                        </button>
                    </div>
                </article>
            `;
        }).join('');

        elements.tableQueue.querySelectorAll('.rt-queue-item').forEach((card) => {
            card.addEventListener('click', function (event) {
                if (event.target.closest('.rt-queue-action')) {
                    return;
                }
                selectTable(Number(this.dataset.tableId));
            });
        });

        elements.tableQueue.querySelectorAll('.rt-queue-action').forEach((button) => {
            button.addEventListener('click', async function (event) {
                event.stopPropagation();
                const tableId = Number(this.dataset.tableId);
                selectTable(tableId);
                if (this.dataset.action === 'charge') {
                    await closeSelectedAccount();
                }
            });
        });
    }

    function renderSelectionPanel() {
        const table = getSelectedTable();
        if (elements.selectedStateBadge) {
            elements.selectedStateBadge.className = `rt-state-badge${table ? ` ${table.estado}` : ''}`;
            elements.selectedStateBadge.textContent = table ? table.estado_label : 'Sin seleccionar';
        }
        fillFormFromTable(table);
        renderQueue();

        if (state.viewMode !== 'service') {
            return;
        }

        const order = table?.open_order || null;
        if (elements.openTotal) {
            elements.openTotal.textContent = order ? money(order.total_acumulado) : '$0';
        }
        if (elements.openMinutes) {
            elements.openMinutes.textContent = order ? `${order.minutes_open} min` : '0 min';
        }
        if (elements.pendingCount) {
            elements.pendingCount.textContent = order ? order.pending_count : '0';
        }
        if (elements.orderMeta) {
            elements.orderMeta.textContent = order
                ? `Cuenta #${order.id} · ${order.comensales || 0} comensales`
                : 'Sin cuenta abierta';
        }
        if (elements.activeOrderStatus) {
            elements.activeOrderStatus.textContent = order ? 'Servicio en curso' : 'Sin consumos activos';
        }
        if (elements.orderClientName) {
            elements.orderClientName.value = order?.cliente_nombre || '';
        }
        if (elements.orderDinings) {
            elements.orderDinings.value = order?.comensales || 1;
        }
        if (elements.orderNotes) {
            elements.orderNotes.value = order?.notas || '';
        }
        if (elements.closePaymentMethod) {
            elements.closePaymentMethod.value = order?.payment_method || 'EFECTIVO';
        }
        if (elements.serviceAreaReference) {
            elements.serviceAreaReference.value = table?.area || '';
        }
        if (elements.chargeTotal) {
            elements.chargeTotal.textContent = order ? money(order.total_acumulado) : '$0';
        }
        if (elements.chargeKitchen) {
            elements.chargeKitchen.textContent = getKitchenStatus(order);
        }
        if (elements.chargeOrderCode) {
            elements.chargeOrderCode.textContent = order ? `#${order.id}` : 'Sin cuenta';
        }

        if (!elements.consumptionList) {
            return;
        }
        if (!order || !order.consumptions || !order.consumptions.length) {
            elements.consumptionList.innerHTML = '<div class="rt-consumption-empty">No hay consumos cargados para esta mesa.</div>';
            return;
        }

        elements.consumptionList.innerHTML = order.consumptions.map((item) => {
            let actionHtml = '<span class="rt-note">Servicio finalizado</span>';
            if (item.estado === 'pendiente') {
                actionHtml = `<button class="rt-consumption-action" type="button" data-consumption-id="${item.id}" data-next-state="preparando">Pasar a cocina</button>`;
            } else if (item.estado === 'preparando') {
                actionHtml = `<button class="rt-consumption-action" type="button" data-consumption-id="${item.id}" data-next-state="servido">Marcar servido</button>`;
            }

            return `
                <article class="rt-consumption-item">
                    <div class="rt-consumption-topline">
                        <div class="rt-consumption-title">${item.descripcion}</div>
                        <strong>${money(item.subtotal)}</strong>
                    </div>
                    <div class="rt-consumption-tags">
                        <span><i class="fas fa-layer-group"></i> ${item.cantidad} und</span>
                        <span><i class="fas fa-fire-alt"></i> ${item.estado_label}</span>
                        <span><i class="fas fa-tag"></i> ${money(item.precio_unitario)}</span>
                    </div>
                    ${item.notas ? `<div class="rt-note">${item.notas}</div>` : ''}
                    <div class="rt-consumption-actions">
                        <span class="rt-note">#${item.id}</span>
                        ${actionHtml}
                    </div>
                </article>
            `;
        }).join('');

        elements.consumptionList.querySelectorAll('.rt-consumption-action').forEach((button) => {
            button.addEventListener('click', async function () {
                await updateConsumptionState(Number(this.dataset.consumptionId), this.dataset.nextState);
            });
        });
    }

    function selectTable(tableId) {
        state.selectedTableId = tableId;
        renderFloor();
        renderSelectionPanel();
        if (state.viewMode === 'service' && tableId) {
            openTableModal(tableId);
        }
    }

    function prepareNewTable() {
        state.selectedTableId = null;
        state.selectedProduct = null;
        if (elements.selectedProductName) {
            elements.selectedProductName.value = '';
        }
        if (elements.consumptionNotes) {
            elements.consumptionNotes.value = '';
        }
        if (elements.consumptionQuantity) {
            elements.consumptionQuantity.value = 1;
        }
        document.querySelectorAll('.rt-product-chip.selected').forEach((node) => node.classList.remove('selected'));
        renderFloor();
        renderSelectionPanel();
    }

    function buildTablePayload(overrides) {
        return {
            table_id: formFields.table_id?.value || null,
            codigo: formFields.codigo?.value || '',
            nombre: formFields.nombre?.value || '',
            area: formFields.area?.value || elements.builderAreaInput?.value || 'Salon principal',
            capacidad: formFields.capacidad?.value || state.builderPreset.capacidad,
            forma: formFields.forma?.value || state.builderPreset.forma,
            estado: formFields.estado?.value || 'disponible',
            pos_x: formFields.pos_x?.value || 8,
            pos_y: formFields.pos_y?.value || 10,
            ancho: formFields.ancho?.value || state.builderPreset.ancho,
            alto: formFields.alto?.value || state.builderPreset.alto,
            rotacion: formFields.rotacion?.value || 0,
            ...(overrides || {}),
        };
    }

    function toastNotify(message, type) {
        // Notificación rápida no bloqueante (no usa Swal.fire que bloquea)
        if (window.Swal && Swal.mixin) {
            Swal.mixin({
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 2200,
                timerProgressBar: true,
            }).fire({ icon: type || 'success', title: message });
        } else {
            notify(message, type);
        }
    }

    async function saveTable(payloadOverrides) {
        try {
            const result = await jsonRequest(endpoints.layout, buildTablePayload(payloadOverrides));
            await refreshData(result.table_id);
            toastNotify('Mesa añadida al plano ✓', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function refreshData(preferredTableId) {
        try {
            const response = await fetch(endpoints.data, { headers: { Accept: 'application/json' } });
            const contentType = response.headers.get('content-type') || '';
            if (!contentType.includes('application/json')) {
                if (response.status === 401 || response.redirected) {
                    throw new Error('Sesión expirada. Recarga la página e inicia sesión.');
                }
                throw new Error('El servidor respondió con un formato inesperado. Recarga la página.');
            }
            const payload = await response.json();
            if (!response.ok || payload.success === false) {
                throw new Error(payload.error || 'No fue posible refrescar el salón.');
            }
            state.data = payload;
            const candidate = preferredTableId || state.selectedTableId;
            const stillExists = state.data.tables.find((table) => table.id === candidate);
            state.selectedTableId = stillExists ? stillExists.id : (state.data.tables[0]?.id || null);
            if (!getVisibleTables().some((table) => table.id === state.selectedTableId)) {
                state.selectedTableId = getVisibleTables()[0]?.id || state.data.tables[0]?.id || null;
            }
            renderSummary();
            renderAreaSwitcher();
            renderFloor();
            renderSelectionPanel();
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function changeTableState(nextState) {
        const table = getSelectedTable();
        if (!table) {
            notify('Selecciona una mesa primero.', 'warning');
            return;
        }

        try {
            await jsonRequest(endpointForTable(endpoints.tableStateBase, table.id), { estado: nextState });
            await refreshData(table.id);
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    function selectProduct(button) {
        state.selectedProduct = {
            id: Number(button.dataset.productId),
            nombre: button.dataset.productName,
            precio: Number(button.dataset.productPrice || 0),
        };
        document.querySelectorAll('.rt-product-chip.selected').forEach((node) => node.classList.remove('selected'));
        button.classList.add('selected');
        if (elements.selectedProductName) {
            elements.selectedProductName.value = `${state.selectedProduct.nombre} · ${money(state.selectedProduct.precio)}`;
        }
    }

    async function addConsumptionToSelectedTable() {
        const table = getSelectedTable();
        if (!table) {
            notify('Selecciona una mesa antes de agregar consumos.', 'warning');
            return;
        }
        if (!state.selectedProduct) {
            notify('Selecciona un producto del catálogo.', 'warning');
            return;
        }

        try {
            await jsonRequest(endpointForTable(endpoints.addConsumptionBase, table.id), {
                product_id: state.selectedProduct.id,
                cantidad: Number(elements.consumptionQuantity?.value || 1),
                notas: elements.consumptionNotes?.value || '',
                cliente_nombre: elements.orderClientName?.value || '',
                comensales: Number(elements.orderDinings?.value || 1),
                order_notes: elements.orderNotes?.value || '',
            });
            if (elements.consumptionNotes) {
                elements.consumptionNotes.value = '';
            }
            if (elements.consumptionQuantity) {
                elements.consumptionQuantity.value = 1;
            }
            // Limpiar selección de producto para evitar cargos duplicados accidentales
            state.selectedProduct = null;
            if (elements.selectedProductName) {
                elements.selectedProductName.value = '';
            }
            document.querySelectorAll('.rt-product-chip.selected').forEach((node) => node.classList.remove('selected'));
            await refreshData(table.id);
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function updateConsumptionState(consumptionId, nextState) {
        const table = getSelectedTable();
        if (!table) {
            return;
        }

        try {
            await jsonRequest(endpointForConsumption(endpoints.consumptionStateBase, consumptionId), { estado: nextState });
            await refreshData(table.id);
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function closeSelectedAccount() {
        const table = getSelectedTable();
        if (!table || !table.open_order) {
            notify('La mesa seleccionada no tiene una cuenta abierta.', 'warning');
            return;
        }
        let paymentMethod = elements.closePaymentMethod?.value || 'EFECTIVO';

        if (window.Swal) {
            const optionsHtml = Array.from(elements.closePaymentMethod?.options || [])
                .map((option) => `<option value="${option.value}" ${option.value === paymentMethod ? 'selected' : ''}>${option.textContent}</option>`)
                .join('');
            const result = await Swal.fire({
                title: `Cobrar ${table.nombre}`,
                html: `
                    <div style="text-align:left; display:grid; gap:12px;">
                        <div style="display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px;">
                            <div style="padding:12px; border-radius:14px; background:#f4f7fc;">
                                <span style="display:block; font-size:12px; color:#68778f;">Cuenta</span>
                                <strong>#${table.open_order.id}</strong>
                            </div>
                            <div style="padding:12px; border-radius:14px; background:#f4f7fc;">
                                <span style="display:block; font-size:12px; color:#68778f;">Total</span>
                                <strong>${money(table.open_order.total_acumulado)}</strong>
                            </div>
                            <div style="padding:12px; border-radius:14px; background:#f4f7fc;">
                                <span style="display:block; font-size:12px; color:#68778f;">Cocina</span>
                                <strong>${getKitchenStatus(table.open_order)}</strong>
                            </div>
                        </div>
                        <label style="display:grid; gap:6px; font-weight:700;">
                            Medio de pago
                            <select id="rtSwalPaymentMethod" class="swal2-select" style="display:flex; width:100%; margin:0;">
                                ${optionsHtml}
                            </select>
                        </label>
                    </div>
                `,
                showCancelButton: true,
                confirmButtonText: 'Cobrar mesa',
                cancelButtonText: 'Cancelar',
                confirmButtonColor: window.BRAND_COLOR_BTN || '#122C94',
                focusConfirm: false,
                preConfirm: () => document.getElementById('rtSwalPaymentMethod')?.value || paymentMethod,
            });
            if (!result.isConfirmed) {
                return;
            }
            paymentMethod = result.value || paymentMethod;
            if (elements.closePaymentMethod) {
                elements.closePaymentMethod.value = paymentMethod;
            }
        } else {
            const confirmed = await confirmAction(`Cobrar la cuenta abierta de ${table.nombre}?`);
            if (!confirmed.isConfirmed) {
                return;
            }
        }

        try {
            const result = await jsonRequest(endpointForTable(endpoints.closeAccountBase, table.id), {
                payment_method: paymentMethod,
            });
            await refreshData(table.id);
            notify(`Cobro registrado. Total final: ${money(result.total)}.`, 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function cancelSelectedOpenAccount() {
        const table = getSelectedTable();
        if (!table || !table.open_order) {
            notify('La mesa seleccionada no tiene una cuenta abierta.', 'warning');
            return;
        }

        const result = await confirmAction(
            `Cancelar la cuenta abierta de ${table.nombre}?`,
            { input: 'text', inputPlaceholder: 'Motivo de cancelación', confirmText: 'Cancelar cuenta' },
        );
        if (!result.isConfirmed) {
            return;
        }

        try {
            await jsonRequest(endpointForTable(endpoints.cancelOpenBase, table.id), { motivo: result.value });
            await refreshData(table.id);
            notify('La cuenta abierta fue cancelada y la mesa quedó liberada.', 'success');
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function cancelClosedOrder(orderId) {
        const result = await confirmAction(
            'Esto registrará una reversión en contabilidad. Indica el motivo:',
            { input: 'text', inputPlaceholder: 'Motivo de anulación', confirmText: 'Anular venta' },
        );
        if (!result.isConfirmed) {
            return;
        }

        try {
            await jsonRequest(endpointForOrder(endpoints.cancelClosedBase, orderId), { motivo: result.value });
            notify('Venta anulada correctamente. La reversión contable quedó registrada.', 'success');
            window.location.reload();
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    function filterProducts() {
        const term = (elements.productSearch?.value || '').trim().toLowerCase();
        document.querySelectorAll('.rt-product-chip').forEach((node) => {
            const name = (node.dataset.productName || '').toLowerCase();
            node.classList.toggle('hidden', term && !name.includes(term));
        });
    }

    function toggleLayoutMode() {
        state.layoutMode = !state.layoutMode;
        if (elements.layoutModeButton) {
            elements.layoutModeButton.classList.toggle('rt-btn-secondary', state.layoutMode);
            elements.layoutModeButton.classList.toggle('rt-btn-ghost', !state.layoutMode);
            elements.layoutModeButton.innerHTML = state.layoutMode
                ? '<i class="fas fa-hand-paper"></i> Layout activo'
                : '<i class="fas fa-vector-square"></i> Modo layout';
        }
        renderFloor();
    }

    function toggleSnapMode() {
        state.snapMode = !state.snapMode;
        if (elements.layoutModeButton) {
            elements.layoutModeButton.innerHTML = state.snapMode
                ? '<i class="fas fa-border-all"></i> Snap activo'
                : '<i class="fas fa-arrows-alt"></i> Snap libre';
        }
    }

    function startDrag(event) {
        if (!state.layoutMode || state.viewMode === 'reports') {
            return;
        }

        const target = event.currentTarget;
        const tableId = Number(target.dataset.tableId);
        const table = state.data.tables.find((item) => item.id === tableId);
        if (!table) {
            return;
        }

        const rect = elements.floor.getBoundingClientRect();
        state.drag = { tableId, rect, target };
        target.classList.add('dragging');
        selectTable(tableId);

        const onMove = function (moveEvent) {
            if (!state.drag) {
                return;
            }
            moveEvent.preventDefault();
            let x = clamp(((moveEvent.clientX - rect.left) / rect.width) * 100, 0, 96);
            let y = clamp(((moveEvent.clientY - rect.top) / rect.height) * 100, 0, 92);
            if (state.snapMode) {
                x = clamp(snap(x, 2), 0, 96);
                y = clamp(snap(y, 2), 0, 92);
            }
            table.pos_x = Number(x.toFixed(1));
            table.pos_y = Number(y.toFixed(1));
            target.style.left = `${table.pos_x}%`;
            target.style.top = `${table.pos_y}%`;
            if (formFields.pos_x) {
                formFields.pos_x.value = table.pos_x.toFixed(1);
            }
            if (formFields.pos_y) {
                formFields.pos_y.value = table.pos_y.toFixed(1);
            }
        };

        const onUp = function () {
            if (state.drag?.target) {
                state.drag.target.classList.remove('dragging');
            }
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
            state.drag = null;
        };

        window.addEventListener('pointermove', onMove, { passive: false });
        window.addEventListener('pointerup', onUp);
    }

    function selectPreset(button) {
        state.builderPreset = {
            forma: button.dataset.presetShape,
            capacidad: Number(button.dataset.presetCapacity || 4),
            ancho: Number(button.dataset.presetWidth || 16),
            alto: Number(button.dataset.presetHeight || 16),
        };
        elements.presetButtons.forEach((node) => node.classList.remove('is-active'));
        button.classList.add('is-active');
        // Activar placement automáticamente al elegir un preset
        if (!state.builderPlacement) {
            state.builderPlacement = true;
            if (elements.placementBadge) {
                elements.placementBadge.textContent = 'Ubicación con clic';
                elements.placementBadge.className = 'rt-state-badge cuenta_solicitada';
            }
            if (elements.placeTableButton) {
                elements.placeTableButton.classList.remove('rt-btn-primary');
                elements.placeTableButton.classList.add('rt-btn-secondary');
            }
        }
        prepareNewTable();
        renderFloor();
        // Scroll al plano para que el usuario vea dónde hacer clic
        elements.floor?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function togglePlacementMode() {
        state.builderPlacement = !state.builderPlacement;
        if (elements.placementBadge) {
            elements.placementBadge.textContent = state.builderPlacement ? 'Ubicación con clic' : 'Edición manual';
            elements.placementBadge.className = `rt-state-badge ${state.builderPlacement ? 'cuenta_solicitada' : ''}`.trim();
        }
        if (elements.placeTableButton) {
            elements.placeTableButton.classList.toggle('rt-btn-secondary', state.builderPlacement);
            elements.placeTableButton.classList.toggle('rt-btn-primary', !state.builderPlacement);
        }
        renderFloor();
    }

    async function placeTableFromBoard(event) {
        if (state.viewMode !== 'builder' || !state.builderPlacement || !elements.floor) {
            return;
        }
        if (event.target.closest('.rt-table-node')) {
            return;
        }

        const rect = elements.floor.getBoundingClientRect();
        let x = ((event.clientX - rect.left) / rect.width) * 100;
        let y = ((event.clientY - rect.top) / rect.height) * 100;
        if (state.snapMode) {
            x = snap(x, 2);
            y = snap(y, 2);
        }
        const payload = buildTablePayload({
            table_id: null,
            codigo: '',
            nombre: '',
            area: elements.builderAreaInput?.value || formFields.area?.value || 'Salon principal',
            capacidad: state.builderPreset.capacidad,
            forma: state.builderPreset.forma,
            estado: 'disponible',
            pos_x: clamp(x, 0, 96),
            pos_y: clamp(y, 0, 92),
            ancho: state.builderPreset.ancho,
            alto: state.builderPreset.alto,
            rotacion: Number(elements.builderRotationInput?.value || 0),
        });
        await saveTable(payload);
    }

    /* ══════════════════════════════════════════════════════════════
       MODAL DE MESA — lógica de apertura, renderizado y acciones
       ══════════════════════════════════════════════════════════════ */

    const modal = {
        overlay:      document.getElementById('rtTableModal'),
        title:        document.getElementById('rtmTableTitle'),
        code:         document.getElementById('rtmTableCode'),
        status:       document.getElementById('rtmTableStatus'),
        total:        document.getElementById('rtmTotal'),
        time:         document.getElementById('rtmTime'),
        kitchen:      document.getElementById('rtmKitchen'),
        orderCode:    document.getElementById('rtmOrderCode'),
        clientName:   document.getElementById('rtmClientName'),
        dinings:      document.getElementById('rtmDinings'),
        list:         document.getElementById('rtmConsumptionList'),
        footerTotal:  document.getElementById('rtmFooterTotal'),
        payment:      document.getElementById('rtmPaymentMethod'),
        catBar:       document.getElementById('rtmCategoryBar'),
        search:       document.getElementById('rtmProductSearch'),
        productGrid:  document.getElementById('rtmProductGrid'),
        addPanel:     document.getElementById('rtmAddPanel'),
        prodName:     document.getElementById('rtmSelectedProductName'),
        prodPrice:    document.getElementById('rtmSelectedProductPrice'),
        qty:          document.getElementById('rtmQty'),
        qtyMinus:     document.getElementById('rtmQtyMinus'),
        qtyPlus:      document.getElementById('rtmQtyPlus'),
        notes:        document.getElementById('rtmNotes'),
        addBtn:       document.getElementById('rtmAddButton'),
        chargeBtn:    document.getElementById('rtmChargeButton'),
        cancelBtn:    document.getElementById('rtmCancelButton'),
        closeBtn:     document.getElementById('rtmCloseButton'),
        stateButtons: Array.from(document.querySelectorAll('.rtm-state-btn')),
    };

    // Categorías únicas de los productos (calculadas una vez)
    function getCategories() {
        const seen = new Set();
        const cats = [];
        state.products.forEach((p) => {
            const cat = p.genero_nombre || 'Sin categoría';
            if (!seen.has(cat)) {
                seen.add(cat);
                cats.push(cat);
            }
        });
        return cats.sort();
    }

    function buildCategoryBar() {
        if (!modal.catBar) return;
        // Mantener el botón "Todos" y agregar los demás
        const existing = modal.catBar.querySelectorAll('[data-cat]:not([data-cat="all"])');
        existing.forEach((b) => b.remove());

        getCategories().forEach((cat) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'rtm-cat-btn';
            btn.dataset.cat = cat;
            btn.textContent = cat;
            modal.catBar.appendChild(btn);
        });

        modal.catBar.querySelectorAll('.rtm-cat-btn').forEach((btn) => {
            btn.addEventListener('click', function () {
                modal.catBar.querySelectorAll('.rtm-cat-btn').forEach((b) => b.classList.remove('is-active'));
                this.classList.add('is-active');
                filterModalProducts(this.dataset.cat, modal.search?.value || '');
            });
        });
    }

    function renderModalProducts() {
        if (!modal.productGrid) return;
        modal.productGrid.innerHTML = '';
        state.products.forEach((product) => {
            const card = document.createElement('button');
            card.type = 'button';
            card.className = 'rtm-product-card';
            card.dataset.productId = product.id;
            card.dataset.productName = product.nombre;
            card.dataset.productPrice = product.precio;
            card.dataset.productCat = product.genero_nombre || 'Sin categoría';

            const imageSrc = resolveProductImage(product.imagen);
            const imgHtml = imageSrc
                ? `<img src="${imageSrc}" alt="${product.nombre}" loading="lazy">`
                : `<i class="fas fa-utensils"></i>`;

            card.innerHTML = `
                <div class="rtm-product-thumb">${imgHtml}</div>
                <div class="rtm-product-info">
                    <div class="rtm-product-name">${product.nombre}</div>
                    <div class="rtm-product-cat">${product.genero_nombre || ''}</div>
                    <div class="rtm-product-price">${money(product.precio)}</div>
                </div>
            `;

            card.addEventListener('click', function () {
                modal.productGrid.querySelectorAll('.rtm-product-card').forEach((c) => c.classList.remove('is-selected'));
                this.classList.add('is-selected');
                state.selectedProduct = {
                    id: Number(this.dataset.productId),
                    nombre: this.dataset.productName,
                    precio: Number(this.dataset.productPrice || 0),
                };
                if (modal.prodName) modal.prodName.textContent = state.selectedProduct.nombre;
                if (modal.prodPrice) modal.prodPrice.textContent = money(state.selectedProduct.precio);
                if (modal.qty) modal.qty.value = 1;
                if (modal.notes) modal.notes.value = '';
                if (modal.addPanel) modal.addPanel.hidden = false;
                modal.addPanel?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            });

            modal.productGrid.appendChild(card);
        });
    }

    function filterModalProducts(cat, search) {
        const searchTerm = (search || '').trim().toLowerCase();
        const allCats = !cat || cat === 'all';
        modal.productGrid?.querySelectorAll('.rtm-product-card').forEach((card) => {
            const matchCat = allCats || card.dataset.productCat === cat;
            const matchSearch = !searchTerm || card.dataset.productName.toLowerCase().includes(searchTerm);
            card.classList.toggle('is-hidden', !(matchCat && matchSearch));
        });
    }

    function renderModalConsumptions(table) {
        if (!modal.list) return;
        const order = table?.open_order || null;

        if (!order || !order.consumptions || !order.consumptions.length) {
            modal.list.innerHTML = `
                <div class="rtm-empty-order">
                    <i class="fas fa-utensils"></i>
                    <p>Aún no hay consumos.<br>Selecciona platos a la derecha.</p>
                </div>`;
            return;
        }

        modal.list.innerHTML = order.consumptions.map((item) => {
            let actionHtml = '<span class="rt-note">Servido</span>';
            if (item.estado === 'pendiente') {
                actionHtml = `<button class="rtm-ci-action" type="button" data-consumption-id="${item.id}" data-next-state="preparando"><i class="fas fa-fire-alt"></i> Cocina</button>`;
            } else if (item.estado === 'preparando') {
                actionHtml = `<button class="rtm-ci-action" type="button" data-consumption-id="${item.id}" data-next-state="servido"><i class="fas fa-check"></i> Servido</button>`;
            }

            return `
                <article class="rtm-consumption-item">
                    <div class="rtm-ci-info">
                        <div class="rtm-ci-name">${item.descripcion}</div>
                        <div class="rtm-ci-tags">
                            <span><i class="fas fa-layer-group"></i> ${item.cantidad} und</span>
                            <span class="rt-state-badge ${item.estado === 'pendiente' ? 'reservada' : item.estado === 'preparando' ? 'ocupada' : 'disponible'}">${item.estado_label}</span>
                        </div>
                        ${item.notas ? `<div class="rtm-ci-notes">${item.notas}</div>` : ''}
                    </div>
                    <div class="rtm-ci-right">
                        <span class="rtm-ci-price">${money(item.subtotal)}</span>
                        ${actionHtml}
                    </div>
                </article>
            `;
        }).join('');

        modal.list.querySelectorAll('.rtm-ci-action').forEach((btn) => {
            btn.addEventListener('click', async function () {
                await updateConsumptionState(Number(this.dataset.consumptionId), this.dataset.nextState);
                const updated = getSelectedTable();
                renderModalConsumptions(updated);
                updateModalHeader(updated);
            });
        });
    }

    function updateModalHeader(table) {
        const order = table?.open_order || null;
        if (modal.title)      modal.title.textContent   = table?.nombre || 'Mesa';
        if (modal.code) {
            modal.code.textContent = table?.codigo || '';
        }
        if (modal.status) {
            modal.status.className   = `rt-state-badge ${table?.estado || ''}`;
            modal.status.textContent = table?.estado_label || '';
        }
        if (modal.total)      modal.total.textContent   = order ? money(order.total_acumulado) : '$0';
        if (modal.time)       modal.time.textContent    = order ? `${order.minutes_open} min` : '0 min';
        if (modal.kitchen)    modal.kitchen.textContent = getKitchenStatus(order);
        if (modal.orderCode)  modal.orderCode.textContent = order ? `Cuenta #${order.id}` : 'Sin cuenta';
        if (modal.footerTotal) modal.footerTotal.textContent = order ? money(order.total_acumulado) : '$0';
        if (modal.clientName) modal.clientName.value    = order?.cliente_nombre || '';
        if (modal.dinings)    modal.dinings.value       = order?.comensales || 1;
        if (modal.payment)    modal.payment.value       = order?.payment_method || 'EFECTIVO';
    }

    function openTableModal(tableId) {
        if (!modal.overlay) return;
        state.selectedTableId = tableId;
        const table = getSelectedTable();
        if (!table) return;

        updateModalHeader(table);
        renderModalConsumptions(table);

        // Resetear panel de añadir
        state.selectedProduct = null;
        if (modal.addPanel)  modal.addPanel.hidden = true;
        if (modal.search)    modal.search.value = '';
        if (modal.catBar) {
            modal.catBar.querySelectorAll('.rtm-cat-btn').forEach((b) => b.classList.remove('is-active'));
            const allBtn = modal.catBar.querySelector('[data-cat="all"]');
            if (allBtn) allBtn.classList.add('is-active');
        }
        filterModalProducts('all', '');

        modal.overlay.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    function closeTableModal() {
        if (!modal.overlay) return;
        modal.overlay.hidden = true;
        document.body.style.overflow = '';
        state.selectedProduct = null;
    }

    async function modalAddConsumption() {
        const table = getSelectedTable();
        if (!table) { notify('Selecciona una mesa.', 'warning'); return; }
        if (!state.selectedProduct) { notify('Selecciona un plato del catálogo.', 'warning'); return; }

        try {
            await jsonRequest(endpointForTable(endpoints.addConsumptionBase, table.id), {
                product_id: state.selectedProduct.id,
                cantidad: Number(modal.qty?.value || 1),
                notas: modal.notes?.value || '',
                cliente_nombre: modal.clientName?.value || '',
                comensales: Number(modal.dinings?.value || 1),
            });

            // Resetear selección
            state.selectedProduct = null;
            if (modal.addPanel) modal.addPanel.hidden = true;
            if (modal.qty)      modal.qty.value = 1;
            if (modal.notes)    modal.notes.value = '';
            modal.productGrid?.querySelectorAll('.rtm-product-card.is-selected').forEach((c) => c.classList.remove('is-selected'));

            await refreshData(table.id);
            // Re-render consumptions in modal with fresh data
            const updated = getSelectedTable();
            renderModalConsumptions(updated);
            updateModalHeader(updated);
        } catch (error) {
            notify(error.message, 'error');
        }
    }

    async function modalChargeAccount() {
        await closeSelectedAccount();
        closeTableModal();
    }

    async function modalCancelAccount() {
        await cancelSelectedOpenAccount();
        closeTableModal();
    }

    function bindModalEvents() {
        if (!modal.overlay) return;

        modal.closeBtn?.addEventListener('click', closeTableModal);
        modal.overlay?.addEventListener('click', function (e) {
            if (e.target === modal.overlay) closeTableModal();
        });

        modal.search?.addEventListener('input', function () {
            const activeCat = modal.catBar?.querySelector('.rtm-cat-btn.is-active')?.dataset.cat || 'all';
            filterModalProducts(activeCat, this.value);
        });

        modal.qtyMinus?.addEventListener('click', function () {
            const current = Number(modal.qty?.value || 1);
            if (modal.qty && current > 1) modal.qty.value = current - 1;
        });

        modal.qtyPlus?.addEventListener('click', function () {
            const current = Number(modal.qty?.value || 1);
            if (modal.qty) modal.qty.value = current + 1;
        });

        modal.addBtn?.addEventListener('click', modalAddConsumption);
        modal.chargeBtn?.addEventListener('click', modalChargeAccount);
        modal.cancelBtn?.addEventListener('click', modalCancelAccount);

        modal.stateButtons.forEach((btn) => {
            btn.addEventListener('click', async function () {
                await changeTableState(this.dataset.nextState);
                const updated = getSelectedTable();
                updateModalHeader(updated);
                renderModalConsumptions(updated);
            });
        });

        // ESC cierra el modal
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !modal.overlay?.hidden) closeTableModal();
        });
    }

    // Inicializar modal una vez
    if (state.viewMode === 'service') {
        buildCategoryBar();
        renderModalProducts();
        bindModalEvents();
    }

    function bindEvents() {
        elements.refreshButton?.addEventListener('click', () => refreshData(state.selectedTableId));
        elements.saveTableButton?.addEventListener('click', () => saveTable());
        elements.resetSelectionButton?.addEventListener('click', prepareNewTable);
        elements.addConsumptionButton?.addEventListener('click', addConsumptionToSelectedTable);
        elements.productSearch?.addEventListener('input', filterProducts);
        elements.closeAccountButton?.addEventListener('click', closeSelectedAccount);
        elements.cancelAccountButton?.addEventListener('click', cancelSelectedOpenAccount);

        elements.quickStateButtons.forEach((button) => {
            button.addEventListener('click', async function () {
                await changeTableState(this.dataset.nextState);
            });
        });

        document.querySelectorAll('.rt-product-chip').forEach((button) => {
            button.addEventListener('click', function () {
                selectProduct(this);
            });
        });

        elements.reportActionButtons.forEach((button) => {
            button.addEventListener('click', function () {
                cancelClosedOrder(Number(this.dataset.orderId));
            });
        });

        elements.areaSwitcher?.querySelectorAll('[data-area]').forEach((button) => {
            button.addEventListener('click', function () {
                setSelectedArea(this.dataset.area);
            });
        });

        elements.floor?.addEventListener('click', placeTableFromBoard);

        if (state.viewMode === 'builder') {
            elements.placeTableButton?.addEventListener('click', togglePlacementMode);
            elements.layoutModeButton?.addEventListener('click', toggleSnapMode);
            elements.presetButtons.forEach((button) => {
                button.addEventListener('click', function () {
                    selectPreset(this);
                });
            });
        } else if (state.viewMode === 'service') {
            elements.layoutModeButton?.addEventListener('click', toggleLayoutMode);
            elements.newTableButton?.addEventListener('click', function () {
                const builderLink = document.querySelector('.rt-module-link[href*="/construccion"]');
                if (builderLink) {
                    window.location.href = builderLink.href;
                } else {
                    window.location.href = '/admin/restaurante/mesas/construccion';
                }
            });
        }
    }

    bindEvents();
    renderSummary();
    renderAreaSwitcher();
    renderFloor();
    renderSelectionPanel();

    if (state.viewMode !== 'reports') {
        window.setInterval(function () {
            if (!state.layoutMode || state.viewMode === 'builder') {
                refreshData(state.selectedTableId);
            }
        }, 15000);
    }
})();
