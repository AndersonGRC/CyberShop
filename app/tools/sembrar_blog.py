# -*- coding: utf-8 -*-
"""Siembra los primeros artículos SEO del blog del OPERADOR (cybershopcol.com)
como BORRADORES redactados por la IA (el dueño revisa y publica desde
/admin/blog). Solo corre sobre la BD del tenant donde se ejecuta.

Uso:  python tools/sembrar_blog.py            # genera los que falten
      python tools/sembrar_blog.py --listar   # solo muestra el plan editorial
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app  # noqa: E402

# Plan editorial inicial: keywords transaccionales/informativas de Colombia
TEMAS = [
    ("Qué es un software POS y por qué tu negocio en Colombia necesita uno",
     "software pos colombia"),
    ("Cómo elegir un programa de punto de venta para tu tienda (guía práctica)",
     "programa punto de venta"),
    ("Software para restaurantes: controla mesas, cocina y caja sin enredos",
     "software para restaurantes colombia"),
    ("Control de inventario para pymes: deja atrás el cuaderno y el Excel",
     "software de inventario para pymes"),
    ("Facturación electrónica DIAN para pequeños negocios: lo que debes saber",
     "facturacion electronica DIAN"),
    ("Cómo empezar a vender en línea en Colombia con tu propia tienda",
     "como vender en linea en colombia"),
    ("Contabilidad sencilla para tu negocio: ingresos, gastos y cierres sin contador de tiempo completo",
     "software contable sencillo"),
    ("Un punto de venta que funciona sin internet: por qué importa en Colombia",
     "punto de venta sin internet"),
]


def main(solo_listar=False):
    from database import get_db_cursor
    from services.ai_service import generar_articulo_blog, ia_disponible

    if solo_listar:
        for t, k in TEMAS:
            print(f"  - {t}  [{k}]")
        return

    if not ia_disponible():
        print("El módulo de IA no está habilitado en este tenant."); return

    creados = 0
    for tema, keyword in TEMAS:
        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT 1 FROM blog_posts WHERE keyword_objetivo = %s", (keyword,))
            if cur.fetchone():
                print(f"  [ok] ya existe: {keyword}")
                continue
        print(f"  [IA] redactando: {tema[:60]}…")
        articulo, err = generar_articulo_blog(tema, keyword)
        if err:
            print(f"    [!] {err}")
            continue
        with get_db_cursor(dict_cursor=True) as cur:
            # slug único
            slug, n = articulo['slug_sugerido'], 1
            while True:
                cur.execute("SELECT 1 FROM blog_posts WHERE slug = %s", (slug,))
                if not cur.fetchone():
                    break
                n += 1
                slug = f"{articulo['slug_sugerido']}-{n}"
            cur.execute("""
                INSERT INTO blog_posts (titulo, slug, meta_descripcion, extracto,
                    cuerpo_html, keyword_objetivo, autor, estado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'borrador')
            """, (articulo['titulo'], slug, articulo['meta_descripcion'],
                  articulo['extracto'], articulo['cuerpo_html'], keyword,
                  'Equipo CyberShop'))
        creados += 1
        print(f"    [✓] borrador: /blog/{slug}")
    print(f"\n{creados} borrador(es) creados — revísalos en /admin/blog y publica.")


if __name__ == '__main__':
    # request context: el servicio de IA resuelve el tenant vía sesión
    with app.test_request_context('/'):
        from flask import session
        session['tenant_id'] = 1        # tenant OPERADOR (cybershopcol.com)
        main('--listar' in sys.argv)
