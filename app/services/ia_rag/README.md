# `services/ia_rag/`

Índice de textos de cada cliente (tabla `ia_documentos`, migración 0012), en
dos mitades que nunca se mezclan:

| Mitad | Qué contiene | Quién lo lee |
|---|---|---|
| **Pública** (`canal_publico = TRUE`) | productos visibles, servicios, FAQ, páginas y blog publicados | el chat del sitio (`services/chat_publico/`), siempre con `solo_publico=True` |
| **Interna** (`canal_publico = FALSE`) | productos ocultos, borradores y los **documentos internos** | solo el asistente del panel |

- `indexador.py` — arma el índice desde las tablas reales (se puede borrar y
  reconstruir). `reindexar()` lo rehace entero; `reindexar_uno()` un grupo.
  `mantener_al_dia()` lo arma solo: el chat del sitio lo llama antes de buscar,
  y reconstruye si está vacío o si tiene más de un día (revisa como mucho cada
  10 min por proceso; un candado de Postgres deja reconstruir a uno solo a la
  vez). Si al cliente le falta la tabla (migración 0012), la crea.
- `buscar.py` — búsqueda por palabras, por parecido y por contenido.
  `solo_publico=True` (valor por defecto) es el candado del chat del sitio.
- `internos.py` — documentos internos (procedimientos, políticas, manuales)
  que el dueño escribe en `/admin/ia/documentos` (tabla
  `ia_documentos_internos`, migración 0016 del maestro). Visibilidad por
  documento: `administracion` (roles base 1 y 2) o `equipo` (quien usa el
  asistente). Se indexan por partes, con la visibilidad en la fuente
  (`interno_admin` / `interno_equipo`). Archivar no borra.

Los documentos internos los consulta la capacidad `documentos_internos`
(`services/ia_datos/`), declarada **solo local**: ni el puente de arranque en
frío ni el respaldo en la nube los reciben.

No usar el índice como fuente de cifras, precios o existencias: esas
respuestas salen de las herramientas de `services/ia_datos/`.

Inventario y estado: [IA_ARCHIVOS_Y_DEPENDENCIAS.md](../../docs/IA_ARCHIVOS_Y_DEPENDENCIAS.md).
