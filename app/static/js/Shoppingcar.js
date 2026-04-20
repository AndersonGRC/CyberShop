/**
 * Shoppingcar.js — Carrito de compras del lado del cliente.
 *
 * Gestiona todo el ciclo de vida del carrito usando localStorage:
 * - Agregar/eliminar productos con animacion de vuelo
 * - Control de cantidades (+/-)
 * - Calculo de subtotales y total
 * - Sincronizacion del badge en menu de escritorio, movil y boton flotante
 * - Envio del carrito al backend para iniciar el flujo de pago
 *
 * Dependencias: SweetAlert2 (notificaciones), Font Awesome (iconos)
 */

// =============================================
// VARIABLES GLOBALES
// =============================================
let carrito = JSON.parse(localStorage.getItem('carrito')) || [];

// =============================================
// FUNCIONES DE UTILIDAD
// =============================================
const parsearPrecio = (precioStr) => {
    if (typeof precioStr === 'number') return precioStr;
    if (!precioStr) return 0;
    if (!isNaN(precioStr)) return parseFloat(precioStr);
    const limpio = precioStr.toString().replace(/[^0-9,.-]/g, '').replace(/\./g, '').replace(',', '.');
    return parseFloat(limpio) || 0;
};

const formatearPrecio = (valor) => {
    const numero = parsearPrecio(valor);
    return numero.toLocaleString('es-CO', { style: 'currency', currency: 'COP', minimumFractionDigits: 0 });
};

const mostrarNotificacion = (mensaje, tipo = 'info') => {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: tipo === 'error' ? 'error' : 'success',
            title: tipo === 'error' ? 'Error' : 'Genial',
            text: mensaje,
            toast: true,
            position: 'bottom-end', // Lo cambié abajo para no tapar el menú
            showConfirmButton: false,
            timer: 2000
        });
    }
};

const mostrarLoader = () => {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'flex';
};

const ocultarLoader = () => {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'none';
};

// =============================================
// ANIMACIÓN: ARCO AL CARRITO
// =============================================
const animarVuelo = (imagenOrigen) => {

    // 1. Determinar destino según dispositivo (768px = breakpoint CSS)
    const destinoEl = window.innerWidth <= 768
        ? document.querySelector('.cart-floating-button a')
        : document.getElementById('menu-carrito-icon');

    if (!destinoEl || !imagenOrigen) return;

    const rectOrigen  = imagenOrigen.getBoundingClientRect();
    const rectDestino = destinoEl.getBoundingClientRect();

    // 2. Crear thumbnail volador (tamaño fijo, no clonar el DOM entero)
    const SIZE = 60;
    const clon = document.createElement('div');
    Object.assign(clon.style, {
        position:      'fixed',
        zIndex:        '9999',
        top:           `${rectOrigen.top  + rectOrigen.height / 2 - SIZE / 2}px`,
        left:          `${rectOrigen.left + rectOrigen.width  / 2 - SIZE / 2}px`,
        width:         `${SIZE}px`,
        height:        `${SIZE}px`,
        borderRadius:  '10px',
        overflow:      'hidden',
        pointerEvents: 'none',
        boxShadow:     '0 6px 20px rgba(0,0,0,0.35)',
        willChange:    'transform, opacity',
    });

    const imgEl = document.createElement('img');
    imgEl.src = imagenOrigen.currentSrc || imagenOrigen.src;
    Object.assign(imgEl.style, {
        width: '100%', height: '100%', objectFit: 'cover', display: 'block'
    });
    clon.appendChild(imgEl);
    document.body.appendChild(clon);

    // 3. Calcular puntos del arco
    // Centros de origen y destino
    const startCX = rectOrigen.left  + rectOrigen.width  / 2;
    const startCY = rectOrigen.top   + rectOrigen.height / 2;
    const endCX   = rectDestino.left + rectDestino.width  / 2;
    const endCY   = rectDestino.top  + rectDestino.height / 2;

    // Punto de control del arco: por encima del punto medio
    const arcCX = (startCX + endCX) / 2;
    const arcCY = Math.min(startCY, endCY) - 110;

    // Desplazamientos relativos al centro inicial del clon
    const dx1 = arcCX - startCX;
    const dy1 = arcCY - startCY;
    const dx2 = endCX - startCX;
    const dy2 = endCY - startCY;

    // 4. Animar con Web Animations API (arco real de 3 puntos)
    const anim = clon.animate([
        {
            transform:    'translate(0, 0) scale(1) rotate(0deg)',
            opacity:      1,
            borderRadius: '10px',
        },
        {
            transform:    `translate(${dx1}px, ${dy1}px) scale(0.6) rotate(14deg)`,
            opacity:      0.88,
            borderRadius: '50%',
            offset:       0.45,
        },
        {
            transform:    `translate(${dx2}px, ${dy2}px) scale(0.08) rotate(28deg)`,
            opacity:      0,
            borderRadius: '50%',
        },
    ], {
        duration: 1100,
        easing:   'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
        fill:     'forwards',
    });

    // 5. Al terminar: limpiar + impacto en carrito
    anim.onfinish = () => {
        clon.remove();

        // Rebote en todos los badges
        document.querySelectorAll('.cart-badge').forEach(badge => {
            badge.classList.remove('bounce');
            void badge.offsetWidth;
            badge.classList.add('bounce');
            setTimeout(() => badge.classList.remove('bounce'), 400);
        });

        // Pulso de impacto en el ícono del carrito
        destinoEl.classList.remove('cart-hit');
        void destinoEl.offsetWidth;
        destinoEl.classList.add('cart-hit');
        setTimeout(() => destinoEl.classList.remove('cart-hit'), 500);
    };
};

