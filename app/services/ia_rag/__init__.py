"""Índice de textos del negocio (RAG) para el asistente.

Los HECHOS (precio, stock, horario) los responden las consultas fijas de
`services/ia_datos/`. Este paquete es para la PROSA: envíos, garantía, formas de
pago, quiénes somos. Cada cliente indexa su propia información en su propia base.
"""

from services.ia_rag.buscar import buscar, contexto_para_modelo  # noqa: F401
from services.ia_rag.indexador import (  # noqa: F401
    FUENTES, estado, indice_disponible, reindexar, reindexar_uno, texto_plano,
)
