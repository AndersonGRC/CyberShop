/*
 * Prueba gratis — asistente de 4 pasos.
 * Sin JS el formulario completo funciona igual (mismo POST y validación del
 * servidor); esto solo lo presenta paso a paso, sugiere la dirección web,
 * verifica que esté libre y muestra en vivo cómo quedará su página.
 */
(function () {
    'use strict';

    /* ── Correo: sugerencia si parece mal escrito (gmial.com → gmail.com) ── */
    var TYPOS = {
        'gmial.com': 'gmail.com', 'gmal.com': 'gmail.com', 'gamil.com': 'gmail.com', 'gmai.com': 'gmail.com',
        'gmail.co': 'gmail.com', 'gmail.con': 'gmail.com', 'gmail.cm': 'gmail.com', 'gmaill.com': 'gmail.com',
        'gnail.com': 'gmail.com', 'gimail.com': 'gmail.com', 'gmail.es': 'gmail.com', 'gmail.om': 'gmail.com',
        'hotmial.com': 'hotmail.com', 'hotmal.com': 'hotmail.com', 'hotmail.co': 'hotmail.com',
        'hotmail.con': 'hotmail.com', 'homail.com': 'hotmail.com', 'hotmai.com': 'hotmail.com',
        'outlok.com': 'outlook.com', 'outloo.com': 'outlook.com', 'outlook.co': 'outlook.com',
        'outlook.con': 'outlook.com', 'yaho.com': 'yahoo.com', 'yahoo.co': 'yahoo.com',
        'yahoo.con': 'yahoo.com', 'yhaoo.com': 'yahoo.com', 'icloud.co': 'icloud.com', 'iclod.com': 'icloud.com'
    };
    function sugerirCorreo(input, caja) {
        if (!input || !caja) return;
        function revisar() {
            var v = input.value.trim().toLowerCase(), partes = v.split('@');
            var sugerido = partes.length === 2 && TYPOS[partes[1]] ? partes[0] + '@' + TYPOS[partes[1]] : '';
            // Si la sugerencia no cambió no se redibuja (al hacer clic en ella el
            // campo pierde el foco y redibujar borraría el botón en pleno clic).
            if (caja.dataset.sug === sugerido) return;
            caja.dataset.sug = sugerido;
            caja.innerHTML = '';
            if (!sugerido) return;
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'tg-sug-btn';
            b.textContent = '¿Quisiste decir ' + sugerido + '? Usar este';
            b.addEventListener('click', function () {
                input.value = sugerido; caja.innerHTML = ''; caja.dataset.sug = '';
                input.dispatchEvent(new Event('input', { bubbles: true }));
            });
            caja.appendChild(b);
        }
        input.addEventListener('input', revisar);
        input.addEventListener('blur', revisar);
    }

    /* ── Pantalla «Revisa tu correo»: corregir el correo ── */
    var corregir = document.getElementById('tgCorregir');
    if (corregir) {
        var abrir = document.getElementById('tgMostrarCorregir');
        corregir.hidden = true;
        abrir.addEventListener('click', function () {
            corregir.hidden = !corregir.hidden;
            if (!corregir.hidden) document.getElementById('tgCorreoNuevo').focus();
        });
        sugerirCorreo(document.getElementById('tgCorreoNuevo'), document.getElementById('tgCorreoNuevoSug'));
        corregir.addEventListener('submit', function () {
            var btn = corregir.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Enviando…';
        });
    }

    var form = document.getElementById('tgForm');
    if (!form) return;
    sugerirCorreo(document.getElementById('tgEmail'), document.getElementById('tgEmailSug'));
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
        // El botón de ayuda cambia al tutorial de este paso.
        document.dispatchEvent(new CustomEvent('tg:paso', { detail: actual }));
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
        mostrarCarga();
    });

    /* Capa de carga mientras el servidor valida, reserva y envía el correo. */
    function mostrarCarga() {
        var capa = document.getElementById('tgCarga');
        if (!capa) return;
        var pasosCarga = capa.querySelectorAll('.tg-carga-pasos li');
        var titulos = ['Estamos validando tus datos…', 'Reservando tu dirección web…', 'Enviándote el correo de confirmación…'];
        var i = 0;
        capa.hidden = false;
        document.body.style.overflow = 'hidden';
        function avanzar() {
            pasosCarga.forEach(function (li, k) { li.className = k < i ? 'is-done' : (k === i ? 'is-on' : ''); });
            document.getElementById('tgCargaTitulo').textContent = titulos[Math.min(i, titulos.length - 1)];
            if (i < pasosCarga.length - 1) { i++; setTimeout(avanzar, 1300); }
        }
        avanzar();
    }

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

    // Volver con «Atrás» del navegador no debe dejar la pantalla de carga pegada.
    window.addEventListener('pageshow', function (e) {
        if (!e.persisted) return;
        var capa = document.getElementById('tgCarga');
        if (capa) capa.hidden = true;
        document.body.style.overflow = '';
        btnCrear.disabled = false;
        btnCrear.innerHTML = '<i class="fas fa-rocket"></i> Crear mi tienda gratis';
    });

    var errorPaso = Number(form.dataset.errorPaso || 0);
    vistaPrevia();
    mostrar(errorPaso || 1);
})();

