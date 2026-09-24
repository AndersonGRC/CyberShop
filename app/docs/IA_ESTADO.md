# Asistente de IA: estado del trabajo, hallazgos y qué falta

> **Para quien retome esto.** Documento de traspaso, escrito el 24/09/2026.
> Dice qué está hecho, por qué está hecho así, qué se midió y qué queda.
> Lo que está en el código no se repite aquí: se apunta a dónde mirar.

Documentos hermanos:
- [`IA_MAPA.md`](IA_MAPA.md) — **generado**: qué función se ejecuta con qué palabras.
- [`IA_MOTORES.md`](IA_MOTORES.md) — mediciones de las máquinas y reglas de los motores.

---

## 1. En qué va el plan

El objetivo es un **chatbot con IA en el sitio público** de cada cliente, y antes
de eso, **ordenar cómo habla la IA** (era el pedido explícito del dueño).

| Fase | Qué es | Estado |
|---|---|---|
| **F0.1** | Registro único de capacidades | ✅ hecho · `1.0.19.0` |
| **F0.2** | Índice de textos (RAG) por cliente | ✅ hecho · `1.0.20.0` |
| **F0.3** | Mapa legible generado del código | ✅ hecho |
| **F0.4** | Trazabilidad de cada respuesta | ✅ columnas listas; **falta llenarlas desde el panel** |
| **F1** | Medir máquinas y elegir modelos | ✅ hecho (ver IA_MOTORES.md) |
| **F2** | Módulo `ai_public` y su interruptor | ✅ hecho |
| **F3** | Qué puede consultar un visitante | ✅ hecho · `1.0.22.0` |
| **F4** | Motor del chat público | ✅ hecho · `1.0.23.0` |
| **F5** | Selector de motores + análisis profundo | ✅ hecho · `1.0.21.0` |
| **F5b** | Respaldo en la nube con frenos de gasto | ✅ hecho · `1.0.23.0/.1` |
| **F6** | Endpoints públicos (`/chat/*`) | ❌ **falta** |
| **F7** | Widget en el sitio | ❌ **falta** |
| **F8** | Pantalla de configuración del cliente | ❌ **falta** |
| **F9** | «Qué preguntan y no sé responder» | ❌ **falta** (los datos ya se guardan) |

**Nada de esto está desplegado todavía.** Está commiteado y publicado en GitHub,
pero nadie ha pulsado «Actualizar app». Ver §7.

---

## 2. La idea que sostiene todo

> **Los hechos los pone Python. Los textos los pone el índice. La IA solo redacta.**

| Tipo de pregunta | Cómo se resuelve | Por qué |
|---|---|---|
| Precio, existencias, horario, dirección | **Función** con SQL fijo | Debe ser exacto; un embedding no responde «¿cuánto vale?» |
| Envíos, garantía, formas de pago, quiénes somos | **Índice de textos** | Es prosa que cada dueño escribe a su manera |
| La frase final | Modelo, sobre datos ya resueltos | Nunca elige datos: solo los dice mejor |

Tres consecuencias que valen más que cualquier optimización:

1. El bot **no puede inventar** un precio: no tiene de dónde sacarlo.
2. **Siempre responde**, aunque no haya ningún modelo vivo.
3. Una inyección de prompt no da acceso a nada: el modelo nunca toca la base.

---

## 3. Mapa de piezas

```
services/ia/                 EL CEREBRO DE LA DECISIÓN (no consulta datos)
  registro.py                registro único: qué existe, en qué canal, con qué motor
  intenciones.py             tabla corrida: qué PALABRAS piden qué FUNCIÓN  ← se lee de un vistazo
  enrutador.py               reconoce la intención sin gastar modelo

services/ia_datos/           LAS CONSULTAS (SQL fijo, una por dominio)
  acceso.py                  quién puede usar qué. ⚠ aquí vive el candado del canal público
  publico.py                 las 5 capacidades del sitio público
  ventas.py, finanzas.py...  las 37 del panel (sin cambios de SQL en todo este trabajo)

services/ia_rag/             EL ÍNDICE DE TEXTOS
  indexador.py               arma ia_documentos desde productos, FAQ, páginas y blog
  buscar.py                  4 pasadas + sinónimos

services/ia_motores.py       A QUÉ MÁQUINA VA CADA PETICIÓN (niveles A/B/C, tareas, topes)
services/ia_nube.py          RESPALDO ANTHROPIC con frenos de gasto
services/chat_publico/       EL CHAT DEL SITIO (orquesta todo lo anterior)
services/ai_service.py       el asistente del panel; ahora pide motor al selector

tools/ia_mapa.py             genera docs/IA_MAPA.md
tools/ia_foto_herramientas.py  foto de las 37 herramientas (antes/después de tocar algo)
tools/ia_comparar_fotos.py   compara dos fotos ignorando lo que depende del reloj
tools/ia_medir_modelos.py    mide modelos locales (GPU/CPU, carga, palabras/s)
tools/ia_medir_tokens.py     cuenta tokens y costo por tipo de mensaje (NO gasta créditos)
```

