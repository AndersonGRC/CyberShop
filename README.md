# CyberShop

> Una tienda de comercio electrónico con una arquitectura modular en Flask, enfocada en la gestión de inventario, facturación y usuarios.

## Visión General

CyberShop es una aplicación web de **Flask** que permite a los administradores gestionar productos, usuarios, pedidos y facturación electrónica. La lógica de negocio se encuentra en el paquete `app`, con rutas y servicios claramente separados.

El proyecto son **dos aplicaciones** integradas:

- **Web** (`CyberShop/app`): plataforma Flask e-commerce + SaaS **multi-tenant** (control plane + 1 base de datos por cliente) con API `/api/v1/sync` para el POS.
- **Escritorio** (`CyberShopDesktop`): POS **offline** (PyQt6 + SQLite) que sincroniza con la web y comparte usuarios/contraseñas.

Referencias clave:
- [CyberShop/app/docs/MAPA_ARCHIVOS.md](app/docs/MAPA_ARCHIVOS.md) — para qué sirve cada archivo.
- [CyberShop/app/docs/INTEGRACION_WEB_DESKTOP.md](app/docs/INTEGRACION_WEB_DESKTOP.md) — cadena de sync web↔escritorio.
- [CyberShop/app/CLAUDE.md](app/CLAUDE.md) — arquitectura del backend.

## Estructura del Código

```
CyberShop/
├── app/              # Código fuente principal
│   ├── __init__.py
│   ├── app.py         # Punto de entrada (Flask)
│   ├── routes/        # Módulos de rutas
│   ├── services/      # Lógica de negocio
│   ├── templates/     # Plantillas Jinja2
│   ├── static/        # CSS/JS/Imágenes
│   │   ├── css/       # Estilos (ver sección de CSS)
│   │   ├── js/        # Scripts
│   │   └── img/       # Imágenes estáticas
│   ├── helpers.py
│   └── security.py
├── docs/              # Documentación adicional
├── requirements.txt
├── app/.cybershop.conf.example
└── README.md
```

## Instalación

1. **Clonar el repositorio**
   ```bash
   git clone https://github.com/tu-usuario/CyberShop.git
   cd CyberShop
   ```
2. **Crear entorno virtual**
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```
3. **Instalar dependencias**
   ```bash
   pip install -r requirements.txt
   ```
4. **Configurar variables de entorno**
   ```bash
   cp app/.cybershop.conf.example app/.cybershop.conf
   ```
   Edita `app/.cybershop.conf` con tus credenciales (Flask secret key, base de datos, claves de pago, etc.). `config.py` lo carga con `load_dotenv`.
5. **Inicializar la base de datos** (si corresponde)
   ```bash
   flask db upgrade   # Si usas Alembic o Flask-Migrate
   ```
6. **Ejecutar la aplicación**
   ```bash
   flask run
   ```
   La aplicación estará disponible en `http://127.0.0.1:5000`.

## Uso

* **Administración**: Accede a `/admin` con las credenciales del super‑usuario.
* **API**: Se exponen varias rutas REST bajo `/api/*`. La documentación Swagger se encuentra en `/swagger` (requiere configuración adicional).
* **Facturación Electrónica**: Genera PDFs desde `/factura_electronica`.

## Pruebas

No existen pruebas automatizadas aún. Se recomienda añadir `pytest` y crear tests para:

* Rutas (GET, POST, etc.)
* Servicios (`app/services/*.py`)
* Validaciones de formularios (`app/forms.py`).

Ejecutar:
```bash
pytest
```

## Contribución

Si deseas colaborar, por favor lee el archivo [CONTRIBUTING.md](CONTRIBUTING.md) para conocer el flujo de trabajo.

## Licencia

MIT © 2026 – Licencia de código abierto.

---

© 2026 CyberShop. Todos los derechos reservados.

## Estilo y CSS

### Centralización de Variables
El proyecto usa un único archivo de variables CSS (`static/css/variables.css`) que contiene todas las definiciones de colores, fuentes y otros valores reutilizables. Cada hoja de estilo importa este archivo con la regla `@import url('variables.css');`, lo que garantiza que cualquier cambio en las variables se propague automáticamente a todos los componentes.

**Ejemplo de `variables.css`:**
```css
/* Color primario y su tono oscuro */
--marca-color-primario: #1155CC;
--marca-color-primario-oscuro: #0D3F99;

/* Colores secundarios */
--marca-color-secundario: #FFCC00;
--marca-color-acento: #28A745;

/* Sombras para tarjetas */
--marca-sombra-card: 0 2px 4px rgba(0,0,0,0.1);
--marca-sombra-sutil: 0 1px 2px rgba(0,0,0,0.05);

/* Otros */
--marca-focus-ring: 0 0 0 3px rgba(0,123,255,0.5);
```

> **Nota:** Todos los colores en las hojas de estilo deben referenciar estas variables con `var(--marca-color-…)`. No se deben usar códigos hexadecimales en línea.

### Uso en Hojas de Estilo
Para aplicar un color de texto o fondo, simplemente hace referencia a la variable:
```css
.button-primary {
  background-color: var(--marca-color-primario);
  color: #fff;
}

.card {
  box-shadow: var(--marca-sombra-card);
}
```

### Cambio Dinámico en Tiempo de Ejecución
El archivo `app.py` pasa el objeto `brand_config` a todas las plantillas. Si necesitas cambiar colores en tiempo de ejecución (por ejemplo, al cargar un cliente con una paleta diferente), puedes insertar un bloque `<style>` en el `<head>` que sobrescriba las variables:
```html
<style>
:root {
  --marca-color-primario: {{ brand_config.colores.primario }};
  --marca-color-primario-oscuro: {{ brand_config.colores.primario_oscuro }};
}
</style>
```

### Comentarios y Mantenimiento
* **Mantén el archivo `variables.css` al principio del proyecto** para que sea fácil localizar.
* **No añadas valores duplicados**; si necesitas un nuevo color, simplemente añádelo al archivo y actualiza los usos.
* **Revisa el archivo antes de hacer merge**: usa linters de CSS para asegurar que no haya errores de sintaxis.
* **Al cambiar valores** revisa los cambios visuales en la aplicación localmente.

---

Con esta centralización, cualquier ajuste de branding requiere editar un solo archivo, reduciendo la posibilidad de inconsistencias.
