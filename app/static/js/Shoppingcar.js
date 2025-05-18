document.addEventListener('DOMContentLoaded', () => {
    const carrito = JSON.parse(localStorage.getItem('carrito')) || [];
    const listaCarrito = document.getElementById('lista-carrito');
    const totalElement = document.getElementById('total');
    const botonesAñadir = document.querySelectorAll('.añadir-carrito');
    const botonVaciar = document.getElementById('vaciar-carrito');
    const botonPagar = document.getElementById('pagar-carrito');  // Añadido

    // Función para convertir "$15.000,00" a 15000
    function parsearPrecioColombiano(precioStr) {
        return parseFloat(precioStr.replace(/[.$]/g, '').replace(',', '.'));
    }

     function guardarCarrito() {
        localStorage.setItem('carrito', JSON.stringify(carrito));
    }
    // Función para convertir 15000 a "$15.000,00"
    function formatearPrecioColombiano(valor) {
        return valor.toLocaleString('es-CO', {
            style: 'currency',
            currency: 'COP',
            minimumFractionDigits: 2
        });
    }

    // Añadir productos al carrito
    botonesAñadir.forEach(boton => {
        boton.addEventListener('click', () => {
            const producto = boton.parentElement;
            const id = producto.getAttribute('data-id');
            const nombre = producto.getAttribute('data-name');
            const precioStr = producto.getAttribute('data-price');
            const precio = parsearPrecioColombiano(precioStr);
            const productoEnCarrito = carrito.find(item => item.id === id);
            if (productoEnCarrito) {
                productoEnCarrito.cantidad += 1;
            } else {
                carrito.push({ id, nombre, precio, cantidad: 1 });
            }
            guardarCarrito(); // <-- Añadir esta línea
            actualizarCarrito();
        });
    });

    // Vaciar carrito
    botonVaciar.addEventListener('click', () => {
        carrito.length = 0;
        guardarCarrito(); // <-- Añadir esta línea
        actualizarCarrito();
    });

    // Botón de pagar
  // Botón de pagar
botonPagar.addEventListener('click', () => {
    if (carrito.length === 0) {
        alert('Tu carrito está vacío. Agrega productos antes de pagar.');
    } else {
        // Calcular el total
        guardarCarrito(); // <-- Añadir esta línea
        const total = carrito.reduce((sum, item) => sum + (item.precio * item.cantidad), 0);
        
            // Enviar datos al servidor
            fetch('/iniciar_pago', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    productos: carrito,
                    total: total
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.url_pago) {
                    // Limpiar carrito después de pagar
                    carrito.length = 0;
                    localStorage.removeItem('carrito');
                    window.location.href = data.url_pago;
                } else {
                    alert('Error al iniciar el pago');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Error al conectar con el servidor');
            });
        }
    });

    // Actualizar la vista del carrito
    function actualizarCarrito() {
        listaCarrito.innerHTML = '';
        let total = 0;

        carrito.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `
                ${item.nombre} 
                <span>${item.cantidad} x ${formatearPrecioColombiano(item.precio)}</span>
            `;
            listaCarrito.appendChild(li);
            total += item.cantidad * item.precio;
        });

        totalElement.textContent = formatearPrecioColombiano(total);
    }

    // Lógica para el pop-up de detalles del producto
    const botonesDescripcion = document.querySelectorAll('.ver-descripcion');
    const popup = document.getElementById('popup-descripcion');
    const popupImagen = document.getElementById('popup-imagen');
    const popupTitulo = document.getElementById('popup-titulo');
    const popupReferencia = document.getElementById('popup-referencia');
    const popupGenero = document.getElementById('popup-genero');
    const popupDescripcion = document.getElementById('popup-descripcion-texto');
    const popupPrecio = document.getElementById('popup-precio');
    const cerrarPopup = document.querySelector('.cerrar-popup');

    botonesDescripcion.forEach(boton => {
        boton.addEventListener('click', () => {
            const producto = boton.parentElement;
            const nombre = producto.getAttribute('data-name');
            const referencia = producto.getAttribute('data-reference');
            const genero = producto.getAttribute('data-gender');
            const descripcion = producto.getAttribute('data-description');
            const precio = producto.getAttribute('data-price');
            const imagen = producto.getAttribute('data-image');

            popupImagen.src = imagen;
            popupTitulo.textContent = nombre;
            popupReferencia.textContent = referencia;
            popupGenero.textContent = genero;
            popupDescripcion.textContent = descripcion;
            popupPrecio.textContent = precio;
            popup.style.display = 'flex';
        });
    });

    // Cerrar el pop-up
    cerrarPopup.addEventListener('click', () => {
        popup.style.display = 'none';
    });

    // Cerrar el pop-up al hacer clic fuera del contenido
    window.addEventListener('click', (event) => {
        if (event.target === popup) {
            popup.style.display = 'none';
        }
    });
});

// En tu Shoppingcar.js
localStorage.setItem('carrito', JSON.stringify(carrito));
window.location.href = '/pagar';