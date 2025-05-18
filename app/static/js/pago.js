document.addEventListener('DOMContentLoaded', function() {
    // Obtener carrito de localStorage
    const carrito = JSON.parse(localStorage.getItem('carrito')) || [];
    const listaProductos = document.getElementById('lista-productos-pago');
    const totalPago = document.getElementById('total-pago');
    
    // Mostrar resumen del pedido
    function mostrarResumen() {
        listaProductos.innerHTML = '';
        let total = 0;
        
        carrito.forEach(item => {
            const li = document.createElement('li');
            li.className = 'list-group-item';
            li.innerHTML = `
                <span>${item.nombre} x ${item.cantidad}</span>
                <span>${formatearPrecioColombiano(item.precio * item.cantidad)}</span>
            `;
            listaProductos.appendChild(li);
            total += item.precio * item.cantidad;
        });
        
        totalPago.textContent = formatearPrecioColombiano(total);
    }
    
    // Función para convertir "$15.000,00" a 15000
    function parsearPrecioColombiano(precioStr) {
        return parseFloat(precioStr.replace(/[.$]/g, '').replace(',', '.'));
    }
    
    // Función para convertir 15000 a "$15.000,00"
    function formatearPrecioColombiano(valor) {
        return valor.toLocaleString('es-CO', {
            style: 'currency',
            currency: 'COP',
            minimumFractionDigits: 2
        });
    }
    
    // Cambiar sección según método de pago seleccionado
    function configurarMetodosPago() {
        const metodosPago = document.querySelectorAll('input[name="metodoPago"]');
        
        metodosPago.forEach(radio => {
            radio.addEventListener('change', function() {
                // Ocultar todas las secciones
                document.querySelectorAll('.seccion-metodo').forEach(div => {
                    div.style.display = 'none';
                });
                
                // Mostrar la sección correspondiente al método seleccionado
                const seccionId = `seccion${this.value}`;
                const seccion = document.getElementById(seccionId);
                if (seccion) {
                    seccion.style.display = 'block';
                }
            });
            
            // Mostrar sección inicial si está seleccionada
            if (radio.checked) {
                const seccionId = `seccion${radio.value}`;
                const seccion = document.getElementById(seccionId);
                if (seccion) {
                    seccion.style.display = 'block';
                }
            }
        });
    }
    
    // Cargar lista de bancos para PSE desde el backend
    function cargarBancos() {
        const selectBanco = document.getElementById('banco');
        if (!selectBanco) return;
        
        fetch('/get_banks')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Error al obtener bancos');
                }
                return response.json();
            })
            .then(data => {
                if (data.banks && Array.isArray(data.banks)) {
                    // Limpiar opciones existentes (excepto la primera)
                    while (selectBanco.options.length > 1) {
                        selectBanco.remove(1);
                    }
                    
                    // Añadir nuevos bancos
                    data.banks.forEach(banco => {
                        const option = document.createElement('option');
                        option.value = banco.pseCode;
                        option.textContent = banco.description;
                        selectBanco.appendChild(option);
                    });
                }
            })
            .catch(error => {
                console.error('Error al cargar bancos:', error);
                // Opcional: Mostrar mensaje al usuario
            });
    }
    
    // Validar formulario antes de enviar
    function validarFormulario(formData) {
        // Validar datos básicos
        if (!formData.nombreCompleto || !formData.email || !formData.telefono || 
            !formData.tipoDocumento || !formData.numeroDocumento) {
            return 'Por favor complete todos los campos obligatorios';
        }
        
        // Validar email
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(formData.email)) {
            return 'Por favor ingrese un email válido';
        }
        
        // Validar método PSE
        if (formData.metodoPago === 'PSE') {
            if (!formData.banco || !formData.tipoCuenta) {
                return 'Por favor seleccione banco y tipo de cuenta para PSE';
            }
        }
        
        return null; // No hay errores
    }
    
    // Manejar el envío del formulario de pago
    function configurarEnvioPago() {
        const formulario = document.getElementById('formularioPago');
        if (!formulario) return;
        
        formulario.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Obtener datos del formulario
            const formData = {
                nombreCompleto: document.getElementById('nombreCompleto').value.trim(),
                email: document.getElementById('email').value.trim(),
                telefono: document.getElementById('telefono').value.trim(),
                tipoDocumento: document.getElementById('tipoDocumento').value,
                numeroDocumento: document.getElementById('numeroDocumento').value.trim(),
                metodoPago: document.querySelector('input[name="metodoPago"]:checked').value,
                productos: carrito,
                total: carrito.reduce((sum, item) => sum + (item.precio * item.cantidad), 0)
            };
            
            // Datos específicos por método de pago
            if (formData.metodoPago === 'PSE') {
                formData.banco = document.getElementById('banco').value;
                formData.tipoCuenta = document.getElementById('tipoCuenta').value;
            } else if (formData.metodoPago === 'TC') {
                formData.numeroTarjeta = document.getElementById('numeroTarjeta').value.trim();
                formData.fechaExpiracion = document.getElementById('fechaExpiracion').value.trim();
                formData.codigoSeguridad = document.getElementById('codigoSeguridad').value.trim();
            }
            
            // Validar formulario
            const error = validarFormulario(formData);
            if (error) {
                alert(error);
                return;
            }
            
            // Mostrar loader (opcional)
            const btnPagar = document.querySelector('.btn-pagar');
            const originalText = btnPagar.innerHTML;
            btnPagar.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Procesando...';
            btnPagar.disabled = true;
            
            // Enviar datos al servidor
            fetch('/iniciar_pago', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Error en la respuesta del servidor');
                }
                return response.json();
            })
            .then(data => {
                if (data.success && data.url_pago) {
                    // Limpiar carrito después de pago exitoso
                    localStorage.removeItem('carrito');
                    // Redirigir a PayU
                    window.location.href = data.url_pago;
                } else {
                    throw new Error(data.error || 'No se pudo procesar el pago');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert(error.message || 'Error al conectar con el servidor');
            })
            .finally(() => {
                // Restaurar botón
                if (btnPagar) {
                    btnPagar.innerHTML = originalText;
                    btnPagar.disabled = false;
                }
            });
        });
    }
    
    // Inicializar la página
    function init() {
        if (carrito.length === 0) {
            // Opcional: Redirigir si el carrito está vacío
            window.location.href = '/productos';
            return;
        }
        
        mostrarResumen();
        configurarMetodosPago();
        cargarBancos();
        configurarEnvioPago();
    }
    
    // Iniciar la aplicación
    init();
});