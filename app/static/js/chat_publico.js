/* static/js/chat_publico.js — Widget del chat público (módulo ai_public).
 *
 * Solo se carga cuando /chat/config respondió 200 (ver bootstrap en
 * layout.js), que además deja el resultado en window.__CBCHAT_CONFIG__ para
 * no volver a pedirlo. Sin sesión propia: el CSRF real se lee del
 * <meta name="csrf-token"> que ya trae toda página pública, igual que
 * cualquier otro POST del sitio.
 */
(function () {
    'use strict';

    var config = window.__CBCHAT_CONFIG__ || {};
    var MAX_HISTORIAL = 8;
    var historial = [];
    var enviando = false;
    var abierto = false;
    var ref = null;

    // Mismo corte que el @media de chat_publico.css: en celular el panel va a
    // pantalla completa.
    var MOVIL = window.matchMedia('(max-width: 768px)');

    // Verificación humana (reCAPTCHA), solo si el servidor la trae configurada
    // en /chat/config. Una vez resuelta, el token firmado que el servidor
    // devuelve sirve para el resto de la conversación — no hay que repetirla
    // en cada mensaje. Sin sesión ni cookies: vive solo en esta variable, se
    // pierde al recargar la página (igual que el resto del estado del chat).
    var verificacionToken = null;
    var recaptchaListoPromesa = null;

    // Mismo nombre que _CAMPO_SENUELO en routes/chat_publico.py.
    var CAMPO_SENUELO = 'asunto_web';

    // Cara de robot (no un globo de chat): a propósito, para que se note a
    // simple vista que del otro lado hay un asistente automático, no una
    // persona — antena + cabeza redondeada + dos ojos + boca.
    var ICONO_ROBOT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="M12 7V4"></path>' +
        '<circle cx="12" cy="3" r="1" fill="currentColor" stroke="none"></circle>' +
        '<rect x="5" y="7" width="14" height="12" rx="3"></rect>' +
        '<circle cx="9.5" cy="13" r="1.3" fill="currentColor" stroke="none"></circle>' +
        '<circle cx="14.5" cy="13" r="1.3" fill="currentColor" stroke="none"></circle>' +
        '<path d="M9.5 16.5h5"></path></svg>';
    var ICONO_CERRAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line>' +
        '<line x1="6" y1="6" x2="18" y2="18"></line></svg>';
    var ICONO_ENVIAR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line>' +
        '<polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';

    function crear(tag, attrs, hijos) {
        var el = document.createElement(tag);
        attrs = attrs || {};
        Object.keys(attrs).forEach(function (k) {
            if (k === 'class') el.className = attrs[k];
            else if (k === 'text') el.textContent = attrs[k];
            else if (k === 'html') el.innerHTML = attrs[k];  // solo iconos SVG propios, nunca datos externos
            else el.setAttribute(k, attrs[k]);
        });
        (hijos || []).forEach(function (h) { el.appendChild(h); });
        return el;
    }

    function tokenCsrf() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function construir() {
        var root = crear('div', { id: 'cbchat-root' });

        var launcher = crear('button', {
            id: 'cbchat-launcher', type: 'button', 'aria-expanded': 'false',
            'aria-controls': 'cbchat-panel', 'aria-label': 'Abrir chat'
        }, [
            crear('span', { class: 'cbchat-icon-abrir', 'aria-hidden': 'true', html: ICONO_ROBOT }),
            crear('span', { class: 'cbchat-icon-cerrar', 'aria-hidden': 'true', html: ICONO_CERRAR })
        ]);

        // Mismo icono de robot en el encabezado del panel: para que quede
        // claro DURANTE toda la conversación (no solo antes de abrir) que
        // se está hablando con un asistente automático, no una persona.
        var avatar = crear('div', { id: 'cbchat-avatar', 'aria-hidden': 'true', html: ICONO_ROBOT });
        var titulo = crear('div', { id: 'cbchat-titulo', text: config.negocio || 'Chat' });
        var subtitulo = crear('div', { id: 'cbchat-subtitulo', text: 'Asistente automático · responde al instante' });
        var cerrar = crear('button', {
            id: 'cbchat-cerrar', type: 'button', 'aria-label': 'Cerrar chat', html: ICONO_CERRAR
        });
        var header = crear('div', { id: 'cbchat-header' }, [
            avatar,
            crear('div', { id: 'cbchat-header-info' }, [titulo, subtitulo]),
            cerrar
        ]);

        var mensajes = crear('div', { id: 'cbchat-mensajes', role: 'log', 'aria-live': 'polite' });
        var sugerenciasWrap = crear('div', { id: 'cbchat-sugerencias' });
        (config.sugerencias || []).forEach(function (texto) {
            var chip = crear('button', { class: 'cbchat-chip', type: 'button', text: texto });
            chip.addEventListener('click', function () { enviarPregunta(texto); });
            sugerenciasWrap.appendChild(chip);
        });

        var input = crear('textarea', {
            id: 'cbchat-input', rows: '1', maxlength: '1000',
            placeholder: 'Escribe tu pregunta…', 'aria-label': 'Escribe tu pregunta'
        });
        var contador = crear('div', { id: 'cbchat-contador', 'aria-hidden': 'true', text: '0/1000' });
        var enviar = crear('button', {
            id: 'cbchat-enviar', type: 'submit', 'aria-label': 'Enviar', html: ICONO_ENVIAR
        });
        // Señuelo anti-bot: fuera de pantalla (no display:none — un poco más
        // difícil de detectar solo mirando el estilo en línea), nunca visible
        // ni alcanzable con tab para un visitante real.
        var senuelo = crear('input', {
            type: 'text', id: 'cbchat-senuelo', class: 'cbchat-senuelo',
            tabindex: '-1', autocomplete: 'off', 'aria-hidden': 'true'
        });
        var campoWrap = crear('div', { id: 'cbchat-campo' }, [input, contador]);
        var form = crear('form', { id: 'cbchat-form' }, [campoWrap, enviar, senuelo]);

        var panel = crear('div', {
            id: 'cbchat-panel', role: 'dialog', 'aria-modal': 'true',
            'aria-labelledby': 'cbchat-titulo', hidden: 'hidden'
        }, [header, mensajes, sugerenciasWrap, form]);

        root.appendChild(launcher);
        root.appendChild(panel);
        document.body.appendChild(root);

        launcher.addEventListener('click', function () { abierto ? cerrarPanel() : abrirPanel(); });
        cerrar.addEventListener('click', cerrarPanel);
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && abierto) cerrarPanel();
        });
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var texto = input.value.trim();
            if (!texto) return;
            input.value = '';
            input.style.height = 'auto';
            enviarPregunta(texto);
        });
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (form.requestSubmit) form.requestSubmit();
                else form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        });
        input.addEventListener('input', function () {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 90) + 'px';
            var restantes = 1000 - input.value.length;
            contador.textContent = input.value.length + '/1000';
            contador.classList.toggle('cbchat-contador-cerca', restantes <= 100);
        });

        ref = { launcher: launcher, panel: panel, input: input, mensajes: mensajes,
                sugerenciasWrap: sugerenciasWrap, enviar: enviar, senuelo: senuelo,
                cerrar: cerrar };

        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', ajustarAlVisor);
            window.visualViewport.addEventListener('scroll', ajustarAlVisor);
        }
        if (MOVIL.addEventListener) MOVIL.addEventListener('change', ajustarAlVisor);

        if (config.saludo) agregarMensaje('bot', config.saludo);
    }

    // Celular: el panel se ajusta al área que de verdad se ve (visualViewport).
    // El teclado virtual achica solo esa área, no la ventana: sin esto el campo
    // quedaba debajo del teclado o el encabezado —con la X— se salía por arriba.
    // Y si la página desborda a lo ancho (p. ej. a 320 px), el navegador agranda
    // el área de los elementos fijos y la X quedaba fuera de la pantalla.
    // En escritorio (o cerrado) manda solo el CSS.
    function ajustarAlVisor() {
        var vv = window.visualViewport;
        if (!ref) return;
        var ajustar = vv && abierto && MOVIL.matches;
        ref.panel.style.left = ajustar ? vv.offsetLeft + 'px' : '';
        ref.panel.style.top = ajustar ? vv.offsetTop + 'px' : '';
        ref.panel.style.width = ajustar ? vv.width + 'px' : '';
        ref.panel.style.height = ajustar ? vv.height + 'px' : '';
    }

    function abrirPanel() {
        abierto = true;
        ref.panel.hidden = false;
        document.body.classList.add('cbchat-abierto');
        ref.launcher.setAttribute('aria-expanded', 'true');
        ref.launcher.setAttribute('aria-label', 'Cerrar chat');
        ajustarAlVisor();
        ref.mensajes.scrollTop = ref.mensajes.scrollHeight;
        // En celular no se abre el teclado de golpe (taparía el saludo y las
        // sugerencias): el foco va a la X, dentro del diálogo.
        window.setTimeout(function () {
            if (MOVIL.matches) ref.cerrar.focus();
            else ref.input.focus();
        }, 30);
    }

    function cerrarPanel() {
        abierto = false;
        ref.panel.hidden = true;
        document.body.classList.remove('cbchat-abierto');
        ref.launcher.setAttribute('aria-expanded', 'false');
        ref.launcher.setAttribute('aria-label', 'Abrir chat');
        ajustarAlVisor();
        ref.launcher.focus();
    }

    function agregarMensaje(rol, texto) {
        var burbuja = crear('div', {
            class: rol === 'usuario' ? 'cbchat-msg cbchat-msg-usuario' : 'cbchat-msg cbchat-msg-bot',
            text: texto
        });
        ref.mensajes.appendChild(burbuja);
        ref.mensajes.scrollTop = ref.mensajes.scrollHeight;
        return burbuja;
    }

    function agregarEspera() {
        var espera = crear('div', { class: 'cbchat-msg-espera' },
            [crear('span'), crear('span'), crear('span')]);
        ref.mensajes.appendChild(espera);
        ref.mensajes.scrollTop = ref.mensajes.scrollHeight;
        return espera;
    }

    function agregarWhatsapp(numero) {
        if (!numero) return;
        var link = crear('a', {
            id: 'cbchat-whatsapp-cta', href: 'https://wa.me/' + numero,
            target: '_blank', rel: 'noopener', text: 'Hablar por WhatsApp'
        });
        ref.mensajes.appendChild(link);
        ref.mensajes.scrollTop = ref.mensajes.scrollHeight;
    }

    function enviarPregunta(texto) {
        if (enviando) return;
        if (config.recaptcha_site_key && !verificacionToken) {
            mostrarTarjetaVerificacion(texto);
            return;
        }
        _enviarAhora(texto, null);
    }

    function _enviarAhora(texto, recaptchaToken) {
        enviando = true;
        ref.enviar.disabled = true;
        ref.sugerenciasWrap.hidden = true;

        agregarMensaje('usuario', texto);
        var espera = agregarEspera();

        var cuerpo = { pregunta: texto, historial: historial };
        cuerpo[CAMPO_SENUELO] = (ref.senuelo && ref.senuelo.value) || '';
        if (recaptchaToken) cuerpo.recaptcha = recaptchaToken;
        if (verificacionToken) cuerpo.verificacion = verificacionToken;

        fetch('/chat/mensaje', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': tokenCsrf() },
            body: JSON.stringify(cuerpo)
        }).then(function (r) {
            if (r.status === 429) {
                return Promise.reject({ amable: 'Muchas preguntas seguidas — dame un momento y '
                                                 + 'vuelve a escribirme.' });
            }
            if (r.status === 400) {
                return r.json().then(function (d) {
                    if (d && d.error === 'verificacion_requerida') {
                        verificacionToken = null;
                        return Promise.reject({ amable: null, repetirVerificacion: true });
                    }
                    return Promise.reject({ amable: null });
                }).catch(function () { return Promise.reject({ amable: null }); });
            }
            if (!r.ok) return Promise.reject({ amable: null });
            return r.json();
        }).then(function (datos) {
            espera.remove();
            agregarMensaje('bot', datos.respuesta);
            if (datos.verificacion) verificacionToken = datos.verificacion;
            historial.push({ rol: 'usuario', texto: texto });
            historial.push({ rol: 'asistente', texto: datos.respuesta });
            if (historial.length > MAX_HISTORIAL) historial = historial.slice(-MAX_HISTORIAL);
            if (datos.escalar && datos.whatsapp) agregarWhatsapp(datos.whatsapp);
        }).catch(function (err) {
            espera.remove();
            if (err && err.repetirVerificacion) {
                mostrarTarjetaVerificacion(texto);
                return;
            }
            var msg = (err && err.amable) || 'No pude responder en este momento. Intenta de nuevo en un momento.';
            agregarMensaje('bot', msg);
            if (config.whatsapp) agregarWhatsapp(config.whatsapp);
        }).finally(function () {
            enviando = false;
            ref.enviar.disabled = false;
        });
    }

    // ── Verificación humana (solo si /chat/config trajo recaptcha_site_key) ──
    function cargarRecaptcha() {
        if (recaptchaListoPromesa) return recaptchaListoPromesa;
        recaptchaListoPromesa = new Promise(function (resolve, reject) {
            window.__cbchatRecaptchaListo = resolve;
            var script = document.createElement('script');
            script.src = 'https://www.google.com/recaptcha/api.js?onload=__cbchatRecaptchaListo&render=explicit';
            script.async = true;
            script.defer = true;
            script.onerror = function () { reject(new Error('no se pudo cargar recaptcha')); };
            document.head.appendChild(script);
        });
        return recaptchaListoPromesa;
    }

    function mostrarTarjetaVerificacion(textoPendiente) {
        var tarjeta = crear('div', { id: 'cbchat-verificacion' }, [
            crear('p', { text: 'Antes de continuar, confirma que eres una persona:' }),
            crear('div', { id: 'cbchat-recaptcha-caja' })
        ]);
        ref.mensajes.appendChild(tarjeta);
        ref.mensajes.scrollTop = ref.mensajes.scrollHeight;

        cargarRecaptcha().then(function () {
            var caja = tarjeta.querySelector('#cbchat-recaptcha-caja');
            if (!caja) return;  // la tarjeta ya se quitó (el usuario cerró el chat, etc.)
            window.grecaptcha.render(caja, {
                sitekey: config.recaptcha_site_key,
                callback: function (token) {
                    tarjeta.remove();
                    _enviarAhora(textoPendiente, token);
                }
            });
        }).catch(function () {
            tarjeta.remove();
            agregarMensaje('bot', 'No se pudo cargar la verificación. Intenta de nuevo en un momento.');
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', construir);
    } else {
        construir();
    }
})();
