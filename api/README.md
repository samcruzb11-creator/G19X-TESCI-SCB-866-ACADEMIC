# API — Sistema de Trazabilidad Documental

## Requisitos

- Python 3.14
- XAMPP con MySQL iniciado y una base de datos llamada `sistema_trazabilidad`

## Preparar el entorno

Desde una terminal PowerShell, entra a la carpeta `api`:

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt
Copy-Item .env.example .env
```

Edita `.env` con la configuración local de MySQL. No subas este archivo a Git. En XAMPP, inicia MySQL y crea la base de datos indicada arriba. Las migraciones Alembic versionan el esquema; revisa y aplica las pendientes antes de desplegar una versión nueva.

## Ejecutar

Desde `api` y con el entorno virtual activado:

```powershell
uvicorn app.main:app --reload
```

Hardening local 6B.4A: [operación, límites, migración 003 y pruning](../docs/FASE_6B_4A_AUTH_HARDENING.md).
El presupuesto global requiere **un único proceso FastAPI**. `--reload` es solo desarrollo;
reinicia el estado global en memoria, pero los buckets MySQL persisten. Desplegar 003 antes
del código nuevo. No incluye integración Turnstile.

Fase 6C: [solicitudes de acceso, recuperación y cola de correo](../docs/FASE_6C_ACCESO_RECUPERACION.md).
El código 6C requiere también la revisión **004**, además de 002/003. Las pruebas
crean esquemas temporales aleatorios; no aplican migraciones a la BD de trabajo.
El correo se procesa mediante CLI Python y configuración SMTP privada, sin SMTP en PHP.

La ruta `GET /` devuelve el estado básico de la API. La documentación interactiva está en <http://127.0.0.1:8000/docs>.
