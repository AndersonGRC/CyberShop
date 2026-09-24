"""Registro único de capacidades del asistente.

Es la ÚNICA fuente de verdad sobre qué sabe hacer la IA. De aquí salen, sin
duplicar nada:

  - el catálogo de herramientas que se le muestra al modelo,
  - el enrutador determinista por palabras clave (`services/ia/enrutador.py`),
  - el mapa legible `docs/IA_MAPA.md` (`tools/ia_mapa.py`),
  - las pruebas que verifican que todo lo anterior sigue cuadrando.

Cada capacidad se declara en DOS lugares, a propósito:

  1. `services/ia_datos/__init__.py` — qué consulta, qué parámetros recibe y qué
     permisos exige. Va junto a la función, que es donde se entiende.
  2. `services/ia/intenciones.py` — con qué palabras la pide un humano, en qué
     canal se puede usar y con qué motor. Es una tabla corrida, para poder leer
     de un vistazo qué dispara qué.

`aplicar_intenciones()` las une y verifica que no se desfasen. Si una capacidad
no aparece en la tabla de intenciones, falla: así no se agregan herramientas
"invisibles" en el mapa.
"""

from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Tuple

# Dónde se puede usar una capacidad. OJO: esto NO es el canal de quien pregunta
# (eso vive en `ia_datos/acceso.py`: web, escritorio, sistema), sino el permiso
# de exposición de la capacidad misma.
CANAL_PANEL = 'panel'        # dentro del admin: sigue mandando la matriz de permisos
CANAL_PUBLICO = 'publico'    # visitante anónimo del sitio: SOLO lo declarado aquí
CANALES = (CANAL_PANEL, CANAL_PUBLICO)

# Qué motor la atiende (ver services/ia_motores.py).
MOTOR_RAPIDO = 'A'      # modelo chico, siempre encendido
MOTOR_BUENO = 'B'       # modelo bueno, cuando la máquina de IA está encendida
MOTOR_PROFUNDO = 'C'    # modelo grande y contexto largo, solo a propósito
MOTORES = (MOTOR_RAPIDO, MOTOR_BUENO, MOTOR_PROFUNDO)


@dataclass(frozen=True)
class Capacidad:
    """Una consulta que la IA puede elegir.

    modulos:      módulos del plan que deben estar activos (vacío = siempre).
    permiso:      módulo de la matriz de permisos que el rol debe poder 'ver'
                  (None = basta con poder usar el asistente).
    sensible:     None, o 'nomina' para datos que solo ven dueño y contador.
    etiqueta:     cómo se nombra al avisar "Consultando {etiqueta}…".
    canales:      dónde se puede usar. Por defecto SOLO el panel: nada queda
                  expuesto al público por olvido.
    disparadores: frases que la enrutan sin gastar modelo.
    ejemplos:     preguntas reales, usadas en el mapa y en las pruebas.
    perfil_motor: motor mínimo que la atiende bien.
    """
    code: str
    fn: Callable
    descripcion: str
    params: Tuple[str, ...] = ()
    etiqueta: str = 'los datos de tu negocio'
    dominio: str = 'general'
    modulos: Tuple[str, ...] = ()
    permiso: Optional[str] = None
    sensible: Optional[str] = None
    extra: dict = field(default_factory=dict, compare=False)
    canales: Tuple[str, ...] = (CANAL_PANEL,)
    disparadores: Tuple[str, ...] = ()
    ejemplos: Tuple[str, ...] = ()
    perfil_motor: str = MOTOR_RAPIDO

    @property
    def publica(self):
        return CANAL_PUBLICO in self.canales


# Nombre histórico: el resto del código (y el POS de escritorio, vía la fachada)
# importa `Herramienta`. Es la misma cosa.
Herramienta = Capacidad

REGISTRO = {}


def registrar(code, fn, descripcion, params=(), **kw):
    """Da de alta una capacidad. La llaman los módulos de `services/ia_datos/`."""
    REGISTRO[code] = Capacidad(code, fn, descripcion, tuple(params), **kw)
    return REGISTRO[code]


def aplicar_intenciones(tabla=None, estricto=True):
    """Fusiona la tabla de intenciones sobre el registro.

    Devuelve (faltan_en_tabla, sobran_en_tabla). Con estricto=True levanta si no
    cuadran: una capacidad sin intención declarada no aparecería en el mapa, y
    una intención sin capacidad es una referencia muerta.
    """
    if tabla is None:
        from services.ia.intenciones import INTENCIONES as tabla

    faltan = sorted(set(REGISTRO) - set(tabla))
    sobran = sorted(set(tabla) - set(REGISTRO))
    if estricto and (faltan or sobran):
        detalle = []
        if faltan:
            detalle.append(f"sin intención declarada: {', '.join(faltan)}")
        if sobran:
            detalle.append(f"intención sin capacidad: {', '.join(sobran)}")
        raise RuntimeError('El registro y services/ia/intenciones.py no cuadran — ' +
                           '; '.join(detalle))

    for code, datos in tabla.items():
        h = REGISTRO.get(code)
        if not h:
            continue
        canales = tuple(datos.get('canales', (CANAL_PANEL,)))
        motor = datos.get('motor', MOTOR_RAPIDO)
        if any(c not in CANALES for c in canales):
            raise RuntimeError(f'{code}: canal desconocido en {canales}')
        if motor not in MOTORES:
            raise RuntimeError(f'{code}: motor desconocido «{motor}»')
        REGISTRO[code] = replace(
            h,
            canales=canales,
            disparadores=tuple(datos.get('disparadores', ())),
            ejemplos=tuple(datos.get('ejemplos', ())),
            perfil_motor=motor,
        )
    return faltan, sobran


def publicas():
    """Capacidades expuestas al chat del sitio. Lista blanca: si no está aquí,
    un visitante no la puede ejecutar ni verla en el catálogo."""
    return [h for h in REGISTRO.values() if h.publica]


def mapa():
    """Filas para el mapa legible: qué dispara qué, en qué canal y con qué motor."""
    filas = []
    for h in REGISTRO.values():
        filas.append({
            'code': h.code,
            'dominio': h.dominio,
            'descripcion': h.descripcion,
            'params': list(h.params),
            'disparadores': list(h.disparadores),
            'ejemplos': list(h.ejemplos),
            'canales': list(h.canales),
            'motor': h.perfil_motor,
            'permiso': h.permiso,
            'modulos': list(h.modulos),
            'sensible': h.sensible,
        })
    return sorted(filas, key=lambda f: (f['dominio'], f['code']))
