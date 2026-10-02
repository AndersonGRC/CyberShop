/* Imágenes de muestra para tiendas nuevas (prueba gratis / compra en línea).
 *
 * Cada <img data-demo-img> se reemplaza por una ilustración generada aquí con
 * los colores de la marca del cliente (variables CSS) y un texto del tipo
 * «Tus imágenes corporativas van aquí». No descarga nada: es un SVG en línea.
 * Atributos: data-demo-texto (título), data-demo-sub (subtítulo),
 *            data-demo-icono = 'imagen' | 'logo' | 'servicio',
 *            data-demo-modo = 'fondo' cuando la página ya pone su propio texto
 *            encima (carrusel): el aviso va como etiqueta pequeña arriba
 *            (sin data-demo-texto, solo el fondo); data-demo-tam = 'grande'
 *            para imágenes que se ven pequeñas (tarjetas de ~150 px).
 */
(function () {
  'use strict';

  function color(nombre, respaldo) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
    return v || respaldo;
  }

  function esc(t) {
    return String(t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // Parte un texto en líneas de ~n caracteres para que quepa en el SVG.
  function lineas(texto, n) {
    var palabras = String(texto || '').split(/\s+/), out = [], actual = '';
    palabras.forEach(function (p) {
      if ((actual + ' ' + p).trim().length > n && actual) { out.push(actual); actual = p; }
      else { actual = (actual + ' ' + p).trim(); }
    });
    if (actual) out.push(actual);
    return out.slice(0, 3);
  }

  var ICONOS = {
    imagen: '<rect x="-46" y="-34" width="92" height="68" rx="10" fill="none" stroke="#fff" stroke-width="6"/>' +
            '<path d="M-38 26 L-12 -4 L6 14 L18 2 L38 26 Z" fill="#fff"/><circle cx="20" cy="-14" r="8" fill="#fff"/>',
    logo: '<circle r="40" fill="none" stroke="#fff" stroke-width="6" stroke-dasharray="10 8"/>' +
          '<path d="M-14 6 L0 -12 L14 6 Z M-14 6 h28 v12 h-28 Z" fill="#fff"/>',
    servicio: '<rect x="-36" y="-36" width="72" height="72" rx="16" fill="none" stroke="#fff" stroke-width="6"/>' +
              '<path d="M-16 0 l11 11 l21 -23" fill="none" stroke="#fff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
  };

  function svg(el) {
    var ancho = 1200, alto = el.getAttribute('data-demo-alto') ? Number(el.getAttribute('data-demo-alto')) : 675;
    var c1 = color('--color-primario', '#334155'), c2 = color('--color-primario-oscuro', '#0f172a');
    var grande = el.getAttribute('data-demo-tam') === 'grande';
    var fondo = el.getAttribute('data-demo-modo') === 'fondo';
    var crudo = el.getAttribute('data-demo-texto');
    var titulo = lineas(crudo === null ? 'Tus imágenes corporativas van aquí' : crudo, grande ? 16 : 26);
    var sub = lineas(el.getAttribute('data-demo-sub') || '', 52);
    var icono = ICONOS[el.getAttribute('data-demo-icono')] || ICONOS.imagen;
    var textos = '', marco = '';
    if (fondo && !titulo.length) {
      icono = '';
    } else if (fondo) {
      // Etiqueta centrada arriba, angosta para que no se recorte en celular.
      var t = titulo.join(' ');
      var w = Math.min(440, t.length * 13 + 100);
      marco = '<g transform="translate(600 112)"><rect x="' + (-w / 2) + '" y="-34" width="' + w + '" height="68" rx="34" fill="#000" fill-opacity=".28" stroke="#fff" stroke-opacity=".6" stroke-width="2" stroke-dasharray="8 6"/>' +
        '<g transform="translate(' + (-w / 2 + 46) + ' 0) scale(.42)">' + icono + '</g></g>';
      textos = '<text x="' + (600 + 30) + '" y="121" font-size="24" font-weight="700">' + esc(t) + '</text>';
      icono = '';
    } else {
      var fs = grande ? 120 : 58, alto_l = grande ? 134 : 70, k = grande ? 2.4 : 1;
      var cy = alto / 2 - (titulo.length * alto_l + sub.length * 44) / 2 + (grande ? 70 : 0);
      var y = cy + alto_l;
      titulo.forEach(function (l) { textos += '<text x="600" y="' + y + '" font-size="' + fs + '" font-weight="800">' + esc(l) + '</text>'; y += alto_l; });
      y += 6;
      sub.forEach(function (l) { textos += '<text x="600" y="' + y + '" font-size="30" opacity=".9">' + esc(l) + '</text>'; y += 42; });
      icono = '<g transform="translate(600 ' + (cy - 30 * k) + ') scale(' + k + ')">' + icono + '</g>';
    }
    var s = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + ancho + ' ' + alto + '" preserveAspectRatio="xMidYMid slice">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + esc(c1) + '"/>' +
      '<stop offset="1" stop-color="' + esc(c2) + '"/></linearGradient>' +
      '<pattern id="p" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M0 48 L48 0" stroke="#fff" stroke-opacity=".07" stroke-width="2"/></pattern></defs>' +
      '<rect width="100%" height="100%" fill="url(#g)"/><rect width="100%" height="100%" fill="url(#p)"/>' +
      '<rect x="40" y="40" width="' + (ancho - 80) + '" height="' + (alto - 80) + '" rx="28" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="' + (grande ? 12 : 4) + '" stroke-dasharray="' + (grande ? '40 30' : '18 14') + '"/>' +
      icono + marco +
      '<g fill="#fff" font-family="Segoe UI, Roboto, Arial, sans-serif" text-anchor="middle">' + textos + '</g></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s);
  }

  function pintar() {
    document.querySelectorAll('img[data-demo-img]').forEach(function (img) {
      img.removeAttribute('srcset');
      var pic = img.closest('picture');
      if (pic) pic.querySelectorAll('source').forEach(function (s) { s.remove(); });
      img.src = svg(img);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pintar);
  else pintar();
})();
