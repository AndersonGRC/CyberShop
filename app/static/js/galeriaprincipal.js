/**
 * galeriaprincipal.js — Menu movil y slider de imagenes para paginas internas.
 *
 * Secciones:
 * 1. Toggle del menu lateral en dispositivos moviles (jQuery)
 * 2. Slider de imagenes con controles prev/next, autoplay cada 4s
 *    y pause on hover
 *
 * Dependencias: jQuery 3.3.1
 */

/*1. Menu Lateral de celular*/

// Agrega un evento 'click' al botón con la clase 'btn-menu'
$('.btn-menu').on('click', function () {
    // Alterna la clase 'nav-toggle' en el elemento con la clase 'nav'
    $('.nav').toggleClass('nav-toggle');
});


/*2. Slider de imágenes */

// Selección de elementos necesarios para el slider
const slider = document.querySelector(".slider"); // Contenedor del slider
const nextBtn = document.querySelector(".next-btn"); // Botón siguiente
const prevBtn = document.querySelector(".prev-btn"); // Botón anterior
const slides = document.querySelectorAll(".slide"); // Todas las diapositivas
const slideIcons = document.querySelectorAll(".slide-icon"); // Iconos de las diapositivas
const numberOfSlides = slides.length; // Número total de diapositivas
var slideNumber = 0; // Índice actual de la diapositiva

// Evento para pasar a la siguiente diapositiva
nextBtn.addEventListener("click", () => {
    // Elimina la clase 'active' de todas las diapositivas
    slides.forEach((slide) => slide.classList.remove("active"));
    slideIcons.forEach((slideIcon) => slideIcon.classList.remove("active"));

    // Incrementa el índice de la diapositiva
    slideNumber++;

    // Si el índice supera el número de diapositivas, vuelve al inicio
    if (slideNumber > (numberOfSlides - 1)) {
        slideNumber = 0;
    }

    // Agrega la clase 'active' a la diapositiva actual
    slides[slideNumber].classList.add("active");
    slideIcons[slideNumber].classList.add("active");
});

// Evento para regresar a la diapositiva anterior
prevBtn.addEventListener("click", () => {
    // Elimina la clase 'active' de todas las diapositivas
    slides.forEach((slide) => slide.classList.remove("active"));
    slideIcons.forEach((slideIcon) => slideIcon.classList.remove("active"));

    // Decrementa el índice de la diapositiva
    slideNumber--;

    // Si el índice es menor a 0, salta a la última diapositiva
    if (slideNumber < 0) {
        slideNumber = numberOfSlides - 1;
    }

    // Agrega la clase 'active' a la diapositiva actual
    slides[slideNumber].classList.add("active");
    slideIcons[slideNumber].classList.add("active");
});
/* Imagen slider autoplay */
var playSlider;

// Función para activar el autoplay
var repeater = () => {
    playSlider = setInterval(function () {
        // Elimina la clase 'active' de todas las diapositivas
        slides.forEach((slide) => slide.classList.remove("active"));
        slideIcons.forEach((slideIcon) => slideIcon.classList.remove("active"));

        // Incrementa el índice de la diapositiva
        slideNumber++;

        // Si el índice supera el número de diapositivas, vuelve al inicio
        if (slideNumber > (numberOfSlides - 1)) {
            slideNumber = 0;
        }

        // Agrega la clase 'active' a la diapositiva actual
        slides[slideNumber].classList.add("active");
        slideIcons[slideNumber].classList.add("active");
    }, 4000); // Cambia cada 4 segundos
};

// Llama a la función de autoplay
repeater();

// Pausa el autoplay cuando el mouse pasa sobre el slider
slider.addEventListener("mouseover", () => {
    clearInterval(playSlider); // Detiene el autoplay
});

// Reinicia el autoplay cuando el mouse sale del slider
slider.addEventListener("mouseout", () => {
    repeater(); // Reinicia el autoplay
});


