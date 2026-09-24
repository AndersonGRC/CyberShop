# Motores de IA: qué máquina atiende qué

El diseño contempla tres niveles de motor. Las mediciones de esta página son
del 23/09/2026, no una verificación del despliegue actual. El panel usa el
selector para respuestas normales; el perfil «profundo» está definido pero
no llega desde el plan de chat actual al selector, y el chat público aún no
tiene endpoint/widget. Ver [inventario de IA](IA_ARCHIVOS_Y_DEPENDENCIAS.md).

| Nivel | Dónde vive | Para qué | Quién lo dispara |
|---|---|---|---|
| **A · Respaldo** | Nube (Anthropic), se cobra por token | Solo cuando el PC lleva minutos sin responder. | Solo el panel, por defecto |
| **B · Bueno** | PC de IA, RTX 5070 Ti | Asistente del panel; previsto para el chat público cuando se conecte. | Según configuración y disponibilidad |
| **C · Profundo** | PC de IA, contexto largo | Perfil previsto para análisis pesados; falta conectarlo al plan de chat del panel. | No disponible por frase del panel hoy |

El motor público previsto no permite nivel C. Su uso del PC tiene límite de
concurrencia y puede responder con datos armados en Python cuando no hay
modelo; Anthropic está excluido del canal público por defecto. Nada de esto
supone que un visitante tenga hoy acceso al chat: faltan ruta y widget.

---

## Medición del PC de IA — 23/09/2026

**Equipo**: RTX 5070 Ti (16,3 GB de VRAM, driver 610.88), 8 núcleos / 16 hilos,
31 GB de RAM. Ollama 0.31.1. Modelos en `S:\Ollama\Models` (1 TB libre).

Cada modelo se midió **en frío** (descargado de memoria antes de empezar), con la
misma pregunta de tienda y 80 tokens de respuesta:

| Modelo | Tamaño | Dónde corre | Carga en frío | Palabras/s |
|---|---|---|---|---|
| `qwen2.5:7b` | 4,4 GB | **GPU, todo** | 38 s | **34,7** |
| **`qwen2.5:14b-instruct-q4_K_M`** | 8,9 GB | **GPU, todo** | 46 s | **27,1** |
| `qwen2.5-coder:14b` | 8,9 GB | **GPU, todo** | 58 s | **29,0** |
| `gpt-oss-cyber` (el de hoy) | 13,1 GB | **85 % GPU, 15 % CPU** | 117 s | **12,5** |

### Lo que dicen estos números

1. **El modelo de producción no cabe entero en la tarjeta.** De sus 13,1 GB solo
   11,1 entran en VRAM: el resto lo procesa la CPU, y eso explica tanto la carga
   de 117 s como que escriba a 12,5 palabras/s. No es la GPU la que está mal
   configurada —las otras pruebas usan la tarjeta al 100 %—, es que ese modelo no
   deja margen: de los 16,3 GB, unos 3,4 los ocupa el escritorio de Windows.
2. **Un 14B es el punto dulce.** Con 8,9 GB cabe completo, deja sitio para el
   contexto y va a 29 palabras/s: **2,3 veces más rápido que el modelo actual**, y
   con mejor calidad que el 7B para elegir herramientas.
3. **`gpt-oss` gasta tokens pensando.** En la prueba generó los 80 tokens y
   devolvió texto visible vacío: se le fueron en el razonamiento interno. Para un
   chat que responde corto, eso es un problema por sí solo.

### Decisión

- **Nivel B**: `qwen2.5:14b-instruct-q4_K_M`, ya descargado y medido. Cabe
  completo en la tarjeta, carga en 46 s (2,5 veces más rápido que el actual) y
  escribe a 27 palabras/s (2,2 veces más rápido). Respondió la prueba de tienda
  con naturalidad y sin inventar cifras.
  Para elegirlo en el cliente primario se usa `.cybershop.conf`; los demás
  clientes usan su `EnvironmentFile` configurado desde el maestro y requieren
  reinicio. No afirmar que el cambio ya está aplicado en producción.
- **Nivel C**: el mismo 14B con contexto largo (32K+). Subir el contexto pesa más
  que subir de modelo, y un modelo que no cabe pierde más de lo que gana.
- `gpt-oss-cyber` se deja de usar para el chat. Sigue sirviendo para tareas sin
  apuro, donde 12 palabras/s no molesta.

> Estas cifras se obtienen con `scratchpad/ia/medir_modelos.py`. Conviene repetir
> la medición cuando cambie el driver, Ollama o el modelo.

---

## Medición del servidor — 23/09/2026: NO alcanza para un modelo

**VPS**: Ubuntu 24.04, 2 núcleos (AMD EPYC 9474F), **1,9 GB de RAM**, 48 GB de
disco (35 libres). Sirve al mismo tiempo: el sitio principal, 3 instancias de
clientes (`cyceconsultores`, `ppn-t001`), el panel maestro, PostgreSQL, Redis y
fail2ban.

