/**
 * wishlist.js — Manejo de lista de deseos (favoritos).
 *
 * Carga los IDs de productos favoritos del usuario y pinta
 * los corazones correspondientes. Permite toggle via AJAX.
 */

(function () {
    'use strict';

    var wishlistIds = [];
    var csrfToken = '';

    // Obtener CSRF token del meta tag
    var metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) csrfToken = metaTag.getAttribute('content');

    function init() {
        fetch('/api/wishlist/ids')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                wishlistIds = data.ids || [];
                pintarCorazones();
            })
            .catch(function () { /* silencioso si no hay sesion */ });
    }

    function pintarCorazones() {
        var botones = document.querySelectorAll('[data-wishlist-id]');
        botones.forEach(function (btn) {
            var prodId = parseInt(btn.getAttribute('data-wishlist-id'));
            var icon = btn.querySelector('i') || btn;
            if (wishlistIds.indexOf(prodId) !== -1) {
                icon.classList.remove('far');
                icon.classList.add('fas');
                btn.classList.add('wishlist-activo');
            } else {
                icon.classList.remove('fas');
                icon.classList.add('far');
                btn.classList.remove('wishlist-activo');
            }
        });
    }

    function toggleWishlist(e) {
        e.preventDefault();
        e.stopPropagation();

        var btn = e.currentTarget;
        var prodId = parseInt(btn.getAttribute('data-wishlist-id'));

        // Animacion rapida
        btn.style.transform = 'scale(1.3)';
        setTimeout(function () { btn.style.transform = ''; }, 200);

        fetch('/api/wishlist/toggle/' + prodId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            }
        })
            .then(function (r) {
                if (r.status === 401) {
                    if (typeof Swal !== 'undefined') {
                        Swal.fire({
                            icon: 'info',
                            title: 'Inicia sesión',
                            text: 'Debes iniciar sesión para agregar a favoritos.',
                            confirmButtonColor: 'var(--color-primario)'
                        });
                    }
                    return null;
                }
                return r.json();
            })
            .then(function (data) {
                if (!data) return;
                var icon = btn.querySelector('i') || btn;

                if (data.action === 'added') {
                    wishlistIds.push(prodId);
                    icon.classList.remove('far');
                    icon.classList.add('fas');
                    btn.classList.add('wishlist-activo');
                } else if (data.action === 'removed') {
                    wishlistIds = wishlistIds.filter(function (id) { return id !== prodId; });
                    icon.classList.remove('fas');
                    icon.classList.add('far');
                    btn.classList.remove('wishlist-activo');
                }
            })
            .catch(function () { /* silencioso */ });
    }

    // Delegacion de eventos para botones dinamicos
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-wishlist-id]');
        if (btn) toggleWishlist(e);
    });

    // Inicializar al cargar
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
