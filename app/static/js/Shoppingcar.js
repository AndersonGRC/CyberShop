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
});