```
              total     usada      libre   disponible
Mem:          1,9Gi     1,3Gi      100Mi      604Mi
Swap:         2,0Gi     174Mi
carga: 0,02   ·   sin procesos muertos por falta de memoria
```

**Disponibles: 604 MB.** Y el swap ya se está usando.

Regla que se había fijado antes de medir:

| RAM disponible | Modelo del nivel A |
|---|---|
| ≥ 4 GB y 2 núcleos holgados | `qwen2.5:3b-instruct-q4_K_M` (~2 GB) |
| 2 – 4 GB | `qwen2.5:1.5b-instruct-q4_K_M` (~1 GB) |
| 1 – 2 GB | `qwen2.5:0.5b-instruct-q4` (~0,4 GB) |
| **< 1 GB** | **No se instala** |

Con 604 MB no entra ni el más pequeño: un 0,5B ocupa ~400 MB de pesos más el
runtime de Ollama y la caché de contexto, es decir cerca de 1 GB. Instalarlo
empujaría a los gunicorn de los clientes al swap, y en 2 núcleos la generación
competiría con las peticiones de sus sitios. **El riesgo lo pagarían los clientes,
no el chat.**

`pgvector` tampoco está disponible, así que no hay embeddings: el índice de
textos funciona con palabras, parecido y sinónimos (ver `services/ia_rag/`).

### Qué se hace entonces

El **motor previsto** del chat público no depende de que haya modelo: puede
armar respuestas con datos exactos en Python. Todavía faltan endpoint, widget
e indexación automática antes de ofrecerlo a visitantes:

- «¿Tienen X?» / «¿cuánto vale?» → consulta al catálogo
- «¿A qué hora abren?» / «¿dónde quedan?» → datos del negocio
- «¿Hacen domicilios?» → índice de textos (preguntas frecuentes)

Lo que aporta el modelo es **redactar** con naturalidad y encadenar. Por eso:

- **Nivel A**: sin modelo propio en la VPS. En su lugar, un **respaldo en la nube**
  (ver abajo) que solo entra si el PC lleva minutos caído.
- **Nivel B**: el 14B del PC, cuando está encendido, para redactar y conversar.
- Si más adelante la VPS crece a 4 GB, se le pone su propio modelo sin tocar
  código: basta con apuntar `AI_MOTOR_A_BASE_URL` al Ollama local del servidor,
  y pasa a tener prioridad sobre la nube.

---

## Respaldo en la nube (Anthropic) — el último recurso

Existe para que el negocio no se quede sin asistente cuando el PC está apagado.
Como **se cobra por token**, tiene tres frenos, y los tres importan:

1. **Tiempo.** No entra apenas el equipo deja de responder: espera
   `AI_NUBE_ESPERA_LOCAL_S` (3 minutos por defecto) de caída continua. Un
   reinicio de Ollama o un corte de VPN no deben costar dinero. Si el equipo
   vuelve, el reloj se reinicia.
2. **Presupuesto.** Umbral local mensual **estimado** en dólares
   (`AI_NUBE_PRESUPUESTO_USD`, US$ 0 por defecto: apagado). Con un valor mayor
   que cero se deja de solicitar respaldo cuando el contador alcanza el umbral,
   pero la concurrencia y la estimación de tokens pueden rebasarlo; no es un
   límite duro de facturación. Configurar también límites reales en el
   proveedor antes de activarlo.
3. **Alcance.** Por defecto **no atiende al chat del sitio público**
   (`AI_NUBE_PARA_PUBLICO=false`). Ese chat ya responde bien sin modelo, y
   dejarlo abierto a internet con una API que se cobra por token es la forma más
   rápida de gastar sin darse cuenta.

Cada llamada admitida intenta quedar contada en `ia_uso_nube` (tokens y costo
estimado). Tras la primera llamada cobrada del mes se intenta enviar un aviso
si hay destinatarios y correo operativo; no es aprobación previa ni entrega
garantizada.

**Si la cuenta se queda sin saldo** —o la clave es inválida— la API responde
`credit balance is too low`. El sistema lo detecta, se apaga 30 minutos y deja de
intentar en cada mensaje; el asistente sigue respondiendo con los datos.
Verificado contra la API real.

Modelo configurado: `claude-haiku-4-5-20251001`. Precios y disponibilidad
pueden cambiar: validar la tarifa vigente del proveedor y ajustar
`AI_NUBE_PRECIO_*` antes de habilitar el respaldo.

> Para instancias no primarias, la clave se configura por cliente desde
> `admin.cybershopcol.com` y queda en `/etc/cybershop/<slug>.env`; requiere
> reiniciar esa instancia. El cliente primario aún lee `.cybershop.conf` y
> **no** aplica los valores guardados por el maestro. Nunca poner claves en
> código, Git ni documentación. Véase
> [IA_ACTUALIZACION_CLIENTES.md](IA_ACTUALIZACION_CLIENTES.md).

> La VPS está justa para lo que ya hace: 604 MB disponibles con swap en uso, para
> 4 instancias más base de datos. Conviene tenerlo presente aunque no se toque el
> tema de la IA.
