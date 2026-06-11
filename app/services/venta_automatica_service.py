"""Orquestación de la venta automática de planes.

- `procesar_compra_plan(referencia)`: lo llaman el webhook de PayU y la página
  de respuesta cuando el pago queda APROBADO. Idempotente.
- `activar_tienda_async(compra_id, slug, nombre_negocio, base_url)`: lo llama
  la página de activación; corre en un hilo porque la creación (con SSL)
  tarda 30-90s y el worker de gunicorn mataría un request síncrono.
"""

import re
import threading

from flask import current_app

from services import plan_compras_service as pcs
from services.software_planes_service import get_plan


# Mismo regex de slug que valida el maestro (tenant_service._SLUG_RE)
SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def _enviar(destino, email_tuple):
    """Envía (asunto, texto, html) sin romper el flujo si el correo falla."""
    if not email_tuple or not destino:
        return False
    try:
        from helpers_gmail import enviar_email_gmail
        asunto, texto, html = email_tuple
        return enviar_email_gmail(destino, asunto, texto, html=html)
    except Exception as exc:  # noqa: BLE001
        try:
            current_app.logger.error(f"Email venta automática falló: {exc}")
        except Exception:
            pass
        return False


def _email_operador():
    from config import Config
    return Config.MAIL_USERNAME


def procesar_compra_plan(referencia, base_url='https://cybershopcol.com'):
    """Pago APROBADO de un pedido: si es compra de plan, dispara el flujo.
    Idempotente: solo actúa sobre estado PENDIENTE_PAGO. Seguro de llamar
    para cualquier referencia (si no es plan, no hace nada)."""
    compra = pcs.get_por_referencia(referencia)
    if not compra:
        return None
    plan = get_plan(compra['plan_key']) or {'nombre': compra['plan_key']}
    from helpers_email_templates import (
        generar_email_activacion_plan, generar_email_plan_anual,
        generar_email_aviso_operador, generar_email_recordatorio_pago,
    )

    # ── Renovación: extiende el período del plan original ──
    if compra.get('renovacion_de'):
        if compra['estado'] != 'PENDIENTE_PAGO':
            return 'ya-procesada'
        # Leer el padre ANTES de extender (extender_periodo limpia el flag
        # de suspensión y necesitamos saber si hay que revivir la instancia).
        padre_pre = pcs.get_por_id(compra['renovacion_de']) or {}
        pcs.marcar_contacto(compra['id'])  # cierra la fila de renovación
        padre = pcs.extender_periodo(compra['renovacion_de']) or {}

        reactivada = ''
        if padre_pre.get('suspendida_por_pago') and padre_pre.get('tenant_id'):
            try:
                from services.master_client import reactivar_tenant
                reactivar_tenant(padre_pre['tenant_id'])
                reactivada = ' — tienda REACTIVADA automáticamente'
            except Exception as exc:  # noqa: BLE001
                reactivada = f' — ⚠️ reactivación automática falló: {exc}'

        _enviar(compra['buyer_email'], generar_email_aviso_operador(
            f"✅ Renovación confirmada — {plan.get('nombre')}",
            [f"Tu tienda: {padre.get('dominio') or ''}"
             + (' (ya está activa de nuevo)' if 'REACTIVADA' in reactivada else ''),
             f"Próximo pago: {padre.get('proximo_pago')}",
             f"Referencia: {referencia}",
             "¡Gracias por seguir con nosotros!"]))
        _enviar(_email_operador(), generar_email_aviso_operador(
            f"💰 Renovación pagada — {plan.get('nombre')}{reactivada}",
            [f"Cliente: {compra.get('buyer_nombre')} <{compra.get('buyer_email')}>",
             f"Tienda: {padre.get('dominio') or ''}",
             f"Nuevo próximo pago: {padre.get('proximo_pago')}",
             f"Referencia: {referencia}"]))
        return 'renovacion'

    # ── Compra inicial ──
    if compra['plan_key'] in pcs.PLANES_AUTOMATICOS:
        token = pcs.marcar_pagada_con_token(compra['id'])
        if not token:
            return 'ya-procesada'
        url = f"{base_url.rstrip('/')}/activar-tienda/{token}"
        _enviar(compra['buyer_email'],
                generar_email_activacion_plan(compra, plan, url))
        resultado = 'activacion-enviada'
    else:
        if not pcs.marcar_contacto(compra['id']):
            return 'ya-procesada'
        _enviar(compra['buyer_email'], generar_email_plan_anual(compra, plan))
        resultado = 'contacto'

    _enviar(_email_operador(), generar_email_aviso_operador(
        f"💰 Nueva venta — {plan.get('nombre')}",
        [f"Cliente: {compra.get('buyer_nombre')} <{compra.get('buyer_email')}>",
         f"Plan: {plan.get('nombre')} ({compra.get('periodo')})",
         f"Referencia: {referencia}",
         f"Flujo: {'activación automática enviada' if resultado == 'activacion-enviada' else 'manejo manual (te contactaremos)'}"]))
    return resultado


def validar_slug(slug):
    """Valida el subdominio elegido. Devuelve (slug_normalizado, error|None)."""
    slug = (slug or '').strip().lower()
    if not (3 <= len(slug) <= 40) or not SLUG_RE.match(slug):
        return slug, ('Usa solo minúsculas, números y guiones (3-40 caracteres), '
                      'sin empezar ni terminar con guión. Ej: panaderia-roma')
    return slug, None


def activar_tienda_async(app, compra_id, slug, nombre_negocio):
    """Lanza el hilo que crea la tienda en el maestro y envía la bienvenida.
    `app` es el Flask app real (para el contexto dentro del hilo)."""

    def _worker():
        with app.app_context():
            from services.master_client import crear_tenant_en_maestro, MasterError
            from helpers_email_templates import (
                generar_email_bienvenida_tienda, generar_email_aviso_operador)
            compra = pcs.get_por_id(compra_id)
            if not compra:
                return
            plan = get_plan(compra['plan_key']) or {}
            master_plan = pcs.PLANES_AUTOMATICOS.get(compra['plan_key'], 'estandar')
            try:
                resultado = crear_tenant_en_maestro(
                    slug=slug, nombre=nombre_negocio,
                    email=compra['buyer_email'], master_plan=master_plan)
                pcs.marcar_activada(compra_id, resultado.get('tenant_id'),
                                    slug, resultado.get('domain'),
                                    periodo=compra.get('periodo') or 'mes')
                compra = pcs.get_por_id(compra_id)
                _enviar(compra['buyer_email'],
                        generar_email_bienvenida_tienda(compra, plan, resultado))
                _enviar(_email_operador(), generar_email_aviso_operador(
                    f"🚀 Tienda activada — {resultado.get('domain')}",
                    [f"Cliente: {compra.get('buyer_nombre')} <{compra.get('buyer_email')}>",
                     f"Plan: {plan.get('nombre')} → módulos '{master_plan}'",
                     f"Tenant ID: {resultado.get('tenant_id')} | Puerto: {resultado.get('port')}"]))
            except MasterError as exc:
                pcs.marcar_error(compra_id, str(exc))
            except Exception as exc:  # noqa: BLE001
                pcs.marcar_error(compra_id, f'Error inesperado: {exc}')
                try:
                    app.logger.exception('Activación de tienda falló')
                except Exception:
                    pass

    hilo = threading.Thread(target=_worker, daemon=True, name=f'activar-{compra_id}')
    hilo.start()
    return hilo
