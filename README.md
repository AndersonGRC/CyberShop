# Achiras de mi Tierra — App legacy (fork antiguo de CyberShop)

Tienda del cliente *Achiras de mi Tierra*. Fork temprano de CyberShop (Flask +
PostgreSQL, BD `achirasdemitierra`).

## Estado
- **Suspendido** (cliente inactivo; dominio achirasdemitierra.org vencido).
- **Administrado por el maestro** (admin.cybershopcol.com): adoptado en el
  control plane; se enciende/apaga con el boton del panel (instancia
  `cybershop@achirasdemitierra`, puerto 6001).
- Credenciales de BD **fuera del codigo**: `/etc/cybershop/achirasdemitierra.env`
  (database.py las lee con os.getenv).
- Tablas de administracion (`cliente_config`, `config_secciones`) agregadas
  para el panel maestro. Su codigo legacy NO las consume.

## Si el cliente regresa
Lo recomendado es **migrarlo al codigo compartido actual** de CyberShop
(/var/www/CyberShop) conservando su BD: ver repo CyberShop ->
`app/docs/ECOSISTEMA.md`.