// ── Ayuda: un video tutorial por paso ────────────────────────────
// Botón flotante que abre el tutorial del paso en que está la persona (paso 1 →
// tutorial 1, «Siguiente» → tutorial 2… hasta el 4); en la pantalla del código, el
// último. Al llegar a un paso nuevo, una guía negra señala el botón (una vez por paso,
// en este navegador). El video (YouTube sin cookies) solo se carga al abrirlo.
(function () {
  var raiz = document.getElementById('tgAyuda');
  if (!raiz) return;
  var btn = document.getElementById('tgAyudaBtn');
  var guia = document.getElementById('tgAyudaGuia');
  var guiaTexto = document.getElementById('tgAyudaGuiaTexto');
  var dialogo = document.getElementById('tgVideo');
  var titulo = document.getElementById('tgVideoTitulo');
  var marco = document.getElementById('tgVideoMarco');
  var tramos = [];
  try { tramos = JSON.parse(raiz.getAttribute('data-tramos') || '[]'); } catch (e) { tramos = []; }
  if (!tramos.length) return;
  var paso = Math.min(Number(raiz.getAttribute('data-paso')) || 1, tramos.length);
  // El asistente ya pudo abrir en otro paso (p. ej. volvió con un error en el paso 3).
  var marcaActual = document.querySelector('.tg-progress-steps li.is-on');
  if (marcaActual) paso = Math.min(Number(marcaActual.getAttribute('data-ind')) || paso, tramos.length);
  var reloj = null;

  function tramo() { return tramos[paso - 1]; }
  function vista(n) {
    try { return localStorage.getItem('tg-ayuda-vista-' + n) === '1'; } catch (e) { return false; }
  }
  function ocultarGuia() {
    guia.hidden = true;
    try { localStorage.setItem('tg-ayuda-vista-' + paso, '1'); } catch (e) { /* sin almacenamiento */ }
  }
  function pintar() {
    var t = tramo();
    btn.setAttribute('aria-label', 'Ayuda: ver el video tutorial ' + paso + ' (' + t.titulo + ')');
    guiaTexto.textContent = paso === 1
      ? 'Toca este botón y mira el video tutorial: te mostramos paso a paso cómo crear tu tienda gratis.'
      : 'Tutorial ' + paso + ' de ' + tramos.length + ': ' + t.titulo + '. Tócalo si tienes dudas en este paso.';
    clearTimeout(reloj);
    guia.hidden = true;
    if (!vista(paso)) reloj = setTimeout(function () { guia.hidden = false; }, paso === 1 ? 1200 : 500);
  }
  document.addEventListener('tg:paso', function (e) {
    var n = Math.min(Number(e.detail) || 1, tramos.length);
    if (n !== paso) { paso = n; pintar(); }
  });
  pintar();

  document.getElementById('tgAyudaEntendido').addEventListener('click', function () {
    ocultarGuia();
    btn.focus();
  });

  // ── Reproductor: API de YouTube sin sus controles (mostraban el video completo);
  // los nuestros solo conocen el tramo del paso y no dejan salirse de él.
  var play = document.getElementById('tgVideoPlay');
  var barra = document.getElementById('tgVideoBarra');
  var tiempo = document.getElementById('tgVideoTiempo');
  var repetir = document.getElementById('tgVideoRepetir');
  var jugador = null, vigilante = null, actualTramo = null, arrastrando = false;

  function mmss(s) { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function largo() { return actualTramo.fin > actualTramo.inicio ? actualTramo.fin - actualTramo.inicio : 0; }
  function pintarTiempo(seg) {
    var total = largo() || (jugador && jugador.getDuration ? jugador.getDuration() : 0);
    barra.max = total || 1;
    if (!arrastrando) barra.value = seg;
    tiempo.textContent = mmss(seg) + ' / ' + mmss(total);
  }
  function icono(sonando) {
    play.innerHTML = '<i class="fas fa-' + (sonando ? 'pause' : 'play') + '" aria-hidden="true"></i>';
    play.setAttribute('aria-label', sonando ? 'Pausar' : 'Reproducir');
  }
  function vigilar() {
    clearInterval(vigilante);
    vigilante = setInterval(function () {
      if (!jugador || !jugador.getCurrentTime) return;
      var t = jugador.getCurrentTime();
      if (t < actualTramo.inicio - 1) { jugador.seekTo(actualTramo.inicio, true); t = actualTramo.inicio; }
      if (largo() && t >= actualTramo.fin - 0.25) {          // fin del tramo: no sigue con el siguiente tutorial
        jugador.pauseVideo();
        jugador.seekTo(actualTramo.inicio, true);
        pintarTiempo(largo());
        repetir.hidden = false;
        icono(false);
        return;
      }
      pintarTiempo(t - actualTramo.inicio);
    }, 250);
  }
  function cargarApi(listo) {
    if (window.YT && window.YT.Player) { listo(); return; }
    var previo = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () { if (previo) previo(); listo(); };
    if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
      var s = document.createElement('script');
      s.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(s);
    }
  }

  btn.addEventListener('click', function () {
    ocultarGuia();
    actualTramo = tramo();
    titulo.textContent = 'Video tutorial ' + paso + ' · ' + actualTramo.titulo;
    repetir.hidden = true;
    icono(true);
    pintarTiempo(0);
    if (typeof dialogo.showModal === 'function') dialogo.showModal(); else dialogo.setAttribute('open', '');
    cargarApi(function () {
      if (jugador && jugador.destroy) jugador.destroy();
      marco.innerHTML = '<div id="tgVideoReproductor"></div>';
      var vars = { autoplay: 1, controls: 0, disablekb: 1, rel: 0, modestbranding: 1, playsinline: 1,
                   iv_load_policy: 3, start: actualTramo.inicio };
      if (largo()) vars.end = actualTramo.fin;
      jugador = new window.YT.Player('tgVideoReproductor', {
        host: 'https://www.youtube-nocookie.com',
        videoId: raiz.getAttribute('data-video'),
        playerVars: vars,
        events: {
          onReady: function (e) {
            var iframe = marco.querySelector('iframe');
            if (iframe) iframe.title = 'Video tutorial ' + paso + ': ' + actualTramo.titulo;
            e.target.seekTo(actualTramo.inicio, true);
            e.target.playVideo();
            vigilar();
          },
          onStateChange: function (e) {
            if (e.data === 1) { icono(true); repetir.hidden = true; } else if (e.data === 2) icono(false);
          }
        }
      });
    });
  });

  play.addEventListener('click', function () {
    if (!jugador || !jugador.getPlayerState) return;
    if (jugador.getPlayerState() === 1) jugador.pauseVideo(); else { repetir.hidden = true; jugador.playVideo(); }
  });
  repetir.addEventListener('click', function () {
    if (!jugador) return;
    jugador.seekTo(actualTramo.inicio, true);
    jugador.playVideo();
    repetir.hidden = true;
    play.focus();
  });
  barra.addEventListener('input', function () {
    arrastrando = true;
    tiempo.textContent = mmss(barra.value) + ' / ' + mmss(largo());
  });
  barra.addEventListener('change', function () {
    arrastrando = false;
    if (jugador) jugador.seekTo(actualTramo.inicio + Number(barra.value), true);   // solo dentro del tramo
  });

  function cerrar() { if (dialogo.open) dialogo.close(); }
  document.getElementById('tgVideoCerrar').addEventListener('click', cerrar);
  dialogo.addEventListener('click', function (e) { if (e.target === dialogo) cerrar(); });
  dialogo.addEventListener('close', function () {
    clearInterval(vigilante);
    if (jugador && jugador.destroy) jugador.destroy();          // detiene el video
    jugador = null;
    marco.textContent = '';
    btn.focus();
  });
})();

