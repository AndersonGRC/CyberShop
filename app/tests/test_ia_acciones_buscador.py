# -*- coding: utf-8 -*-
"""Fase 1 de las acciones del panel: encontrar el contacto como lo nombra la
persona, «el que acabo de crear», reactivar y teléfonos por número completo.

Caso real (Panadería Nicol's, 28-sep): tras crear «Cybershop», el dueño pidió
«edita el contacto de Cybershop Proveedor Tecnológico…» y la IA respondió «No
encontré ese contacto» (exigía el nombre exacto); luego «está ubicado en Bogotá»
se fue al chat de consultas."""
import uuid

import pytest

from services import ia_acciones as acciones
from services.ia import buscador

MARCA = uuid.uuid4().hex[:6]


@pytest.fixture()
def contactos(cursor):
    """Tres contactos con nombres que no existen en la base de pruebas."""
    datos = [
        ('Zyxshop', 'proveedor', f'ventas{MARCA}@zyxshop.co', '3027974969'),
        ('Distribuidora Qwandes', 'proveedor', None, None),
        ('Qwandes Tech', 'cliente', None, None),
    ]
    ids = {}
    with cursor() as cur:
        for nombre, tipo, email, tel in datos:
            cur.execute("""INSERT INTO crm_contactos (tipo, nombre, email, telefono, activo, notas)
                           VALUES (%s, %s, %s, %s, TRUE, %s) RETURNING id""",
                        (tipo, nombre, email, tel, f'pytest {MARCA}'))
            ids[nombre] = cur.fetchone()['id']
    yield ids
    with cursor() as cur:
        cur.execute('DELETE FROM crm_contactos WHERE notas = %s', (f'pytest {MARCA}',))


def _elegido(cur, referencia, activos=True):
    filas, modo = buscador.contactos(cur, referencia, activos=activos)
    return buscador.elegir(filas, modo), filas, modo


def test_el_caso_de_la_panaderia_encuentra_el_contacto(contactos, cursor):
    with cursor() as cur:
        elegido, _, modo = _elegido(cur, 'Zyxshop Provvedor Tecnologico')
    assert elegido['id'] == contactos['Zyxshop'] and modo == 'parcial'


@pytest.mark.parametrize('referencia', ['302 797 4969', 'ventas{m}@zyxshop.co', 'zyxshop'])
def test_por_telefono_correo_o_nombre(contactos, cursor, referencia):
    with cursor() as cur:
        elegido, _, _ = _elegido(cur, referencia.format(m=MARCA))
    assert elegido['id'] == contactos['Zyxshop']


def test_con_varios_candidatos_no_adivina(contactos, cursor):
    with cursor() as cur:
        elegido, filas, modo = _elegido(cur, 'Qwandes')
        assert elegido is None and modo == 'todas'
        assert {f['id'] for f in filas} >= {contactos['Distribuidora Qwandes'],
                                              contactos['Qwandes Tech']}
        elegido, _, _ = _elegido(cur, 'Distribuidora Qwandes')
        assert elegido['id'] == contactos['Distribuidora Qwandes']
        with pytest.raises(acciones.AccionAclarar) as exc:
            acciones._contacto(cur, {'contacto': 'Qwandes'})
    mensaje = str(exc.value)
    assert f"ID {contactos['Qwandes Tech']} · Qwandes Tech · cliente" in mensaje
    assert 'Responde con su ID' in mensaje


def test_reactivar_de_punta_a_punta(contactos, cursor):
    cid = contactos['Zyxshop']
    with cursor() as cur:
        cur.execute('UPDATE crm_contactos SET activo = FALSE WHERE id = %s', (cid,))
    with cursor() as cur:
        with pytest.raises(acciones.AccionAclarar, match='No encontré un contacto activo'):
            acciones._contacto(cur, {'contacto': 'Zyxshop'})
        payload, resumen, _ = acciones._preparar_datos(
            cur, {'tipo': 'reactivar_contacto', 'contacto': 'Zyxshop'})
        assert resumen == f'Reactivar contacto Zyxshop (ID {cid}).'
        resultado = acciones._ejecutar(cur, {'tipo': 'reactivar_contacto', 'payload': payload}, 1)
    assert resultado['contacto_id'] == cid
    with cursor() as cur:
        cur.execute('SELECT activo FROM crm_contactos WHERE id = %s', (cid,))
        assert cur.fetchone()['activo'] is True


@pytest.mark.parametrize('frase, tipo', [
    ('Reactiva el contacto Zyxshop', 'reactivar_contacto'),
    ('Activa de nuevo el proveedor Andes', 'reactivar_contacto'),
    ('Desactiva el contacto Zyxshop', 'eliminar_contacto'),
    ('Archiva el proveedor Andes', 'eliminar_contacto'),
])
def test_verbos_de_activar_y_desactivar(frase, tipo):
    assert acciones.parece_operativa(frase) and acciones._tipo_solicitado(frase) == tipo


