/* Notas adicionales con IA en el generador de cotizaciones (1.9.13.0).
 *
 * «Sugerir notas con IA» manda al servidor lo que se está cotizando (descripción,
 * cantidad e IVA de cada ítem), la ciudad y lo necesario para saber si el cliente es
 * empresa o persona (su nombre y documento no llegan a la IA), las indicaciones del
 * negocio y las notas ya escritas. La respuesta llega por secciones; la persona marca
 * las que quiere y se agregan al cuadro de notas organizadas (TÍTULO + viñetas), que es
 * como se ven bien en el PDF. Al generar el PDF avisa si quedan valores [entre corchetes].
 */
(function () {
    'use strict';
    var raiz = document.getElementById('cotIa');
    var notas = document.getElementById('notasAdicionales');
    if (!raiz || !notas) return;

    var url = raiz.getAttribute('data-url');
    var boton = document.getElementById('cotIaBtn');
    var estado = document.getElementById('cotIaEstado');
    var panel = document.getElementById('cotIaPanel');
    var titulo = document.getElementById('cotIaTitulo');
    var contAvisos = document.getElementById('cotIaAvisos');
    var contSecciones = document.getElementById('cotIaSecciones');
    var indicaciones = document.getElementById('cotIaIndicaciones');
    var meta = document.querySelector('meta[name="csrf-token"]');
    var CSRF = meta ? meta.getAttribute('content') : '';
    var reiniciar = document.getElementById('cotIaReiniciar');
    var agregar = document.getElementById('cotIaAgregar');
    var VINETA = '•';
    var orden = [];      // orden de las secciones en el PDF (lo manda el servidor)
    var vistas = [];     // sugerencias ya mostradas en esta pantalla: no se vuelven a sugerir
    var mostradas = [];  // las del panel abierto

    function decir(texto) { estado.textContent = texto || ''; }

    function campo(nombre) {
        var el = document.querySelector('[name="' + nombre + '"]');
        return el ? el.value : '';
    }

    function itemsCotizados() {
        var filas = document.querySelectorAll('#items-card .item-row');   // comunes y opciones
        var lista = [];
        Array.prototype.forEach.call(filas, function (fila) {
            var d = fila.querySelector('input[name="descripcion[]"]');
            var c = fila.querySelector('input[name="cantidad[]"]');
            var iva = fila.querySelector('input[name="iva_check[]"]');
            if (d && d.value.trim()) {
                lista.push({ descripcion: d.value.trim(), cantidad: c ? c.value : 1, iva: iva && iva.checked ? 19 : 0 });
            }
        });
        return lista;
    }

    // ── Texto organizado: las mismas reglas que services/notas_cotizacion.bloques ──
    var RE_VINETA = /^\s*[•\-*–·]\s+/;

    function esTitulo(linea) {
        var t = linea.trim();
        if (!t || t.length > 60 || RE_VINETA.test(t)) return false;
        var letras = (t.match(/[A-Za-zÀ-ſ]/g) || []).length;
        return (t.slice(-1) === ':' && t.length <= 50) || (letras >= 3 && t.toUpperCase() === t);
    }

    function sinTildes(t) {
        return (t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
    }

    function bloquesDe(texto) {
        var salida = [], actual = null;
        (texto || '').split(/\r?\n/).forEach(function (linea) {
            if (!linea.trim()) return;
            if (esTitulo(linea)) {
                actual = { titulo: linea.trim().replace(/:$/, '').trim(), lineas: [] };
                salida.push(actual);
                return;
            }
            if (!actual) { actual = { titulo: '', lineas: [] }; salida.push(actual); }
            var vineta = RE_VINETA.test(linea);
            actual.lineas.push({ vineta: vineta, texto: linea.replace(RE_VINETA, '').trim() });
        });
        return salida;
    }

    function aTexto(bloques) {
        return bloques.filter(function (b) { return b.titulo || b.lineas.length; }).map(function (b) {
            var lineas = b.titulo ? [b.titulo.toUpperCase()] : [];
            b.lineas.forEach(function (l) { lineas.push(l.vineta ? VINETA + ' ' + l.texto : l.texto); });
            return lineas.join('\n');
        }).join('\n\n');
    }

    function posicionDe(titulo) {
        var t = sinTildes(titulo);
        for (var i = 0; i < orden.length; i++) { if (sinTildes(orden[i]) === t) return i; }
        return -1;
    }

    // Una sección nueva entra en su lugar (antes de la primera que va después de ella).
    function insertarSeccion(bloques, bloque) {
        var k = posicionDe(bloque.titulo), pos = bloques.length;
        if (k >= 0) {
            for (var i = 0; i < bloques.length; i++) {
                if (posicionDe(bloques[i].titulo) > k) { pos = i; break; }
            }
        }
        bloques.splice(pos, 0, bloque);
    }

    // ── Panel de sugerencias ──
    function recordarMostradas() {
        mostradas.forEach(function (n) { if (vistas.indexOf(n) === -1) vistas.push(n); });
        mostradas = [];
    }

    function pintar(datos) {
        contAvisos.textContent = '';
        contSecciones.textContent = '';
        mostradas = [];
        reiniciar.hidden = true;
        var propias = datos.de_tus_indicaciones || [];
        (datos.avisos || []).forEach(function (a) {
            var p = document.createElement('p');
            p.className = 'cot-ia-aviso';
            p.textContent = a;
            contAvisos.appendChild(p);
        });
        var total = 0;
        (datos.secciones || []).forEach(function (s, i) {
            if (!s.notas || !s.notas.length) return;
            var grupo = document.createElement('fieldset');
            grupo.className = 'cot-ia-seccion';
            var leyenda = document.createElement('legend');
            leyenda.textContent = s.titulo;
            grupo.appendChild(leyenda);
            s.notas.forEach(function (n, j) {
                var id = 'cotIaN' + i + '_' + j;
                var fila = document.createElement('div');
                fila.className = 'cot-ia-nota';
                var caja = document.createElement('input');
                caja.type = 'checkbox';
                caja.id = id;
                caja.checked = true;
                caja.setAttribute('data-seccion', s.titulo);
                caja.value = n;
                var etiqueta = document.createElement('label');
                etiqueta.htmlFor = id;
                etiqueta.textContent = n;
                if (propias.indexOf(n) !== -1) {
                    var marca = document.createElement('span');
                    marca.className = 'cot-ia-tag';
                    marca.textContent = 'Tu indicación';
                    etiqueta.appendChild(marca);
                }
                fila.appendChild(caja);
                fila.appendChild(etiqueta);
                grupo.appendChild(fila);
                mostradas.push(n);
                total += 1;
            });
            contSecciones.appendChild(grupo);
        });
        var avisos = (datos.avisos || []).length;
        if (!total && !avisos) {
            panel.hidden = true;
            reiniciar.hidden = !vistas.length;
            decir('No hay sugerencias nuevas: tus notas ya cubren lo importante' +
                  (vistas.length ? ' y ya viste las demás.' : '.') +
                  ' Si quieres otra condición, escríbela en «Indicaciones para la IA».');
            return;
        }
        agregar.hidden = !total;
        titulo.textContent = !total ? 'Revisión de tus notas'
            : (datos.origen === 'ia' ? 'Sugerencias de la IA' : 'Sugerencias base (revisadas)');
        panel.hidden = false;
        decir(total ? total + ' sugerencias nuevas. Marca las que quieras y pulsa «Agregar las seleccionadas».'
                    : 'No hay sugerencias nuevas; revisa los avisos sobre tus notas.');
        titulo.focus();
    }

    boton.addEventListener('click', function () {
        var items = itemsCotizados();
        if (!items.length) { decir('Agrega primero lo que vas a cotizar.'); return; }
        boton.disabled = true;
        boton.setAttribute('aria-busy', 'true');
        decir('La IA está leyendo lo que cotizas… La primera consulta del día puede tardar hasta un minuto.');
        var control = window.AbortController ? new AbortController() : null;
        var reloj = setTimeout(function () { if (control) control.abort(); }, 95000);
        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({
                items: items,
                cliente: { nombre: campo('cliente_nombre'), documento: campo('cliente_documento'), ciudad: campo('cliente_ciudad') },
                indicaciones: indicaciones ? indicaciones.value : '',
                notas_actuales: notas.value,
                ya_vistas: vistas.slice(-80)
            }),
            signal: control ? control.signal : undefined
        }).then(function (r) {
            return r.json().catch(function () { return { ok: false, error: 'Respuesta inesperada del servidor.' }; });
        }).then(function (d) {
            if (!d.ok) { decir(d.error || 'No se pudieron preparar las sugerencias.'); return; }
            orden = d.orden || orden;
            pintar(d);
        }).catch(function () {
            decir('La IA tardó demasiado o se perdió la conexión. Intenta de nuevo.');
        }).then(function () {
            clearTimeout(reloj);
            boton.disabled = false;
            boton.removeAttribute('aria-busy');
        });
    });

    document.getElementById('cotIaAgregar').addEventListener('click', function () {
        var marcadas = contSecciones.querySelectorAll('input[type="checkbox"]:checked');
        if (!marcadas.length) { decir('Marca al menos una sugerencia.'); return; }
        var bloques = bloquesDe(notas.value);
        var agregadas = 0;
        Array.prototype.forEach.call(marcadas, function (caja) {
            var seccion = caja.getAttribute('data-seccion');
            var bloque = bloques.filter(function (b) { return sinTildes(b.titulo) === sinTildes(seccion); })[0];
            if (!bloque) { bloque = { titulo: seccion.toUpperCase(), lineas: [] }; insertarSeccion(bloques, bloque); }
            var repetida = bloque.lineas.some(function (l) { return sinTildes(l.texto) === sinTildes(caja.value); });
            if (!repetida) { bloque.lineas.push({ vineta: true, texto: caja.value }); agregadas += 1; }
        });
        notas.value = aTexto(bloques);
        notas.dispatchEvent(new Event('input', { bubbles: true }));
        recordarMostradas();
        panel.hidden = true;
        decir(agregadas ? 'Agregué ' + agregadas + ' notas, organizadas por sección. Completa los valores entre [corchetes].'
                        : 'Esas notas ya estaban escritas.');
        notas.focus();
    });

    document.getElementById('cotIaDescartar').addEventListener('click', function () {
        recordarMostradas();
        panel.hidden = true;
        decir('Sugerencias descartadas. No te las volveré a sugerir en esta cotización.');
        reiniciar.hidden = !vistas.length;
        boton.focus();
    });

    reiniciar.addEventListener('click', function () {
        vistas = [];
        reiniciar.hidden = true;
        boton.click();
    });

    // Antes del PDF: ¿quedan valores por confirmar entre [corchetes]?
    var avisado = false;
    if (notas.form) {
        notas.form.addEventListener('submit', function (e) {
            if (!avisado && /\[[^\]\n]{1,40}\]/.test(notas.value)) {
                e.preventDefault();
                avisado = true;
                decir('Quedan valores por completar entre [corchetes] en las notas. Revísalos, o vuelve a pulsar ' +
                      '«Generar PDF» para continuar así.');
                notas.focus();
            }
        });
    }
})();
