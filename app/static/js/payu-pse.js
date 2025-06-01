// payu-pse.js
document.addEventListener('DOMContentLoaded', function() {
    // Variables globales
    let currentStep = 1;
    const totalSteps = 3;
    let bancosDisponibles = [];
    let pseData = {
        financialInstitutionCode: '',
        userType: '',
        pseReference2: '',
        pseReference3: '',
        buyerFullName: '',
        buyerEmail: '',
        buyerPhone: '',
        shippingStreet1: '',
        shippingCity: '',
        shippingState: '',
        shippingPostalCode: '',
        billingStreet1: '',
        billingCity: '',
        billingState: '',
        billingPostalCode: '',
        deviceSessionId: '',
        cookie: '',
        userAgent: navigator.userAgent
    };

    // Elementos del DOM
    const paso1 = document.getElementById('paso-1');
    const paso2 = document.getElementById('paso-2');
    const paso3 = document.getElementById('paso-3');
    const selectBanco = document.getElementById('select-banco');
    const btnPagar = document.getElementById('btn-pagar');
    const mismaDireccionCheckbox = document.getElementById('same-as-shipping');
    const facturacionContainer = document.getElementById('facturacion-container');

    // Inicialización
    init();

    function init() {
        setupEventListeners();
        cargarBancos();
        generateDeviceSessionId();
    }

    function setupEventListeners() {
        // Navegación
        document.getElementById('seleccionar-pse').addEventListener('click', () => nextStep());
        
        document.querySelectorAll('.btn-volver').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                prevStep();
            });
        });

        document.querySelectorAll('.btn-continuar').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                nextStep();
            });
        });

        // Selección de banco
        selectBanco.addEventListener('change', function() {
            pseData.financialInstitutionCode = this.value;
            document.querySelector('#paso-2 .btn-continuar').disabled = !this.value;
        });

        // Dirección de facturación
        if (mismaDireccionCheckbox) {
            mismaDireccionCheckbox.addEventListener('change', function() {
                facturacionContainer.style.display = this.checked ? 'none' : 'block';
                if (!this.checked) {
                    document.querySelectorAll('#facturacion-container [required]').forEach(input => {
                        input.required = true;
                    });
                }
            });
        }

        // Procesar pago
        btnPagar.addEventListener('click', procesarPagoPSE);
    }

    function cargarBancos() {
          fetch('/api/payu/bancos', {
        method: 'GET',
            headers: {
            'Authorization': 'Bearer token_valido', // 👈 Esto es lo que faltaba
            'Content-Type': 'application/json'
            }
        })
            .then(response => {
                if (!response.ok) throw new Error('Error al cargar bancos');
                return response.json();
            })
            .then(data => {
                bancosDisponibles = data;
                actualizarSelectBancos();
            })
            .catch(error => {
                console.error('Error cargando bancos:', error);
                selectBanco.innerHTML = '<option value="">Error cargando bancos. Intente nuevamente.</option>';
            });
    }

    function actualizarSelectBancos() {
        selectBanco.innerHTML = '<option value="">- Seleccione su banco -</option>';
        
        bancosDisponibles.forEach(banco => {
            const option = document.createElement('option');
            option.value = banco.pseCode || banco.codigo;
            option.textContent = banco.description || banco.nombre;
            selectBanco.appendChild(option);
        });
    }

    function nextStep() {
        if (currentStep >= totalSteps) return;
        
        // Validar datos antes de avanzar
        if (currentStep === 2 && !pseData.financialInstitutionCode) {
            alert('Por favor selecciona un banco');
            return;
        }
        
        if (currentStep === 3) {
            if (!validarDatosPagador()) return;
            recopilarDatosPagador();
        }

        document.getElementById(`paso-${currentStep}`).classList.remove('paso-activo');
        document.getElementById(`paso-${currentStep}`).classList.add('paso-oculto');
        
        currentStep++;
        document.getElementById(`paso-${currentStep}`).classList.remove('paso-oculto');
        document.getElementById(`paso-${currentStep}`).classList.add('paso-activo');
    }

    function prevStep() {
        if (currentStep <= 1) return;
        
        document.getElementById(`paso-${currentStep}`).classList.remove('paso-activo');
        document.getElementById(`paso-${currentStep}`).classList.add('paso-oculto');
        
        currentStep--;
        document.getElementById(`paso-${currentStep}`).classList.remove('paso-oculto');
        document.getElementById(`paso-${currentStep}`).classList.add('paso-activo');
    }

    function validarDatosPagador() {
        const requiredFields = [
            'tipo-persona', 'tipo-documento', 'numero-documento',
            'nombre-titular', 'telefono', 'email',
            'shipping-street1', 'shipping-city', 'shipping-state', 'shipping-postalcode'
        ];

        let isValid = true;

        requiredFields.forEach(fieldId => {
            const field = document.getElementById(fieldId);
            if (!field || !field.value) {
                field.style.borderColor = '#e74c3c';
                isValid = false;
            } else {
                field.style.borderColor = '';
            }
        });

        // Validar campos de facturación si son visibles
        if (!mismaDireccionCheckbox.checked) {
            const billingFields = [
                'billing-street1', 'billing-city', 'billing-state', 'billing-postalcode'
            ];

            billingFields.forEach(fieldId => {
                const field = document.getElementById(fieldId);
                if (!field || !field.value) {
                    field.style.borderColor = '#e74c3c';
                    isValid = false;
                } else {
                    field.style.borderColor = '';
                }
            });
        }

        if (!isValid) {
            alert('Por favor completa todos los campos obligatorios');
            return false;
        }

        // Validación adicional del email
        const email = document.getElementById('email').value;
        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            alert('Por favor ingresa un correo electrónico válido');
            return false;
        }

        // Validación del teléfono
        const telefono = document.getElementById('telefono').value;
        if (!/^[0-9]{10,15}$/.test(telefono)) {
            alert('Por favor ingresa un número de teléfono válido (10-15 dígitos)');
            return false;
        }

        return true;
    }

    function recopilarDatosPagador() {
        pseData = {
            userType: document.getElementById('tipo-persona').value,
            pseReference2: document.getElementById('tipo-documento').value,
            pseReference3: document.getElementById('numero-documento').value,
            buyerFullName: document.getElementById('nombre-titular').value,
            buyerPhone: document.getElementById('telefono').value,
            buyerEmail: document.getElementById('email').value,
            shippingStreet1: document.getElementById('shipping-street1').value,
            shippingCity: document.getElementById('shipping-city').value,
            shippingState: document.getElementById('shipping-state').value,
            shippingPostalCode: document.getElementById('shipping-postalcode').value,
            deviceSessionId: generateDeviceSessionId(),
            cookie: getCookie('session_id') || 'cookie_' + Math.random().toString(36).substring(2),
            userAgent: navigator.userAgent
        };

        // Dirección de facturación
        if (mismaDireccionCheckbox.checked) {
            pseData.billingStreet1 = pseData.shippingStreet1;
            pseData.billingCity = pseData.shippingCity;
            pseData.billingState = pseData.shippingState;
            pseData.billingPostalCode = pseData.shippingPostalCode;
        } else {
            pseData.billingStreet1 = document.getElementById('billing-street1').value;
            pseData.billingCity = document.getElementById('billing-city').value;
            pseData.billingState = document.getElementById('billing-state').value;
            pseData.billingPostalCode = document.getElementById('billing-postalcode').value;
        }
    }

    function generateDeviceSessionId() {
        return 'dsid_' + Math.random().toString(36).substring(2) + '_' + new Date().getTime();
    }

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
    }

    async function procesarPagoPSE() {
        if (!validarDatosPagador()) return;
        recopilarDatosPagador();

        try {
            // Obtener el total del carrito
            const total = parseFloat(document.querySelector('.total .subtotal').textContent.replace(/[^0-9.]/g, ''));

            // Mostrar loader
            document.getElementById('loader').style.display = 'flex';

            // Enviar a tu backend que se comunicará con PayU
            const response = await fetch('/api/payu/procesar-pse', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ...pseData,
                    body: JSON.stringify(pseData)
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || 'Error al procesar el pago');
            }

            if (data.success && data.transaction.paymentUrl) {
                window.location.href = data.transaction.paymentUrl;
            } else {
                throw new Error('No se pudo obtener la URL de pago');
            }
            
        } catch (error) {
            console.error('Error:', error);
            alert(`Error al procesar el pago: ${error.message}`);
        } finally {
            document.getElementById('loader').style.display = 'none';
        }
    }
});