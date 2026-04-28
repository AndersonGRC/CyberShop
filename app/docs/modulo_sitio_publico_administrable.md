# Proyecto: Módulo de Configuración Pública por Cliente con Base de Datos Independiente

## Nombre del proyecto
**Sitio Público Administrable de CyberShop**

## Resumen
Este módulo rediseña la administración de la parte pública de CyberShop pensando en el modelo real del negocio:
cada empresa opera con su propia base de datos y su propia configuración pública.

La solución ya no depende de una arquitectura multi-tenant centralizada para branding, landing o contenido visible
antes del login. En su lugar, cada instalación mantiene una capa local y estructurada del sitio público, con seed
reproducible por migración y panel administrativo unificado.

## Qué quedó implementado
- Panel único `/admin/sitio-publico` para:
  - branding,
  - colores,
  - logo,
  - textos corporativos,
  - visibilidad del sitio y del menú público,
  - slides,
  - publicaciones,
  - servicios.
- Previsualización en vivo, pequeña y escalada dentro del panel.
- Resaltado visual de cambios en la preview mediante subrayado y contorno.
- Nueva capa de datos pública con tablas propias:
  - `public_site_settings`
  - `public_site_blocks`
  - `public_site_items`
- Bootstrap y compatibilidad con instalaciones existentes:
  - lectura con fallback desde `cliente_config`, `config_secciones`, `slides_home`, `publicaciones_home`, `servicios_home`
  - sincronización de claves relevantes hacia `cliente_config` y `config_secciones`
- Frontend público refactorizado para consumir el servicio unificado.
- Navegación administrativa simplificada para que “Contenido Web” apunte al panel consolidado.

## Modelo técnico
### 1. `public_site_settings`
Clave/valor para configuración simple del sitio público:
- branding
- contacto
- colores
- toggles de visibilidad

### 2. `public_site_blocks`
Bloques editables de landing:
- quiénes somos
- misión
- visión
- título de publicaciones
- bloque de contacto
- hero de servicios

### 3. `public_site_items`
Elementos repetibles del sitio:
- slides
- publicaciones
- servicios

## Archivos principales
- [services/public_site_service.py](/var/www/CyberShop/app/services/public_site_service.py:1)
- [routes/admin.py](/var/www/CyberShop/app/routes/admin.py:1452)
- [routes/public.py](/var/www/CyberShop/app/routes/public.py:54)
- [templates/sitio_publico_admin.html](/var/www/CyberShop/app/templates/sitio_publico_admin.html:1)
- [migrate_public_site_structured.sql](/var/www/CyberShop/app/migrate_public_site_structured.sql:1)

## Arquitectura aplicada
- 1 empresa = 1 base de datos.
- El contenido operativo público no se centraliza en una sola base compartida.
- La escalabilidad de nuevos clientes se resuelve por:
  - migración SQL versionada,
  - seed inicial reproducible,
  - bootstrap local compatible con bases existentes.

## Previsualización en vivo
El panel incluye una maqueta reducida del sitio público que permite:
- ver branding y textos actualizados mientras se editan,
- verificar visibilidad de secciones,
- revisar el efecto sobre slides, publicaciones y servicios,
- detectar cambios por subrayado o contorno antes de guardar.

## Compatibilidad
Para no romper módulos existentes:
- se mantienen sincronizadas claves públicas relevantes en `cliente_config`,
- se mantienen sincronizados los toggles en `config_secciones`,
- el frontend usa la nueva capa estructurada cuando existe y cae a la estructura vieja si todavía no se ha migrado la base.

## Validación realizada
Se validó sintaxis Python con:

```bash
python3 -m py_compile app.py helpers.py routes/public.py routes/admin.py services/public_site_service.py
```

## Paso operativo por entorno
Aplicar la migración estructurada en cada base cliente:

```bash
psql -d <base_cliente> -f migrate_public_site_structured.sql
```

## Resultado
CyberShop queda con un módulo de **Sitio Público Administrable** alineado con la operación real por cliente:
base independiente, estructura pública propia, panel unificado y vista previa de cambios antes de publicar.
