# Limpieza de tenant_id y facturacion electronica por registro

## Resumen

Quitar `tenant_id` de los modulos operativos que viven dentro de una base por cliente: productos, inventario, POS local y restaurante. Mantener `tenant_id` solo en la capa de modulos SaaS y en el contexto de facturacion electronica. La facturacion electronica debe depender de dos condiciones: modulo activo y decision explicita por venta o pedido.

## Cambios principales

- Catalogo e inventario:
  - `productos` queda como catalogo local por base.
  - `visible_en_ecommerce` sigue controlando solo la visibilidad web.
  - El cargue masivo no usa `tenant_id`.
- Restaurante:
  - Quitar `tenant_id` de rutas y servicios operativos.
  - Mantener `tenant_id` solo en administracion SaaS de modulos.
  - Las mesas, ordenes y consumos se resuelven por `id` y relaciones locales.
- POS y pedidos:
  - Agregar `facturar_electronicamente BOOLEAN NOT NULL DEFAULT FALSE` en `ventas_pos` y `pedidos`.
  - POS debe permitir marcar si una venta va a FE.
  - Checkout debe permitir marcar si un pedido va a FE.
- Facturacion electronica:
  - `emitir_factura_electronica()` y `emitir_factura_pos()` solo deben continuar si:
    - el modulo FE esta activo para el tenant actual, y
    - el registro esta marcado con `facturar_electronicamente = TRUE`.

## Validaciones

- Producto visible: aparece en ecommerce, POS y restaurante.
- Producto oculto: no aparece en ecommerce, si aparece en POS y restaurante.
- Venta POS sin marca FE: no se envia a DIAN.
- Venta POS con marca FE y modulo activo: si se envia a DIAN.
- Pedido web sin marca FE: no se envia a DIAN aunque el pago quede aprobado.
- Pedido web con marca FE y modulo activo: si se envia a DIAN.
- Restaurante opera sin filtrar por `tenant_id`.

## Supuestos

- Una base de datos representa a un solo cliente operativo.
- `tenant_id` sigue siendo valido para modulos SaaS y FE, no para catalogo ni operacion local.
- En esta fase no se eliminan columnas `tenant_id` de la base; solo se dejan de usar donde no hacen falta.
