"""Estadística determinista para el análisis del negocio de CADA cliente.

Las cifras de tendencias y segmentos NO las calcula el modelo de lenguaje: un
LLM puede equivocarse con los números. Se calculan aquí, en Python puro y
reproducible, sobre los datos de la BD del tenant; la IA solo las explica.

Sin dependencias externas (numpy/scikit-learn no están en los venvs de
producción y los volúmenes de un comercio —cientos o pocos miles de filas— no
las necesitan).

Contenido:
- regresion_lineal: recta de mínimos cuadrados + R² (qué tan confiable es la
  tendencia).
- kmeans: agrupamiento con inicialización k-means++ reproducible (semilla fija).
- elegir_k_codo: método del codo (punto de máxima curvatura de la inercia).
- silueta: calidad de la separación de los grupos (-1 a 1).
"""
import math
import random


# ── Regresión lineal ──────────────────────────────────────────────────────────
def regresion_lineal(xs, ys):
    """Ajusta y = a + b·x por mínimos cuadrados.

    Devuelve {'pendiente', 'intercepto', 'r2', 'n'}. R² mide qué parte de la
    variación de y explica la recta: 1 = la tendencia describe perfectamente los
    datos; cerca de 0 = los datos suben y bajan sin una tendencia real.
    Con menos de 3 puntos, o si x no varía, no hay regresión posible (None).
    """
    n = len(xs)
    if n != len(ys) or n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    # Serie constante: la recta horizontal la explica toda (sin variación que explicar).
    r2 = 1.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
    return {'pendiente': b, 'intercepto': a, 'r2': r2, 'n': n}


# ── Utilidades de vectores ────────────────────────────────────────────────────
def estandarizar(filas):
    """Z-score por columna (media 0, desviación 1). Columnas constantes → 0.
    Sin esto, una variable en pesos (millones) aplastaría a una en días."""
    if not filas:
        return []
    cols = len(filas[0])
    medias, desv = [], []
    for j in range(cols):
        vals = [f[j] for f in filas]
        m = sum(vals) / len(vals)
        d = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
        medias.append(m)
        desv.append(d if d > 0 else 1.0)
    return [[(f[j] - medias[j]) / desv[j] for j in range(cols)] for f in filas]


def _dist2(p, q):
    return sum((a - b) ** 2 for a, b in zip(p, q))


def _centroide(puntos, dims):
    if not puntos:
        return [0.0] * dims
    return [sum(p[j] for p in puntos) / len(puntos) for j in range(dims)]


# ── K-means ───────────────────────────────────────────────────────────────────
def kmeans(puntos, k, semilla=42, intentos=5, max_iter=100):
    """K-means con k-means++. Devuelve {'etiquetas', 'centroides', 'inercia'}.

    Semilla fija: el mismo conjunto de datos da siempre los mismos grupos, así
    el dueño no ve segmentos distintos cada vez que pregunta. Se prueban varios
    arranques y se queda el de menor inercia (suma de distancias² al centro).
    """
    n = len(puntos)
    if n == 0 or k < 1:
        return None
    k = min(k, n)
    dims = len(puntos[0])
    rng = random.Random(semilla)
    mejor = None
    for _ in range(max(1, intentos)):
        # k-means++: centros iniciales separados entre sí
        centros = [list(puntos[rng.randrange(n)])]
        while len(centros) < k:
            d2 = [min(_dist2(p, c) for c in centros) for p in puntos]
            total = sum(d2)
            if total == 0:
                centros.append(list(puntos[rng.randrange(n)]))
                continue
            umbral, acum = rng.random() * total, 0.0
            for p, d in zip(puntos, d2):
                acum += d
                if acum >= umbral:
                    centros.append(list(p))
                    break
        etiquetas = [0] * n
        for _it in range(max_iter):
            nuevas = [min(range(k), key=lambda c: _dist2(p, centros[c])) for p in puntos]
            cambio = nuevas != etiquetas
            etiquetas = nuevas
            for c in range(k):
                miembros = [p for p, e in zip(puntos, etiquetas) if e == c]
                # Grupo vacío: se re-siembra en el punto más lejano a su centro actual.
                if miembros:
                    centros[c] = _centroide(miembros, dims)
                else:
                    # por índice: con puntos repetidos (clientes de perfil idéntico)
                    # puntos.index() devolvería siempre el primero.
                    lejano = max(range(n), key=lambda i: _dist2(puntos[i], centros[etiquetas[i]]))
                    centros[c] = list(puntos[lejano])
            if not cambio and _it > 0:
                break
        inercia = sum(_dist2(p, centros[e]) for p, e in zip(puntos, etiquetas))
        if mejor is None or inercia < mejor['inercia']:
            mejor = {'etiquetas': etiquetas, 'centroides': centros, 'inercia': inercia}
    return mejor


