# Guía de instalación

Sistema de Trazabilidad Documental para Auditorías. Esta guía describe una instalación local desde cero. El [README](../README.md#inicio-rápido) contiene el recorrido resumido.

## 1. Requisitos previos

Windows con Git, Python 3.14 de 64 bits, MySQL 8/InnoDB y PHP 8.1 o superior. PHP necesita `curl`, `mbstring`, `fileinfo`, `openssl` y sesiones. XAMPP puede proporcionar PHP; **su MariaDB no sustituye a MySQL 8**. El frontend no necesita Apache, Composer ni Node.

Se requiere acceso a PyPI para descargar dependencias, permisos para crear un schema vacío y espacio disponible para los archivos. El sistema de archivos debe admitir hardlinks, como NTFS o ext4. Chrome sólo se necesita para las pruebas de navegador. La base utiliza UTF-8 y las conexiones de la aplicación fijan la zona horaria en UTC.

Los ejemplos principales son para **CMD**. Mantenga dos terminales para FastAPI y PHP; el worker de correo se ejecuta aparte cuando se configure SMTP. En PowerShell, ante un ejecutable entre comillas use `&`. Puede usar directamente `api\venv\Scripts\python.exe` sin activar el entorno; los ejemplos que utilizan `python` requieren el venv activado.

Verifique:

```bat
git --version
py -3.14 --version
mysql --version
C:\xampp\php\php.exe -v
C:\xampp\php\php.exe -m
```

Si `mysql` no está en PATH, use el ejecutable de la carpeta `bin` de MySQL 8 o su consola SQL. Inicie el servicio y compruebe que el puerto 3306 le pertenece; detenga el MariaDB de XAMPP si usa ese mismo puerto. PHP debe tener habilitadas las extensiones indicadas en el `php.ini` de CLI, consultable con `php --ini`. Si PHP está en PATH, puede sustituir `C:\xampp\php\php.exe` por `php`.

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

Después del clone y del cambio de directorio, los comandos parten de la raíz salvo que se indique otra ubicación. La copia de `.env` corresponde a un clone nuevo: no sobrescriba una configuración existente. No copie el venv, `.env`, storage o dump de otra persona. `requirements.txt` contiene dependencias de ejecución; `requirements-lock.txt` fija las versiones verificadas. Las herramientas de pruebas se instalan por separado.

En PowerShell puede activar el entorno con `api\venv\Scripts\Activate.ps1` si la política lo permite, o sustituir `python` por el ejecutable del venv. Desde la raíz, la ruta es `api\venv\Scripts\python.exe`; dentro de `api`, es `venv\Scripts\python.exe`. Para copiar el ejemplo en una instalación nueva:

```powershell
Copy-Item -LiteralPath api/.env.example -Destination api/.env
```

Las rutas principales son `api/app/` para FastAPI, `api/app/db/migrations/` para Alembic, `frontend/` para PHP y `scripts/` para herramientas operativas. `storage/` contiene los archivos privados y está ignorado en Git; `docs/` reúne las referencias técnicas.

## 3. MySQL vacío y cuenta local

Abra una consola MySQL con una cuenta que pueda crear schemas y usuarios. `-p` solicita la contraseña sin colocarla en la línea de comandos:

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

Este permiso incluye DDL para Alembic durante la instalación local. Un despliegue de producción requeriría separar la identidad migradora de la identidad de ejecución y revisar sus privilegios; ese despliegue no forma parte del MVP local. No reutilice una base operativa, no ejecute DROP ni importe un dump personal. Si el schema o el usuario ya existen, elija nombres nuevos y ajuste las instrucciones y `api/.env` en consecuencia.

## 4. Configuración privada

Edite **únicamente** `api/.env` en su instalación. No publique sus valores ni cree un `.env` dentro de `frontend/`. Configure:

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

Los marcadores no son credenciales válidas. El secreto de ejemplo impide iniciar FastAPI. Las contraseñas de las cuentas demo son distintas de los secretos de MySQL, JWT y SMTP: no las reutilice. Las variables del entorno del proceso prevalecen sobre `.env`; revise overrides antiguos si la aplicación apunta al schema equivocado. Para contraseñas con caracteres especiales respete las comillas de dotenv. Reinicie los procesos después de cambiar su configuración.

`STORAGE_PATH` permanece fijado a `storage/` junto a la raíz del proyecto: el aislamiento se obtiene usando un clone nuevo, no cambiando esta variable. La [referencia de configuración](CONFIGURACION.md) detalla los límites de carga, autenticación, Turnstile y correo; no es necesario ajustar todos esos parámetros para el recorrido local.

## 5. Migraciones Alembic

Desde la raíz, con el venv activado:

```bat
cd api
python -m alembic upgrade head
python -m alembic current
cd ..
```

Alembic debe terminar en **005**, la última revisión disponible en `api/app/db/migrations/versions/`. No hay migración 006. No use `stamp` para sustituir la creación real de tablas. Antes de continuar, compruebe que el schema configurado sea el recién creado.

## 6. Usuarios y datos de evaluación

### Archivo privado necesario

Para reproducir la demo necesita `01_ACCESOS_PRUEBA.md`, recibido por un canal privado. Guárdelo en `%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md`, fuera del clone. Si utiliza otra ubicación externa, sustituya sólo esa ruta en los comandos. No copie el documento al repositorio ni publique sus cuentas o contraseñas.

El repositorio no contiene cuentas públicas predeterminadas y FastAPI no crea usuarios al arrancar. Si ya recibió el archivo, utilícelo sin generar otras contraseñas. Si no dispone de él, solicítelo al responsable de los accesos; sin cuentas preparadas no podrá iniciar sesión.

### Cargar cuentas y dataset

Desde la raíz, con el venv activado:

```bat
cd api
python -m app.scripts.seed_evaluation_demo --with-dataset
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
cd ..
```

El primer comando sólo muestra el plan. El segundo crea cuatro cuentas sintéticas y Área Demo. El dataset añade dos auditorías, dos documentos, una versión TXT, una evidencia NOTE, un hallazgo, una ronda y una decisión pendiente. La ronda puede iniciarse como ADMIN y decidirse como APROBADOR. Los códigos empiezan por `EVAL-`. El segundo documento pertenece a ADMIN y permite comprobar el alcance restringido.

El seed exige `APP_ENV=development`, MySQL 8 en loopback, Alembic 005 y un archivo privado válido. Usa un bloqueo compartido con la rotación para evitar ejecuciones simultáneas incompatibles. Sin `--with-dataset`, prepara las cuentas y el área. Los roles son ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO y APROBADOR; la [matriz de permisos](MATRIZ_PERMISOS.md) describe sus diferencias.

Para comprobar idempotencia, vuelva a entrar en `api` y repita el comando confirmado con el mismo archivo: debe informar `Cuentas nuevas: 0`. No restablece contraseñas ni corrige atributos existentes; si una identidad difiere, aborta y exige revisión humana. El archivo ausente, inválido o situado dentro del repositorio se rechaza sin credenciales de respaldo. Se conservan IDs, hashes, eventos y archivos; los IDs y timestamps iniciales se asignan localmente.

### Preparar nuevos accesos

Sólo el responsable de preparar una nueva demo debe generar un documento distinto. El [contrato de credenciales](CREDENCIALES_EVALUACION.md) contiene el comando y las validaciones: requiere un directorio externo existente y un archivo de salida inexistente, aplica permisos privados y no crea usuarios. La rotación de cuentas existentes es una operación separada, con IDs y fingerprint explícitos; no forma parte de una instalación limpia.

El bootstrap histórico de primer ADMIN está restringido a otra combinación de schema y revisión Alembic; no sustituye este procedimiento en una instalación nueva con `005`.

## 7. Iniciar backend

Terminal 1, desde la raíz:

```bat
cd api
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Mantenga un solo proceso API. No use `--workers` múltiples: los presupuestos globales de admisión y rate limiting son locales al proceso. `--reload` sólo sirve para desarrollo y reinicia presupuestos en memoria.

## 8. Iniciar frontend

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

El servidor integrado PHP es sólo para uso local. Para archivos de hasta 20 MiB, asegure margen multipart en `php.ini`, por ejemplo `upload_max_filesize=20M` y `post_max_size=22M`; reinicie PHP. La aplicación aplica además sus límites backend. La dirección de la API está en `frontend/config/config.php`, mediante `API_BASE_URL`; no es una variable de `.env`. Si cambia puertos, ajuste esa dirección y `PUBLIC_FRONTEND_URL` de forma coherente.

## 9. Verificar el funcionamiento

| Servicio | Dirección local |
|---|---|
| Interfaz PHP | http://127.0.0.1:8080 |
| Estado básico de la API | http://127.0.0.1:8000 |
| Swagger | http://127.0.0.1:8000/docs |
| Prefijo de endpoints | http://127.0.0.1:8000/api/v1 |

La raíz de la API sólo informa el estado básico; no sustituye la comprobación de MySQL mediante Alembic y la preparación del dataset. El prefijo `/api/v1` agrupa los endpoints, no es una pantalla de inicio.

Abra la interfaz e inicie sesión con las cuentas del documento privado. Cierre sesión entre comprobaciones:

- **ADMIN:** recorra dashboard, auditorías, Documento de Evidencia Demo, versiones, Hallazgo Demo, aprobaciones y análisis. Descargue el TXT sintético.
- **RESPONSABLE_AREA:** debe ver sólo Documento de Evidencia Demo y sus aprobaciones; puede cargar una nueva versión propia. Auditorías, hallazgos y solicitudes de acceso no están disponibles. Al abrir `index.php?pagina=auditorias`, el acceso debe rechazarse. Dashboard y análisis reflejan sus recursos autorizados.
- **AUDITOR_INTERNO:** compruebe el rol en la cabecera y la consulta de sus auditorías asignadas.
- **APROBADOR:** compruebe el rol y su ronda asignada. Una decisión requiere iniciar antes la ronda como ADMIN; consultar la ronda no cambia su estado.

Swagger es una herramienta técnica complementaria. En `POST /api/v1/auth/login` use la cuenta demo, luego Authorize con el token obtenido y consulte `GET /api/v1/auth/me` para comprobar el rol. No publique ni capture el token. Tras `POST /api/v1/auth/logout`, una consulta a `/api/v1/auth/me` con esa sesión debe responder 401.

## 10. Correo y servicios externos

**Correo no disponible en la demo:** están implementados el backend de recuperación, los tokens y controles de seguridad, la cola, el worker y la configuración SMTP. No se ha acreditado recepción real. El estado documentado sigue siendo `SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS`.

El recorrido local de login y documentos no requiere SMTP. La recuperación por correo y la activación tras aprobar una solicitud sí requieren proveedor SMTP configurado, worker y buzón autorizado. Las cuentas ficticias de evaluación no tienen buzón, incluso si se configura el proveedor.

La recepción de solicitudes y su revisión o rechazo por ADMIN están implementadas. Aprobar una solicitud prepara el correo inicial, pero no crea inmediatamente una cuenta: ésta se crea al confirmar el enlace válido y establecer la contraseña (`FULFILLED`). El reset revoca sesiones y encola un aviso. No existe registro público automático.

La [referencia SMTP](SMTP_RECUPERACION.md) explica los campos reales (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY`, remitente, timeout y `PUBLIC_FRONTEND_URL`) y la validación con un buzón autorizado. No existen `SMTP_ENABLED`, `SMTP_USER`, `SMTP_FROM` ni `SMTP_USE_TLS`; se utiliza `SMTP_SECURITY=starttls` o `ssl`. No publique secretos ni active debug SMTP.