// =============================================
// LÓGICA DE CARRITO
// =============================================
const actualizarBadge = () => {
    // 1. Calcular total
    const totalItems = carrito.reduce((acc, item) => acc + (parseInt(item.cantidad) || 1), 0);

    // 2. BUSCAR TODOS LOS CONTADORES (Menu escritorio, menu movil, flotante)
    // Usamos la clase .cart-badge en lugar del ID
    const badges = document.querySelectorAll('.cart-badge');

    // 3. Actualizar cada uno
    badges.forEach(badge => {
        badge.textContent = totalItems;

        if (totalItems > 0) {
            // Usamos flex para centrar el numero
            badge.style.display = 'flex';
            badge.style.justifyContent = 'center';
            badge.style.alignItems = 'center';

            // Reiniciar animación de rebote
            badge.classList.remove('bounce');
            void badge.offsetWidth; // Truco para reiniciar animación
            badge.classList.add('bounce');
        } else {
            badge.style.display = 'none';
        }
    });
};

const guardarCarrito = () => {
    localStorage.setItem('carrito', JSON.stringify(carrito));
    actualizarBadge();
};

const actualizarCarrito = () => {
    // Buscar tabla (solo existe en carrito.html)
    const tablaCuerpo = document.getElementById('lista-carrito-body');
    const totalPagina = document.getElementById('total-pagina');
    const mensajeVacio = document.getElementById('mensaje-vacio');
    const controlesFinales = document.getElementById('controles-finales');
    const tablaHeader = document.querySelector('.tabla-carrito'); // Para ocultar cabecera si está vacío

    let totalCalculado = 0;
    carrito.forEach(item => {
        totalCalculado += parsearPrecio(item.precio) * (parseInt(item.cantidad) || 1);
    });

    if (tablaCuerpo) {
        tablaCuerpo.innerHTML = '';

        if (carrito.length === 0) {
            if (mensajeVacio) mensajeVacio.style.display = 'block';
            if (controlesFinales) controlesFinales.style.display = 'none';
            if (tablaHeader) tablaHeader.style.display = 'none';
        } else {
            if (mensajeVacio) mensajeVacio.style.display = 'none';
            if (controlesFinales) controlesFinales.style.display = 'flex';
            if (tablaHeader) tablaHeader.style.display = 'table';
        }

        carrito.forEach((item) => {
            const precio = parsearPrecio(item.precio);
            const cantidad = parseInt(item.cantidad) || 1;
            const subtotal = precio * cantidad;

            // SECURITY A3: Construir DOM sin innerHTML para evitar XSS
            const tr = document.createElement('tr');

            // Columna producto
            const tdProd = document.createElement('td');
            const divProd = document.createElement('div');
            divProd.style.cssText = 'display:flex; align-items:center; gap:10px;';
            const img = document.createElement('img');
            img.src = item.imagen || '';
            img.className = 'img-carrito-preview';
            const divTexto = document.createElement('div');
            const strong = document.createElement('strong');
            strong.textContent = item.nombre || '';
            const br = document.createElement('br');
            const small = document.createElement('small');
            small.textContent = item.referencia || '';
            divTexto.appendChild(strong);
            divTexto.appendChild(br);
            divTexto.appendChild(small);
            divProd.appendChild(img);
            divProd.appendChild(divTexto);
            tdProd.appendChild(divProd);

            // Columna precio
            const tdPrecio = document.createElement('td');
            tdPrecio.textContent = formatearPrecio(precio);

            // Columna controles cantidad
            const tdCtrl = document.createElement('td');
            const divCtrl = document.createElement('div');
            divCtrl.className = 'item-controls';
            const btnMenos = document.createElement('button');
            btnMenos.className = 'disminuir btn-control';
            btnMenos.dataset.id = item.id;
            btnMenos.textContent = '-';
            const spanCant = document.createElement('span');
            spanCant.className = 'cantidad';
            spanCant.textContent = cantidad;
            const btnMas = document.createElement('button');
            btnMas.className = 'aumentar btn-control';
            btnMas.dataset.id = item.id;
            btnMas.textContent = '+';
            divCtrl.appendChild(btnMenos);
            divCtrl.appendChild(spanCant);
            divCtrl.appendChild(btnMas);
            tdCtrl.appendChild(divCtrl);

            // Columna subtotal
            const tdSub = document.createElement('td');
            tdSub.textContent = formatearPrecio(subtotal);

            // Columna eliminar
            const tdElim = document.createElement('td');
            const btnElim = document.createElement('button');
            btnElim.className = 'eliminar-item';
            btnElim.dataset.id = item.id;
            const icon = document.createElement('i');
            icon.className = 'fas fa-trash';
            btnElim.appendChild(icon);
            tdElim.appendChild(btnElim);

            tr.appendChild(tdProd);
            tr.appendChild(tdPrecio);
            tr.appendChild(tdCtrl);
            tr.appendChild(tdSub);
            tr.appendChild(tdElim);
            tablaCuerpo.appendChild(tr);
        });

        if (totalPagina) {
            totalPagina.textContent = formatearPrecio(totalCalculado);
            totalPagina.dataset.valor = totalCalculado;
        }
    }

    guardarCarrito(); // Actualiza localStorage y el badge

    // Validar botones de aumento y botones de catalogo

    // 1. Resetear estado visual de TODOS los productos en catalogo (por si se elimino algo)
    document.querySelectorAll('.producto').forEach(card => {
        const id = card.dataset.id;
        const stockMax = parseInt(card.dataset.stock) || 0;
        const btnAgregar = card.querySelector('.añadir-carrito') || card.querySelector('.agotado-btn');
        const stockInfo = card.querySelector('.stock-info span');

        // Buscar cantidad en carrito
        const itemEnCarrito = carrito.find(i => i.id === id);
        const cantidadEnCarrito = itemEnCarrito ? (parseInt(itemEnCarrito.cantidad) || 0) : 0;

        const disponibles = stockMax - cantidadEnCarrito;

        // Actualizar texto de disponibles
        if (stockInfo) {
            stockInfo.textContent = disponibles > 0 ? disponibles : 0;
            stockInfo.style.color = disponibles < 5 ? 'red' : 'green';
        }

        // Deshabilitar boton si ya no hay stock real
        if (btnAgregar && !btnAgregar.classList.contains('agotado-btn')) { // No tocar los que ya venian agotados de server
            if (cantidadEnCarrito >= stockMax) {
                btnAgregar.disabled = true;
                btnAgregar.textContent = 'Max. Alcanzado';
                btnAgregar.style.backgroundColor = 'var(--color-gris-deshabilitado)';
                btnAgregar.style.cursor = 'not-allowed';
            } else {
                btnAgregar.disabled = false;
                btnAgregar.textContent = 'Añadir al carrito';
                btnAgregar.style.backgroundColor = ''; // Restaurar color original (CSS)
                btnAgregar.style.cursor = 'pointer';
            }
        }
    });

    // 2. Validar botones "+" dentro del carrito
    carrito.forEach(item => {
        if (parseInt(item.cantidad) >= parseInt(item.stock)) {
            const btn = document.querySelector(`.aumentar[data-id="${item.id}"]`);
            if (btn) {
                btn.disabled = true;
                btn.style.opacity = '0.5';
                btn.style.cursor = 'not-allowed';
            }
        }
    });
};

