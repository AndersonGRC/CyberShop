"""Chat del sitio público (módulo ai_public).

Atiende a visitantes anónimos con la información que el propio negocio publicó:
catálogo, servicios, contacto y sus preguntas frecuentes. Nunca toca ventas,
contabilidad, nómina ni datos de clientes — eso lo garantiza la lista blanca del
canal público (services/ia_datos/acceso.py).
"""

from services.chat_publico.motor import config_publica, preparar, responder  # noqa: F401
from services.chat_publico.historial import preguntas_sin_responder  # noqa: F401