Después de configurar el proveedor, ejecute desde la raíz, en otra terminal:

```bat
api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --max-jobs 20
```

Es un procesador por lotes, no un daemon. Ejecútelo después de solicitar recuperación o aprobar acceso; la operación continua requiere programarlo periódicamente. La cola utiliza leases, hasta tres intentos y backoff; los retries reemplazan tokens y pueden producir correos duplicados. `Trabajos procesados` no significa correos recibidos.

Turnstile es opcional y permanece deshabilitado en el recorrido local. Los límites locales de autenticación continúan activos. Para habilitarlo se necesitan claves y configuración externa; consulte [configuración](CONFIGURACION.md).

## 11. Pruebas automatizadas

Son opcionales para instalar y ejecutar la aplicación. Desde la raíz, en CMD:

```bat
api\venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-lock.txt
set PYTHONPATH=%CD%\api
set PYTHONDONTWRITEBYTECODE=1
api\venv\Scripts\python.exe -B -m pytest api/tests_unit -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_unit_nuevo
api\venv\Scripts\python.exe -B -m pytest frontend/tests -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_php_nuevo
```

Para MySQL real, la cuenta de pruebas debe poder crear y eliminar **schemas temporales aleatorios**; la cuenta limitada a `trazabilidad_evaluacion.*` no tiene esos privilegios. Use una identidad local de pruebas con ese permiso en el entorno del proceso; no amplíe los permisos de la identidad de ejecución. Los fixtures bloquean el engine de la base operativa:

