document.addEventListener("DOMContentLoaded", function () {
    const btnMenu = document.querySelector(".btn-menu");
    const header = document.querySelector("header");

    btnMenu.addEventListener("click", function () {
        header.classList.toggle("hidden");
    });

    // Ajustar el menú en dispositivos móviles
    function adjustMenuForMobile() {
        if (window.innerWidth <= 768) {
            header.classList.add("hidden"); // Menú colapsado por defecto en móviles
        } else {
            header.classList.remove("hidden"); // Menú expandido por defecto en escritorio
        }
    }

    // Ajustar el menú al cargar la página y al cambiar el tamaño de la ventana
    adjustMenuForMobile();
    window.addEventListener("resize", adjustMenuForMobile);
});