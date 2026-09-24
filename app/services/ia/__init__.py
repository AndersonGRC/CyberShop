"""Núcleo del asistente: el registro único de capacidades, el mapa de
intenciones y el enrutador determinista.

Las consultas (el SQL) viven en `services/ia_datos/`; los motores, en
`services/ia_motores.py`. Aquí está solo el "quién hace qué y cuándo".
"""

from services.ia.registro import (  # noqa: F401
    CANAL_PANEL, CANAL_PUBLICO, CANALES, MOTORES, MOTOR_BUENO, MOTOR_PROFUNDO, MOTOR_RAPIDO,
    Capacidad, Herramienta, REGISTRO, aplicar_intenciones, mapa, publicas, registrar,
)
