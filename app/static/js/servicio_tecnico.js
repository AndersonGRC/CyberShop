/* Servicio Técnico: comportamiento de las pantallas del módulo.
 *  - Campos del equipo según el tipo (columnas comunes + campos propios).
 *  - Asistente de nueva orden: cliente → equipo → falla → confirmar.
 *  - Ver la clave de desbloqueo (POST con CSRF; queda en la bitácora).
 *  - Pestañas de la ficha del equipo y botón «Copiar enlace».
 * Sin JS todo el formulario se ve completo y se puede enviar igual.
 */
(function () {
  'use strict';

  var CSRF = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function $(sel, raiz) { return (raiz || document).querySelector(sel); }
  function $$(sel, raiz) { return Array.prototype.slice.call((raiz || document).querySelectorAll(sel)); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ── Campos del equipo según el tipo ────────────────────────────
  var TIPOS = {};
  try { TIPOS = JSON.parse(($('#st-tipos-json') || {}).textContent || '{}'); } catch (e) { TIPOS = {}; }

  function tipoActual() {
    var r = $('input[name="equipo_tipo"]:checked');
    return r ? r.value : '';
  }

  function dibujarExtras(tipo) {
    var caja = $('#st-extras');
    if (!caja) return;
    var valores = {};
    try { valores = JSON.parse(caja.getAttribute('data-valores') || '{}'); } catch (e) { valores = {}; }
    // Conserva lo que ya se escribió si se cambia de tipo y se vuelve.
    $$('[data-extra]', caja).forEach(function (el) { if (el.value) valores[el.getAttribute('data-extra')] = el.value; });
    caja.setAttribute('data-valores', JSON.stringify(valores));
    var info = TIPOS[tipo];
    if (!info || !info.extras.length) { caja.innerHTML = ''; return; }
    caja.innerHTML = info.extras.map(function (c) {
      var id = 'ex-' + c.clave, nombre = 'equipo_extra_' + c.clave, v = valores[c.clave] || '';
      var campo;
      if (c.tipo === 'opcion') {
        campo = '<select id="' + id + '" name="' + nombre + '" data-extra="' + c.clave + '"><option value="">—</option>' +
          c.opciones.map(function (o) { return '<option' + (o === v ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select>';
      } else if (c.tipo === 'si_no') {
        campo = '<select id="' + id + '" name="' + nombre + '" data-extra="' + c.clave + '"><option value="">—</option>' +
          '<option value="si"' + (v === 'si' ? ' selected' : '') + '>Sí</option><option value="no"' + (v === 'no' ? ' selected' : '') + '>No</option></select>';
      } else {
        var tipoInput = c.tipo === 'fecha' ? 'date' : 'text';
        var extra = c.tipo === 'numero' ? ' inputmode="decimal"' : '';
        campo = '<input type="' + tipoInput + '" id="' + id + '" name="' + nombre + '" data-extra="' + c.clave + '" value="' + esc(v) + '"' + extra + '>';
      }
      return '<div class="st-campo"><label for="' + id + '">' + esc(c.etiqueta) + '</label>' + campo + '</div>';
    }).join('');
  }

  function aplicarTipo() {
    var tipo = tipoActual();
    var info = TIPOS[tipo];
    $$('[data-col]').forEach(function (div) {
      var visible = !info || info.columnas.indexOf(div.getAttribute('data-col')) !== -1;
      div.hidden = !visible;
      var input = $('input', div);
      if (input) input.disabled = !visible;
    });
    dibujarExtras(tipo);
  }

  $$('[data-st-tipo]').forEach(function (r) { r.addEventListener('change', aplicarTipo); });
  if ($('[data-st-tipo]')) aplicarTipo();

  // ── Asistente de nueva orden ───────────────────────────────────
  var form = $('#st-form-orden');
  if (form) {
    var paso = 1, TOTAL = 4;
    var secciones = $$('section[data-paso]', form);
    var btnAtras = $('#st-atras'), btnSig = $('#st-siguiente'), btnGuardar = $('#st-guardar');
    var error = $('#st-error');
    var contactoId = $('#st-contacto-id'), equipoId = $('#st-equipo-id');

    $('#st-pasos').hidden = false;

    function mostrarError(texto) {
      error.textContent = texto || '';
      error.hidden = !texto;
    }

    function irA(n, enfocar) {
      paso = n;
      secciones.forEach(function (s) { s.hidden = Number(s.getAttribute('data-paso')) !== n; });
      $$('#st-pasos li').forEach(function (li) {
        var p = Number(li.getAttribute('data-paso'));
        if (p === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
        li.classList.toggle('hecho', p < n);
      });
      btnAtras.hidden = n === 1;
      btnSig.hidden = n === TOTAL;
      btnGuardar.hidden = n !== TOTAL;
      if (n === TOTAL) resumen();
      mostrarError('');
      var titulo = $('section[data-paso="' + n + '"] h2', form);
      if (titulo && enfocar !== false) { titulo.setAttribute('tabindex', '-1'); titulo.focus({ preventScroll: false }); }
    }

    function valida(n) {
      if (n === 1) {
        var nuevo = !$('#st-cliente-nuevo').hidden;
        if (!contactoId.value && !(nuevo && $('#cl-nombre').value.trim())) {
          return 'Escoge un cliente de la lista o escribe el nombre del cliente nuevo.';
        }
        var correo = $('#cl-email').value.trim();
        if (nuevo && correo && correo.indexOf('@') === -1) return 'El correo del cliente no es válido.';
      }
      if (n === 2 && !equipoId.value) {
        if (!tipoActual()) return 'Escoge el tipo de equipo.';
        var imei = ($('#eq-imei') || {}).value || '';
        if (imei && !imeiValido(imei)) return 'El IMEI no es válido: revisa los 15 dígitos (márcalo con *#06#).';
      }
      if (n === 3 && !$('#o-falla').value.trim()) return 'Describe la falla que reporta el cliente.';
      return '';
    }

    function imeiValido(imei) {
      var d = imei.replace(/\D/g, '');
      if (d.length !== 15) return false;
      var t = 0;
      for (var i = 0; i < 15; i++) {
        var n = Number(d[i]);
        if (i % 2 === 1) { n *= 2; if (n > 9) n -= 9; }
        t += n;
      }
      return t % 10 === 0;
    }

    function resumen() {
      var filas = [];
      var cliente = contactoId.value ? $('#st-cliente-nombre').textContent : $('#cl-nombre').value + ' (nuevo)';
      filas.push(['Cliente', cliente]);
      var equipo;
      if (equipoId.value) {
        var b = $('#st-equipos-lista [aria-pressed="true"]');
        equipo = b ? b.getAttribute('data-desc') : 'Equipo registrado';
      } else {
        var tipo = TIPOS[tipoActual()] || {};
        equipo = [tipo.nombre, ($('#eq-marca') || {}).value, ($('#eq-modelo') || {}).value].filter(Boolean).join(' · ');
      }
      filas.push(['Equipo', equipo]);
      filas.push(['Falla', $('#o-falla').value]);
      var acc = $$('input[name="accesorios"]:checked').map(function (c) { return c.value; });
      if ($('input[name="accesorios_otros"]').value) acc.push($('input[name="accesorios_otros"]').value);
      filas.push(['Accesorios', acc.join(', ') || 'Ninguno']);
      filas.push(['Clave', $('#o-clave').value ? 'Guardada (cifrada)' : 'Sin clave']);
      if ($('#o-valor').value) filas.push(['Valor estimado', '$ ' + $('#o-valor').value]);
      if ($('#o-promesa').value) filas.push(['Fecha prometida', $('#o-promesa').value]);
      filas.push(['Garantía', ($('#o-garantia').value || '0') + ' días']);
      $('#st-resumen').innerHTML = filas.map(function (f) {
        return '<dt>' + esc(f[0]) + '</dt><dd>' + esc(f[1]) + '</dd>';
      }).join('');
    }

    btnSig.addEventListener('click', function () {
      var e = valida(paso);
      if (e) { mostrarError(e); return; }
      irA(paso + 1);
    });
    btnAtras.addEventListener('click', function () { irA(paso - 1); });
    form.addEventListener('submit', function (ev) {
      for (var n = 1; n < TOTAL; n++) {
        var e = valida(n);
        if (e) { ev.preventDefault(); irA(n); mostrarError(e); return; }
      }
      btnGuardar.disabled = true;
      btnGuardar.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Guardando…';
    });
    // Enter en un campo no envía el formulario a medio llenar.
    form.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' && ev.target.tagName === 'INPUT' && paso < TOTAL) { ev.preventDefault(); btnSig.click(); }
    });

    // Cliente: búsqueda
    var apiClientes = form.getAttribute('data-api-clientes');
    var apiEquipos = form.getAttribute('data-api-equipos');
    var buscar = $('#st-buscar-cliente'), lista = $('#st-clientes'), temporizador = null;

    buscar.addEventListener('input', function () {
      clearTimeout(temporizador);
      var q = buscar.value.trim();
      if (q.length < 2) { lista.innerHTML = ''; return; }
      temporizador = setTimeout(function () {
        fetch(apiClientes + '?q=' + encodeURIComponent(q), { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
          .then(function (r) { return r.json(); })
          .then(function (d) {
            var cs = (d && d.clientes) || [];
            lista.innerHTML = cs.length ? cs.map(function (c) {
              var datos = [c.whatsapp || c.telefono, c.email, c.empresa].filter(Boolean).join(' · ');
              return '<button type="button" class="st-opcion" data-id="' + c.id + '" data-nombre="' + esc(c.nombre) +
                '" data-datos="' + esc(datos) + '"><i class="fas fa-user" aria-hidden="true"></i><span><strong>' +
                esc(c.nombre) + '</strong><small>' + esc(datos || 'Sin datos de contacto') + '</small></span></button>';
            }).join('') : '<p class="st-vacio-dato">No hay clientes con ese dato. Créalo como cliente nuevo.</p>';
          })
          .catch(function () { lista.innerHTML = '<p class="st-vacio-dato">No se pudo buscar. Intenta de nuevo.</p>'; });
      }, 250);
    });

    lista.addEventListener('click', function (ev) {
      var b = ev.target.closest('.st-opcion');
      if (!b) return;
      elegirCliente(b.getAttribute('data-id'), b.getAttribute('data-nombre'), b.getAttribute('data-datos'));
    });

    function elegirCliente(id, nombre, datos) {
      contactoId.value = id;
      $('#st-cliente-nombre').textContent = nombre;
      $('#st-cliente-datos').textContent = datos || '';
      $('#st-cliente-elegido').hidden = false;
      $('#st-cliente-buscar').hidden = true;
      $('#st-cliente-nuevo').hidden = true;
      cargarEquipos(id);
    }

    $('#st-cambiar-cliente').addEventListener('click', function () {
      contactoId.value = '';
      equipoId.value = '';
      $('#st-cliente-elegido').hidden = true;
      $('#st-cliente-buscar').hidden = false;
      $('#st-equipos-cliente').hidden = true;
      $('#st-equipo-nuevo').hidden = false;
      buscar.focus();
    });

    $('#st-cliente-nuevo-btn').addEventListener('click', function () {
      contactoId.value = '';
      $('#st-cliente-nuevo').hidden = false;
      $('#st-equipos-cliente').hidden = true;
      $('#st-equipo-nuevo').hidden = false;
      var q = buscar.value.trim();
      if (q && !/\d{5,}/.test(q) && !$('#cl-nombre').value) $('#cl-nombre').value = q;
      if (/^[\d\s+]{7,}$/.test(q) && !$('#cl-whatsapp').value) $('#cl-whatsapp').value = q;
      $('#cl-nombre').focus();
    });

    // Equipos del cliente escogido
    function cargarEquipos(id) {
      var url = apiEquipos.replace(/\/0\/equipos$/, '/' + encodeURIComponent(id) + '/equipos');
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var eqs = (d && d.equipos) || [];
          var caja = $('#st-equipos-cliente');
          if (!eqs.length) { caja.hidden = true; return; }
          $('#st-equipos-lista').innerHTML = eqs.map(function (e) {
            var det = [e.serial ? 'Serial ' + e.serial : '', e.imei ? 'IMEI ' + e.imei : ''].filter(Boolean).join(' · ');
            return '<button type="button" class="st-opcion" aria-pressed="false" data-id="' + e.id + '" data-desc="' + esc(e.descripcion) +
              '"><i class="fas fa-' + esc(e.icono) + '" aria-hidden="true"></i><span><strong>' + esc(e.descripcion) +
              '</strong><small>' + esc(det || 'Sin serial') + '</small></span></button>';
          }).join('');
          caja.hidden = false;
        })
        .catch(function () { $('#st-equipos-cliente').hidden = true; });
    }

    $('#st-equipos-lista').addEventListener('click', function (ev) {
      var b = ev.target.closest('.st-opcion');
      if (!b) return;
      $$('#st-equipos-lista .st-opcion').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
      b.setAttribute('aria-pressed', 'true');
      equipoId.value = b.getAttribute('data-id');
      $('#st-equipo-nuevo').hidden = true;
    });
    $('#st-equipo-nuevo-btn').addEventListener('click', function () {
      equipoId.value = '';
      $$('#st-equipos-lista .st-opcion').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
      $('#st-equipo-nuevo').hidden = false;
    });

    if (contactoId.value) cargarEquipos(contactoId.value);
    irA(1, false);
  }

  // ── Ver clave de desbloqueo ────────────────────────────────────
  $$('[data-st-clave]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var destino = document.getElementById(btn.getAttribute('aria-controls'));
      btn.disabled = true;
      fetch(btn.getAttribute('data-st-clave'), {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' }
      }).then(function (r) { return r.json(); }).then(function (d) {
        destino.hidden = false;
        destino.textContent = d.ok ? d.clave : (d.error || 'No se pudo leer la clave.');
        btn.hidden = !!d.ok;
      }).catch(function () {
        destino.hidden = false;
        destino.textContent = 'No se pudo leer la clave.';
      }).then(function () { btn.disabled = false; });
    });
  });

  // ── Pestañas (ficha del equipo) ────────────────────────────────
  $$('[role="tablist"]').forEach(function (lista) {
    var tabs = $$('[role="tab"]', lista);
    function activar(tab, enfocar) {
      tabs.forEach(function (t) {
        var activo = t === tab;
        t.setAttribute('aria-selected', activo ? 'true' : 'false');
        t.tabIndex = activo ? 0 : -1;
        var panel = document.getElementById(t.getAttribute('aria-controls'));
        if (panel) panel.hidden = !activo;
      });
      if (enfocar) tab.focus();
    }
    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { activar(t, false); });
      t.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
          var j = (i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
          activar(tabs[j], true);
        }
      });
    });
    var porHash = tabs.filter(function (t) { return '#' + t.getAttribute('aria-controls') === location.hash; })[0];
    activar(porHash || tabs[0], false);
  });

  // ── WhatsApp desde la bandeja «Hoy» y desde la orden ─────────
  // El enlace abre WhatsApp como siempre; además se registra en segundo plano
  // (bandeja: el seguimiento queda hecho; orden: nota en la bitácora).
  function postear(url, datos) {
    var fd = new FormData();
    Object.keys(datos || {}).forEach(function (k) { fd.append(k, datos[k]); });
    return fetch(url, {
      method: 'POST', body: fd, keepalive: true,
      headers: { 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); });
  }
  var avisoSeg = $('#st-seg-aviso');
  $$('[data-st-wa-marcar]').forEach(function (a) {
    a.addEventListener('click', function () {
      var tarjeta = a.closest('[data-st-seg]');
      postear(a.getAttribute('data-st-wa-marcar'), { canal: 'whatsapp' }).then(function (d) {
        if (!d || !d.ok) return;
        if (tarjeta) {
          tarjeta.style.opacity = '.45';
          $$('button, a, summary', tarjeta).forEach(function (el) { el.setAttribute('tabindex', '-1'); el.setAttribute('aria-disabled', 'true'); });
        }
        if (avisoSeg) { avisoSeg.hidden = false; avisoSeg.textContent = 'Listo: el seguimiento quedó registrado como enviado por WhatsApp.'; }
      }).catch(function () { /* sin conexión: se puede marcar «Hecho» a mano */ });
    });
  });
  $$('[data-st-wa-nota]').forEach(function (a) {
    a.addEventListener('click', function () {
      postear(a.getAttribute('data-st-wa-nota'), { estado: a.getAttribute('data-estado') || '' }).catch(function () {});
    });
  });

  // ── Copiar enlace ──────────────────────────────────────────────
  $$('[data-st-copiar]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var texto = btn.getAttribute('data-st-copiar');
      var listo = function () {
        var antes = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> Copiado';
        setTimeout(function () { btn.innerHTML = antes; }, 1600);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(texto).then(listo, function () { window.prompt('Copia el enlace:', texto); });
      else window.prompt('Copia el enlace:', texto);
    });
  });
})();