```bat
set AUTH_MYSQL_TEST=1
set AUTH_BROWSER_TEST=1
api\venv\Scripts\python.exe -B -m pytest api/tests_auth_mysql -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_mysql_nuevo
```

`AUTH_BROWSER_TEST=1` activa Chrome instalado con perfil efímero; opcionalmente configure `CHROME_TEST_BINARY` y `PHP_TEST_BINARY`. Sin opt-in, los tests de navegador se omiten. Use una carpeta basetemp nueva y propia: pytest puede limpiar esa carpeta. **No ejecute `api/tests` contra la configuración operativa**: es una suite histórica con fixture antiguo. La regresión protegida de 6A es `api/tests_auth_mysql/test_6a_regression_mysql.py`. Las suites normales no contactan SMTP ni Turnstile reales.

Los resultados históricos de QA y de instalación desde un clone nuevo se conservan en el [informe de cierre](FASE_9_CIERRE_ENTREGA.md).

## 12. Almacenamiento y operación local

`storage/` permanece privado junto al proyecto. No lo sirva estáticamente ni coloque expedientes bajo `frontend/` o en Git. Las descargas pasan por la autorización de FastAPI y PHP. Mantenga permisos del operador, espacio disponible y soporte de hardlinks; no reubique archivos mediante enlaces. El límite predeterminado es de 20 MiB por archivo; PHP puede imponer uno menor.

