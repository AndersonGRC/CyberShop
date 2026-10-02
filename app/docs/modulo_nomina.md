# Módulo de Nómina (Colombia)

Liquida la nómina mensual o quincenal de empleados, aprendices y contratistas
con la normativa laboral y tributaria colombiana vigente (motor `2026.10`).

## Estructura

| Archivo | Rol |
|---|---|
| `nomina_engine.py` | **Motor único** de cálculos puros: jornada, recargos, IBC, seguridad social, parafiscales, provisiones, retención, contratistas, incapacidades, liquidación del periodo y del contrato. Sin Flask, sin BD, sin pandas. |
| `CyberShopDesktop/nomina_calc.py` | **Copia literal** del motor para liquidar sin conexión. Si cambia la web, se vuelve a copiar. |
| `nomina_inteligente.py` | Capa de compatibilidad: re-exporta el motor y las tablas de referencia que usan las rutas. |
| `services/nomina_service.py` | Único punto que guarda resultados en la BD: calcular y guardar el periodo, recalcular novedades automáticas, marcar pagado, liquidación con vista previa. Amplía el esquema (solo columnas nuevas). |
| `routes/nomina.py` | Blueprint Flask: dashboard, parámetros, empleados, contratistas y PILA, periodos, novedades, liquidaciones, desprendibles. |
| `routes/api_sync.py` (op `nomina_op`) | El escritorio calcula, crea y borra novedades a través del mismo servicio. |
| `templates/nomina_*.html`, `nomina_macros.html` | Vistas administrativas (accesibles: etiquetas, tablas con encabezados, avisos con `aria-live`, foco visible). |

## Parámetros legales por año

Centralizados en `nomina_engine.PARAMETROS_OFICIALES_NOMINA`:

| Año | SMMLV | Aux. transporte | UVT | Estado |
|---:|---:|---:|---:|:---|
| 2025 | $1.423.500 | $200.000 | $49.799 | Oficial |
| 2026 | $1.750.905 | $249.095 | $52.374 | Oficial (Decreto 159/2026, que reexpidió el 1469/2025 suspendido) |
| 2027 | $1.847.205 | $262.795 | $55.256 | **Proyectado** (~5,5 % IPC) |

Los parámetros de cada empresa se guardan en `nomina_parametros`, con el
interruptor **exonerado_114_1** (verdadero por defecto).

## Reglas por fecha

| Regla | Valor | Norma |
|---|---|---|
| Divisor del valor hora | 240 → 235 (15-jul-2023) → 230 (15-jul-2024) → 220 (15-jul-2025) → **210 (15-jul-2026)** | Ley 2101/2021 |
| Recargo dominical/festivo | 75 % → 80 % (1-jul-2025) → **90 % (1-jul-2026)** → 100 % (1-jul-2027) | Ley 2466/2025 |
| Hora extra festiva | HEDF = 1,25 + recargo dominical; HENF = 1,75 + recargo; RNDF = 0,35 + recargo | Arts. 168-179 CST |
| Trabajo nocturno | desde las 21:00; **desde las 19:00 a partir del 25-dic-2025** | Ley 2466/2025 |
| Reforma pensional | rige el 1-abr-2027: se avisa en los periodos desde esa fecha | Ley 2381/2024, C-264/2026 |

El valor de cada novedad se calcula con la **fecha de la novedad**.

## Cálculo del empleado

- **IBC**: salario devengado; piso de 1 SMMLV proporcional a los días; tope de 25 SMMLV.
  Salario integral: 70 % (debe ser ≥ 13 SMMLV, Art. 132 CST). Pagos no salariales
  sobre el 40 % de la remuneración entran al IBC (Ley 1393/2010, art. 30).
- **Empleado**: salud 4 %, pensión 4 %, Fondo de Solidaridad del 1 % al 2 % según el
  IBC **mensual** (Ley 797/2003).
- **Empresa**: salud 8,5 %, pensión 12 %, ARL según el nivel (I 0,522 % … V 6,96 %),
  caja 4 %, ICBF 3 %, SENA 2 %. Salud 8,5 %, ICBF y SENA se exoneran (Art. 114-1 ET)
  si la empresa está exonerada y el trabajador gana < 10 SMMLV.
- **Provisiones**: cesantías 1/12 e intereses 12 % (base salario + auxilio),
  prima 1/12, vacaciones 15/360 (sin auxilio). Salario integral: solo vacaciones.
- **Auxilio de transporte**: hasta 2 SMMLV, proporcional a los días trabajados
  (no en vacaciones, incapacidades ni licencias).
