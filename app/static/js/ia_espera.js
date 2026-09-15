/* ia_espera.js — Mensajes de espera de la IA.
 *
 * Una respuesta puede tardar desde un segundo hasta más de un minuto (cuando el
 * modelo arranca en frío). Con un spinner o un "Pensando…" fijo el usuario cree
 * que se colgó, así que se le va contando en qué va, con frases que avanzan con
 * el tiempo.
 *
 * Si el servidor informa la fase real (el chat con streaming), esa frase manda y
 * el reloj solo rellena los silencios largos para que nunca parezca detenido.
 *
 * Uso:
 *   var espera = IAEspera.iniciar(elemento, { icono: '<i class="fas fa-spinner fa-spin"></i> ' });
 *   Opciones: icono (HTML antes del texto), primera (frase inicial propia del
 *   botón, p. ej. "Pensando un nombre…"), alPintar(texto) (destino que no es
 *   texto, p. ej. el placeholder de un textarea; reemplaza a `elemento`).
 *   espera.fase('Consultando tus ventas…');   // opcional: fase real del servidor
 *   espera.detener();                          // al llegar la respuesta o el error
 */
(function () {
    'use strict';

    // Secuencia base por tiempo transcurrido (segundos).
    var FRASES = [
        { a: 0,  texto: 'Estamos procesando los datos…' },
        { a: 4,  texto: 'Iniciamos el análisis de los datos…' },
        { a: 10, texto: 'Organizando la información más importante…' },
        { a: 18, texto: 'Pronto te entregaremos el resultado…' }
    ];

    // Esperas largas (arranque en frío): se rotan para que se note que sigue vivo.
    var LARGAS = [
        'Seguimos trabajando en tu análisis…',
        'La primera consulta tarda un poco más; ya casi está…',
        'Pronto te entregaremos el resultado…'
    ];

    var SILENCIO_MS = 12000;   // sin novedades durante este tiempo → frase de relleno

    function escapar(texto) {
        return String(texto == null ? '' : texto)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function iniciar(el, opciones) {
        opciones = opciones || {};
        var icono = opciones.icono || '';
        var timers = [];
        var relleno = null;
        var indiceLarga = 0;
        var activo = true;
        var frases = FRASES.map(function (f, i) {
            return { a: f.a, texto: (i === 0 && opciones.primera) ? opciones.primera : f.texto };
        });

        function pintar(texto) {
            if (!activo) return;
            if (typeof opciones.alPintar === 'function') { opciones.alPintar(texto); return; }
            if (!el) return;
            if (icono) el.innerHTML = icono + escapar(texto);
            else el.textContent = texto;
        }

        function programarRelleno() {
            if (relleno) clearInterval(relleno);
            relleno = setInterval(function () {
                pintar(LARGAS[indiceLarga % LARGAS.length]);
                indiceLarga += 1;
            }, SILENCIO_MS);
        }

        function limpiarSecuencia() {
            timers.forEach(clearTimeout);
            timers = [];
        }

        // Arranca la secuencia base (la primera frase se pinta ya, sin esperar).
        pintar(frases[0].texto);
        frases.slice(1).forEach(function (f, i, resto) {
            timers.push(setTimeout(function () {
                pintar(f.texto);
                // Tras la última frase base, empieza el relleno de esperas largas.
                if (i === resto.length - 1) programarRelleno();
            }, f.a * 1000));
        });

        return {
            // Fase real informada por el servidor: reemplaza la secuencia por tiempo.
            fase: function (texto) {
                if (!activo || !texto) return;
                limpiarSecuencia();
                pintar(texto);
                programarRelleno();
            },
            detener: function () {
                activo = false;
                limpiarSecuencia();
                if (relleno) clearInterval(relleno);
                relleno = null;
            }
        };
    }

    window.IAEspera = { iniciar: iniciar };
})();