Migraciones (repo **CyberShopAdmin**): `0012` índice de textos · `0013` trazabilidad ·
`0014` contador de gasto en la nube.

---

## 4. Decisiones del dueño (respetarlas)

| Fecha | Decisión |
|---|---|
| 23/09 | Primero **ordenar** la IA; después construir el chat. |
| 23/09 | Alcance del bot: catálogo + servicios + empresa + **preguntas frecuentes nuevas**. |
| 23/09 | Escalada: botón **«hablar con una persona» → WhatsApp**, sin guardar datos del visitante. |
| 23/09 | Motor: **solo su PC por ahora** (el servidor no da; ver §5). |
| 24/09 | Respaldo en la nube: **solo si el PC lleva minutos apagado**, modelo barato, tope fijo y **aviso por correo** cuando empieza el cobro. |
| 24/09 | Acceso al servidor: se queda como está (clave a mano cuando haga falta). |

Reglas permanentes del proyecto: no se borran registros de producción · cada
despliegue sube la versión · el despliegue web es **solo por git** y lo dispara
el dueño · los catálogos de módulos viven en **dos repos** y hay que tocar los dos.

---

## 5. Lo que se midió (no son estimaciones)

**El PC del dueño — RTX 5070 Ti, 16,3 GB**

| Modelo | Dónde corre | Carga | Palabras/s |
|---|---|---|---|
| `qwen2.5:14b-instruct-q4_K_M` | **GPU, todo** | 46 s | **27,1** ← el elegido |
| `qwen2.5:7b` | GPU, todo | 38 s | 34,7 |
| `gpt-oss-cyber` (el que corre hoy) | **85 % GPU** | 117 s | 12,5 |

**El modelo que está en producción no cabe en la tarjeta**: 11,1 de sus 13,1 GB
entran en VRAM y el resto lo procesa la CPU. Cambiarlo por el 14B es 2,2× más
rápido y es solo una línea del `.cybershop.conf`. **Pendiente de aplicar.**

**El servidor — 1,9 GB de RAM, 2 núcleos, 604 MB disponibles, swap en uso.**
No entra ni un modelo de 0,5B sin empujar al swap los sitios de los clientes.
Decisión: **no se le instala nada**. `pgvector` tampoco está disponible, así que
no hay embeddings (el índice funciona con palabras, parecido y sinónimos).

**Costo por mensaje en la nube** (contado con `/v1/messages/count_tokens`, que no
gasta créditos):

| Caso | Entrada | US$/mensaje |
|---|---|---|
| Chat del sitio, redactar | 245 | 0,00084 |
| Chat del panel, redactar | 314 | 0,00206 |
| Chat del panel, **elegir herramienta** | **2.253** | **0,00335** |

Elegir la herramienta cuesta **9 veces más que redactar**, porque el prompt lleva
el catálogo entero. Por eso el enrutador por palabras clave no es un lujo.

> **La cuenta de Anthropic no tiene saldo.** La clave autentica bien, pero la API
> responde `credit balance is too low`. El sistema lo detecta, se apaga 30 minutos
> y sigue respondiendo con los datos. Verificado contra la API real.

---

## 6. Hallazgos que costaron encontrar

