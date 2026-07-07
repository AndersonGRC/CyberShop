"""
services/image_optimizer.py — Optimización de imágenes subidas (SEO/CWV).

Las imágenes se subían tal cual (sliders de 600+ KB castigando el LCP de
Core Web Vitals). Este helper:
  - Redimensiona a máx MAX_ANCHO px (mantiene proporción; nunca agranda).
  - Recomprime: JPEG (quality 82, progresivo) y PNG grandes → re-encode
    optimizado (los PNG con transparencia se conservan como PNG).
  - Corrige la orientación EXIF (fotos de celular giradas).
  - NUNCA rompe el flujo: ante cualquier error deja el archivo original.

Uso (tras `product_images.save(...)` que devuelve el nombre guardado):
    from services.image_optimizer import optimizar_imagen
    optimizar_imagen(ruta_absoluta)
"""
import os

MAX_ANCHO = 1600
JPEG_QUALITY = 82
UMBRAL_BYTES = 60 * 1024   # < 60 KB no se toca (ya es liviana)


def optimizar_imagen(ruta, max_ancho=MAX_ANCHO):
    """Optimiza in-place. Devuelve (bytes_antes, bytes_despues) o None si no
    se tocó (liviana, formato no soportado o error)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        ruta = str(ruta)
        if not os.path.isfile(ruta):
            return None
        antes = os.path.getsize(ruta)
        ext = os.path.splitext(ruta)[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
            return None
        if antes < UMBRAL_BYTES:
            return None

        with Image.open(ruta) as img:
            img = ImageOps.exif_transpose(img)   # orientación de fotos móviles
            if img.width > max_ancho:
                alto = int(img.height * max_ancho / img.width)
                img = img.resize((max_ancho, alto), Image.LANCZOS)

            tmp = ruta + '.opt'
            if ext in ('.jpg', '.jpeg'):
                img = img.convert('RGB')
                img.save(tmp, 'JPEG', quality=JPEG_QUALITY,
                         optimize=True, progressive=True)
            elif ext == '.webp':
                img.save(tmp, 'WEBP', quality=JPEG_QUALITY, method=6)
            else:  # PNG: SIEMPRE se re-guarda como PNG (mismo formato que la
                    # extensión — nunca bytes JPEG bajo un nombre .png). El
                    # resize a 1600px ya da el grueso del ahorro.
                if img.mode == 'P':
                    img = img.convert('RGBA' if 'transparency' in img.info else 'RGB')
                img.save(tmp, 'PNG', optimize=True)

        despues = os.path.getsize(tmp)
        if despues < antes:
            os.replace(tmp, ruta)
            return antes, despues
        os.remove(tmp)               # no mejoró: conservar original
        return None
    except Exception:
        try:
            if os.path.isfile(ruta + '.opt'):
                os.remove(ruta + '.opt')
        except Exception:
            pass
        return None


def optimizar_guardado(upload_set, nombre_guardado):
    """Conveniencia: optimiza el archivo recién guardado por un UploadSet de
    Flask-Uploads. Silencioso (el upload nunca falla por la optimización)."""
    try:
        ruta = upload_set.path(nombre_guardado)
        resultado = optimizar_imagen(ruta)
        if resultado:
            antes, despues = resultado
            try:
                from flask import current_app
                current_app.logger.info(
                    f"imagen optimizada: {nombre_guardado} "
                    f"{antes // 1024}KB → {despues // 1024}KB")
            except Exception:
                pass
    except Exception:
        pass
    return nombre_guardado