// Anti double-click: evita agregar duplicados por clic rápido
let _agregandoAlCarrito = false;

const agregarAlCarrito = (producto, imagenElemento) => {
    if (_agregandoAlCarrito) return;
    _agregandoAlCarrito = true;
    setTimeout(() => { _agregandoAlCarrito = false; }, 1000);

    const precio = parsearPrecio(producto.precio);
    const itemExistente = carrito.find(item => item.id === producto.id);

    // Animación visual
    if (imagenElemento) {
        animarVuelo(imagenElemento);
    }

    if (itemExistente) {
        if (parseInt(itemExistente.cantidad) + 1 > parseInt(producto.stock)) {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    icon: 'warning',
                    title: 'Límite alcanzado',
                    text: `Solo hay ${producto.stock} unidades disponibles de este producto.`
                });
            } else {
                alert(`Solo hay ${producto.stock} unidades disponibles de este producto.`);
            }
            return;
        }
        itemExistente.cantidad = (parseInt(itemExistente.cantidad) || 1) + 1;
    } else {
        carrito.push({ ...producto, precio: precio, cantidad: 1, stock: parseInt(producto.stock) });
    }

    // Esperamos un poco a que la animación llegue para actualizar el número
    setTimeout(() => {
        actualizarCarrito();
    }, 800);

    // Feedback visual opcional
    // mostrarNotificacion(`${producto.nombre} agregado`, 'success');
};