def elegir_k_codo(inercias):
    """Método del codo. `inercias` = {k: inercia} para k consecutivos desde 1.

    Normaliza la curva y toma el k más alejado de la recta que une el primer y
    el último punto (máxima curvatura): a partir de ahí, agregar grupos casi no
    mejora la agrupación. Con menos de 3 valores de k no hay codo que buscar.
    """
    ks = sorted(inercias)
    if len(ks) < 3:
        return ks[-1] if ks else None
    xs = [(k - ks[0]) / (ks[-1] - ks[0]) for k in ks]
    ymax, ymin = max(inercias.values()), min(inercias.values())
    rango = (ymax - ymin) or 1.0
    ys = [(inercias[k] - ymin) / rango for k in ks]
    # distancia de cada punto a la recta (x0,y0)-(x1,y1)
    x0, y0, x1, y1 = xs[0], ys[0], xs[-1], ys[-1]
    den = math.hypot(x1 - x0, y1 - y0) or 1.0
    distancias = [abs((y1 - y0) * x - (x1 - x0) * y + x1 * y0 - y1 * x0) / den for x, y in zip(xs, ys)]
    return ks[max(range(len(ks)), key=lambda i: distancias[i])]


def silueta(puntos, etiquetas):
    """Coeficiente de silueta medio (-1 a 1). Cerca de 1 = grupos bien
    separados; cerca de 0 = se solapan; negativo = mal asignados.
    O(n²): se usa solo con muestras de tamaño comercio (≤ 2 000 puntos)."""
    grupos = set(etiquetas)
    if len(grupos) < 2 or len(puntos) < 3:
        return None
    total, contados = 0.0, 0
    for i, p in enumerate(puntos):
        propio = etiquetas[i]
        dist = {}
        for j, q in enumerate(puntos):
            if i != j:
                dist.setdefault(etiquetas[j], []).append(math.sqrt(_dist2(p, q)))
        if not dist.get(propio):
            continue   # grupo de un solo punto: silueta indefinida, no cuenta
        a = sum(dist[propio]) / len(dist[propio])
        b = min(sum(v) / len(v) for g, v in dist.items() if g != propio)
        s = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
        total += s
        contados += 1
    return total / contados if contados else None


def mediana(valores):
    v = sorted(valores)
    n = len(v)
    if n == 0:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

def desviacion_estandar(valores):
    """Desviación estándar muestral (n-1). None con menos de 2 datos."""
    v = [float(x) for x in valores]
    if len(v) < 2:
        return None
    media = sum(v) / len(v)
    return math.sqrt(sum((x - media) ** 2 for x in v) / (len(v) - 1))


def z_score(valor, historico, minimo=6):
    """A cuántas desviaciones está `valor` del promedio de `historico`.

    Sirve para avisar de un día raro (ventas muy bajas o muy altas) sin fijar
    umbrales a dedo. Devuelve None si hay pocos datos o si todos son iguales
    (sin variación no hay con qué comparar). |z| >= 2 se considera anormal.
    """
    v = [float(x) for x in historico]
    if len(v) < minimo:
        return None
    s = desviacion_estandar(v)
    if not s:
        return None
    return (float(valor) - sum(v) / len(v)) / s
