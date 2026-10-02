# Guía de Contribución

## 1. Requisitos Previos

* Python 3.12 (o compatible)
* Entorno virtual activado
* Clon del repositorio local

## 2. Flujo de Trabajo

1. **Crea una rama** desde `main` o `master`:
   ```bash
   git checkout -b feature/nombre-de-la-rama
   ```
2. **Desarrolla**: haz cambios, commits claros y pequeños.
3. **Prueba local**: asegúrate de que las pruebas pasan (si existen) y que la aplicación funciona.
4. **Sube la rama**:
   ```bash
   git push -u origin feature/nombre-de-la-rama
   ```
5. **Pull Request**: abre un PR con un título descriptivo y una breve descripción. Indica los archivos modificados y el objetivo.
6. **Revisión**: los revisores pueden comentar y solicitar cambios. Responde a los comentarios y actualiza el PR.
7. **Merge**: una vez aprobado, haz merge siguiendo la política del proyecto (fast‑forward o squash). Si no estás seguro, pide ayuda.

## 3. Estilo de Código

* **Python**: PEP8, `black` y `flake8` están configurados. Ejecuta `black .` y `flake8 .` antes de commit.
* **HTML/CSS**: Usa variables de `static/css/variables.css` y evita colores hexadecimales en línea.
* **JavaScript**: Mantén la lógica en `static/js/*.js` y usa `var(--color‑…)` cuando sea necesario.

## 4. Pruebas

Añade pruebas en `tests/` con `pytest`. Cada PR debe incluir al menos un test nuevo o una corrección de test existente.

## 5. Seguridad

* No incluyas credenciales en el código.
* Revisa los formularios con CSRF y XSS.
* El proyecto usa `psycopg2` con **consultas parametrizadas** (sin ORM): pasa siempre los valores como
  parámetros (`cur.execute(sql, (a, b))`), **nunca** concatenes ni formatees valores dentro del SQL.

## 6. Licencia

El proyecto está bajo la licencia MIT. No olvides incluir el archivo `LICENSE`.
