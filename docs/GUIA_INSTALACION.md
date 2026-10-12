# Guía de instalación

Sistema de Trazabilidad Documental para Auditorías. Entrega de evaluación local, 9 de octubre de 2026.

## 1. Requisitos previos

Windows con Git, Python 3.14 de 64 bits, MySQL 8/InnoDB y PHP 8.1 o superior. PHP necesita `curl`, `mbstring`, `fileinfo`, `openssl` y sesiones. XAMPP puede proporcionar PHP; **su MariaDB no sustituye a MySQL 8**. El frontend no necesita Apache, Composer ni Node.

Los ejemplos principales son para **CMD**, con tres terminales independientes. En PowerShell, ante un ejecutable entre comillas use `&`, y para activar el entorno use `api\venv\Scripts\Activate.ps1` si la política lo permite; también puede usar directamente el ejecutable del venv y evitar activación.

Verifique:

```bat
git --version
py -3.14 --version
mysql --version
C:\xampp\php\php.exe -v
C:\xampp\php\php.exe -m
```

Si `mysql` no está en PATH, use el ejecutable de la carpeta `bin` de MySQL 8 o su consola SQL. Instale el servidor real de MySQL y encienda su servicio. Compruebe que el puerto 3306 le pertenece; detenga el MariaDB de XAMPP si usa ese mismo puerto. PHP debe tener habilitadas las extensiones indicadas en su `php.ini`.

## 2. Descargar y crear el entorno

```bat
git clone https://github.com/samcruzb11-creator/G19X-TESCI-SCB-866-ACADEMIC.git
cd G19X-TESCI-SCB-866-ACADEMIC
py -3.14 -m venv api\venv
api\venv\Scripts\activate
python -m pip install -r requirements.txt -c requirements-lock.txt
python -m pip check
copy api\.env.example api\.env
```

Después del clone y del cambio de directorio, ejecute los comandos restantes desde la raíz del repositorio. No copie el venv, `.env`, storage o dump de otra persona.

## 3. MySQL vacío y cuenta local

Abra una consola MySQL con una cuenta que pueda crear schemas/usuarios. `-p` solicita la contraseña sin colocarla en la línea de comandos:

```bat
mysql -h 127.0.0.1 -P 3306 -u root -p
```

Ejecute, **sólo en una instalación nueva**, sustituyendo el marcador por una contraseña operativa privada:

```sql
SELECT VERSION();
CREATE DATABASE trazabilidad_evaluacion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'trazabilidad_local'@'127.0.0.1' IDENTIFIED BY '<CONTRASENA_DB_PRIVADA>';
GRANT ALL PRIVILEGES ON trazabilidad_evaluacion.* TO 'trazabilidad_local'@'127.0.0.1';
```

Este permiso incluye DDL para Alembic durante instalación local. En producción separe la identidad migradora de la identidad de ejecución y revise sus privilegios. No reutilice un schema real para evaluación. No ejecute DROP ni importe un dump personal. Si el nombre ya existe, seleccione otro schema vacío y ajuste `DB_NAME`.

## 4. Configuración privada

Edite **únicamente** `api/.env` en su instalación. No lo suba a Git. Configure:

```env
APP_ENV=development
DEBUG=false
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=trazabilidad_evaluacion
DB_USER=trazabilidad_local
DB_PASSWORD=<CONTRASENA_DB_PRIVADA>
JWT_SECRET_KEY=<SECRETO_ALEATORIO_PRIVADO>
JWT_ALGORITHM=HS256
TURNSTILE_MODE=disabled
PUBLIC_FRONTEND_URL=http://127.0.0.1:8080
```

Genere su secreto JWT; copie la salida sólo a `JWT_SECRET_KEY` en `.env` y no la publique:

