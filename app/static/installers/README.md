# static/installers/

Carpeta donde se publican los binarios del POS Desktop.

## Archivos esperados

| Archivo | Descripción |
|---|---|
| `CyberShopSetup_base.exe` | Instalador base (Inno Setup). Lo genera `CyberShopDesktop\build_installer.bat`. **No se sube a git** (binario grande). |
| `version.json` | Manifiesto de versión leído por `/api/v1/sync/version`. **Sí va a git**. |

## Flujo

1. El dev corre `cd CyberShopDesktop && build_installer.bat` → produce el `.exe` y lo copia aquí.
2. Edita `version.json` con la nueva versión y los release notes.
3. Hace commit del `version.json` (no del `.exe`).
4. El `.exe` se sube a producción por separado (rsync, FTP, S3, etc.) o se compila en CI.

## Notas

- El `.gitignore` debe excluir `*.exe` en esta carpeta.
- El instalador base nunca cambia por cliente: la personalización vive en `bootstrap.json`, generado por `services/installer_packager.py` y empacado en el ZIP que sirve `/descargar`.