// =============================================
// EVENTOS
// =============================================
const configurarEventos = () => {

    // 1. Agregar desde PRODUCTOS
    document.querySelectorAll('.añadir-carrito').forEach(boton => {
        boton.addEventListener('click', (e) => {
            const card = boton.closest('.producto');
            if (!card) return;

            // Buscamos la imagen dentro de la tarjeta para animarla
            const imagen = card.querySelector('img');

            const producto = {
                id: card.dataset.id,
                nombre: card.dataset.name,
                precio: card.dataset.price,
                imagen: card.dataset.image,
                referencia: card.dataset.reference,
                stock: card.dataset.stock
            };
            agregarAlCarrito(producto, imagen);
        });
    });

    // 2. Eventos dentro del CARRITO (Delegación)
    const contenedor = document.querySelector('.container');
    if (contenedor) {
        contenedor.addEventListener('click', (e) => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const id = btn.dataset.id;

            if (btn.classList.contains('aumentar')) {
                const item = carrito.find(i => i.id === id);
                if (item) {
                    if (parseInt(item.cantidad) + 1 > parseInt(item.stock)) {
                        if (typeof Swal !== 'undefined') {
                            Swal.fire({
                                icon: 'warning',
                                title: 'Stock Máximo',
                                text: `No puedes agregar más. Solo hay ${item.stock} unidades disponibles.`,
                                timer: 2000,
                                showConfirmButton: false
                            });
                        } else {
                            alert(`No puedes agregar más. Solo hay ${item.stock} unidades disponibles.`);
                        }
                        return;
                    }
                    item.cantidad++;
                    actualizarCarrito();
                }
            }
            else if (btn.classList.contains('disminuir')) {
                const item = carrito.find(i => i.id === id);
                if (item) {
                    if (item.cantidad > 1) {
                        item.cantidad--;
                        actualizarCarrito();
                    } else {
                        if (confirm("¿Eliminar producto?")) {
                            carrito = carrito.filter(i => i.id !== id);
                            actualizarCarrito();
                        }
                    }
                }
            }
            else if (btn.classList.contains('eliminar-item')) {
                if (confirm("¿Eliminar producto?")) {
                    carrito = carrito.filter(i => i.id !== id);
                    actualizarCarrito();
                }
            }
            else if (btn.id === 'vaciar-carrito-btn') {
                if (confirm('¿Vaciar todo el carrito?')) {
                    carrito = [];
                    actualizarCarrito();
                }
            }
            else if (btn.id === 'procesar-pedido-btn') {
                procesarPago();
            }
        });
    }

};

// Lógica de Pago — SECURITY C1: enviar por POST, no exponer carrito en URL
const procesarPago = async () => {
    if (carrito.length === 0) return alert("Carrito vacío");
    mostrarLoader();

    // Solo enviar IDs y cantidades; el backend recalcula precios desde BD
    const data = {
        items: carrito.map(i => ({
            id: i.id,
            nombre: i.nombre,
            imagen: i.imagen,
            referencia: i.referencia,
            cantidad: parseInt(i.cantidad) || 1
        }))
    };

    // Obtener token CSRF del meta tag para que Flask-WTF acepte la peticion
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    try {
        const resp = await fetch('/procesar-carrito', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });
        if (resp.ok) {
            window.location.href = '/metodos-pago';
        } else {
            ocultarLoader();
            alert('Error al procesar el carrito. Intenta de nuevo.');
        }
    } catch (err) {
        ocultarLoader();
        alert('Error de conexión. Intenta de nuevo.');
    }
};

// INICIO
document.addEventListener('DOMContentLoaded', () => {
    configurarEventos();
    actualizarCarrito(); // Carga inicial del badge o la tabla
});