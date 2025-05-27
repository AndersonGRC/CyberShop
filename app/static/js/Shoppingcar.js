// =============================================
// VARIABLES GLOBALES Y CONFIGURACIÓN INICIAL
// =============================================
let carrito = JSON.parse(localStorage.getItem('carrito')) || [];
let productos = []; // Para almacenar los productos disponibles

// =============================================
// FUNCIONES DE UTILIDAD
// =============================================
// Asegura una conversión robusta a número sin errores por puntos y comas
const parsearPrecio = (precioStr) => {
    if (typeof precioStr === 'number') return precioStr;
    if (!precioStr) return 0;

    // Verifica si ya es un número válido
    if (!isNaN(precioStr)) return parseFloat(precioStr);

    // Si viene con puntos o comas en formato string
    const limpio = precioStr.toString()
        .replace(/[^0-9,.-]/g, '')     // Elimina caracteres no numéricos
        .replace(/\./g, '')           // Elimina puntos de miles
        .replace(',', '.');           // Sustituye la coma decimal por punto

    const valor = parseFloat(limpio);
    return isNaN(valor) ? 0 : valor;
};

// Formateador para mostrar como moneda en COP
const formatearPrecio = (valor) => {
    const numero = parsearPrecio(valor);
    return numero.toLocaleString('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    });
};


const mostrarNotificacion = (mensaje, tipo = 'info') => {
    console.log(`[${tipo.toUpperCase()}] ${mensaje}`);
    alert(`[${tipo.toUpperCase()}] ${mensaje}`);
};

const mostrarLoader = () => {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'flex';
    else console.warn("Elemento 'loader' no encontrado en el DOM");
};

const ocultarLoader = () => {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'none';
    else console.warn("Elemento 'loader' no encontrado en el DOM");
};

// =============================================
// FUNCIONES PRINCIPALES DEL CARRITO
// =============================================
const guardarCarrito = () => {
    localStorage.setItem('carrito', JSON.stringify(carrito));
    sessionStorage.setItem('carritoPendiente', JSON.stringify({
        items: carrito,
        total: parsearPrecio(document.getElementById('total').textContent)
    }));
};

const actualizarCarrito = () => {
    const listaCarrito = document.getElementById('lista-carrito');
    const totalElement = document.getElementById('total');
    listaCarrito.innerHTML = '';
    let total = 0;
    carrito.forEach(item => {
        const precio = parsearPrecio(item.precio);
        const cantidad = parseInt(item.cantidad) || 1;
        const subtotal = precio * cantidad;
        total += subtotal;

        const li = document.createElement('li');
        li.dataset.id = item.id;
        li.innerHTML = `
            <div class="item-info">
                <img src="${item.imagen}" alt="${item.nombre}" width="50">
                <span>${item.nombre}</span>
                <span>${formatearPrecio(precio)}</span>
            </div>
            <div class="item-controls">
                <button class="disminuir" data-id="${item.id}">-</button>
                <span class="cantidad">${cantidad}</span>
                <button class="aumentar" data-id="${item.id}">+</button>
                <button class="eliminar-item" data-id="${item.id}">✕</button>
            </div>
        `;
        listaCarrito.appendChild(li);
    });

    totalElement.textContent = formatearPrecio(total);
    guardarCarrito();
};

const agregarAlCarrito = (producto) => {
    const precio = parsearPrecio(producto.precio);
    const itemExistente = carrito.find(item => item.id === producto.id);
    
    if (itemExistente) {
        itemExistente.cantidad++;
    } else {
        carrito.push({
            ...producto,
            precio: precio,
            cantidad: 1
        });
    }
    actualizarCarrito();
};

// =============================================
// MANEJADORES DE EVENTOS
// =============================================
const configurarEventos = () => {
    // Añadir productos al carrito
    document.querySelectorAll('.añadir-carrito').forEach(boton => {
        boton.addEventListener('click', () => {
            const productoElemento = boton.closest('.producto');
            const producto = {
                id: productoElemento.dataset.id,
                nombre: productoElemento.dataset.name,
                precio: productoElemento.dataset.price,
                imagen: productoElemento.dataset.image,
                referencia: productoElemento.dataset.reference
            };
            agregarAlCarrito(producto);
        });
    });

    // Manejar eventos del carrito
    document.getElementById('lista-carrito').addEventListener('click', (e) => {
        const id = e.target.dataset.id;
        const item = carrito.find(item => item.id === id);
        if (!item) return;

        if (e.target.classList.contains('aumentar')) {
            item.cantidad++;
        } else if (e.target.classList.contains('disminuir')) {
            item.cantidad > 1 ? item.cantidad-- : carrito = carrito.filter(i => i.id !== id);
        } else if (e.target.classList.contains('eliminar-item')) {
            carrito = carrito.filter(i => i.id !== id);
        }
        actualizarCarrito();
    });

    // Vaciar carrito
    document.getElementById('vaciar-carrito').addEventListener('click', () => {
        carrito = [];
        actualizarCarrito();
        mostrarNotificacion('Carrito vaciado', 'info');
    });

    // Procesar pago
    document.getElementById('pagar-carrito').addEventListener('click', async () => {
        try {
            if (carrito.length === 0) {
                mostrarNotificacion('Tu carrito está vacío', 'error');
                return;
            }

            mostrarLoader();
            
            const carritoData = {
                items: carrito,
                total: parsearPrecio(document.getElementById('total').textContent)
            };

            const response = await fetch('/procesar-carrito', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(carritoData)
            });

            const result = await response.json();
            
            if (!response.ok || !result.success) {
                throw new Error(result.error || 'Error al procesar el pago');
            }

            window.location.href = "/metodos-pago";
        } catch (error) {
            console.error('Error:', error);
            mostrarNotificacion(error.message, 'error');
        } finally {
            ocultarLoader();
        }
    });

    // Popup de detalles
    document.querySelectorAll('.ver-descripcion').forEach(boton => {
        boton.addEventListener('click', () => {
            const producto = boton.closest('.producto');
            document.getElementById('popup-imagen').src = producto.dataset.image;
            document.getElementById('popup-titulo').textContent = producto.dataset.name;
            document.getElementById('popup-referencia').textContent = producto.dataset.reference;
            document.getElementById('popup-genero').textContent = producto.dataset.gender;
            document.getElementById('popup-descripcion-texto').textContent = producto.dataset.description;
            document.getElementById('popup-precio').textContent = formatearPrecio(parsearPrecio(producto.dataset.price));
            document.getElementById('popup-descripcion').style.display = 'flex';
        });
    });

    // Cerrar popup
    document.querySelector('.cerrar-popup').addEventListener('click', () => {
        document.getElementById('popup-descripcion').style.display = 'none';
    });
};

// =============================================
// INICIALIZACIÓN
// =============================================
document.addEventListener('DOMContentLoaded', () => {
    configurarEventos();
    actualizarCarrito();
    
    // Cargar productos desde el backend (opcional)
    fetch('/api/productos')
        .then(response => response.json())
        .then(data => {
            productos = data;
        })
        .catch(error => console.error('Error cargando productos:', error));
});