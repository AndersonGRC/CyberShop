# -*- coding: utf-8 -*-
"""Optimiza las imágenes YA subidas en static/media y static/img (one-shot).

Las subidas nuevas se optimizan solas (wrap en app.py); este script arregla lo
histórico (sliders de 600+ KB → <100 KB) para mejorar LCP/Core Web Vitals.

Uso:
    python tools/optimizar_media.py --dry-run   # muestra qué haría
    python tools/optimizar_media.py             # optimiza in-place
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.image_optimizer import optimizar_imagen, UMBRAL_BYTES  # noqa: E402

CARPETAS = ('static/media', 'static/img')
EXTS = ('.jpg', '.jpeg', '.png', '.webp')


def main(dry_run):
    base = Path(__file__).resolve().parent.parent
    total_antes = total_despues = tocadas = 0
    for carpeta in CARPETAS:
        raiz = base / carpeta
        if not raiz.is_dir():
            continue
        for ruta in sorted(raiz.rglob('*')):
            if not ruta.is_file() or ruta.suffix.lower() not in EXTS:
                continue
            peso = ruta.stat().st_size
            if peso < UMBRAL_BYTES:
                continue
            if dry_run:
                print(f"  [DRY] {ruta.relative_to(base)} ({peso // 1024} KB)")
                tocadas += 1
                continue
            resultado = optimizar_imagen(str(ruta))
            if resultado:
                antes, despues = resultado
                total_antes += antes
                total_despues += despues
                tocadas += 1
                print(f"  [OK] {ruta.relative_to(base)}: "
                      f"{antes // 1024} KB → {despues // 1024} KB")
    if dry_run:
        print(f"\n{tocadas} imagen(es) candidatas (>{UMBRAL_BYTES // 1024} KB).")
    else:
        ahorro = total_antes - total_despues
        print(f"\n{tocadas} optimizadas — ahorro total {ahorro // 1024} KB "
              f"({total_antes // 1024} → {total_despues // 1024} KB).")


if __name__ == '__main__':
    main('--dry-run' in sys.argv)
