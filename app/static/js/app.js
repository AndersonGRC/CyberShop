/**
 * app.js — Comportamiento compartido del panel de administracion.
 *
 * Controla la apertura del sidebar en desktop/mobile, el backdrop en
 * pantallas pequenas, el marcado de enlace activo y los submenus
 * desplegables por clic en desktop y mobile.
 */

(function () {
    var sidebar = document.getElementById('app-sidebar') || document.querySelector('header');
    var toggleButton = document.querySelector('.btn-menu');
    var backdrop = document.querySelector('.layout-backdrop');
    var pageSubnavLinks = document.querySelectorAll('.Submenunavegacion a');
    var submenuParents = document.querySelectorAll('.nav ul li');

    if (!sidebar || !toggleButton) {
        return;
    }

    var wasMobile = window.matchMedia('(max-width: 768px)').matches;

    function isMobile() {
        return window.matchMedia('(max-width: 768px)').matches;
    }

    /* On mobile the CSS is inverted: default = translateX(-100%) hidden,
       .hidden class = translateX(0) visible.
       On desktop: default = visible, .hidden = translateX(-100%) hidden. */
    function isSidebarOpen() {
        return isMobile()
            ? sidebar.classList.contains('hidden')
            : !sidebar.classList.contains('hidden');
    }

    function syncSidebarState() {
        var mobile = isMobile();
        var open = isSidebarOpen();

        document.body.classList.toggle('sidebar-mobile-open', mobile && open);
        toggleButton.setAttribute('aria-expanded', String(open));

        if (backdrop) {
            backdrop.hidden = !(mobile && open);
        }
    }

    function closeSidebarOnMobile() {
        if (!isMobile()) {
            return;
        }
        sidebar.classList.remove('hidden');
        syncSidebarState();
    }

    function resetSidebarForViewport() {
        var mobile = isMobile();

        if (mobile !== wasMobile) {
            sidebar.classList.remove('hidden');
            submenuParents.forEach(function (item) { item.classList.remove('active'); });
            wasMobile = mobile;
        }

        syncSidebarState();
    }

    toggleButton.addEventListener('click', function () {
        sidebar.classList.toggle('hidden');
        syncSidebarState();
    });

    if (backdrop) {
        backdrop.addEventListener('click', closeSidebarOnMobile);
    }

    // Marca el enlace activo del submenu de pagina (tabs horizontales)
    (function markPageSubnav() {
        var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';

        pageSubnavLinks.forEach(function (link) {
            try {
                var linkPath = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, '') || '/';
                if (linkPath === currentPath) {
                    link.classList.add('active');
                }
            } catch (e) {
                // Ignora enlaces no parseables
            }
        });
    })();

    // Marca enlaces activos del sidebar y abre su submenu contenedor
    (function markSidebarActiveLink() {
        var currentPath = window.location.pathname.replace(/\/+$/, '') || '/';

        document.querySelectorAll('header .nav a[href]').forEach(function (link) {
            try {
                var linkPath = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, '') || '/';
                if (linkPath !== currentPath) {
                    return;
                }

                link.classList.add('is-active');

                var parentSubmenu = link.closest('.submenu');
                if (parentSubmenu) {
                    var parentItem = parentSubmenu.closest('li');
                    if (parentItem) {
                        parentItem.classList.add('has-active-child', 'active');
                        var trigger = parentItem.querySelector(':scope > a');
                        if (trigger) {
                            trigger.classList.add('is-active-parent');
                            trigger.setAttribute('aria-expanded', 'true');
                        }
                    }
                }
            } catch (e) {
                // Ignora enlaces no parseables
            }
        });
    })();

    function closeSiblingSubmenus(currentItem) {
        submenuParents.forEach(function (otherItem) {
            if (otherItem === currentItem) {
                return;
            }

            if (otherItem.classList.contains('has-active-child')) {
                return;
            }

            otherItem.classList.remove('active');
            var otherTrigger = otherItem.querySelector(':scope > a');
            if (otherTrigger) {
                otherTrigger.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // Submenus desplegables por clic
    submenuParents.forEach(function (item) {
        var submenu = item.querySelector(':scope > .submenu');
        var trigger = item.querySelector(':scope > a');

        if (!submenu || !trigger) {
            return;
        }

        trigger.setAttribute('aria-expanded', String(item.classList.contains('active')));

        trigger.addEventListener('click', function (event) {
            event.preventDefault();

            var willOpen = !item.classList.contains('active');
            closeSiblingSubmenus(item);

            item.classList.toggle('active', willOpen);
            trigger.setAttribute('aria-expanded', String(willOpen));
        });
    });

    // Click fuera del sidebar cierra submenus y sidebar en mobile
    document.addEventListener('click', function (event) {
        if (!event.target.closest('#app-sidebar') && !event.target.closest('header') && !event.target.closest('.btn-menu')) {
            submenuParents.forEach(function (item) {
                if (item.classList.contains('has-active-child')) {
                    return;
                }

                item.classList.remove('active');
                var trigger = item.querySelector(':scope > a');
                if (trigger) {
                    trigger.setAttribute('aria-expanded', 'false');
                }
            });

            if (isMobile()) {
                closeSidebarOnMobile();
            }
        }
    });

    window.addEventListener('resize', resetSidebarForViewport);
    syncSidebarState();
})();
