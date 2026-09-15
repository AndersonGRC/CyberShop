"""Herramientas de solo-lectura del Asistente IA conversacional (fachada).

El código vive en `services/ia_datos/` (un módulo por dominio, con registro,
permisos por rol y parámetros validados). Este módulo se conserva porque
ai_service, el dashboard y el inventario importan desde aquí.
"""

from services.ia_datos import (  # noqa: F401
    CONTEXTO_DATOS, REGISTRO, TOOLS, Contexto, Herramienta, catalogo_para_prompt, contexto_actual,
    ejecutar, permitidas, puede_usar, sanear_params,
)
from services.ia_datos.base import (  # noqa: F401
    _PEDIDO_PAGADO, _PERIODO_SQL, _columnas, _existe, _label_periodo, _periodo, _sql_periodo, _suma,
)
from services.ia_datos.inventario import (  # noqa: F401
    catalogo_pendiente, productos_bajo_stock, resumen_inventario, sugerencia_reorden,
)
from services.ia_datos.ventas import (  # noqa: F401
    _CLAVES_ANONIMAS, _DIAS_SEMANA, _analizar_segmentos, _analizar_tendencia, _ventas_en,
    conteo_general, kpis_dashboard, pedidos_por_despachar, segmentos_clientes, tendencia_ventas,
    top_clientes, top_productos, ventas_periodo,
)