1. **Un visitante anónimo se hacía pasar por el POS de escritorio.**
   `contexto_actual()` devuelve el canal «escritorio» cuando no hay sesión, y ese
   canal puede usar *toda* herramienta sin permiso declarado. Por eso el canal
   público es **lista blanca cerrada** y la ruta lo declara explícitamente, sin
   deducirlo. Está en `ia_datos/acceso.py::puede_usar`, y hay 12 pruebas que lo
   verifican herramienta por herramienta.

2. **`valor or defecto` convierte el 0 en el valor por defecto.** Una espera de
   0 segundos se volvía 180, y el respaldo no entraba nunca. Ojo con este patrón
   en toda configuración numérica.

3. **El contador no ve el módulo de cotizaciones.** `quotes` tiene permiso
   `ADMIN_STAFF` (sin contador) y `billing` tiene `ADMIN_CONTADOR` (sin
   empleado). Una función que ambos necesiten va en `billing_bp`. Ya documentado
   en la memoria del proyecto.

4. **`plainto_tsquery` exige TODAS las palabras.** «¿puedo pagar con Nequi?» no
   encontraba la respuesta de formas de pago solo porque el texto no dice
   «puedo». De ahí la segunda pasada con OR, y el diccionario de sinónimos para
   «abren» → «horario».

5. **El índice respondía preguntas de ventas con fichas de producto.** «¿cuánto
   vendieron este mes?» encontraba un producto por la palabra «vende». Ahora las
   preguntas sobre el interior del negocio se responden con un «eso es interno»,
   sin buscar nada (`_DEL_NEGOCIO` en `chat_publico/motor.py`).

6. **`migrate_db` no captura errores.** Una migración frágil deja al cliente sin
   poder actualizarse. Por eso `0012` envuelve los `CREATE EXTENSION` en bloques
   con `EXCEPTION`: si el usuario de la base no puede crearlas, el cliente igual
   se actualiza.

---

## 7. Qué falta, en orden

### F6 — Endpoints públicos (`routes/chat_publico.py`)
El motor ya funciona; falta exponerlo.

- `GET /chat/config` → `{activo, saludo, sugerencias, whatsapp}`.
  Usar `services.chat_publico.config_publica()`.
- `POST /chat/mensaje` → `services.chat_publico.responder(pregunta)`.
- `GET /chat/stream` → SSE. **Poner `charset=utf-8` explícito** o se ve mojibake
  (ya pasó con el chat del panel), y `X-Accel-Buffering: no` para nginx.

Los tres: **404 si `is_module_active('ai_public')` es falso**. Sin sesión ni
cookies. Exentos de CSRF como `/enviar-mensaje` (`routes/public.py::_csrf_exempt`)
y a cambio `@limiter.limit('10 per minute; 60 per hour')` (`extensions.py`) más
`security.controlar_tasa_solicitudes`. Registrar el blueprint en
`routes/__init__.py`.

### F7 — El widget
**Montarlo desde `static/js/layout.js` + un CSS nuevo, NO desde
`templates/plantillaindex.html`.** Esa plantilla está en `PUBLIC_PATHS`
(`CyberShopAdmin/provisioning_service.py`) y tocarla **bloquea el botón
«Actualizar app»** de todos los clientes. `layout.js` fluye siempre, y como el
módulo viene apagado, no cambia nada visible hasta encenderlo.

Debe **reemplazar** el botón flotante `.chat-button` de WhatsApp: ese pasa a ser
«Hablar con una persona» dentro del panel del chat. Si el negocio no tiene
WhatsApp configurado, no ofrecerlo (hoy cae a un número de CyberShop puesto a
mano en la plantilla).

### F8 — Configuración del cliente
Pestaña en `/admin/sitio-publico` (`routes/admin.py::sitio_publico`): saludo,
tres sugerencias, tono, si menciona precios, y el **editor de preguntas
frecuentes**. Para las FAQ: agregar `'faq'` a `PUBLIC_ITEM_TYPES` en
`services/public_site_service.py` y copiar el patrón de
`routes/admin.py::gestion_servicios`. Al guardar, llamar a
`services.ia_rag.reindexar_uno('faq', id)`.

Guardar **siempre** con `services/config_tenant.py::set_cliente_config`: en
producción `cliente_config.clave` no es única y `ON CONFLICT` revienta.

Claves que el motor ya lee: `chat_publico_saludo`, `chat_publico_sugerencias`
(separadas por `|`), `chat_publico_tono`, `chat_publico_precios`, y
`empresa_horario` (hoy no existe y el bot lo echa de menos).

