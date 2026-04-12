"""
Capa inteligente de nómina colombiana basada en pandas.

Centraliza validaciones normativas y el cálculo tabular del periodo para no
duplicar reglas dentro de las rutas Flask.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - depende del runtime del servidor
    pd = None

from nomina_engine import (
    calcular_auxilio_transporte,
    calcular_fondo_solidaridad,
    calcular_retencion_fuente,
    calcular_salud_pension,
    dias_360,
)


ARL_NIVELES = {
    "I": 0.522,
    "II": 1.044,
    "III": 2.436,
    "IV": 4.350,
    "V": 6.960,
}

TABLA_RETENCION_ART_383 = [
    {"rango_desde": 0, "rango_hasta": 95, "tarifa_marginal": 0.0, "uvt_mas": 0, "uvt_base": 0},
    {"rango_desde": 95, "rango_hasta": 150, "tarifa_marginal": 19.0, "uvt_mas": 0, "uvt_base": 95},
    {"rango_desde": 150, "rango_hasta": 360, "tarifa_marginal": 28.0, "uvt_mas": 10, "uvt_base": 150},
    {"rango_desde": 360, "rango_hasta": 640, "tarifa_marginal": 33.0, "uvt_mas": 69, "uvt_base": 360},
    {"rango_desde": 640, "rango_hasta": 945, "tarifa_marginal": 35.0, "uvt_mas": 162, "uvt_base": 640},
    {"rango_desde": 945, "rango_hasta": 2300, "tarifa_marginal": 37.0, "uvt_mas": 268, "uvt_base": 945},
    {"rango_desde": 2300, "rango_hasta": float("inf"), "tarifa_marginal": 39.0, "uvt_mas": 770, "uvt_base": 2300},
]

PARAMETROS_OFICIALES_NOMINA = {
    2025: {
        "salario_minimo": 1423500.0,
        "auxilio_transporte": 200000.0,
        "uvt": 49799.0,
        "fuente": "Decreto 1572 de 2024, Decreto 1573 de 2024 y Resolución DIAN 000193 de 2024",
    },
    2026: {
        "salario_minimo": 1750905.0,
        "auxilio_transporte": 249095.0,
        "uvt": 52374.0,
        "fuente": "Decreto 159 de 2026, Decreto 1470 de 2025 y Resolución DIAN 000238 de 2025",
    },
}

TIPOS_EXTRAS = {"HED", "HEN", "HEDF", "HENF", "RN", "RD"}
TIPOS_LICENCIAS_REMUNERADAS = {"INCAPACIDAD_GEN", "INCAPACIDAD_LAB", "LICENCIA_MAT", "LICENCIA_PAT", "LICENCIA_LUTO"}
TIPOS_LICENCIAS_NO_REMUNERADAS = {"LICENCIA_NR"}
TIPOS_SOPORTADOS = TIPOS_EXTRAS | TIPOS_LICENCIAS_REMUNERADAS | TIPOS_LICENCIAS_NO_REMUNERADAS


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if _is_na(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if _is_na(value):
        return None
    if pd is not None and isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    if pd is not None:
        parsed = pd.to_datetime(value, errors="coerce")
        if _is_na(parsed):
            return None
        return parsed.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _money(value: Any) -> float:
    return round(_to_float(value), 2)


def _alert(level: str, message: str, empleado_id: Any = None) -> dict[str, Any]:
    payload = {"nivel": level, "mensaje": message}
    if empleado_id is not None:
        payload["empleado_id"] = empleado_id
    return payload


def _is_na(value: Any) -> bool:
    if value is None:
        return True
    if pd is None:
        return False
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _normalizar_registros(registros: list[Any]) -> list[dict[str, Any]]:
    normalizados = []
    for registro in registros or []:
        try:
            normalizados.append(dict(registro))
        except Exception:
            normalizados.append(registro)
    return normalizados


def _dias_periodo(periodo: dict[str, Any]) -> int:
    fecha_inicio = _to_date(periodo.get("fecha_inicio"))
    fecha_fin = _to_date(periodo.get("fecha_fin"))
    if fecha_inicio and fecha_fin:
        return dias_360(fecha_inicio, fecha_fin)
    return 15 if periodo.get("numero_periodo") in (1, 2) else 30


def _dias_trabajados_en_periodo(empleado: pd.Series, fecha_inicio: date | None, fecha_fin: date | None, dias_periodo: int) -> int:
    fecha_ingreso = _to_date(empleado.get("fecha_ingreso"))
    if not fecha_inicio or not fecha_fin:
        return dias_periodo
    if not fecha_ingreso:
        return dias_periodo
    if fecha_ingreso > fecha_fin:
        return 0
    if fecha_ingreso > fecha_inicio:
        return dias_360(fecha_ingreso, fecha_fin)
    return dias_periodo


def _pivot_novedades(df_novedades: pd.DataFrame, campo: str) -> pd.DataFrame:
    if df_novedades.empty:
        return pd.DataFrame()

    pivot = df_novedades.pivot_table(
        index="empleado_id",
        columns="tipo_novedad",
        values=campo,
        aggfunc="sum",
        fill_value=0.0,
    )
    pivot.columns = [f"{campo}_{str(col).upper()}" for col in pivot.columns]
    return pivot


def _valor_columna(df: pd.DataFrame, columna: str) -> pd.Series:
    if columna in df.columns:
        return pd.to_numeric(df[columna], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index, dtype="float64")


def _sumar_columnas(df: pd.DataFrame, columnas: set[str], prefijo: str) -> pd.Series:
    series = pd.Series(0.0, index=df.index, dtype="float64")
    for columna in columnas:
        series = series + _valor_columna(df, f"{prefijo}_{columna}")
    return series


def _serie_texto(df: pd.DataFrame, columna: str) -> pd.Series:
    if columna in df.columns:
        return df[columna].fillna("").astype(str)
    return pd.Series("", index=df.index, dtype="object")


def _agrupar_novedades(novedades: list[dict[str, Any]]) -> tuple[dict[int, dict[str, float]], set[str]]:
    agregadas: dict[int, dict[str, float]] = {}
    tipos_detectados: set[str] = set()

    for novedad in novedades:
        empleado_id = int(_to_float(novedad.get("empleado_id"), 0))
        if empleado_id <= 0:
            continue

        tipo = str(novedad.get("tipo_novedad") or "").strip().upper()
        if not tipo:
            continue

        bucket = agregadas.setdefault(empleado_id, {})
        bucket[f"cantidad_{tipo}"] = bucket.get(f"cantidad_{tipo}", 0.0) + _to_float(novedad.get("cantidad"))
        bucket[f"valor_total_{tipo}"] = bucket.get(f"valor_total_{tipo}", 0.0) + _to_float(novedad.get("valor_total"))
        tipos_detectados.add(tipo)

    return agregadas, tipos_detectados


def _parametros_normativos(periodo: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    anio = int(_to_float(periodo.get("anio"), 0))
    oficiales = PARAMETROS_OFICIALES_NOMINA.get(anio)
    if not oficiales:
        return []

    alertas = []
    for clave, etiqueta in (
        ("salario_minimo", "salario mínimo"),
        ("auxilio_transporte", "auxilio de transporte"),
        ("uvt", "UVT"),
    ):
        actual = _to_float(params.get(clave))
        oficial = _to_float(oficiales.get(clave))
        if abs(actual - oficial) > 1:
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"El parámetro {etiqueta} {anio} no coincide con el valor oficial. "
                        f"Configurado: ${actual:,.0f}. Oficial: ${oficial:,.0f}. "
                        f"Fuente: {oficiales['fuente']}."
                    ),
                )
            )
    return alertas


def _retencion_periodo(ingreso_gravable: float, deducciones: float, uvt: float, dias_periodo: int) -> float:
    if ingreso_gravable <= 0 or uvt <= 0 or dias_periodo <= 0:
        return 0.0

    factor_mensualizacion = 30 / dias_periodo
    ingreso_mensualizado = ingreso_gravable * factor_mensualizacion
    deducciones_mensualizadas = deducciones * factor_mensualizacion
    retencion_mensual = calcular_retencion_fuente(
        ingreso_mensualizado,
        deducciones_mensualizadas,
        uvt,
        TABLA_RETENCION_ART_383,
    )
    return _money(retencion_mensual / factor_mensualizacion)


def _seguridad_social_contratista(honorarios_periodo: float, smmlv: float, nivel_arl: str) -> tuple[dict[str, float], list[dict[str, Any]]]:
    alertas = []
    if honorarios_periodo <= 0:
        return {
            "base": 0.0,
            "salud": 0.0,
            "pension": 0.0,
            "arl": 0.0,
            "arl_empresa": 0.0,
            "total": 0.0,
        }, alertas

    base = honorarios_periodo * 0.40
    if base < smmlv:
        base = smmlv

    base = min(base, smmlv * 25) if smmlv > 0 else base

    salud = base * 0.125
    pension = base * 0.16
    arl_pct = ARL_NIVELES.get(nivel_arl, ARL_NIVELES["I"])
    arl = base * (arl_pct / 100)
    arl_empresa = 0.0

    if nivel_arl in {"IV", "V"}:
        arl_empresa = arl
        arl = 0.0
        alertas.append(
            _alert(
                "warning",
                (
                    "Se detectó un contratista en ARL clase IV o V. "
                    "La ARL no se descontó como referencia al contratista porque normalmente "
                    "corresponde al contratante."
                ),
            )
        )

    return {
        "base": _money(base),
        "salud": _money(salud),
        "pension": _money(pension),
        "arl": _money(arl),
        "arl_empresa": _money(arl_empresa),
        "total": _money(salud + pension + arl),
    }, alertas


def _calcular_nomina_periodo_fallback(
    periodo: dict[str, Any],
    params: dict[str, Any],
    empleados: list[dict[str, Any]],
    novedades: list[dict[str, Any]],
) -> dict[str, Any]:
    smmlv = _to_float(params.get("salario_minimo"))
    aux_transporte = _to_float(params.get("auxilio_transporte"))
    uvt = _to_float(params.get("uvt"))
    fecha_inicio = _to_date(periodo.get("fecha_inicio"))
    fecha_fin = _to_date(periodo.get("fecha_fin"))
    dias_periodo = _dias_periodo(periodo)

    alertas = _parametros_normativos(periodo, params)
    novedades_por_empleado, tipos_detectados = _agrupar_novedades(novedades)
    tipos_no_soportados = sorted(tipos_detectados - TIPOS_SOPORTADOS)

    for tipo in tipos_no_soportados:
        alertas.append(
            _alert(
                "warning",
                (
                    f"La novedad {tipo} no tiene regla automática en el motor inteligente. "
                    "Se tratará como un devengado salarial manual para evitar omisiones."
                ),
            )
        )

    detalles = []
    total_empleados = 0
    total_contratistas = 0

    for empleado in empleados:
        empleado_id = int(_to_float(empleado.get("id"), 0))
        if empleado_id <= 0:
            continue

        tipo_vinculacion = str(empleado.get("tipo_vinculacion") or "").upper()
        salario_base = _to_float(empleado.get("salario_base"))
        dias_trabajados = _dias_trabajados_en_periodo(empleado, fecha_inicio, fecha_fin, dias_periodo)
        novedades_emp = novedades_por_empleado.get(empleado_id, {})

        if tipo_vinculacion == "CONTRATISTA":
            total_contratistas += 1
            nivel_arl = str(empleado.get("nivel_arl") or "I").strip().upper()
            honorarios_periodo = salario_base * (dias_trabajados / 30) if dias_trabajados else 0.0
            ss, alertas_contratista = _seguridad_social_contratista(honorarios_periodo, smmlv, nivel_arl)
            nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
            for alerta in alertas_contratista:
                alerta["empleado_id"] = empleado_id
                alerta["mensaje"] = f"{nombre}: {alerta['mensaje']}"
                alertas.append(alerta)

            detalles.append(
                {
                    "empleado_id": empleado_id,
                    "dias_trabajados": dias_trabajados,
                    "sueldo_basico": _money(honorarios_periodo),
                    "auxilio_transporte": 0.0,
                    "horas_extras": 0.0,
                    "total_devengado": _money(honorarios_periodo),
                    "salud_empleado": ss["salud"],
                    "pension_empleado": ss["pension"],
                    "fondo_solidaridad": ss["arl"],
                    "retencion_fuente": 0.0,
                    "total_deducido": ss["total"],
                    "neto_pagar": _money(honorarios_periodo),
                }
            )
            continue

        total_empleados += 1

        extras = sum(_to_float(novedades_emp.get(f"valor_total_{tipo}")) for tipo in TIPOS_EXTRAS)
        pagos_licencias = sum(_to_float(novedades_emp.get(f"valor_total_{tipo}")) for tipo in TIPOS_LICENCIAS_REMUNERADAS)
        dias_licencias_rem = sum(_to_float(novedades_emp.get(f"cantidad_{tipo}")) for tipo in TIPOS_LICENCIAS_REMUNERADAS)
        dias_licencias_nr = sum(_to_float(novedades_emp.get(f"cantidad_{tipo}")) for tipo in TIPOS_LICENCIAS_NO_REMUNERADAS)
        otros_devengados = sum(
            _to_float(valor)
            for clave, valor in novedades_emp.items()
            if clave.startswith("valor_total_") and clave.replace("valor_total_", "") not in TIPOS_SOPORTADOS
        )

        total_dias_novedad = dias_licencias_rem + dias_licencias_nr
        if total_dias_novedad > dias_trabajados:
            nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"{nombre}: las novedades del periodo suman {total_dias_novedad:.1f} días y exceden "
                        f"los {dias_trabajados} días del periodo. El cálculo fue limitado al máximo permitido."
                    ),
                    empleado_id=empleado_id,
                )
            )

        dias_licencias_rem = min(dias_licencias_rem, dias_trabajados)
        dias_licencias_nr = min(dias_licencias_nr, max(dias_trabajados - dias_licencias_rem, 0))
        dias_basico = max(dias_trabajados - dias_licencias_rem - dias_licencias_nr, 0)

        basico = salario_base * (dias_basico / 30) if dias_basico else 0.0
        aux_base = calcular_auxilio_transporte(salario_base, smmlv, aux_transporte)
        aux_trans = aux_base * (dias_basico / 30) if aux_base and dias_basico else 0.0

        if tipo_vinculacion == "APRENDIZ_SENA":
            nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"{nombre}: el cálculo automático del aprendiz SENA es referencial. "
                        "Revise etapa lectiva/productiva, apoyo de sostenimiento y aportes reales antes de aprobar."
                    ),
                    empleado_id=empleado_id,
                )
            )
            aux_trans = 0.0
            salud_emp = 0.0
            pension_emp = 0.0
            fsp = 0.0
            retencion = 0.0
        else:
            if salario_base < smmlv:
                nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
                alertas.append(
                    _alert(
                        "warning",
                        (
                            f"{nombre}: el salario base configurado (${salario_base:,.0f}) está por debajo del "
                            f"SMMLV (${smmlv:,.0f}). Revise si corresponde a tiempo parcial, suspensión o un dato mal cargado."
                        ),
                        empleado_id=empleado_id,
                    )
                )

            if not str(empleado.get("eps", "")).strip():
                alertas.append(_alert("warning", f"Empleado {empleado_id} no tiene EPS registrada.", empleado_id=empleado_id))
            if not str(empleado.get("fondo_pension", "")).strip():
                alertas.append(
                    _alert("warning", f"Empleado {empleado_id} no tiene fondo de pensión registrado.", empleado_id=empleado_id)
                )
            if not str(empleado.get("fondo_cesantias", "")).strip():
                alertas.append(
                    _alert("warning", f"Empleado {empleado_id} no tiene fondo de cesantías registrado.", empleado_id=empleado_id)
                )

            base_ss = basico + extras + pagos_licencias + otros_devengados
            salud_emp, pension_emp = calcular_salud_pension(base_ss, 4, 4)
            fsp = calcular_fondo_solidaridad(base_ss, smmlv)
            retencion = _retencion_periodo(base_ss, salud_emp + pension_emp + fsp, uvt, dias_periodo)

        total_devengado = basico + aux_trans + extras + pagos_licencias + otros_devengados
        total_deducido = salud_emp + pension_emp + fsp + retencion
        neto = total_devengado - total_deducido

        detalles.append(
            {
                "empleado_id": empleado_id,
                "dias_trabajados": dias_trabajados,
                "sueldo_basico": _money(basico),
                "auxilio_transporte": _money(aux_trans),
                "horas_extras": _money(extras),
                "total_devengado": _money(total_devengado),
                "salud_empleado": _money(salud_emp),
                "pension_empleado": _money(pension_emp),
                "fondo_solidaridad": _money(fsp),
                "retencion_fuente": _money(retencion),
                "total_deducido": _money(total_deducido),
                "neto_pagar": _money(neto),
            }
        )

    resumen = {
        "empleados": total_empleados,
        "contratistas": total_contratistas,
        "total_devengado": _money(sum(detalle["total_devengado"] for detalle in detalles)),
        "total_neto": _money(sum(detalle["neto_pagar"] for detalle in detalles)),
    }

    return {"detalles": detalles, "alertas": alertas, "resumen": resumen}


def calcular_nomina_periodo_inteligente(
    periodo: dict[str, Any],
    params: dict[str, Any],
    empleados: list[Any],
    novedades: list[Any],
) -> dict[str, Any]:
    periodo = dict(periodo or {})
    params = dict(params or {})
    empleados = _normalizar_registros(empleados)
    novedades = _normalizar_registros(novedades)

    if pd is None:
        return _calcular_nomina_periodo_fallback(periodo, params, empleados, novedades)

    smmlv = _to_float(params.get("salario_minimo"))
    aux_transporte = _to_float(params.get("auxilio_transporte"))
    uvt = _to_float(params.get("uvt"))
    fecha_inicio = _to_date(periodo.get("fecha_inicio"))
    fecha_fin = _to_date(periodo.get("fecha_fin"))
    dias_periodo = _dias_periodo(periodo)

    alertas = _parametros_normativos(periodo, params)

    df_empleados = pd.DataFrame(empleados)
    if df_empleados.empty:
        return {"detalles": [], "alertas": alertas, "resumen": {"empleados": 0, "contratistas": 0}}

    if "id" not in df_empleados.columns:
        raise ValueError("No se encontraron identificadores de empleados para calcular la nómina.")

    df_empleados["id"] = pd.to_numeric(df_empleados["id"], errors="coerce")
    df_empleados = df_empleados.dropna(subset=["id"]).copy()
    df_empleados["id"] = df_empleados["id"].astype(int)
    df_empleados["tipo_vinculacion"] = _serie_texto(df_empleados, "tipo_vinculacion").str.upper()
    df_empleados["salario_base"] = pd.to_numeric(df_empleados["salario_base"], errors="coerce").fillna(0.0)

    df_novedades = pd.DataFrame(novedades)
    if not df_novedades.empty:
        df_novedades["empleado_id"] = pd.to_numeric(df_novedades["empleado_id"], errors="coerce")
        df_novedades = df_novedades.dropna(subset=["empleado_id"]).copy()
        df_novedades["empleado_id"] = df_novedades["empleado_id"].astype(int)
        df_novedades["tipo_novedad"] = _serie_texto(df_novedades, "tipo_novedad").str.upper()
        df_novedades["cantidad"] = pd.to_numeric(df_novedades["cantidad"], errors="coerce").fillna(0.0)
        df_novedades["valor_total"] = pd.to_numeric(df_novedades["valor_total"], errors="coerce").fillna(0.0)
    else:
        df_novedades = pd.DataFrame(columns=["empleado_id", "tipo_novedad", "cantidad", "valor_total"])

    tipos_no_soportados = sorted(set(df_novedades["tipo_novedad"].unique()) - TIPOS_SOPORTADOS)
    for tipo in tipos_no_soportados:
        if tipo:
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"La novedad {tipo} no tiene regla automática en el motor inteligente. "
                        "Se tratará como un devengado salarial manual para evitar omisiones."
                    ),
                )
            )

    pivot_cantidades = _pivot_novedades(df_novedades, "cantidad")
    pivot_valores = _pivot_novedades(df_novedades, "valor_total")
    columnas_novedades = []
    if not pivot_cantidades.empty:
        columnas_novedades.extend(pivot_cantidades.columns.tolist())
        df_empleados = df_empleados.merge(pivot_cantidades, left_on="id", right_index=True, how="left")
    if not pivot_valores.empty:
        columnas_novedades.extend(pivot_valores.columns.tolist())
        df_empleados = df_empleados.merge(pivot_valores, left_on="id", right_index=True, how="left")
    for columna in columnas_novedades:
        if columna in df_empleados.columns:
            df_empleados[columna] = pd.to_numeric(df_empleados[columna], errors="coerce").fillna(0.0)

    detalles = []

    for _, empleado in df_empleados.iterrows():
        empleado_id = int(empleado["id"])
        tipo_vinculacion = str(empleado.get("tipo_vinculacion", "")).upper()
        salario_base = _to_float(empleado.get("salario_base"))
        dias_trabajados = _dias_trabajados_en_periodo(empleado, fecha_inicio, fecha_fin, dias_periodo)

        if tipo_vinculacion == "CONTRATISTA":
            nivel_arl = str(empleado.get("nivel_arl") or "I").strip().upper()
            honorarios_periodo = salario_base * (dias_trabajados / 30) if dias_trabajados else 0.0
            ss, alertas_contratista = _seguridad_social_contratista(honorarios_periodo, smmlv, nivel_arl)
            for alerta in alertas_contratista:
                alerta["empleado_id"] = empleado_id
                nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
                alerta["mensaje"] = f"{nombre}: {alerta['mensaje']}"
                alertas.append(alerta)

            detalles.append(
                {
                    "empleado_id": empleado_id,
                    "dias_trabajados": dias_trabajados,
                    "sueldo_basico": _money(honorarios_periodo),
                    "auxilio_transporte": 0.0,
                    "horas_extras": 0.0,
                    "total_devengado": _money(honorarios_periodo),
                    "salud_empleado": ss["salud"],
                    "pension_empleado": ss["pension"],
                    "fondo_solidaridad": ss["arl"],
                    "retencion_fuente": 0.0,
                    "total_deducido": ss["total"],
                    "neto_pagar": _money(honorarios_periodo),
                }
            )
            continue

        extras = _sumar_columnas(df_empleados.loc[[empleado.name]], TIPOS_EXTRAS, "valor_total").iloc[0]
        pagos_licencias = _sumar_columnas(df_empleados.loc[[empleado.name]], TIPOS_LICENCIAS_REMUNERADAS, "valor_total").iloc[0]
        dias_licencias_rem = _sumar_columnas(df_empleados.loc[[empleado.name]], TIPOS_LICENCIAS_REMUNERADAS, "cantidad").iloc[0]
        dias_licencias_nr = _sumar_columnas(df_empleados.loc[[empleado.name]], TIPOS_LICENCIAS_NO_REMUNERADAS, "cantidad").iloc[0]

        otras_columnas_valor = {
            columna.replace("valor_total_", "")
            for columna in df_empleados.columns
            if columna.startswith("valor_total_")
        } - TIPOS_SOPORTADOS
        otros_devengados = _sumar_columnas(df_empleados.loc[[empleado.name]], otras_columnas_valor, "valor_total").iloc[0]

        total_dias_novedad = dias_licencias_rem + dias_licencias_nr
        if total_dias_novedad > dias_trabajados:
            nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"{nombre}: las novedades del periodo suman {total_dias_novedad:.1f} días y exceden "
                        f"los {dias_trabajados} días del periodo. El cálculo fue limitado al máximo permitido."
                    ),
                    empleado_id=empleado_id,
                )
            )

        dias_licencias_rem = min(dias_licencias_rem, dias_trabajados)
        dias_licencias_nr = min(dias_licencias_nr, max(dias_trabajados - dias_licencias_rem, 0))
        dias_basico = max(dias_trabajados - dias_licencias_rem - dias_licencias_nr, 0)

        basico = salario_base * (dias_basico / 30) if dias_basico else 0.0
        aux_base = calcular_auxilio_transporte(salario_base, smmlv, aux_transporte)
        aux_trans = aux_base * (dias_basico / 30) if aux_base and dias_basico else 0.0

        if tipo_vinculacion == "APRENDIZ_SENA":
            nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
            alertas.append(
                _alert(
                    "warning",
                    (
                        f"{nombre}: el cálculo automático del aprendiz SENA es referencial. "
                        "Revise etapa lectiva/productiva, apoyo de sostenimiento y aportes reales antes de aprobar."
                    ),
                    empleado_id=empleado_id,
                )
            )
            aux_trans = 0.0
            salud_emp = 0.0
            pension_emp = 0.0
            fsp = 0.0
            retencion = 0.0
        else:
            if salario_base < smmlv:
                nombre = f"{empleado.get('nombres', '')} {empleado.get('apellidos', '')}".strip()
                alertas.append(
                    _alert(
                        "warning",
                        (
                            f"{nombre}: el salario base configurado (${salario_base:,.0f}) está por debajo del "
                            f"SMMLV (${smmlv:,.0f}). Revise si corresponde a tiempo parcial, suspensión o un dato mal cargado."
                        ),
                        empleado_id=empleado_id,
                    )
                )

            if not str(empleado.get("eps", "")).strip():
                alertas.append(_alert("warning", f"Empleado {empleado_id} no tiene EPS registrada.", empleado_id=empleado_id))
            if not str(empleado.get("fondo_pension", "")).strip():
                alertas.append(
                    _alert("warning", f"Empleado {empleado_id} no tiene fondo de pensión registrado.", empleado_id=empleado_id)
                )
            if not str(empleado.get("fondo_cesantias", "")).strip():
                alertas.append(
                    _alert("warning", f"Empleado {empleado_id} no tiene fondo de cesantías registrado.", empleado_id=empleado_id)
                )

            base_ss = basico + extras + pagos_licencias + otros_devengados
            salud_emp, pension_emp = calcular_salud_pension(base_ss, 4, 4)
            fsp = calcular_fondo_solidaridad(base_ss, smmlv)
            retencion = _retencion_periodo(base_ss, salud_emp + pension_emp + fsp, uvt, dias_periodo)

        total_devengado = basico + aux_trans + extras + pagos_licencias + otros_devengados
        total_deducido = salud_emp + pension_emp + fsp + retencion
        neto = total_devengado - total_deducido

        detalles.append(
            {
                "empleado_id": empleado_id,
                "dias_trabajados": dias_trabajados,
                "sueldo_basico": _money(basico),
                "auxilio_transporte": _money(aux_trans),
                "horas_extras": _money(extras),
                "total_devengado": _money(total_devengado),
                "salud_empleado": _money(salud_emp),
                "pension_empleado": _money(pension_emp),
                "fondo_solidaridad": _money(fsp),
                "retencion_fuente": _money(retencion),
                "total_deducido": _money(total_deducido),
                "neto_pagar": _money(neto),
            }
        )

    resumen = {
        "empleados": int((df_empleados["tipo_vinculacion"] != "CONTRATISTA").sum()),
        "contratistas": int((df_empleados["tipo_vinculacion"] == "CONTRATISTA").sum()),
        "total_devengado": _money(sum(detalle["total_devengado"] for detalle in detalles)),
        "total_neto": _money(sum(detalle["neto_pagar"] for detalle in detalles)),
    }

    return {"detalles": detalles, "alertas": alertas, "resumen": resumen}