```bat
api\venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Los marcadores anteriores no son credenciales ejecutables. Las variables del entorno del proceso prevalecen sobre `.env`; elimine overrides antiguos si se conecta al schema equivocado. Para contraseñas con caracteres especiales respete las comillas de dotenv. `STORAGE_PATH` permanece fijado a `storage/` junto a la raíz del proyecto: el aislamiento se obtiene usando un clone nuevo, no cambiando esta variable.

SMTP y Turnstile reales son opcionales para el recorrido local de login/documentos. **Correo no disponible en la demo:** el backend de recuperación, tokens/controles, cola, worker y configuración SMTP están implementados, pero no se configuró un proveedor externo ni se acreditó recepción real. Sin SMTP no se completa la recuperación por correo ni la activación de la cuenta mediante enlace tras la aprobación administrativa. La recepción de solicitudes y su revisión o rechazo por ADMIN están implementados y son verificables; la activación posterior requiere SMTP externo, worker y buzón autorizado. Las cuentas ficticias de evaluación no tienen buzón, incluso si se configura el proveedor. Consulte [SMTP y recuperación](SMTP_RECUPERACION.md) y la [referencia completa de configuración](CONFIGURACION.md).

## 5. Crear estructura y cuentas demo

Obtenga `01_ACCESOS_PRUEBA.md` de TODO Academy y guárdelo en `%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md`, fuera del clone. No ejecute el generador: el seed debe usar exactamente el documento recibido.

Desde la raíz, con el venv activado:

```bat
cd api
python -m alembic upgrade head
python -m alembic current
python -m app.scripts.seed_evaluation_demo --with-dataset
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
cd ..
```

Alembic debe terminar en **005**. El primer seed sólo muestra el plan. El segundo crea cuatro cuentas sintéticas y Área Demo; el dataset añade dos auditorías, dos documentos, una versión TXT, una evidencia NOTE, un hallazgo, una ronda y una decisión pendiente. La ronda puede iniciarse como ADMIN y decidirse como APROBADOR. Los códigos empiezan por `EVAL-`. El segundo documento pertenece a ADMIN y permite demostrar el alcance restringido.

Repita el segundo comando para verificar idempotencia: debe mostrar `Cuentas nuevas: 0`. El seed nunca restablece contraseñas ni corrige atributos de cuentas existentes; si una identidad demo ya existe con datos diferentes, aborta y exige revisión humana. El archivo privado es obligatorio en la ejecución confirmada; formato inválido o ausente falla seguro. Sus cuatro identidades y contraseñas se reproducen exactamente. [Contrato, generación y rotación](CREDENCIALES_EVALUACION.md). Los IDs y timestamps se asignan localmente; los nombres, contenido y relaciones son deterministas. No se crean demos al arrancar FastAPI.

## 6. Iniciar backend

Terminal 1, desde la raíz:

```bat
cd api
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Mantenga un solo proceso API. No use `--workers` múltiples: los presupuestos globales de admisión y rate limiting son locales al proceso. `--reload` sólo sirve para desarrollo y reinicia presupuestos en memoria.

## 7. Iniciar frontend

Terminal 2, desde la raíz:

```bat
C:\xampp\php\php.exe -S 127.0.0.1:8080 -t frontend
```

Si PHP está en PATH:

```bat
php -S 127.0.0.1:8080 -t frontend
```

En PowerShell:

```powershell
& 'C:\xampp\php\php.exe' -S 127.0.0.1:8080 -t frontend
```

El servidor integrado es para evaluación local. Para archivos de hasta 20 MiB, asegure margen multipart en `php.ini`, por ejemplo `upload_max_filesize=20M` y `post_max_size=22M`; reinicie PHP. La aplicación aplica además sus límites backend. La API default está en `frontend/config/config.php`.

## 8. Prueba rápida

Abra frontend `http://127.0.0.1:8080`. Las credenciales se reciben por separado mediante TODO Academy en el documento privado externo `01_ACCESOS_PRUEBA.md`; [Accesos de prueba](ACCESOS_PRUEBA.md) explica el procedimiento público. Como ADMIN recorra dashboard, auditorías, Documento de Evidencia Demo, versiones, Hallazgo Demo, aprobaciones y análisis. Descargue el TXT sintético. Cierre sesión.

