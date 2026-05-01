# Módulo de Nómina (Colombia)

Liquida nómina mensual o quincenal de empleados y contratistas, aplicando la
normativa laboral y tributaria colombiana vigente.

## Estructura

| Archivo | Rol |
|---|---|
| `nomina_engine.py` | Motor de cálculos puros (horas extras, retención, prestaciones, indemnización, incapacidades). Sin Flask, sin DB. |
| `nomina_inteligente.py` | Capa con pandas: agrega novedades, calcula la nómina del periodo y emite alertas normativas. Aquí viven los **parámetros oficiales** y los **% de aportes**. |
| `routes/nomina.py` | Blueprint Flask: dashboard, parámetros, empleados, contratistas, periodos, novedades, liquidaciones, desprendibles. |
| `templates/nomina_*.html` | Vistas administrativas. |

## Parámetros legales por año

Centralizados en `nomina_inteligente.PARAMETROS_OFICIALES_NOMINA`:

| Año | SMMLV | Aux. transporte | UVT | Estado |
|---:|---:|---:|---:|:---|
| 2025 | $1.423.500 | $200.000 | $49.799 | Oficial |
| 2026 | $1.750.905 | $249.095 | $52.374 | Oficial |
| 2027 | $1.847.205 | $262.795 | $55.256 | **Proyectado** (~5,5% IPC) |

> Los valores 2027 son una proyección hasta que el Gobierno expida el decreto
> de SMMLV (típicamente diciembre 2026) y la DIAN la resolución de UVT
> (típicamente noviembre 2026). Actualizar `PARAMETROS_OFICIALES_NOMINA`
> cuando se publiquen.

## Base normativa aplicada

### Ley laboral
- **CST** (Código Sustantivo del Trabajo): jornada, recargos, prestaciones.
- **Ley 50/1990**: cesantías anualizadas, salario integral.
- **Ley 2101 de 2021**: reducción gradual de la jornada semanal
  (47 → 46 → 44 → **42 horas** desde 2026).

### Seguridad social
- **Ley 100/1993**: aportes salud (4% empleado + 8.5% empleador) y pensión
  (4% empleado + 12% empleador).
- **Ley 797/2003**: Fondo de Solidaridad Pensional (1% a 2% según SMMLV).
- **Decreto 1295/1994**: ARL Riesgos I (0.522%) a V (6.96%), 100% empleador.

### Parafiscales y exoneración
- **Ley 21/1982**: Caja de Compensación 4% (siempre se paga).
- **Ley 89/1988** (ICBF) y **Ley 119/1994** (SENA): 3% + 2%.
- **Ley 1607/2012, Art. 114-1 ET**: exonera salud empleador, ICBF y SENA
  cuando el trabajador devenga **menos de 10 SMMLV**.

### Tributario
- **Estatuto Tributario, Art. 383**: tabla progresiva en UVT para retención
  en la fuente laboral (Procedimiento 1).
- **Art. 206 num. 10 ET**: renta exenta del 25% con tope de 790 UVT/año.

### Otros
- **Ley 15/1959**: auxilio de transporte para salarios ≤ 2 SMMLV.
- **Ley 52/1975**: 12% anual de intereses sobre cesantías.

## Tipos de novedades soportadas

| Código | Descripción |
|---|---|
| `HED` / `HEN` | Hora extra diurna / nocturna |
| `HEDF` / `HENF` | Hora extra diurna / nocturna festiva |
| `RN` / `RD` | Recargo nocturno / dominical o festivo |
| `INCAPACIDAD_GEN` | Incapacidad por enfermedad general |
| `INCAPACIDAD_LAB` | Incapacidad por accidente o enfermedad laboral |
| `LICENCIA_MAT` / `LICENCIA_PAT` | Licencia de maternidad / paternidad |
| `LICENCIA_LUTO` | Licencia por luto (Ley 1280/2009) |
| `LICENCIA_NR` | Licencia no remunerada |

Las novedades con tipo desconocido se tratan como devengado manual y emiten
una alerta para revisión.

## Flujo de uso

1. **Parámetros** → registrar SMMLV, auxilio y UVT del año.
2. **Empleados** → datos personales, salario, ARL, EPS, fondos.
3. **Periodo** → abrir quincena o mes, registrar **novedades**, calcular.
4. **Aprobar** → revisar detalle, aprobar e imprimir desprendibles.
5. **Liquidación** → al retirar un empleado se calculan cesantías, prima,
   vacaciones e indemnización (Art. 64 CST).

## Mantenimiento anual (checklist diciembre)

- [ ] Revisar Decreto SMMLV publicado por el Gobierno.
- [ ] Revisar Decreto del auxilio de transporte.
- [ ] Revisar Resolución DIAN de la UVT.
- [ ] Actualizar `PARAMETROS_OFICIALES_NOMINA` con valores oficiales y cambiar
      el estado de `proyectado` a `oficial`.
- [ ] Revisar si la `JORNADA_LEY_2101` aplica un nuevo escalón.
- [ ] Crear el registro de parámetros del nuevo año desde el formulario.
