# Cotización con IA — banco para afinar el análisis (1.9.14.0)

100 ejemplos para enseñarle al modelo local a **armar una cotización con lo que mandó el
cliente**: la conversación de WhatsApp (transcrita por la IA de visión o exportada como
.txt), a veces una cotización anterior en PDF y los productos del catálogo.

| Archivo | Para qué |
|---|---|
| `cotizacion_auto_ft.jsonl` | Entrenamiento: una conversación por línea `{"messages": [system, user, assistant]}` |
| `banco_cotizacion_auto.json` | Los mismos casos con lo esperado (ítems, cantidades, precios de referencia), para evaluar |

Se regeneran con `python tools/ia_cotizacion_dataset.py` (no editar a mano).

## Cómo trabaja la cotización con IA

1. **Navegador**: OCR de capturas y fotos (Tesseract.js, español), texto de los PDF (pdf.js)
   y el chat exportado. Las capturas solo viajan al servidor del negocio y a su equipo de IA.
2. **Visión** (equipo de IA, `AI_MODEL_VISION`, por defecto `qwen3.5:9b`): transcribe cada
   imagen y dice quién habló (Cliente / Negocio).
3. **Análisis profundo** (equipo de IA, motor C): arma el JSON de la propuesta. **Este es el
   paso que se afina con este banco.**
4. **Precios** (Python, nunca la IA): catálogo → documento o cotización anterior → historial →
   costo + margen → internet (nube, solo lo que falte) → vacío para el negocio.
5. **Notas**: catálogo revisado de notas legales (`services/notas_cotizacion.py`).

La nube (Claude) solo se usa en el paso 4 y solo para los ítems sin ningún precio: una llamada
corta, con búsqueda en internet, sin datos del cliente, y lo consultado se recuerda un día.

## Qué enseña

- Cotizar solo lo pedido; lo que se agregue va `"sugerido": true` con su razón.
- Las cantidades que dijo el cliente; lo que falte va en `dudas` para preguntárselo.
- El nombre exacto del catálogo cuando el producto está ahí (50 casos).
- El precio de una cotización anterior en PDF, con su fuente (25 casos); nunca inventar precios.
- Las condiciones habladas (fecha, anticipo, factura) en `condiciones`.
- Leer el chat exportado de WhatsApp (34 casos) y la transcripción de capturas (66 casos).

## Cómo afinar (fuera de la app)

Igual que el banco de notas (`../notas_cotizacion/README.md`): LoRA con Unsloth o
`trl.SFTTrainer` sobre el mismo modelo que corre el análisis profundo, 3 épocas,
`max_seq_length=4096`, 10 ejemplos aparte para validar; exportar a GGUF y crear el modelo en
Ollama. Conviene mezclar este banco con el de notas en el mismo entrenamiento.

Evaluar antes y después con el equipo de IA encendido:

```
python tools/ia_cotizacion_banco.py 20
```

Mide si el modelo devuelve JSON válido, si acierta los ítems y las cantidades, si respeta los
precios de referencia y si deja dudas y condiciones.