- **Retención (procedimiento 1)**: ingreso − INCR (salud, pensión, FSP) − dependientes
  (10 %, máx. 32 UVT) − intereses de vivienda (100 UVT) − prepagada (16 UVT) −
  aportes voluntarios/AFC (30 %, 3.800 UVT/año) − 25 % exento (790 UVT/año);
  todo limitado al **40 % / 1.340 UVT al año** (Art. 336 ET). Tabla del Art. 383.
- **Aprendiz SENA (Ley 2466/2025)**: lectiva 75 % SMMLV, sin descuentos, salud 12,5 %
  y ARL a cargo de la empresa sobre 1 SMMLV; productiva 100 % SMMLV como dependiente.

## Contratistas (prestación de servicios)

- Cotizan sobre el **40 %** del valor mensual, mínimo 1 SMMLV y máximo 25 SMMLV:
  salud 12,5 %, pensión 16 %, FSP desde 4 SMMLV y ARL. Riesgo IV y V: la ARL la
  paga la empresa (Decreto 1072/2015).
- La seguridad social **no se descuenta**: el sistema muestra cuánto debe pagar en la
  PILA y permite registrar la planilla por periodo. Si paga menos, queda pendiente.
- **Retención**: si no contrata 2 o más trabajadores, tabla del Art. 383 (par. 2)
  con la seguridad social como no constitutiva y el 25 % exento; si sí, Art. 392:
  honorarios 10 % (11 % si el contrato pasa de 3.300 UVT al año), servicios 4 %
  declarante / 6 % no declarante (base mínima 4 UVT).
- Neto = honorarios − retención − descuentos.

## Novedades

| Código | Descripción | Valor |
|---|---|---|
| `HED` / `HEN` | Hora extra diurna / nocturna | Automático |
| `HEDF` / `HENF` | Hora extra diurna / nocturna dominical o festiva | Automático |
| `RN` / `RD` / `RNDF` | Recargo nocturno / dominical / nocturno dominical | Automático |
| `INCAPACIDAD_GEN` | Enfermedad general: 66,67 % (días 1-2 empresa, luego EPS), 50 % desde el día 91, mínimo 1 SMMLV diario | Automático |
| `INCAPACIDAD_LAB` | Laboral: 100 % a cargo de la ARL | Automático |
| `LICENCIA_MAT` / `LICENCIA_PAT` | Maternidad / paternidad: 100 %, las paga la EPS | Automático |
| `LICENCIA_LUTO` / `VACACIONES` | Luto (Ley 1280/2009) / vacaciones disfrutadas: 100 % empresa | Automático |
| `LICENCIA_NR` | Licencia no remunerada | $0 |
| `COMISION` / `BONIF_S` | Comisión / bonificación salarial | Manual |
| `BONIF_NS` | Bonificación no salarial (regla del 40 %) | Manual |
| `PRESTAMO` / `OTRA_DEDUCCION` | Descuentos autorizados | Manual |

- Si el usuario escribe el valor, se guarda con `valor_manual = TRUE` y se respeta.
- Las automáticas (incluidas las que crea el escritorio) se **recalculan** al
  calcular el periodo, con el salario y la jornada vigentes.
- Solo se pueden crear o borrar novedades en periodos abiertos (borrador,
  calculada, rechazada). Si el periodo estaba calculado, vuelve a borrador.

## Estados del periodo e integridad

`borrador → calculada → aprobada → pagada` (y `rechazada` vuelve a calcularse).

- Aprobados y pagados **nunca** se recalculan ni cambian sus novedades (web y escritorio).
- Cada cálculo guarda `motor_version`, `parametros_usados` y `alertas` en el
  periodo, y la explicación por persona en `nomina_detalle.calculo`.
- Las migraciones son aditivas (`ADD COLUMN IF NOT EXISTS`) y toleran tablas ausentes.

## Liquidación definitiva

Vista previa → confirmar. Cesantías e intereses del **año** en curso, prima del
semestre, base con auxilio (≤ 2 SMMLV) y promedio variable de los últimos 12
meses, vacaciones pendientes, salarios y descuentos pendientes. La
**indemnización (Art. 64 CST) solo aplica en despido sin justa causa**. Los
contratistas no se liquidan. Una sola liquidación por empleado.

## Fuera del alcance

- Nómina electrónica DIAN (no se envía nada a la DIAN).
- Envío de la PILA al operador (solo se calcula y se registra la planilla).

## Mantenimiento anual (checklist diciembre)

- [ ] Decreto del SMMLV y del auxilio de transporte; resolución DIAN de la UVT.
- [ ] Actualizar `PARAMETROS_OFICIALES_NOMINA` (estado `oficial`) y copiar el motor al escritorio.
- [ ] Revisar la reforma pensional (Ley 2381): tramos del FSP desde el 1-abr-2027.
- [ ] Crear el registro de parámetros del nuevo año desde el formulario.
