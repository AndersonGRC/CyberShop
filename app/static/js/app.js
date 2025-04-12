// Toggle del menú principal
document.querySelector('.btn-menu').addEventListener('click', () => {
    document.querySelector('header').classList.toggle('hidden');
});

// Funcionalidad para submenús móviles
if (window.matchMedia("(max-width: 768px)").matches) {
    document.querySelectorAll('.nav ul li').forEach(item => {
        if (item.querySelector('.submenu')) {
            const link = item.querySelector('a');
            link.addEventListener('click', (e) => {
                e.preventDefault();
                item.classList.toggle('active');
                
                // Cerrar otros submenús
                document.querySelectorAll('.nav ul li').forEach(otherItem => {
                    if (otherItem !== item) {
                        otherItem.classList.remove('active');
                    }
                });
            });
        }
    });

    // Cerrar submenús al hacer click fuera
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.nav ul li')) {
            document.querySelectorAll('.nav ul li').forEach(item => {
                item.classList.remove('active');
            });
        }
    });
}