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
// ANIMACIÓN: VOLAR AL CARRITO
// =============================================
const animarVuelo = (imagenOrigen) => {

    // 1. Determinar el Destino según el dispositivo
    let destinoFinal;

    // Si la pantalla es menor a 800px (Móvil según tu CSS)
    if (window.innerWidth <= 800) {
        // MÓVIL: El destino es el botón flotante redondo
        destinoFinal = document.querySelector('.cart-floating-button a');
    } else {
        // PC: El destino es el ícono en la barra de menú
        destinoFinal = document.getElementById('menu-carrito-icon');
    }

    // Validación de seguridad: si no existe el destino elegido, no hacemos nada
    if (!destinoFinal || !imagenOrigen) return;

    // 2. Clonar la imagen
    const imagenClon = imagenOrigen.cloneNode(true);

    // 3. Obtener coordenadas (Aquí está la magia: calcula dónde está el destino AHORA)
    const rectOrigen = imagenOrigen.getBoundingClientRect();
    const rectDestino = destinoFinal.getBoundingClientRect();

    // 4. Configurar estilo inicial del clon (encima de la imagen original)
    imagenClon.classList.add('fly-img');
    imagenClon.style.top = `${rectOrigen.top}px`;
    imagenClon.style.left = `${rectOrigen.left}px`;
    imagenClon.style.width = `${rectOrigen.width}px`;
    imagenClon.style.height = `${rectOrigen.height}px`;
    imagenClon.style.opacity = '1';

    document.body.appendChild(imagenClon);

    // 5. Iniciar animación hacia el destino calculado
    setTimeout(() => {
        // Ajustamos +10px para que caiga en el centro del ícono
        imagenClon.style.top = `${rectDestino.top + 10}px`;
        imagenClon.style.left = `${rectDestino.left + 10}px`;
        imagenClon.style.width = '20px'; // Se hace pequeña
        imagenClon.style.height = '20px';
        imagenClon.style.opacity = '0.5';
    }, 50);

    // 6. Limpiar al terminar
    setTimeout(() => {
        imagenClon.remove();

        // Efecto de rebote en TODOS los badges (para que se vea en móvil y PC)
        const badges = document.querySelectorAll('.cart-badge');
        badges.forEach(badge => {
            badge.classList.add('bounce');
            setTimeout(() => badge.classList.remove('bounce'), 300);
        });

    }, 800);
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

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <div style="display:flex; align-items:center; gap:10px;">
                        <img src="${item.imagen}" class="img-carrito-preview">
                        <div>
                            <strong>${item.nombre}</strong><br>
                            <small>${item.referencia || ''}</small>
                        </div>
                    </div>
                </td>
                <td>${formatearPrecio(precio)}</td>
                <td>
                    <div class="item-controls">
                        <button class="disminuir btn-control" data-id="${item.id}">-</button>
                        <span class="cantidad">${cantidad}</span>
                        <button class="aumentar btn-control" data-id="${item.id}">+</button>
                    </div>
                </td>
                <td>${formatearPrecio(subtotal)}</td>
                <td>
                    <button class="eliminar-item" data-id="${item.id}">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            `;
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

const agregarAlCarrito = (producto, imagenElemento) => {
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

    // 3. Popups (sin cambios)
    document.querySelectorAll('.ver-descripcion').forEach(boton => {
        boton.addEventListener('click', () => {
            const card = boton.closest('.producto');
            const popup = document.getElementById('popup-descripcion');
            if (popup) {
                document.getElementById('popup-imagen').src = card.dataset.image;
                document.getElementById('popup-titulo').textContent = card.dataset.name;
                document.getElementById('popup-referencia').textContent = card.dataset.reference;
                document.getElementById('popup-genero').textContent = card.dataset.gender;
                document.getElementById('popup-descripcion-texto').textContent = card.dataset.description;
                document.getElementById('popup-precio').textContent = formatearPrecio(parsearPrecio(card.dataset.price));
                popup.style.display = 'flex';
            }
        });
    });

    const cerrar = document.querySelector('.cerrar-popup');
    if (cerrar) cerrar.addEventListener('click', () => document.getElementById('popup-descripcion').style.display = 'none');

    window.addEventListener('click', (e) => {
        const popup = document.getElementById('popup-descripcion');
        if (popup && e.target === popup) popup.style.display = 'none';
    });
};

// Lógica de Pago
const procesarPago = () => {
    if (carrito.length === 0) return alert("Carrito vacío");
    mostrarLoader();

    let total = 0;
    carrito.forEach(i => total += parsearPrecio(i.precio) * (parseInt(i.cantidad) || 1));

    const data = { items: carrito, total: total };
    sessionStorage.setItem('carritoPendiente', JSON.stringify(data));
    localStorage.setItem('carrito', JSON.stringify(carrito));

    window.location.href = `/metodos-pago?carrito=${encodeURIComponent(JSON.stringify(data))}`;
};

// INICIO
document.addEventListener('DOMContentLoaded', () => {
    configurarEventos();
    actualizarCarrito(); // Carga inicial del badge o la tabla
});