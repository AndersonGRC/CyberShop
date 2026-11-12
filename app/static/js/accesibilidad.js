/**
 * accesibilidad.js — base común de accesibilidad (1.9.21.0).
 *
 * Lo cargan las dos plantillas base. No cambia el aspecto de nada:
 * 1. Los elementos marcados con data-a11y-boton (que no son <button>, como el
 *    menú de tres puntos de la tienda en el celular) responden a Enter y
 *    Espacio igual que a un clic.
 * 2. El menú de la tienda en el celular avisa si está abierto o cerrado
 *    (aria-expanded), según la clase nav-toggle que ya usa layout.js.
 */
(function () {
    'use strict';

    function activarConTeclado(evento) {
        var el = evento.target.closest ? evento.target.closest('[data-a11y-boton]') : null;
        if (!el || el.tagName === 'BUTTON') return;
        if (evento.key === 'Enter' || evento.key === ' ' || evento.key === 'Spacebar') {
            evento.preventDefault();
            el.click();
        }
    }

    function sincronizarMenuTienda() {
        var boton = document.querySelector('[data-a11y-menu-tienda]');
        var nav = document.querySelector('.nav');
        if (!boton || !nav) return;
        var abierto = nav.classList.contains('nav-toggle');
        boton.setAttribute('aria-expanded', abierto ? 'true' : 'false');
        boton.setAttribute('aria-label', abierto ? 'Cerrar menú' : 'Abrir menú');
    }

    document.addEventListener('keydown', activarConTeclado);

    document.addEventListener('click', function (evento) {
        if (evento.target.closest && evento.target.closest('[data-a11y-menu-tienda]')) {
            // layout.js alterna la clase en su propio clic; se lee después.
            setTimeout(sincronizarMenuTienda, 0);
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', sincronizarMenuTienda);
    } else {
        sincronizarMenuTienda();
    }
})();
