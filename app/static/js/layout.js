/*2. Menú fijo al hacer scroll*/

var elementTop = $('.nav').offset().top;

$(window).scroll(function(){
    if( $(window).scrollTop() >= elementTop){
        $('body').addClass('nav_fixed');
    } else {
        $('body').removeClass('nav_fixed');
    }
});