La herramienta de integridad es de sólo lectura. Desde la raíz puede consultar sus opciones:

```bat
api\venv\Scripts\python.exe scripts/verificar_integridad.py --help
```

El [manual técnico](MANUAL_TECNICO.md) explica la comprobación de referencias, hashes y archivos, las herramientas de contraseñas y el respaldo coordinado de MySQL y storage. No hay backup automático. Una interrupción entre MySQL y el filesystem puede dejar archivos sin referencia; su reconciliación requiere revisión humana. No elimine archivos huérfanos ni datos históricos automáticamente.

El análisis documental 7E usa reglas deterministas y heurísticas de nombres; no analiza semánticamente el contenido ni requiere descargar Ollama, LLM o modelos entrenados. Sus límites y posibles resultados parciales se describen en las [reglas de análisis](EXPLICACION_ANALISIS_RULES.md). Las alertas del dashboard se muestran al consultarlo; no se envían automáticamente por correo.

## 13. Resolución de problemas

| Síntoma | Acción |
|---|---|
| `py` no existe | Instale Python 3.14 con launcher o use la ruta del intérprete 3.14 para crear el venv |
| No conecta a MySQL | Compruebe servicio, host/puerto, permisos y `.env`; descarte MariaDB |
| Alembic falla | Ejecute desde `api`, revise schema y usuario con DDL; no use `stamp` para ocultar migraciones faltantes |
| JWT inseguro | Genere un secreto aleatorio privado y reinicie backend |
| `.env` ausente | Copie `api/.env.example` a `api/.env`; los valores de ejemplo no bastan para iniciar de forma segura |
| Puerto 8000/8080 ocupado | Identifique el proceso dueño; detenga sólo su proceso o configure puertos y URL de forma coherente |
| PHP sin cURL/mbstring/fileinfo | Habilite la extensión en el `php.ini` de CLI (`php --ini`) y reinicie |
| PowerShell rechaza activación | Use directamente `api\venv\Scripts\python.exe`; para una ruta entre comillas utilice `&` |
| HTTP 503 en flujos de correo | Revise SMTP y URL; la entrega requiere ejecutar el worker. Consulte la cola sin exponer tokens |
| Seed devuelve conflicto o rechaza el archivo | Revise entorno, Alembic 005, ruta externa y contrato; no borre cuentas ni cambie atributos para forzar la ejecución |
| Error de storage o carga | Revise permisos, espacio, hardlinks y límites PHP/backend; no use enlaces hacia fuera |
| Análisis tarda o informa truncación | Consulte un documento concreto y revise los límites; no hay un modelo que descargar |
| HTTP 409 | Recargue el recurso y revise estado y versión antes de reintentar |

Para operación, seguridad y límites adicionales consulte el [manual técnico](MANUAL_TECNICO.md). No se ha realizado un despliegue de producción como parte del MVP local.