// ── Recorrido de bienvenida (solo la primera vez) ────────────────
// PRIMERA_VEZ: ¿esta persona entra por primera vez al asistente (en este navegador)?
// Si sí, un recorrido corto ilumina qué llenar, cómo avanzar y dónde está la ayuda.
// Se puede saltar en cualquier momento (botón o Esc) y no vuelve a salir.
(function () {
  var CLAVE = 'tg-recorrido-visto';
  var PRIMERA_VEZ = (function () {
    try { return localStorage.getItem(CLAVE) !== '1'; } catch (e) { return false; }
  })();
  window.tgPrimeraVez = PRIMERA_VEZ;
  var page = document.querySelector('.tg-page');
  var marcaUno = document.querySelector('.tg-progress-steps li.is-on');
  if (!PRIMERA_VEZ || !page || !document.getElementById('tgNegocio') ||
      !marcaUno || marcaUno.getAttribute('data-ind') !== '1') return;

  var pasos = [
    { el: '#tgNegocio', titulo: 'Nombre de tu negocio',
      texto: 'Escribe cómo se llama tu negocio. Así aparecerá en tu tienda.' },
    { el: '.tg-tipos', titulo: '¿A qué se dedica?',
      texto: 'Toca la opción que más se parezca. Solo cambia los textos de ejemplo.' },
    { el: '#tgSiguiente', titulo: 'Avanza con «Siguiente»',
      texto: 'Son 4 pasos cortos: tu negocio, tu dirección web, el diseño y tus datos.' },
    { el: '#tgAyudaBtn', titulo: '¿Dudas? Aquí está la ayuda',
      texto: 'En cualquier paso, toca este botón y mira un video corto de ese paso.' }
  ].filter(function (p) {
    var el = document.querySelector(p.el);
    return el && el.getClientRects().length;
  });
  if (!pasos.length) return;

  var foco = document.createElement('div');
  foco.className = 'tg-recorrido-foco';
  var capa = document.createElement('div');
  capa.className = 'tg-recorrido-capa';
  var burbuja = document.createElement('div');
  burbuja.className = 'tg-recorrido-burbuja';
  burbuja.setAttribute('role', 'dialog');
  burbuja.setAttribute('aria-labelledby', 'tgRecTitulo');
  burbuja.setAttribute('aria-describedby', 'tgRecTexto');
  burbuja.innerHTML =
    '<span class="tg-recorrido-cuenta" id="tgRecCuenta"></span>' +
    '<h2 id="tgRecTitulo"></h2><p id="tgRecTexto"></p>' +
    '<div class="tg-recorrido-acciones">' +
    '<button type="button" class="tg-recorrido-saltar" id="tgRecSaltar">Saltar</button>' +
    '<button type="button" class="tg-recorrido-sig" id="tgRecSig">Siguiente</button></div>';
  [capa, foco, burbuja].forEach(function (n) { page.appendChild(n); });
  document.body.classList.add('tg-en-recorrido');

  var i = 0;
  function objetivo() { return document.querySelector(pasos[i].el); }
  function ubicar() {
    var el = objetivo();
    if (!el) return;
    var r = el.getBoundingClientRect();
    var m = 8;
    foco.style.top = (r.top - m) + 'px';
    foco.style.left = (r.left - m) + 'px';
    foco.style.width = (r.width + m * 2) + 'px';
    foco.style.height = (r.height + m * 2) + 'px';
    var ancho = Math.min(320, window.innerWidth - 32);
    burbuja.style.width = ancho + 'px';
    var alto = burbuja.offsetHeight;
    var arriba = r.bottom + m + 12;
    if (arriba + alto > window.innerHeight - 8) arriba = Math.max(8, r.top - m - 12 - alto);
    var izquierda = Math.min(Math.max(16, r.left), window.innerWidth - ancho - 16);
    burbuja.style.top = arriba + 'px';
    burbuja.style.left = izquierda + 'px';
  }
  function mostrar() {
    var p = pasos[i];
    document.getElementById('tgRecCuenta').textContent = (i + 1) + ' de ' + pasos.length;
    document.getElementById('tgRecTitulo').textContent = p.titulo;
    document.getElementById('tgRecTexto').textContent = p.texto;
    document.getElementById('tgRecSig').textContent = i === pasos.length - 1 ? 'Empezar' : 'Siguiente';
    var el = objetivo();
    var r = el.getBoundingClientRect();
    if (r.top < 80 || r.bottom > window.innerHeight - 80) el.scrollIntoView({ block: 'center' });
    ubicar();
    setTimeout(ubicar, 350);
    document.getElementById('tgRecSig').focus();
  }
  function terminar() {
    try {
      localStorage.setItem(CLAVE, '1');
      localStorage.setItem('tg-ayuda-vista-1', '1');      // el recorrido ya mostró la ayuda
    } catch (e) { /* sin almacenamiento */ }
    window.tgPrimeraVez = false;
    var guiaAyuda = document.getElementById('tgAyudaGuia');
    if (guiaAyuda) guiaAyuda.hidden = true;
    [capa, foco, burbuja].forEach(function (n) { n.remove(); });
    document.body.classList.remove('tg-en-recorrido');
    window.removeEventListener('resize', ubicar);
    window.removeEventListener('scroll', ubicar, true);
    document.removeEventListener('keydown', teclas);
    var nombre = document.getElementById('tgNegocio');
    if (nombre) nombre.focus();
  }
  function teclas(e) { if (e.key === 'Escape') terminar(); }
  document.getElementById('tgRecSig').addEventListener('click', function () {
    if (i < pasos.length - 1) { i += 1; mostrar(); } else terminar();
  });
  document.getElementById('tgRecSaltar').addEventListener('click', terminar);
  window.addEventListener('resize', ubicar);
  window.addEventListener('scroll', ubicar, true);
  document.addEventListener('keydown', teclas);
  setTimeout(mostrar, 400);
})();
