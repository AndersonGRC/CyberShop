# Versionado del software CyberShop — REGLA OBLIGATORIA

> **LEY DE DESARROLLO:** todo cambio que se despliega **debe** subir la versión.
> Sin bump de versión, el cambio no está "terminado". Aplica a **todos los
> productos y todos los clientes, incluido CyberShop**.

## Esquema: `A.B.C.D`

Cuatro segmentos. Se sube el segmento correspondiente a la magnitud del cambio
(y los de la derecha se reinician a 0):

| Segmento | Nombre | Cuándo se sube | Ejemplo |
|---|---|---|---|
| **A** | Mayor / radical | Reescritura o cambio radical de plataforma | `1.x.x.x → 2.0.0.0` |
| **B** | Módulo | Un **módulo nuevo** grande o hito funcional | `1.0.x.x → 1.1.0.0` |
| **C** | Estabilización | Mejora, módulo menor, refactor, endurecimiento | `1.0.0.x → 1.0.1.0` |
| **D** | Corrección | Bugfix, ajuste de UI, cambio pequeño | `1.0.0.0 → 1.0.0.1` |

Regla mínima: **cada desarrollo sube al menos `D`.** Módulo nuevo → sube `B`.
Estabilización → sube `C`. Cambio radical → sube `A`.

## Dónde vive la versión (única fuente por producto)

| Producto | Archivo / variable | Se muestra en |
|---|---|---|
| **Admin web** (CyberShop) | `config.py` → `Config.APP_VERSION` | Footer del panel `/admin` (`CyberShop Admin vX.Y.Z.W`), para todos los clientes |
| **POS Escritorio** | `main.py` → `APP_VERSION` (+ `installer.iss`) | Footer de la app + `/api/v1/sync/version` (auto-update) |

## Cómo saber si un cliente tiene la última versión

- **Admin web**: el código es **compartido** → todos los clientes corren SIEMPRE
  la misma versión (la última desplegada). El número del footer es informativo:
  dice qué release está vivo. No hay "clientes desactualizados" en la web.
- **POS Escritorio**: cada PC tiene su instalación. El auto-update compara la
  `APP_VERSION` instalada contra `version.json` del servidor. Ver el flujo de
  publicación en el pipeline del escritorio (`tools/publish_update.py`).

## Procedimiento al cerrar un desarrollo (checklist)

1. **Subir la versión** en el archivo del producto afectado:
   - Web → `config.py: Config.APP_VERSION`.
   - Escritorio → `main.py: APP_VERSION` **y** `installer.iss: AppVersion`.
2. Si es escritorio: `build_installer.bat` → `tools/publish_update.py --version X` → subir al servidor.
3. Commit + push (mensaje que mencione la versión).
4. Desplegar (web por `git pull`; escritorio por el pipeline de instalador).

> Nota: la versión web y la del escritorio son **independientes** (artefactos
> distintos); cada una lleva su propio `A.B.C.D`.
