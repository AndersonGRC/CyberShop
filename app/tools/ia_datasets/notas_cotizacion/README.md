# Notas adicionales de cotizaciones — banco para afinar la IA (1.9.13.0)

100 ejemplos para enseñarle al modelo local a sugerir las **notas adicionales** de una
cotización: legales en Colombia, justas para el cliente y para el negocio, organizadas por
sección y en el formato JSON que espera la app.

| Archivo | Para qué |
|---|---|
| `notas_cotizacion_ft.jsonl` | Entrenamiento (fine-tuning): una conversación por línea `{"messages": [system, user, assistant]}` |
| `banco_notas_cotizacion.json` | Los mismos 100 casos como preguntas, para evaluar el modelo antes y después |

Se regeneran con `python tools/ia_notas_dataset.py` (no editar a mano: salen del catálogo
revisado de `services/notas_cotizacion.py`).

## Qué contiene

- 50 negocios inventados (taller de computadores, redes, cámaras, repostería, eventos,
  desarrollo web, muebles, obra, electricidad, imprenta, fotografía, asesorías, cursos,
  trasteos, aseo, licencias, usados, catering, alquiler, transporte, hosting…) × 2 variantes:
  empresa (con NIT) o persona natural, con o sin indicaciones del negocio y con notas ya escritas.
- 25 casos donde el negocio pide algo abusivo («pon que no hay garantía», «el anticipo no es
  reembolsable», «no se aceptan devoluciones», «no nos hacemos responsables por daños»): la
  respuesta ideal NO lo incluye, deja la alternativa justa y lo explica en `avisos`.
- 30 casos con condiciones propias del negocio («el valor incluye los materiales básicos…»,
  «el transporte fuera del perímetro urbano se cobra aparte»): la respuesta ideal las deja
  como nota, bien redactada, en su sección.
- Casos con notas ya escritas: la respuesta ideal no las repite (ni con otras palabras), solo
  complementa, y si alguna es abusiva («No se aceptan devoluciones») lo advierte en `avisos`.
- Normas citadas solo de esta lista: Ley 1480 de 2011 (arts. 7, 8, 11, 16, 18, 43, 47),
  Ley 1581 de 2012, Código de Comercio (arts. 845, 846, 884), Estatuto Tributario (IVA 19 %),
  Ley 23 de 1982 art. 20 (modificado por la Ley 1450 de 2011), Res. 2674 de 2013, Res. 4272 de
  2021 y RETIE. La app descarta cualquier nota que cite otra norma.
- Sin datos reales: al modelo nunca le llegan el nombre ni el documento del cliente, solo si
  es empresa o persona natural y su ciudad.

> Las notas son una guía general, no reemplazan la asesoría de un abogado. Antes de usarlas
> en un contrato grande, conviene que un abogado revise el catálogo.

## Cómo afinar el modelo (fuera de la app)

El entrenamiento no corre en el servidor ni en la app: se hace una vez en un equipo con GPU
(o en Google Colab) y el resultado se carga en Ollama.

1. **Escoger el modelo base**, uno pequeño de instrucciones que ya hable bien español
   (por ejemplo, Qwen 2.5/3 de 7-9 B o Gemma de 9-12 B). Debe ser el mismo que luego se usa
   en Ollama.
2. **Entrenar un LoRA** con [Unsloth](https://github.com/unslothai/unsloth) o con
   `trl.SFTTrainer`, usando `notas_cotizacion_ft.jsonl` como conjunto de chat
   (plantilla de chat del modelo base). Valores de partida: 3 épocas, `lr=2e-4`, `r=16`,
   `lora_alpha=16`, `max_seq_length=4096` (el ejemplo más largo tiene unos 8.700 caracteres).
   Dejar 10 ejemplos aparte para validar.
3. **Exportar a GGUF** (Unsloth: `model.save_pretrained_gguf(..., quantization_method="q4_k_m")`).
4. **Crear el modelo en Ollama** con un `Modelfile`:
   ```
   FROM ./notas-cotizacion-q4_k_m.gguf
   PARAMETER temperature 0.3
   PARAMETER num_ctx 8192
   ```
   `ollama create cybershop-notas -f Modelfile`
5. **Evaluar** antes de usarlo: `python tools/ia_notas_banco.py` con la IA encendida.
   Debe dar origen `ia` en todos los casos, 0 notas descartadas por citar normas inventadas
   o por ser abusivas, y los avisos en los casos abusivos.

Mientras no haya un modelo afinado, la app ya funciona con el modelo actual: le manda las
mismas cláusulas de referencia y revisa su respuesta (cita de normas, cláusulas abusivas,
repetidas). Si la IA no responde, muestra las sugerencias base del catálogo.
