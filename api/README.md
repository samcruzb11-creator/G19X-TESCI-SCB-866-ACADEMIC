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

Edita `.env` con la configuración local de MySQL. No subas este archivo a Git. En XAMPP, inicia MySQL y crea la base de datos indicada arriba. Alembic está preparado, pero todavía no hay migraciones ni tablas de negocio.

## Ejecutar

Desde `api` y con el entorno virtual activado:

```powershell
uvicorn app.main:app --reload
```

La ruta `GET /` devuelve el estado básico de la API. La documentación interactiva está en <http://127.0.0.1:8000/docs>.