### F9 — «Qué preguntan y no sé responder»
Los datos ya se guardan en `ia_consultas` (`via='sin_respuesta'`). Falta la
pantalla en el panel del cliente. Es la lista de lo que hay que agregar a las
preguntas frecuentes.

### Pendientes sueltos
- **F0.4 a medias**: el chat del panel todavía no escribe `intencion`/`via`/`motor`
  en `ia_consultas` (el chat público sí). Falta pasar esos campos en el `plan` de
  `_plan_chat_pasos`.
- **El enrutador determinista no se usa todavía en el panel**, solo en el chat
  público. Conectarlo ahorraría los 2.253 tokens de catálogo por pregunta. Hacerlo
  con medición: comparar acierto contra el banco de ejemplos del registro.
- **Embeddings**: descartados hasta que haya `pgvector`. El código está preparado
  para que entren sin reescribir la búsqueda.

---

## 8. Cómo verificar lo que ya está

```bash
cd C:/Cybershop/CyberShop/app

# Toda la suite (266 pruebas; test_ratelimit falla sin Redis local, es normal)
DB_NAME=cybershop_test FLASK_SECRET_KEY=prueba \
  ../venv/Scripts/python.exe -m pytest tests/ -q

# Solo lo de IA (187 pruebas, todas deben pasar)
... -m pytest tests/test_ia_registro.py tests/test_ia_rag.py tests/test_ia_motores.py \
              tests/test_ia_nube.py tests/test_chat_publico_acceso.py -q

# ¿Las 37 herramientas siguen devolviendo lo mismo? (antes y después de tocar algo)
python tools/ia_foto_herramientas.py antes.json
#   ...cambios...
python tools/ia_foto_herramientas.py despues.json
python tools/ia_comparar_fotos.py antes.json despues.json

# El mapa no puede quedar desactualizado (hay una prueba que lo verifica)
python tools/ia_mapa.py

# Medir modelos locales / costo en la nube
python tools/ia_medir_modelos.py qwen2.5:14b-instruct-q4_K_M
ANTHROPIC_API_KEY=... python tools/ia_medir_tokens.py
```

La base `cybershop_test` tiene sembrados servicios, 6 preguntas frecuentes, un
artículo de blog y textos de «quiénes somos» para poder probar el índice.
El módulo `ai_public` queda **apagado** después de correr las pruebas (lo limpia
su fixture): encenderlo a mano si se va a probar el chat.

---

## 9. Despliegue (cuando se decida)

**Dos pasos, en este orden.** El primero se olvida siempre:

1. **El maestro primero** — de ahí salen los módulos *y las migraciones*:
   ```bash
   cd /var/www/CyberShopAdmin && sudo -u www-data git pull && sudo systemctl restart cybershop-admin
   ```
2. Después, **«⬆ Actualizar app» en un solo cliente** (cybershop), revisar, y
   luego el resto. Ese botón corre las migraciones `0011`–`0014`.

Si se hace el paso 2 sin el 1, no se rompe nada: la app queda al día y en modo
tolerante hasta que las migraciones existan.

**Cambio de una línea, muy rentable**: en el `.cybershop.conf` del servidor,
`AI_MODEL=qwen2.5:14b-instruct-q4_K_M` (el modelo ya está descargado en el PC).
2,2 veces más rápido que lo que corre hoy.

**Para activar el respaldo en la nube** hacen falta dos cosas: saldo en la cuenta
de Anthropic y `AI_NUBE_API_KEY` en ese mismo archivo. La clave **nunca** va al
código ni a git.

---

## 10. Decisiones que esperan al dueño

1. **¿Cargar créditos en Anthropic?** Sin saldo, el respaldo no puede responder.
   Con los números medidos, US$ 5 al mes cubren ~6.000 mensajes del sitio.
2. **¿Rotar la clave de la API?** Se compartió por chat.
3. **¿Cambiar `AI_MODEL` al 14B?** Es configuración de producción; no se tocó.
4. **¿Ampliar la VPS?** Hoy tiene 604 MB disponibles con swap en uso para cuatro
   instancias más la base de datos. No es solo por la IA.
