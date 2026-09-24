# Motores de IA: qué máquina atiende qué

El asistente usa tres niveles de motor. La idea es que **siempre haya alguien que
conteste**, sin depender de que una máquina esté encendida.

| Nivel | Dónde vive | Para qué | Quién lo dispara |
|---|---|---|---|
| **A · Siempre** | Servidor (VPS), solo CPU | Chat público cuando el PC de IA está apagado. Respaldo de todo. | Cualquiera |
| **B · Bueno** | PC de IA, RTX 5070 Ti | Chat público con el PC encendido, y el asistente del panel. | Cualquiera, con tope |
| **C · Profundo** | PC de IA, contexto largo | Informes, artículos, análisis pesados. | Solo el dueño, a propósito |

El canal público **nunca** llega al nivel C, y su uso del B está topado: si se
pasa, baja solo al A. Así un visitante no puede monopolizar la GPU.

---

## Medición del PC de IA — 23/09/2026

**Equipo**: RTX 5070 Ti (16,3 GB de VRAM, driver 610.88), 8 núcleos / 16 hilos,
31 GB de RAM. Ollama 0.31.1. Modelos en `S:\Ollama\Models` (1 TB libre).

Cada modelo se midió **en frío** (descargado de memoria antes de empezar), con la
misma pregunta de tienda y 80 tokens de respuesta:

| Modelo | Tamaño | Dónde corre | Carga en frío | Palabras/s |
|---|---|---|---|---|
| `qwen2.5:7b` | 4,4 GB | **GPU, todo** | 38 s | **34,7** |
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

- **Nivel B**: un 14B en q4 (~9 GB). Candidato: `qwen2.5:14b-instruct-q4_K_M`.
  Queda pendiente descargarlo y medirlo igual que los demás.
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

El chat público **no depende de que haya modelo**. Sin ninguno responde igual, al
instante y con datos exactos, porque las respuestas las arma Python:

- «¿Tienen X?» / «¿cuánto vale?» → consulta al catálogo
- «¿A qué hora abren?» / «¿dónde quedan?» → datos del negocio
- «¿Hacen domicilios?» → índice de textos (preguntas frecuentes)

Lo que aporta el modelo es **redactar** con naturalidad y encadenar. Por eso:

- **Nivel A**: sin modelo por ahora. Respuestas armadas, siempre instantáneas.
- **Nivel B**: el 14B del PC, cuando está encendido, para redactar y conversar.
- Si más adelante la VPS crece a 4 GB, el nivel A se activa sin tocar código:
  basta con apuntar `AI_MOTOR_A_BASE_URL` al Ollama local del servidor.

> La VPS está justa para lo que ya hace: 604 MB disponibles con swap en uso, para
> 4 instancias más base de datos. Conviene tenerlo presente aunque no se toque el
> tema de la IA.