Inicie como RESPONSABLE_AREA: debe ver sólo Documento de Evidencia Demo y sus aprobaciones; puede cargar una nueva versión propia. Auditorías, hallazgos y solicitudes de acceso no están disponibles. Escriba manualmente `index.php?pagina=auditorias`: debe ser rechazado. El dashboard y análisis reflejan sólo sus documentos. Cierre sesión.

Swagger está en `http://127.0.0.1:8000/docs`, como herramienta técnica. En `POST /api/v1/auth/login` use correo/password demo, luego Authorize con el token obtenido; compruebe `/auth/me`. No publique ni capture el token. Logout revoca la sesión y un `/auth/me` posterior debe responder 401.

## 9. Pruebas automatizadas

Desde raíz:

```bat
api\venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-lock.txt
set PYTHONPATH=%CD%\api
set PYTHONDONTWRITEBYTECODE=1
api\venv\Scripts\python.exe -B -m pytest api/tests_unit -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_unit_nuevo
api\venv\Scripts\python.exe -B -m pytest frontend/tests -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_php_nuevo
```

Para MySQL real, la cuenta de pruebas debe poder crear/eliminar **schemas temporales aleatorios**; la cuenta limitada a `trazabilidad_evaluacion.*` no tiene esos privilegios. Use una identidad local de pruebas con ese permiso en el entorno del proceso; no amplíe los permisos de la identidad de producción. Los fixtures bloquean el engine de la BD operativa:

```bat
set AUTH_MYSQL_TEST=1
set AUTH_BROWSER_TEST=1
api\venv\Scripts\python.exe -B -m pytest api/tests_auth_mysql -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_mysql_nuevo
```

`AUTH_BROWSER_TEST=1` activa Chrome instalado con perfil efímero; opcionalmente configure `CHROME_TEST_BINARY` y `PHP_TEST_BINARY`. Sin opt-in, los tests browser se omiten. Use una carpeta basetemp nueva y propia: pytest puede limpiar esa carpeta. **No ejecute `api/tests` contra la configuración operativa**: es una suite histórica con fixture antiguo. La regresión protegida de 6A es `api/tests_auth_mysql/test_6a_regression_mysql.py`.

## 10. Resolución de problemas

| Síntoma | Acción |
|---|---|
| `py` no existe | Instale Python 3.14 con launcher o use la ruta del intérprete 3.14 para crear el venv |
| No conecta a MySQL | Compruebe servicio, host/puerto, permisos y `.env`; descarte MariaDB |
| Alembic falla | Ejecute desde `api`, revise schema vacío/usuario DDL; no use `stamp` para ocultar migraciones faltantes |
| JWT inseguro | Genere secreto aleatorio privado y reinicie backend |
| `.env` ausente | Copie `.env.example`; los valores default no bastan para iniciar de forma segura |
| Puerto 8000/8080 ocupado | Identifique el proceso dueño; detenga sólo su proceso o configure puertos/URL de forma coherente |
| PHP sin cURL/mbstring/fileinfo | Habilite extensión en el `php.ini` de CLI (`php --ini`) y reinicie |
| HTTP 503 en reset/acceso | Complete SMTP y URL; ejecute worker; consulte el estado de cola sin exponer tokens |
| Seed devuelve conflicto | No borre cuentas ni cambie atributos; use un schema nuevo o revise la procedencia |
| Error de storage | Conceda acceso NTFS al operador para `storage/`, conserve hardlinks y no use enlaces hacia fuera |
| Análisis tarda o informa truncación | Respete límites; consulte un documento concreto; no hay modelo que descargar |
| HTTP 409 | Recargue el recurso y revise estado/versión antes de reintentar |

La [referencia de operación](MANUAL_TECNICO.md) incluye backup e integridad. No elimine datos legacy ni archivos huérfanos automáticamente.
