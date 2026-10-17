/* Generar cotización con IA (1.9.14.0).
 *
 * 1. Lee en el navegador lo que mandó el cliente: OCR de las capturas y fotos
 *    (Tesseract.js, español), texto de los PDF (pdf.js; las páginas escaneadas se
 *    leen con OCR) y el chat exportado de WhatsApp (.txt). Las capturas no se suben a
 *    ningún servicio externo: viajan solo al servidor del negocio y a su equipo de IA.
 * 2. Manda todo al servidor, que arranca el análisis en segundo plano (tarda minutos)
 *    y la pantalla pregunta el avance cada 2 s: visión, catálogo e historial, análisis
 *    profundo, precios, consulta de precios faltantes y notas. Se ve el plan y lo que
 *    está haciendo en cada momento; cerrar la ventana detiene el análisis.
 * 3. Muestra la propuesta (ítems con la fuente de cada precio, totales, dudas para el
 *    cliente y notas) y, si el negocio la acepta, llena el formulario. Nada se guarda
 *    hasta que el negocio genere el PDF.
 */
(function () {
    'use strict';
    var dialogo = document.getElementById('ciaDialogo');
    var abrir = document.getElementById('ciaAbrir');
    if (!dialogo || !abrir) return;

    var TESSERACT = 'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js';
    var PDFJS = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js';
    var PDFJS_WORKER = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    var MAX_IMAGENES = 8, MAX_PAGINAS = 10, LADO_MAX = 1600, MAX_ARCHIVO = 25 * 1024 * 1024;
    var PASOS = [
        ['leer', 'Leer tus archivos (OCR en tu navegador)'],
        ['vision', 'Mirar las imágenes con la IA de visión'],
        ['contexto', 'Buscar en tu catálogo y en tus cotizaciones anteriores'],
        ['razonar', 'Razonar la cotización (análisis profundo)'],
        ['precios', 'Calcular precios: catálogo, historial y costo + margen'],
        ['mercado', 'Consultar en internet los precios que falten (nube, solo si hace falta)'],
        ['notas', 'Redactar las notas adicionales']
    ];
    var ICONOS = { pendiente: '', activo: '', listo: '✓', omitido: '–', error: '✕' };
    var ESTADOS = { pendiente: 'pendiente', activo: 'en curso', listo: 'listo', omitido: 'no hizo falta', error: 'con error' };

    var url = dialogo.getAttribute('data-url');
    var meta = document.querySelector('meta[name="csrf-token"]');
    var CSRF = meta ? meta.getAttribute('content') : '';
    var $ = function (id) { return document.getElementById(id); };
    var entradaArchivos = $('ciaArchivos'), zona = $('ciaZona'), lista = $('ciaLista');
    var formulario = $('ciaFormulario'), progreso = $('ciaProgreso'), resultado = $('ciaResultado');
    var pasosLista = $('ciaPasos'), estado = $('ciaEstado'), reloj = $('ciaReloj');
    var btnIniciar = $('ciaIniciar'), btnUsar = $('ciaUsar'), btnOtra = $('ciaOtra');
    var margen = $('ciaMargen'), nube = $('ciaNube'), conversacion = $('ciaConversacion');

    var archivos = [], propuesta = null, control = null, inicio = 0, temporizador = null;

    try {
        var guardado = localStorage.getItem('cia-margen');
        if (guardado !== null && guardado !== '') margen.value = guardado;
    } catch (e) { /* sin almacenamiento: queda el valor por defecto */ }

    // ── Abrir, cerrar ──
    abrir.addEventListener('click', function () {
        if (typeof dialogo.showModal === 'function') dialogo.showModal(); else dialogo.setAttribute('open', '');
        setTimeout(function () { entradaArchivos.focus(); }, 0);
    });
    function cerrar() {
        if (control) control.abort();
        if (dialogo.open) dialogo.close();
        abrir.focus();
    }
    $('ciaCerrar').addEventListener('click', cerrar);
    dialogo.addEventListener('cancel', function (e) {
        if (control) { e.preventDefault(); decir('Sigo trabajando. Para detenerme, pulsa la ×.'); }
    });

    // ── Archivos ──
    function agregar(lista_) {
        Array.prototype.forEach.call(lista_, function (f) {
            if (f.size > MAX_ARCHIVO) { decir('«' + f.name + '» pesa demasiado (máximo 25 MB).'); return; }
            if (!/^image\//.test(f.type) && !/pdf$/i.test(f.type) && !/\.pdf$/i.test(f.name) &&
                !/^text\//.test(f.type) && !/\.txt$/i.test(f.name)) {
                decir('«' + f.name + '» no es una imagen, un PDF ni un .txt.');
                return;
            }
            archivos.push(f);
        });
        pintarLista();
    }
    function pintarLista() {
        lista.textContent = '';
        archivos.forEach(function (f, i) {
            var li = document.createElement('li');
            var nombre = document.createElement('span');
            nombre.textContent = f.name;
            var quitar = document.createElement('button');
            quitar.type = 'button';
            quitar.textContent = '×';
            quitar.setAttribute('aria-label', 'Quitar ' + f.name);
            quitar.addEventListener('click', function () { archivos.splice(i, 1); pintarLista(); entradaArchivos.focus(); });
            li.appendChild(nombre);
            li.appendChild(quitar);
            lista.appendChild(li);
        });
    }
    entradaArchivos.addEventListener('change', function () { agregar(entradaArchivos.files); entradaArchivos.value = ''; });
    ['dragenter', 'dragover'].forEach(function (ev) {
        zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.add('cia-encima'); });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
        zona.addEventListener(ev, function (e) { e.preventDefault(); zona.classList.remove('cia-encima'); });
    });
    zona.addEventListener('drop', function (e) { if (e.dataTransfer) agregar(e.dataTransfer.files); });

    // ── Plan y estado ──
    function decir(t) { estado.textContent = t || ''; }
    function pintarPlan(pasos) {
        var actuales = {};
        Array.prototype.forEach.call(pasosLista.children, function (li) {
            actuales[li.getAttribute('data-id')] = { estado: li.getAttribute('data-estado'),
                detalle: li.querySelector('.cia-paso__detalle').textContent };
        });
        pasosLista.textContent = '';
        pasos.forEach(function (p) {
            var li = document.createElement('li');
            li.setAttribute('data-id', p[0]);
            var icono = document.createElement('span');
            icono.className = 'cia-paso__icono';
            icono.setAttribute('aria-hidden', 'true');
            var titulo = document.createElement('span');
            titulo.className = 'cia-paso__titulo';
            titulo.textContent = p[1];
            var oculto = document.createElement('span');
            oculto.className = 'sr-only cia-paso__estado';
            oculto.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)';
            titulo.appendChild(oculto);
            var detalle = document.createElement('span');
            detalle.className = 'cia-paso__detalle';
            li.appendChild(icono);
            li.appendChild(titulo);
            li.appendChild(detalle);
            pasosLista.appendChild(li);
            var previo = actuales[p[0]] || { estado: 'pendiente', detalle: '' };
            marcar(p[0], previo.estado || 'pendiente', previo.detalle);
        });
    }
    function marcar(id, est, detalle) {
        var li = pasosLista.querySelector('[data-id="' + id + '"]');
        if (!li) return;
        li.className = 'cia-paso cia-paso--' + est;
        li.setAttribute('data-estado', est);
        li.querySelector('.cia-paso__icono').textContent = ICONOS[est] || '';
        li.querySelector('.cia-paso__estado').textContent = ' (' + (ESTADOS[est] || est) + ')';
        if (detalle !== undefined) li.querySelector('.cia-paso__detalle').textContent = detalle || '';
        if (est === 'activo' || est === 'error') {
            decir(li.querySelector('.cia-paso__titulo').firstChild.textContent + (detalle ? ': ' + detalle : ''));
        }
    }
    function arrancarReloj() {
        inicio = Date.now();
        clearInterval(temporizador);
        temporizador = setInterval(function () {
            var s = Math.round((Date.now() - inicio) / 1000);
            reloj.textContent = '· ' + (s >= 60 ? Math.floor(s / 60) + ' min ' + ('0' + (s % 60)).slice(-2) + ' s' : s + ' s');
        }, 1000);
    }

    // ── Lectura en el navegador ──
    function cargarScript(src) {
        return new Promise(function (ok, mal) {
            if (document.querySelector('script[data-cia="' + src + '"]')) { ok(); return; }
            var s = document.createElement('script');
            s.src = src;
            s.async = true;
            s.setAttribute('data-cia', src);
            s.onload = function () { ok(); };
            s.onerror = function () { mal(new Error('No se pudo cargar el lector (' + src.split('/')[2] + ').')); };
            document.head.appendChild(s);
        });
    }
    var lector = null;
    async function ocr(fuente) {
        if (!lector) {
            await cargarScript(TESSERACT);
            lector = await window.Tesseract.createWorker('spa');
        }
        var r = await lector.recognize(fuente);
        return r.data || {};
    }
    // En una captura de WhatsApp los mensajes del cliente van a la izquierda y los del
    // negocio a la derecha: se etiqueta cada línea para que la IA sepa quién dijo qué.
    function textoConLados(datos, ancho, alto) {
        var lineas = datos.lines || [];
        if (!lineas.length || !ancho || alto < ancho * 1.3) return (datos.text || '').trim();
        var salida = [], anterior = '';
        lineas.forEach(function (l) {
            var t = (l.text || '').trim();
            if (!t || !l.bbox) return;
            var centro = (l.bbox.x0 + l.bbox.x1) / 2 / ancho;
            var lado = l.bbox.x0 > ancho * 0.3 && centro > 0.55 ? 'Negocio' : (centro < 0.45 ? 'Cliente' : '');
            salida.push(lado && lado !== anterior ? lado + ': ' + t : t);
            if (lado) anterior = lado;
        });
        return salida.join('\n');
    }
    function reducir(fuente, ancho, alto) {
        var escala = Math.min(1, LADO_MAX / Math.max(ancho, alto));
        var lienzo = document.createElement('canvas');
        lienzo.width = Math.round(ancho * escala);
        lienzo.height = Math.round(alto * escala);
        lienzo.getContext('2d').drawImage(fuente, 0, 0, lienzo.width, lienzo.height);
        return lienzo.toDataURL('image/jpeg', 0.85);
    }
    async function leerImagen(f, quedan) {
        var mapa = await createImageBitmap(f);
        var datos = await ocr(f);
        var salida = { nombre: f.name, tipo: 'imagen', texto: textoConLados(datos, mapa.width, mapa.height) };
        if (quedan > 0) salida.imagen = reducir(mapa, mapa.width, mapa.height);
        return [salida];
    }
    async function leerPdf(f, quedan, avisar) {
        await cargarScript(PDFJS);
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        var doc = await window.pdfjsLib.getDocument({ data: await f.arrayBuffer() }).promise;
        var textos = [], imagenes = [];
        for (var n = 1; n <= Math.min(doc.numPages, MAX_PAGINAS); n++) {
            avisar('«' + f.name + '», página ' + n + ' de ' + doc.numPages);
            var pagina = await doc.getPage(n);
            var contenido = await pagina.getTextContent();
            var texto = contenido.items.map(function (i) { return i.str + (i.hasEOL ? '\n' : ' '); }).join('').trim();
            if (texto.length < 40) {
                // Página escaneada: se dibuja y se lee con OCR.
                var vista = pagina.getViewport({ scale: 2 });
                var lienzo = document.createElement('canvas');
                lienzo.width = vista.width;
                lienzo.height = vista.height;
                await pagina.render({ canvasContext: lienzo.getContext('2d'), viewport: vista }).promise;
                texto = ((await ocr(lienzo)).text || '').trim();
                if (imagenes.length < quedan) {
                    imagenes.push({ nombre: f.name + ' (pág. ' + n + ')', tipo: 'pdf', texto: texto,
                                    imagen: reducir(lienzo, lienzo.width, lienzo.height) });
                    continue;
                }
            }
            if (texto) textos.push('[Página ' + n + ']\n' + texto);
        }
        var salida = imagenes;
        if (textos.length) salida.unshift({ nombre: f.name, tipo: 'pdf', texto: textos.join('\n\n') });
        return salida;
    }
    async function leerTexto(f) {
        var t = await f.text();
        return [{ nombre: f.name, tipo: 'texto', texto: t.slice(-20000) }];
    }
    async function leerTodo() {
        var salida = [], imagenes = 0;
        for (var i = 0; i < archivos.length; i++) {
            var f = archivos[i];
            var base = 'Leyendo «' + f.name + '» (' + (i + 1) + ' de ' + archivos.length + ')';
            marcar('leer', 'activo', base + '…');
            var leidos;
            try {
                if (/^image\//.test(f.type)) leidos = await leerImagen(f, MAX_IMAGENES - imagenes);
                else if (/pdf$/i.test(f.type) || /\.pdf$/i.test(f.name)) {
                    leidos = await leerPdf(f, MAX_IMAGENES - imagenes, function (t) { marcar('leer', 'activo', 'Leyendo ' + t + '…'); });
                } else leidos = await leerTexto(f);
            } catch (e) {
                if (e && e.name === 'AbortError') throw e;
                leidos = [];
                decir('No pude leer «' + f.name + '»: ' + ((e && e.message) || 'archivo dañado') + '. Sigo con los demás.');
            }
            leidos.forEach(function (l) { if (l.imagen) imagenes += 1; salida.push(l); });
            if (control && control.signal.aborted) throw new DOMException('cancelado', 'AbortError');
        }
        return salida;
    }

    // ── Conversación con el servidor ──
    // El análisis corre en segundo plano (tarda minutos): se pregunta el avance cada 2 s.
    var urlEstado = dialogo.getAttribute('data-estado'), urlCancelar = dialogo.getAttribute('data-cancelar');
    var trabajo = null;
    function esperar(ms) { return new Promise(function (ok) { setTimeout(ok, ms); }); }
    async function seguir(id) {
        var desde = 0, fallos = 0;
        for (;;) {
            if (control && control.signal.aborted) throw new DOMException('cancelado', 'AbortError');
            var r;
            try {
                r = await fetch(urlEstado.replace('__T__', encodeURIComponent(id)) + '?desde=' + desde,
                                { credentials: 'same-origin', cache: 'no-store', signal: control ? control.signal : undefined });
            } catch (e) {
                if (e && e.name === 'AbortError') throw e;
                if (++fallos > 15) throw new Error('Se perdió la conexión con el servidor.');
                await esperar(4000);
                continue;
            }
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok || !d.ok) throw new Error(d.error || 'No se pudo consultar el avance.');
            fallos = 0;
            d.eventos.forEach(manejar);
            desde = d.total;
            if (d.fin) return;
            await esperar(2000);
        }
    }
    function cancelarTrabajo() {
        if (!trabajo) return;
        fetch(urlCancelar.replace('__T__', encodeURIComponent(trabajo)), {
            method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF }
        }).catch(function () { /* si falla, el trabajo termina solo */ });
        trabajo = null;
    }
    function manejar(ev) {
        if (ev.e === 'plan') pintarPlan(ev.d.map(function (p) { return [p.id, p.titulo]; }));
        else if (ev.e === 'paso') marcar(ev.d.id, ev.d.estado, ev.d.detalle);
        else if (ev.e === 'resultado') mostrar(ev.d);
        else if (ev.e === 'error') { decir(ev.d); btnOtra.hidden = false; }
    }

    btnIniciar.addEventListener('click', async function () {
        var pegada = conversacion.value.trim();
        if (!archivos.length && pegada.length < 10) {
            decir('Adjunta una captura, un PDF o pega la conversación.');
            entradaArchivos.focus();
            return;
        }
        try { localStorage.setItem('cia-margen', margen.value); } catch (e) { /* opcional */ }
        formulario.hidden = true;
        progreso.hidden = false;
        resultado.hidden = true;
        btnOtra.hidden = true;
        btnUsar.hidden = true;
        propuesta = null;
        pasosLista.textContent = '';
        pintarPlan(PASOS);
        arrancarReloj();
        control = window.AbortController ? new AbortController() : null;
        $('ciaPlanTitulo').focus();
        try {
            var leidos = await leerTodo();
            var form = document.querySelector('form[action*="cotizar/generar"]');
            var campo = function (n) { var el = form && form.querySelector('[name="' + n + '"]'); return el ? el.value : ''; };
            var respuesta = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
                body: JSON.stringify({
                    archivos: leidos,
                    conversacion: pegada,
                    margen: margen.value,
                    consultar_nube: nube.checked,
                    cliente: { nombre: campo('cliente_nombre'), documento: campo('cliente_documento'),
                               ciudad: campo('cliente_ciudad'), telefono: campo('cliente_telefono') }
                }),
                signal: control ? control.signal : undefined
            });
            var d = await respuesta.json().catch(function () { return {}; });
            if (!respuesta.ok || !d.trabajo) throw new Error(d.error || 'El servidor no pudo empezar el análisis.');
            trabajo = d.trabajo;
            await seguir(trabajo);
            trabajo = null;
        } catch (e) {
            if (e && e.name === 'AbortError') { cancelarTrabajo(); decir('Análisis detenido.'); }
            else decir((e && e.message) || 'Se perdió la conexión. Intenta de nuevo.');
            btnOtra.hidden = false;
        } finally {
            clearInterval(temporizador);
            control = null;
            if (!propuesta) btnOtra.hidden = false;
        }
    });

    btnOtra.addEventListener('click', function () {
        progreso.hidden = true;
        resultado.hidden = true;
        formulario.hidden = false;
        btnOtra.hidden = true;
        btnUsar.hidden = true;
        reloj.textContent = '';
        decir('');
        entradaArchivos.focus();
    });

    // ── La propuesta ──
    var pesos = function (n) { return (Number(n) || 0).toLocaleString('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }); };
    function nodo(tag, clase, texto) {
        var el = document.createElement(tag);
        if (clase) el.className = clase;
        if (texto !== undefined) el.textContent = texto;
        return el;
    }
    function bloque(titulo, contenido) {
        var b = nodo('div', 'cia-bloque');
        b.appendChild(nodo('h4', '', titulo));
        b.appendChild(contenido);
        return b;
    }
    function mostrar(r) {
        propuesta = r;
        var caja = $('ciaPropuesta');
        caja.textContent = '';
        if (r.resumen) caja.appendChild(nodo('p', 'cia-resumen', r.resumen));
        var datos = Object.keys(r.cliente || {}).filter(function (k) { return r.cliente[k]; });
        if (datos.length) {
            var ul = nodo('ul');
            var nombres = { nombre: 'Nombre', telefono: 'Teléfono', ciudad: 'Ciudad', documento: 'Documento', direccion: 'Dirección' };
            datos.forEach(function (k) { ul.appendChild(nodo('li', '', nombres[k] + ': ' + r.cliente[k])); });
            caja.appendChild(bloque('Cliente', ul));
        }
        var items = nodo('ul', 'cia-items');
        r.items.forEach(function (it) {
            var li = nodo('li', 'cia-item');
            var linea = nodo('div', 'cia-item__linea');
            linea.appendChild(nodo('span', 'cia-item__desc', it.descripcion + (it.sugerido ? ' (sugerido)' : '')));
            linea.appendChild(nodo('span', 'cia-item__valor', it.cantidad + ' × ' + (it.precio ? pesos(it.precio) : '[precio]') + (it.iva ? ' + IVA' : '')));
            li.appendChild(linea);
            li.appendChild(nodo('div', 'cia-item__fuente', 'Precio: ' + it.fuente));
            if (it.por_que) li.appendChild(nodo('div', 'cia-item__porque', 'Por qué: ' + it.por_que));
            (it.avisos || []).forEach(function (a) { li.appendChild(nodo('span', 'cia-aviso', a)); });
            items.appendChild(li);
        });
        caja.appendChild(items);
        var t = r.totales || {};
        var dl = nodo('dl', 'cia-totales');
        [['Subtotal', t.subtotal], ['IVA', t.iva], ['Total', t.total]].forEach(function (f) {
            dl.appendChild(nodo('dt', '', f[0]));
            dl.appendChild(nodo('dd', '', pesos(f[1])));
        });
        if (t.ganancia_estimada !== null && t.ganancia_estimada !== undefined) {
            dl.appendChild(nodo('dt', '', 'Ganancia estimada (ítems con costo)'));
            dl.appendChild(nodo('dd', '', pesos(t.ganancia_estimada)));
        }
        caja.appendChild(dl);
        if ((r.dudas || []).length) {
            var dudas = nodo('ul');
            r.dudas.forEach(function (d) { dudas.appendChild(nodo('li', '', d)); });
            var copiar = nodo('button', 'btn-ia-sec', 'Copiar preguntas para WhatsApp');
            copiar.type = 'button';
            copiar.style.marginTop = '8px';
            copiar.addEventListener('click', function () {
                var texto = 'Para enviarte la cotización exacta, ¿me confirmas por favor?\n' +
                    r.dudas.map(function (d, i) { return (i + 1) + '. ' + d; }).join('\n');
                (navigator.clipboard ? navigator.clipboard.writeText(texto) : Promise.reject())
                    .then(function () { decir('Preguntas copiadas. Pégalas en el chat del cliente.'); })
                    .catch(function () { decir('No se pudo copiar; selecciónalas a mano.'); });
            });
            var envoltura = nodo('div');
            envoltura.appendChild(dudas);
            envoltura.appendChild(copiar);
            caja.appendChild(bloque('Dudas para confirmar con el cliente', envoltura));
        }
        if ((r.avisos || []).length) {
            var av = nodo('ul');
            r.avisos.forEach(function (a) { av.appendChild(nodo('li', '', a)); });
            caja.appendChild(bloque('Avisos', av));
        }
        if (r.notas) caja.appendChild(bloque('Notas adicionales que se agregarán', nodo('pre', '', r.notas)));
        resultado.hidden = false;
        btnUsar.hidden = false;
        btnOtra.hidden = false;
        var sinPrecio = r.items.filter(function (i) { return !i.precio; }).length;
        decir('Propuesta lista: ' + r.items.length + ' ítems' + (sinPrecio ? ', ' + sinPrecio + ' sin precio' : '') +
              '. Revísala y pulsa «Pasar al formulario».');
        $('ciaPropuestaTitulo').focus();
    }

    // ── Llenar el formulario ──
    btnUsar.addEventListener('click', function () {
        if (!propuesta) return;
        var form = document.querySelector('form[action*="cotizar/generar"]');
        var c = propuesta.cliente || {};
        [['cliente_nombre', c.nombre], ['cliente_telefono', c.telefono], ['cliente_ciudad', c.ciudad],
         ['cliente_documento', c.documento], ['cliente_direccion', c.direccion]].forEach(function (par) {
            var el = form.querySelector('[name="' + par[0] + '"]');
            // Lo que el negocio ya escribió manda; la ciudad por defecto («Bogotá») sí se reemplaza.
            if (el && par[1] && (!el.value.trim() || (par[0] === 'cliente_ciudad' && el.value === 'Bogotá'))) el.value = par[1];
        });
        var contenedor = document.getElementById('items-container');
        Array.prototype.forEach.call(contenedor.querySelectorAll('.item-row'), function (fila) {
            var d = fila.querySelector('input[name="descripcion[]"]');
            if (d && !d.value.trim()) fila.remove();
        });
        propuesta.items.forEach(function (it) {
            window.addItem();
            var fila = contenedor.lastElementChild;
            fila.querySelector('input[name="descripcion[]"]').value = it.descripcion;
            fila.querySelector('input[name="cantidad[]"]').value = it.cantidad;
            fila.querySelector('input[name="precio[]"]').value = it.precio || 0;
            var iva = fila.querySelector('input[name="iva_check[]"]');
            if (iva) iva.checked = !!it.iva;
            window.calcular(fila.querySelector('input[name="cantidad[]"]'));
        });
        if (!contenedor.querySelector('.item-row')) window.addItem();
        var notas = document.getElementById('notasAdicionales');
        if (notas && propuesta.notas) {
            var actual = notas.value.trim();
            var nuevas = propuesta.notas.split('\n').filter(function (l) { return !l.trim() || actual.indexOf(l.trim()) === -1; }).join('\n').trim();
            notas.value = actual ? actual + (nuevas ? '\n\n' + nuevas : '') : nuevas;
            notas.dispatchEvent(new Event('input', { bubbles: true }));
        }
        dialogo.close();
        var primera = contenedor.querySelector('input[name="descripcion[]"]');
        if (primera) { primera.scrollIntoView({ block: 'center' }); primera.focus(); }
    });
})();
