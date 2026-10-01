/*
 * Prueba gratis — asistente de 4 pasos.
 * Sin JS el formulario completo funciona igual (mismo POST y validación del
 * servidor); esto solo lo presenta paso a paso, sugiere la dirección web,
 * verifica que esté libre y muestra en vivo cómo quedará su página.
 */
(function () {
    'use strict';
    var form = document.getElementById('tgForm');
    if (!form) return;
    var page = form.closest('.tg-page');
    var pasos = Array.prototype.slice.call(form.querySelectorAll('.tg-step'));
    var bar = document.getElementById('tgBar');
    var marcas = Array.prototype.slice.call(document.querySelectorAll('.tg-progress-steps li'));
    var btnAtras = document.getElementById('tgAtras');
    var btnSig = document.getElementById('tgSiguiente');
    var btnCrear = document.getElementById('tgCrear');
    var $ = function (id) { return document.getElementById(id); };
    var actual = 1;
    var slugEstado = { valor: '', libre: null };

    page.classList.add('tg-js');

    /* ── Pasos ─────────────────────────────────────────── */
    function mostrar(n) {
        actual = Math.max(1, Math.min(pasos.length, n));
        pasos.forEach(function (p) { p.classList.toggle('is-on', Number(p.dataset.step) === actual); });
        marcas.forEach(function (m) {
            var i = Number(m.dataset.ind);
            m.classList.toggle('is-on', i === actual);
            m.classList.toggle('is-done', i < actual);
        });
        if (bar) bar.style.width = (actual / pasos.length * 100) + '%';
        btnAtras.hidden = actual === 1;
        btnSig.hidden = actual === pasos.length;
        btnCrear.hidden = actual !== pasos.length;
        if (actual === 4) resumen();
        if (actual === 3) vistaPrevia();
        var primero = pasos[actual - 1].querySelector('input:not([type="radio"]):not([type="hidden"])');
        if (primero && window.matchMedia('(pointer: fine)').matches) primero.focus({ preventScroll: true });
        // El menú del sitio es fijo: se deja la tarjeta debajo de él, no tapada.
        var tarjeta = form.closest('.tg-card').getBoundingClientRect();
        // Al desplazarse, el menú (.nav) se vuelve fijo arriba (body.nav_fixed).
        var menu = document.querySelector('header .nav');
        var alto = menu ? menu.offsetHeight : 0;
        if (tarjeta.top < alto || tarjeta.top > window.innerHeight * 0.6) {
            window.scrollTo({ top: window.scrollY + tarjeta.top - alto - 16, behavior: 'smooth' });
        }
    }

    function pasoValido(n) {
        var campos = pasos[n - 1].querySelectorAll('input[required], input[pattern]');
        for (var i = 0; i < campos.length; i++) {
            var c = campos[i];
            c.classList.toggle('is-invalid', !c.checkValidity());
            if (!c.checkValidity()) { c.reportValidity(); return false; }
        }
        if (n === 2 && slugEstado.libre === false && slugEstado.valor === $('tgSlug').value) {
            $('tgSlug').focus();
            return false;
        }
        if (n === 3 && contrasteMalo(colorElegido())) return false;
        return true;
    }

    btnSig.addEventListener('click', function () { if (pasoValido(actual)) mostrar(actual + 1); });
    btnAtras.addEventListener('click', function () { mostrar(actual - 1); });
    form.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && e.target.tagName === 'INPUT' && actual < pasos.length) {
            e.preventDefault();
            btnSig.click();
        }
    });
    form.addEventListener('submit', function (e) {
        for (var n = 1; n <= pasos.length; n++) {
            if (!pasoValido(n)) { e.preventDefault(); mostrar(n); pasoValido(n); return; }
        }
        btnCrear.disabled = true;
        btnCrear.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Preparando tu tienda…';
    });

    /* ── Dirección web: sugerida desde el nombre y verificada en vivo ── */
    function slugify(t) {
        return String(t || '').toLowerCase()
            .normalize('NFD').replace(/[̀-ͯ]/g, '')
            .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '');
    }
    var slugManual = !!$('tgSlug').value;
    var temporizador = null;
    function verificarSlug() {
        var s = $('tgSlug').value, est = $('tgSlugEstado');
        clearTimeout(temporizador);
        slugEstado = { valor: s, libre: null };
        if (s.length < 3) { est.textContent = ''; est.className = 'tg-slug-estado'; return; }
        est.textContent = 'Revisando si está libre…';
        est.className = 'tg-slug-estado is-busy';
        temporizador = setTimeout(function () {
            fetch(form.dataset.slugUrl + '?s=' + encodeURIComponent(s), { headers: { 'Accept': 'application/json' } })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if ($('tgSlug').value !== s) return;
                    slugEstado = { valor: s, libre: d.disponible };
                    if (d.disponible === true) {
                        est.innerHTML = '<i class="fas fa-check-circle"></i> ¡Disponible! Tu tienda será https://' + s + '.cybershopcol.com';
                        est.className = 'tg-slug-estado is-ok';
                    } else if (d.disponible === false) {
                        est.innerHTML = '<i class="fas fa-times-circle"></i> ' + (d.motivo || 'No disponible.');
                        est.className = 'tg-slug-estado is-mal';
                    } else {
                        est.textContent = '';
                        est.className = 'tg-slug-estado';
                    }
                })
                .catch(function () { est.textContent = ''; est.className = 'tg-slug-estado'; });
        }, 450);
    }
    $('tgNegocio').addEventListener('input', function () {
        if (!slugManual) { $('tgSlug').value = slugify(this.value); verificarSlug(); }
        vistaPrevia();
    });
    $('tgSlug').addEventListener('input', function () {
        slugManual = true;
        var limpio = slugify(this.value.replace(/-$/, '')) + (/-$/.test(this.value) ? '-' : '');
        if (this.value !== limpio) this.value = limpio;
        verificarSlug();
    });
    if ($('tgSlug').value) verificarSlug();

    /* ── Diseño: color, frase y vista previa en vivo ── */
    function hexRgb(h) { return [1, 3, 5].map(function (i) { return parseInt(h.slice(i, i + 2), 16); }); }
    function mezclar(a, b, p) {
        var x = hexRgb(a), y = hexRgb(b);
        return '#' + x.map(function (v, i) {
            return ('0' + Math.round(v + (y[i] - v) * p).toString(16)).slice(-2);
        }).join('');
    }
    function contraste(h) {
        var l = hexRgb(h).map(function (v) {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return 1.05 / (0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2] + 0.05);
    }
    function colorElegido() {
        var r = form.querySelector('input[name="color_marca"]:checked');
        return r ? r.value : '#334155';
    }
    function contrasteMalo(h) {
        var aviso = $('tgColorAviso'), malo = !/^#[0-9a-f]{6}$/i.test(h) || contraste(h) < 3;
        aviso.hidden = !malo;
        if (malo) aviso.textContent = 'Ese color es muy claro: el texto blanco de botones y títulos no se leería. Elige un tono más oscuro.';
        return malo;
    }
    function vistaPrevia() {
        var c = colorElegido().toLowerCase(), prev = $('tgPreview');
        if (/^#[0-9a-f]{6}$/.test(c)) {
            page.style.setProperty('--tg-marca', c);
            page.style.setProperty('--tg-marca-oscuro', mezclar(c, '#0b1220', 0.78));
            page.style.setProperty('--tg-marca-claro', mezclar(c, '#ffffff', 0.92));
        }
        var nombre = $('tgNegocio').value.trim() || 'Tu negocio';
        $('tgpNombre').textContent = nombre;
        $('tgpNombre2').textContent = nombre;
        $('tgpPie').textContent = '© ' + nombre;
        $('tgpLema').textContent = $('tgLema').value.trim() || 'Así se verá tu página principal';
        contrasteMalo(c);
        if (prev) prev.setAttribute('aria-label', 'Vista previa de ' + nombre);
    }
    form.querySelectorAll('input[name="color_marca"]').forEach(function (r) { r.addEventListener('change', vistaPrevia); });
    $('tgColorLibre').addEventListener('input', function () {
        var radio = $('tgColorLibreRadio');
        radio.value = this.value;
        radio.checked = true;
        vistaPrevia();
    });
    $('tgLema').addEventListener('input', vistaPrevia);

    /* ── Resumen ── */
    function resumen() {
        var s = $('tgSlug').value || 'minegocio';
        $('tgrUrl').textContent = 'https://' + s + '.cybershopcol.com';
        $('tgrEmail').textContent = $('tgEmail').value.trim() || '(tu correo)';
    }
    $('tgEmail').addEventListener('input', resumen);

    var errorPaso = Number(form.dataset.errorPaso || 0);
    vistaPrevia();
    mostrar(errorPaso || 1);
})();
