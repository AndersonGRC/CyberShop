/* Servicio Técnico: comportamiento de las pantallas del módulo.
 *  - Campos del equipo según el tipo (columnas comunes + campos propios).
 *  - Asistente de nueva orden: cliente → equipo → falla → confirmar.
 *  - Registrar equipo (una página): cliente del CRM, ficha, fotos y plan.
 *  - Vista previa de fotos y validación del IMEI mientras se escribe.
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

  // ── IMEI: 15 dígitos + dígito de control (Luhn) ────────────────
  function imeiValido(imei) {
    var d = String(imei || '').replace(/\D/g, '');
    if (d.length !== 15) return false;
    var t = 0;
    for (var i = 0; i < 15; i++) {
      var n = Number(d[i]);
      if (i % 2 === 1) { n *= 2; if (n > 9) n -= 9; }
      t += n;
    }
    return t % 10 === 0;
  }
  var imeiInput = $('#eq-imei'), imeiAyuda = $('#eq-imei-ayuda');
  if (imeiInput && imeiAyuda) {
    var ayudaBase = imeiAyuda.textContent;
    var revisarImei = function () {
      var d = imeiInput.value.replace(/\D/g, '');
      imeiAyuda.classList.remove('st-ok', 'st-mal');
      if (!d) { imeiAyuda.textContent = ayudaBase; imeiInput.removeAttribute('aria-invalid'); return; }
      if (d.length < 15) { imeiAyuda.textContent = 'Faltan ' + (15 - d.length) + ' dígitos.'; imeiInput.removeAttribute('aria-invalid'); return; }
      var ok = imeiValido(d);
      imeiAyuda.textContent = ok ? 'IMEI válido.' : 'El IMEI no es válido: revisa los dígitos (márcalo con *#06#).';
      imeiAyuda.classList.add(ok ? 'st-ok' : 'st-mal');
      if (ok) imeiInput.removeAttribute('aria-invalid'); else imeiInput.setAttribute('aria-invalid', 'true');
    };
    imeiInput.addEventListener('input', revisarImei);
    revisarImei();
  }

  // ── Cliente: buscar en el CRM, escoger o crear ─────────────────
  // al.elegir(id), al.cambiar(), al.nuevo(): lo propio de cada formulario.
  function iniciarCliente(form, al) {
    al = al || {};
    var contactoId = $('#st-contacto-id', form);
    var apiClientes = form.getAttribute('data-api-clientes');
    var buscar = $('#st-buscar-cliente', form), lista = $('#st-clientes', form), temporizador = null;
    if (!contactoId || !buscar || !lista) return;

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
      contactoId.value = b.getAttribute('data-id');
      $('#st-cliente-nombre', form).textContent = b.getAttribute('data-nombre');
      $('#st-cliente-datos', form).textContent = b.getAttribute('data-datos') || '';
      $('#st-cliente-elegido', form).hidden = false;
      $('#st-cliente-buscar', form).hidden = true;
      $('#st-cliente-nuevo', form).hidden = true;
      if (al.elegir) al.elegir(contactoId.value);
    });

    $('#st-cambiar-cliente', form).addEventListener('click', function () {
      contactoId.value = '';
      $('#st-cliente-elegido', form).hidden = true;
      $('#st-cliente-buscar', form).hidden = false;
      if (al.cambiar) al.cambiar();
      buscar.focus();
    });

    $('#st-cliente-nuevo-btn', form).addEventListener('click', function () {
      contactoId.value = '';
      $('#st-cliente-nuevo', form).hidden = false;
      var q = buscar.value.trim();
      if (q && !/\d{5,}/.test(q) && !$('#cl-nombre', form).value) $('#cl-nombre', form).value = q;
      if (/^[\d\s+]{7,}$/.test(q) && !$('#cl-whatsapp', form).value) $('#cl-whatsapp', form).value = q;
      if (al.nuevo) al.nuevo();
      $('#cl-nombre', form).focus();
    });
  }

  function clienteValido(form) {
    var nuevo = !$('#st-cliente-nuevo', form).hidden;
    if (!$('#st-contacto-id', form).value && !(nuevo && $('#cl-nombre', form).value.trim())) {
      return 'Escoge un cliente de la lista o escribe el nombre del cliente nuevo.';
    }
    var correo = $('#cl-email', form).value.trim();
    if (nuevo && correo && correo.indexOf('@') === -1) return 'El correo del cliente no es válido.';
    return '';
  }

  // ── Vista previa de las fotos escogidas ────────────────────────
  $$('[data-st-fotos]').forEach(function (input) {
    var vista = $(input.getAttribute('data-st-fotos'));
    if (!vista) return;
    input.addEventListener('change', function () {
      vista.innerHTML = '';
      Array.prototype.slice.call(input.files || []).forEach(function (archivo) {
        var li = document.createElement('li');
        li.className = 'st-foto';
        if (/^image\//.test(archivo.type) && window.URL && URL.createObjectURL) {
          var img = document.createElement('img');
          img.src = URL.createObjectURL(archivo);
          img.alt = 'Vista previa: ' + archivo.name;
          img.onload = function () { URL.revokeObjectURL(img.src); };
          li.appendChild(img);
        }
        var pie = document.createElement('div');
        pie.className = 'st-foto-pie';
        var mb = archivo.size / 1048576;
        pie.textContent = archivo.name + ' · ' + (mb >= 1 ? mb.toFixed(1) + ' MB' : Math.max(1, Math.round(archivo.size / 1024)) + ' KB') +
          (archivo.size > 15 * 1048576 ? ' · pesa más de 15 MB, no se subirá' : '');
        li.appendChild(pie);
        vista.appendChild(li);
      });
    });
  });

  // ── Registrar equipo (una sola página) ─────────────────────────
  var formEquipo = $('#st-form-equipo');
  if (formEquipo) {
    iniciarCliente(formEquipo);
    var errorEq = $('#st-error', formEquipo);
    formEquipo.addEventListener('submit', function (ev) {
      var e = clienteValido(formEquipo);
      if (!e && !tipoActual()) e = 'Escoge el tipo de equipo.';
      var imei = ($('#eq-imei') || {}).value || '';
      if (!e && imei && !($('#eq-imei').disabled) && !imeiValido(imei)) e = 'El IMEI no es válido: revisa los 15 dígitos (márcalo con *#06#).';
      if (e) {
        ev.preventDefault();
        errorEq.textContent = e;
        errorEq.hidden = false;
        errorEq.scrollIntoView({ block: 'center' });
        return;
      }
      errorEq.hidden = true;
      var b = $('#st-guardar', formEquipo);
      b.disabled = true;
      b.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Guardando…';
    });
  }

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
        var errCliente = clienteValido(form);
        if (errCliente) return errCliente;
      }
      if (n === 2 && !equipoId.value) {
        if (!tipoActual()) return 'Escoge el tipo de equipo.';
        var imei = ($('#eq-imei') || {}).value || '';
        if (imei && !imeiValido(imei)) return 'El IMEI no es válido: revisa los 15 dígitos (márcalo con *#06#).';
      }
      if (n === 3 && !$('#o-falla').value.trim()) return 'Describe la falla que reporta el cliente.';
      return '';
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

    // Cliente: buscador compartido + los equipos que ya tiene registrados.
    var apiEquipos = form.getAttribute('data-api-equipos');
    iniciarCliente(form, {
      elegir: function (id) { cargarEquipos(id); },
      cambiar: function () {
        equipoId.value = '';
        $('#st-equipos-cliente').hidden = true;
        $('#st-equipo-nuevo').hidden = false;
      },
      nuevo: function () {
        $('#st-equipos-cliente').hidden = true;
        $('#st-equipo-nuevo').hidden = false;
      }
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
      // En celular la barra se desplaza: que la pestaña activa quede a la vista.
      if (lista.scrollWidth > lista.clientWidth) {
        lista.scrollLeft = Math.max(0, tab.offsetLeft - (lista.clientWidth - tab.offsetWidth) / 2);
      }
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
    window.addEventListener('hashchange', function () {
      var t = tabs.filter(function (x) { return '#' + x.getAttribute('aria-controls') === location.hash; })[0];
      if (t) { activar(t, false); lista.scrollIntoView({ block: 'start' }); }
    });
  });

  // Un enlace a algo plegado («Pegar información», «#st-caso»…) lo abre solo.
  function abrirDestino(hash) {
    if (!hash || hash.length < 2) return;
    var el = null;
    try { el = document.getElementById(decodeURIComponent(hash.slice(1))); } catch (e) { el = null; }
    if (!el) return;
    if (el.tagName === 'DETAILS') el.open = true;
    var padre = el.parentElement ? el.parentElement.closest('details') : null;
    while (padre) {
      padre.open = true;
      padre = padre.parentElement ? padre.parentElement.closest('details') : null;
    }
  }
  abrirDestino(location.hash);
  window.addEventListener('hashchange', function () { abrirDestino(location.hash); });
  $$('a[data-st-abrir]').forEach(function (a) {
    a.addEventListener('click', function () {
      var destino = a.getAttribute('href') || '';
      if (destino.charAt(0) === '#') abrirDestino(destino);
    });
  });

  // Formularios que piden confirmación (p. ej. quitar una foto).
  $$('form[data-st-confirmar]').forEach(function (f) {
    f.addEventListener('submit', function (ev) {
      if (!window.confirm(f.getAttribute('data-st-confirmar'))) ev.preventDefault();
    });
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

  // ── IA: leer información pegada, especificaciones, mensajes ───
  function esperando(btn, si, texto) {
    if (si) {
      btn.setAttribute('data-antes', btn.innerHTML);
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> ' + (texto || 'Leyendo…');
    } else {
      btn.disabled = false;
      btn.innerHTML = btn.getAttribute('data-antes') || btn.innerHTML;
    }
  }

  function enviarJSON(url, datos) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify(datos)
    }).then(function (r) { return r.json(); });
  }

  // Formulario «actual → sugerido»: el técnico escoge qué guardar.
  function pintarPropuestas(caja, d, aplicarUrl, texto) {
    var html = '';
    if (d.aviso) html += '<p class="st-aviso">' + esc(d.aviso) + '</p>';
    if (d.resumen) html += '<p class="st-texto st-mensaje"><strong>Resumen:</strong> ' + esc(d.resumen) + '</p>';
    var props = d.propuestas || [];
    var sug = d.sugerencias || [];
    if (!props.length && !sug.length && !d.resumen) {
      caja.innerHTML = html + '<p class="st-vacio-dato">No se encontraron datos nuevos para la ficha.</p>';
      return;
    }
    html += '<form method="post" action="' + esc(aplicarUrl) + '" class="st-grid" style="gap:12px">' +
      '<input type="hidden" name="csrf_token" value="' + esc(CSRF) + '">';
    if (texto !== null) html += '<input type="hidden" name="texto" value="' + esc(texto) + '">';
    if (d.resumen) html += '<input type="hidden" name="resumen" value="' + esc(d.resumen) + '">';
    if (sug.length || texto !== null) html += '<input type="hidden" name="sugerencias" value="' + esc(JSON.stringify(sug)) + '">';
    if (props.length) {
      html += '<p class="st-label" style="margin:0">Marca lo que quieres guardar en la ficha (puedes corregir el valor):</p>' +
        '<ul class="st-propuestas">' + props.map(function (pr, i) {
          var id = 'pr-' + i;
          var marcado = pr.verificado !== false && (!pr.actual || pr.fuente === 'lector');
          return '<li><input type="checkbox" id="' + id + '" name="aplicar" value="' + esc(pr.campo) + '"' + (marcado ? ' checked' : '') + '>' +
            '<label for="' + id + '"><strong>' + esc(pr.etiqueta) + '</strong>' +
            (pr.actual ? '<small class="st-tachado">' + esc(pr.actual) + '</small>' : '<small>vacío</small>') +
            ' <i class="fas fa-arrow-right" aria-hidden="true"></i></label>' +
            '<input type="text" name="valor_' + esc(pr.campo) + '" value="' + esc(pr.sugerido) + '" aria-label="Nuevo valor de ' + esc(pr.etiqueta) + '">' +
            (pr.verificado === false
              ? '<span class="st-chip st-chip-aviso" title="La IA lo propuso pero no aparece tal cual en el texto">Revisar</span>'
              : '<span class="st-chip st-chip-' + (pr.fuente === 'lector' ? 'exito' : 'info') + '">' + (pr.fuente === 'lector' ? 'Leído' : 'IA') + '</span>') + '</li>';
        }).join('') + '</ul>';
    }
    if (sug.length) {
      html += '<p class="st-label" style="margin:0"><i class="fas fa-lightbulb" aria-hidden="true"></i> Mejoras sugeridas</p><ul class="st-sugerencias">' +
        sug.map(function (s) { return '<li><strong>' + esc(s.titulo) + '</strong>' + (s.detalle ? '<br><small>' + esc(s.detalle) + '</small>' : '') + '</li>'; }).join('') + '</ul>';
    }
    if (d.fuentes && d.fuentes.length) {
      html += '<p class="st-vacio-dato" style="margin:0">Fuentes: ' + d.fuentes.map(function (f) {
        return '<a href="' + esc(f.url) + '" target="_blank" rel="noopener nofollow">' + esc(f.dominio) + '</a>';
      }).join(' · ') + '</p>';
    }
    html += '<div><button class="st-btn" type="submit"><i class="fas fa-save" aria-hidden="true"></i> Guardar en la ficha</button></div></form>';
    caja.innerHTML = html;
    var primero = caja.querySelector('input, button');
    if (primero) primero.focus();
  }

  $$('[data-st-leer]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var texto = $('#st-info-texto').value;
      var caja = $('#st-propuestas');
      esperando(btn, true, 'Leyendo…');
      caja.innerHTML = '<p class="st-vacio-dato">Leyendo la información… (con IA puede tardar hasta un minuto)</p>';
      enviarJSON(btn.getAttribute('data-st-leer'), { equipo_id: btn.getAttribute('data-equipo'), texto: texto })
        .then(function (d) {
          if (!d.ok) { caja.innerHTML = '<p class="st-aviso st-aviso-peligro">' + esc(d.error || 'No se pudo leer.') + '</p>'; return; }
          pintarPropuestas(caja, d, btn.getAttribute('data-aplicar'), d.texto_limpio || texto);
        })
        .catch(function () { caja.innerHTML = '<p class="st-aviso st-aviso-peligro">No se pudo leer. Intenta de nuevo.</p>'; })
        .then(function () { esperando(btn, false); });
    });
  });

  $$('[data-st-specs]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var caja = $('#st-propuestas');
      esperando(btn, true, 'Buscando…');
      caja.innerHTML = '<p class="st-vacio-dato">Buscando las especificaciones del modelo…</p>';
      enviarJSON(btn.getAttribute('data-st-specs'), {})
        .then(function (d) {
          if (!d.ok) { caja.innerHTML = '<p class="st-aviso st-aviso-peligro">' + esc(d.error || 'No se pudo buscar.') + '</p>'; return; }
          pintarPropuestas(caja, d, btn.getAttribute('data-aplicar'), null);
        })
        .catch(function () { caja.innerHTML = '<p class="st-aviso st-aviso-peligro">No se pudo buscar. Intenta de nuevo.</p>'; })
        .then(function () { esperando(btn, false); });
    });
  });

  // Asistente de nueva orden: llena los campos del equipo con lo leído.
  $$('[data-st-llenar]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var salida = $('#st-llenar-resultado');
      var tipo = tipoActual();
      salida.hidden = false;
      if (!tipo) { salida.textContent = 'Escoge primero el tipo de equipo.'; return; }
      var actual = {};
      $$('[data-col] input').forEach(function (i) { if (!i.disabled && i.value) actual[i.name.replace('equipo_', '')] = i.value; });
      esperando(btn, true, 'Leyendo…');
      salida.textContent = 'Leyendo la información…';
      enviarJSON(btn.getAttribute('data-st-llenar'), { tipo: tipo, texto: $('#eq-info').value, actual: actual })
        .then(function (d) {
          if (!d.ok) { salida.textContent = d.error || 'No se pudo leer.'; return; }
          var llenos = 0;
          (d.propuestas || []).forEach(function (pr) {
            if (pr.verificado === false) return;     // lo no verificado no se llena solo
            var campo = pr.campo.indexOf('extra_') === 0 ? $('#ex-' + pr.campo.slice(6)) : $('#eq-' + pr.campo);
            if (campo && !campo.disabled) { campo.value = pr.sugerido; llenos++; }
          });
          if (d.texto_limpio) $('#eq-info').value = d.texto_limpio;
          $('#eq-resumen-ia').value = d.resumen || '';
          salida.textContent = (llenos ? 'Se llenaron ' + llenos + ' campo(s). Revísalos antes de seguir.' : 'No se encontraron datos nuevos.') +
            (d.aviso ? ' ' + d.aviso : '');
        })
        .catch(function () { salida.textContent = 'No se pudo leer. Intenta de nuevo.'; })
        .then(function () { esperando(btn, false); });
    });
  });

  // Mejorar el mensaje de WhatsApp con IA (orden o bandeja).
  $$('[data-st-mejorar]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var raiz = btn.closest('[data-st-seg]') || btn.closest('section');
      var p = raiz && $('.st-mensaje', raiz);
      var wa = raiz && $('a.st-btn-wa', raiz);
      esperando(btn, true, 'Escribiendo…');
      enviarJSON(btn.getAttribute('data-st-mejorar'), { seg_id: btn.getAttribute('data-seg'), orden_id: btn.getAttribute('data-orden') })
        .then(function (d) {
          if (!d.ok) { if (p) p.insertAdjacentHTML('afterend', '<p class="st-vacio-dato">' + esc(d.error || 'La IA no respondió.') + '</p>'); return; }
          if (p) p.textContent = d.texto;
          if (wa && d.wa_url) wa.href = d.wa_url;
        })
        .catch(function () {})
        .then(function () { esperando(btn, false); });
    });
  });

  // Formularios que llaman a la IA: botón en espera para no enviar dos veces.
  $$('form[data-st-espera]').forEach(function (f) {
    f.addEventListener('submit', function () {
      var b = $('button[type="submit"]', f);
      if (b) esperando(b, true, 'Pensando… (hasta un minuto)');
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
