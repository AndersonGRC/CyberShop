# `services/ia_datos/`

Consultas de solo lectura agrupadas por dominio, con parámetros y permisos
validados. Usan la conexión del cliente actual; no son una base de datos
compartida. `__init__.py` importa los dominios y registra las 46 capacidades.
Las escrituras confirmadas viven aparte en `services/ia_acciones.py`.

Inventario y estado: [IA_ARCHIVOS_Y_DEPENDENCIAS.md](../../docs/IA_ARCHIVOS_Y_DEPENDENCIAS.md).