# ── Respuestas cortas y «el que acabo de crear» ────────────────
@pytest.mark.parametrize('respuesta, dato', [
    ('1', 'ID 1'), ('el 12', 'ID 12'), ('#7', 'ID 7'), ('proveedor', 'proveedor'),
])
def test_elegir_por_id_de_la_lista(respuesta, dato):
    assert acciones.combinar('Edita el contacto Qwandes', respuesta) == \
        f'Edita el contacto Qwandes. Dato adicional: {dato}'


def test_el_id_elegido_cuenta_como_dicho():
    plan = {'tipo': 'editar_contacto', 'contacto_id': 7, 'cambios': {'ciudad': 'Cali'}}
    acciones._solo_datos_dichos(
        plan, acciones.combinar('Cambia la ciudad del contacto Qwandes a Cali', '7'), None)


def test_dato_suelto_sobre_el_ultimo_contacto():
    ultimo = {'entidad': 'contacto', 'id': 1}
    orden = acciones.sobre_ultimo(ultimo, 'está ubicado en Bogotá')
    assert orden == 'Edita el contacto ID 1: está ubicado en Bogotá'
    plan = {'tipo': 'editar_contacto', 'contacto_id': 1, 'cambios': {'ciudad': 'Bogotá'}}
    acciones._solo_datos_dichos(plan, orden, None)
    assert acciones.sobre_ultimo(ultimo, '¿Dónde está ubicado?') is None
    assert acciones.sobre_ultimo(ultimo, 'hola') is None
    assert acciones.sobre_ultimo(None, 'está ubicado en Bogotá') is None


def test_la_ruta_usa_el_ultimo_registro(monkeypatch):
    from routes import ia as rutas
    monkeypatch.setattr(acciones, 'ultimo_registro', lambda: {'entidad': 'contacto', 'id': 1})
    assert rutas._texto_de_accion('está ubicado en Bogotá', None) == (
        'Edita el contacto ID 1: está ubicado en Bogotá', False)
    monkeypatch.setattr(acciones, 'ultimo_registro',
                        lambda: pytest.fail('sin dato de contacto no se consulta la base'))
    assert rutas._texto_de_accion('¿cuánto vendí hoy?', None) == (None, False)


# ── Teléfonos: número completo, no dígitos pegados ─────────────
def test_telefono_por_numero_completo():
    assert acciones._numero_dicho('3027974969', 'mi número es 302 797 4969')
    assert acciones._numero_dicho('573027974969', 'teléfono 3027974969')
    # Antes: «302797496» + «9 unidades» pegados formaban un número que nadie dijo.
    assert not acciones._numero_dicho('3027974969', 'teléfono 302797496 y 9 unidades')


def test_aviso_de_telefono_incompleto():
    assert acciones._avisos_telefono({'telefono': '302797496'}) == [
        '⚠ El telefono 302797496 tiene 9 dígitos; revisa que esté completo.']
    assert acciones._avisos_telefono({'telefono': '3027974969', 'whatsapp': '573027974969'}) == []


# ── Identidad sin depender de que el modelo la copie (medido con Qwen) ──
@pytest.mark.parametrize('frase, tipo, nombre', [
    ('Desactiva el contacto Cybershop', 'eliminar_contacto', 'Cybershop'),
    ('Elimina el proveedor Andes', 'eliminar_contacto', 'Andes'),
    ('Activa de nuevo el proveedor Cybershop', 'reactivar_contacto', 'Cybershop'),
    ('Archiva el cliente Ana Pérez por favor', 'eliminar_contacto', 'Ana Pérez'),
])
def test_si_el_modelo_pide_el_contacto_se_toma_de_la_frase(frase, tipo, nombre):
    assert acciones._tipo_solicitado(frase) == tipo
    plan = acciones._completar_identidad({'tipo': 'aclarar', 'campo': 'contacto'}, tipo, frase)
    assert plan == {'tipo': tipo, 'contacto': nombre}


def test_sin_nombre_sigue_preguntando():
    plan = {'tipo': 'aclarar', 'campo': 'contacto'}
    assert acciones._completar_identidad(plan, 'reactivar_contacto', 'Reactiva un contacto') == plan


def test_el_id_elegido_de_la_lista_manda_sobre_el_nombre_ambiguo():
    orden = acciones.combinar('Cambia la ciudad del contacto Qwandes a Cali', '37')
    plan = {'tipo': 'editar_contacto', 'contacto': 'Qwandes', 'cambios': {'ciudad': 'Cali'}}
    assert acciones._completar_identidad(plan, 'editar_contacto', orden) == {
        'tipo': 'editar_contacto', 'cambios': {'ciudad': 'Cali'}, 'contacto_id': 37}


def test_cliente_suelto_no_es_una_orden():
    assert not acciones.parece_operativa('Crea un pedido para el cliente Juan')
