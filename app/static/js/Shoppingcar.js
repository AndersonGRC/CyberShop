document.addEventListener('DOMContentLoaded', () => {
    const carrito = [];
    const listaCarrito = document.getElementById('lista-carrito');
    const totalElement = document.getElementById('total');
    const botonesAñadir = document.querySelectorAll('.añadir-carrito');
    const botonVaciar = document.getElementById('vaciar-carrito');

    // Añadir productos al carrito
    botonesAñadir.forEach(boton => {
        boton.addEventListener('click', () => {
            const producto = boton.parentElement;
            const id = producto.getAttribute('data-id');
            const nombre = producto.getAttribute('data-name');
            const precio = parseFloat(producto.getAttribute('data-price'));

            // Verificar si el producto ya está en el carrito
            const productoEnCarrito = carrito.find(item => item.id === id);
            if (productoEnCarrito) {
                productoEnCarrito.cantidad += 1;
            } else {
                carrito.push({ id, nombre, precio, cantidad: 1 });
            }

            actualizarCarrito();
        });
    });

    // Vaciar carrito
    botonVaciar.addEventListener('click', () => {
        carrito.length = 0;
        actualizarCarrito();
    });

    // Actualizar la vista del carrito
    function actualizarCarrito() {
        listaCarrito.innerHTML = '';
        let total = 0;

        carrito.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `
                ${item.nombre} 
                <span>${item.cantidad} x $${item.precio.toFixed(2)}</span>
            `;
            listaCarrito.appendChild(li);
            total += item.cantidad * item.precio;
        });

        totalElement.textContent = `$${total.toFixed(2)}`;
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

            // Mostrar el pop-up con los detalles del producto
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