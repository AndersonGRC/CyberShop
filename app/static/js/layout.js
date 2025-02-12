
/*1. Botón de menú desplegable*/ 
document.querySelector('.btn-menu').addEventListener('click', function () {
    const menu = document.querySelector('nav ul');
    menu.classList.toggle('open');
    menu.classList.toggle('hidden');
});


/*2. Menú fijo al hacer scroll*/

var elementTop = $('.nav').offset().top;

$(window).scroll(function(){
    if( $(window).scrollTop() >= elementTop){
        $('body').addClass('nav_fixed');
    } else {
        $('body').removeClass('nav_fixed');
    }
});
/*3. Alternar clase del menú*/

// Agrega un evento 'click' al botón con la clase 'btn-menu'
$('.btn-menu').on('click', function() {
    // Alterna la clase 'nav-toggle' en el elemento con la clase 'nav'
    $('.nav').toggleClass('nav-toggle');
});

/*5. Slider de imágenes*/

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
// Variable para el intervalo del slider
var playSlider;

// Función para activar el autoplay
var repeater = () => {
    playSlider = setInterval(function() {
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






//Componente de tarjeta interactiva usando Vue.js


//TARGETAS
// Habilita las herramientas de desarrollo de Vue.js
Vue.config.devtools = true;

// Define un componente Vue llamado 'card'
Vue.component('card', {
    // Plantilla HTML del componente
    template: `
    <div class="card-wrap"
        @mousemove="handleMouseMove" 
        @mouseenter="handleMouseEnter" 
        @mouseleave="handleMouseLeave" 
        ref="card">
        <div class="card" :style="cardStyle">
            <div class="card-bg" :style="[cardBgTransform, cardBgImage]"></div>
            <div class="card-info">
                <slot name="header"></slot> <!-- Espacio para el encabezado -->
                <slot name="content"></slot> <!-- Espacio para el contenido -->
            </div>
        </div>
    </div>`,
    
    // Define las propiedades del componente
    props: ['dataImage'], // Recibe una imagen como propiedad externa
    
    // Define el estado inicial del componente
    data: () => ({
        width: 0, // Ancho de la tarjeta
        height: 0, // Alto de la tarjeta
        mouseX: 0, // Posición X del mouse
        mouseY: 0, // Posición Y del mouse
        mouseLeaveDelay: null // Temporizador para cuando el mouse sale de la tarjeta
    }),
    
    // Computed properties: Calcula dinámicamente estilos y transformaciones
    computed: {
        mousePX() {
            return this.mouseX / this.width; // Proporción X del mouse
        },
        mousePY() {
            return this.mouseY / this.height; // Proporción Y del mouse
        },
        cardStyle() {
            const rX = this.mousePX * 30; // Rotación en X
            const rY = this.mousePY * -30; // Rotación en Y
            return {
                transform: `rotateY(${rX}deg) rotateX(${rY}deg)`
            };
        },
        cardBgTransform() {
            const tX = this.mousePX * -40; // Traslación en X
            const tY = this.mousePY * -40; // Traslación en Y
            return {
                transform: `translateX(${tX}px) translateY(${tY}px)`
            };
        },
        cardBgImage() {
            return {
                backgroundImage: `url(${this.dataImage})` // Imagen de fondo
            };
        }
    },
    
    // Métodos del componente
    methods: {
        handleMouseMove(e) {
            // Actualiza las coordenadas del mouse
            this.mouseX = e.pageX - this.$refs.card.offsetLeft - this.width / 2;
            this.mouseY = e.pageY - this.$refs.card.offsetTop - this.height / 2;
        },
        handleMouseEnter() {
            clearTimeout(this.mouseLeaveDelay); // Cancela el temporizador cuando el mouse entra
        },
        handleMouseLeave() {
            // Establece un retraso para reiniciar la posición del mouse
            this.mouseLeaveDelay = setTimeout(() => {
                this.mouseX = 0;
                this.mouseY = 0;
            }, 1000); // 1 segundo de retraso
        }
    },
    
    // Lifecycle hook: se ejecuta cuando el componente se monta
    mounted() {
        this.width = this.$refs.card.offsetWidth; // Calcula el ancho de la tarjeta
        this.height = this.$refs.card.offsetHeight; // Calcula el alto de la tarjeta
    }
});

// Instancia de Vue
const app = new Vue({
    el: '#app' // Conecta Vue al elemento con id 'app'
});



