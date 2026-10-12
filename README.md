# Sistema de Trazabilidad Documental para Auditorías

Aplicación local que organiza documentos, versiones, evidencias y hallazgos de auditoría, registra quién realiza cada operación y permite revisar aprobaciones, indicadores y anomalías documentales.

## Objetivo

Mantener un expediente verificable durante el ciclo de auditoría: responsables, archivos con SHA-256, versiones históricas, decisiones y eventos. El proyecto corresponde a la residencia profesional de Samuel Cruz Barrientos, Ingeniería en Sistemas, Tecnológico de Estudios Superiores de Cuautitlán Izcalli / TecNM, con PluriOne S.A. de C.V. / Develop Talent & Technology, septiembre de 2026 a enero de 2027.

## Funcionalidades y estado

MVP funcional local: autenticación, sesiones revocables, RBAC, solicitudes de acceso revisadas por ADMIN, backend de recuperación de contraseña, auditorías, documentos/versiones, evidencias, hallazgos, aprobaciones por versión, dashboard y análisis determinista explicable. No existe registro público automático.

**Correo no disponible en la demo:** están implementados los tokens y controles de seguridad, la cola de correo, el worker y la configuración SMTP. El envío real requiere un proveedor SMTP externo configurado, ejecutar el worker y un buzón autorizado; no se ha demostrado correo real recibido. Las cuentas ficticias de evaluación no tienen buzón y no pueden completar la recuperación por correo.

Fase 8 tiene QA documentada sobre `d54a81e`. La auditoría final independiente de Fase 9.2 aprobó la release, según el dictamen comunicado. La entrega corresponde a evaluación local y no implica un servicio de producción alojado.

## Arquitectura

```text
Navegador -> PHP (sesión, CSRF, presentación)
                  -> FastAPI (JWT, RBAC, reglas y eventos)
                       -> MySQL 8 (metadatos y trazabilidad)
                       -> storage/ (archivos con SHA-256)
Worker Python -> cola MySQL -> SMTP TLS -> correo del destinatario
```

PHP no accede directamente a MySQL. JWT permanece en la sesión PHP del servidor. El almacenamiento no se expone como directorio web.

## Stack verificado

Python 3.14, FastAPI, Uvicorn, SQLAlchemy, PyMySQL, Alembic y MySQL 8/InnoDB; PHP, HTML, CSS y JavaScript. Argon2id para contraseñas, JWT y SHA-256. XAMPP sirve como distribución local de PHP, no como sustituto MySQL mediante MariaDB.

## Estructura del repositorio

```text
api/app/              routers, schemas, modelos, servicios y herramientas explícitas
api/app/db/migrations revisiones Alembic 001–005
api/tests_unit/       pruebas aisladas
api/tests_auth_mysql/ integración MySQL efímera y E2E
frontend/             interfaz PHP, cliente API y tests
scripts/              operación: bootstrap, contraseña, correo, pruning, integridad
docs/                 manuales, requisitos, evidencia y fases históricas
storage/              archivos privados locales (ignorado en Git)
requirements.txt      dependencias runtime
requirements-lock.txt snapshot runtime verificado de evaluación
requirements-dev.txt  herramientas de pruebas
MVP.md                alcance mínimo entregado a TODO Academy
```

## Roles

| Rol | Alcance real |
|---|---|
| ADMIN | Visibilidad global y gestión de operaciones existentes; revisa solicitudes; no reescribe versiones/eventos ni suplanta decisiones |
| AUDITOR_INTERNO | Auditorías donde es responsable; puede crearlas para sí; hallazgos y rondas dentro de su alcance |
| AUDITOR_EXTERNO | Lee sus auditorías y registra evidencias en ese alcance; sin gestión de hallazgos/rondas |
| RESPONSABLE_AREA | Documentos propios, cargas/versiones, consulta de sus rondas, dashboard/análisis restringidos; sin acceso a auditorías/hallazgos |
| APROBADOR | Versiones y rondas asignadas; decide con su identidad mientras la decisión está pendiente |

La matriz completa está en [Permisos](docs/MATRIZ_PERMISOS.md). ADMIN administra acceso mediante solicitudes y herramientas locales: no existe CRUD HTTP de usuarios ni áreas. La herramienta de contraseña modifica sólo una identidad confirmada y revoca sus sesiones. No hay endpoint de cambio de rol de usuario ni borrado general.

## Requisitos

Git; Python 3.14 de 64 bits; MySQL 8 con InnoDB, UTF-8 y UTC; PHP 8.1+ con cURL, mbstring, fileinfo, OpenSSL y sesiones; filesystem que permita hardlinks (NTFS/ext4). Chrome sólo para pruebas browser. Se necesita acceso a PyPI para instalar paquetes y permisos locales para crear un schema vacío.

## Instalación desde cero

Comandos CMD desde una carpeta de su elección:

```bat
git clone https://github.com/samcruzb11-creator/G19X-TESCI-SCB-866-ACADEMIC.git
cd G19X-TESCI-SCB-866-ACADEMIC
py -3.14 -m venv api\venv
api\venv\Scripts\activate
python -m pip install -r requirements.txt -c requirements-lock.txt
python -m pip check
copy api\.env.example api\.env
```

En PowerShell puede usar el ejecutable `api\venv\Scripts\python.exe` directamente. Los pasos detallados, SQL y verificación se encuentran en [Guía de instalación](docs/GUIA_INSTALACION.md).

## Configuración `.env`

En `api/.env` configure host/puerto/schema/usuario/contraseña MySQL y un `JWT_SECRET_KEY` aleatorio privado. Para HS256:

```bat
api\venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Guarde ese resultado sólo en `.env`; no lo publique. El placeholder impide startup. `APP_ENV=development`, `TURNSTILE_MODE=disabled` y `PUBLIC_FRONTEND_URL=http://127.0.0.1:8080` sirven para evaluación local. No copie secretos de otra instalación. Variables del proceso prevalecen sobre dotenv. La [referencia de configuración](docs/CONFIGURACION.md) distingue obligatorio, opcional y producción.

## Crear MySQL

Use MySQL 8 real, no el MariaDB de XAMPP. En una consola SQL administrativa, para una instalación nueva:

```sql
CREATE DATABASE trazabilidad_evaluacion CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'trazabilidad_local'@'127.0.0.1' IDENTIFIED BY '<CONTRASENA_DB_PRIVADA>';
GRANT ALL PRIVILEGES ON trazabilidad_evaluacion.* TO 'trazabilidad_local'@'127.0.0.1';
```

Sustituya el marcador por su secreto local. Configure `DB_NAME=trazabilidad_evaluacion`, `DB_USER=trazabilidad_local`, `DB_HOST=127.0.0.1` y el password privado en `.env`. No dependa de un dump personal. Para pruebas MySQL, use otra identidad autorizada a crear/eliminar schemas temporales; no conceda ese permiso a la aplicación en producción.

## Migraciones Alembic

Desde raíz, con venv activado:

```bat
cd api
python -m alembic upgrade head
python -m alembic current
```

El head esperado es **005**. No hay migración 006 de Fase 9. No use `stamp` para sustituir la creación real de tablas. El bootstrap personal histórico puede operar en instalaciones existentes; la demo se crea directamente después de 005.

## Cuentas demo y dataset con archivo privado

GitHub contiene únicamente código y documentación pública. Edgar recibe **por separado**, mediante Accesos de prueba de TODO Academy, `01_ACCESOS_PRUEBA.md` con las cuatro cuentas. Guarde ese archivo en `%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md`, fuera del clone. Si usa otra ubicación externa, sustituya únicamente esa ruta en los comandos. No copie el documento al repositorio ni genere otras contraseñas para evaluar esta entrega.

Desde `api`, con el venv activado:

```bat
python -m app.scripts.seed_evaluation_demo --with-dataset
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

El primer comando sólo muestra el plan. Los dos siguientes deben informar cuatro cuentas nuevas y después cero. El seed crea exactamente las identidades y contraseñas del documento privado; la segunda ejecución conserva IDs, hashes, eventos y archivos. Un archivo ausente/inválido, un rol inesperado o una identidad existente diferente aborta sin sobrescrituras. No existe fallback ni generación silenciosa.

Guardas: `APP_ENV=development`, MySQL 8 loopback, Alembic 005, named lock compartido con rotación y transacción. No hay auto-seed en startup. Sin `--with-dataset`, crea cuentas y área. Roles: ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO y APROBADOR. Permisos en [matriz](docs/MATRIZ_PERMISOS.md).

El dataset incluye dos auditorías, dos documentos (uno propio y otro para probar IDOR), TXT con versión/hash, hallazgo con nota y aprobación pendiente. Los vínculos documento–auditoría se provisionan en el seed; no existe una operación HTTP general para crearlos.

El [contrato público](docs/CREDENCIALES_EVALUACION.md) define el bloque `evaluation-credentials-v1` del Markdown privado, sus validaciones, generación opt-in y rotación separada. El evaluador que recibió el documento **no ejecuta el generador**. Sólo el responsable de preparar una nueva entrega puede generar un archivo externo inexistente:

```bat
python -m app.scripts.evaluation_credentials --confirm-generate --output "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

El generador usa `secrets`, UTF-8 y ACL restringida en Windows; no imprime credenciales, no sobrescribe archivos y no crea usuarios. La rotación requiere IDs explícitos, contrato anterior privado, plan/fingerprint y `--confirm-rotate-demo`; conserva actores y registros históricos. No es parte de una instalación limpia.

## Backend

Terminal 1, desde raíz:

```bat
cd api
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Un solo proceso. Los presupuestos globales de seguridad y admisión son locales al proceso. No configure múltiples workers sin diseñar un presupuesto compartido.

## Frontend

Terminal 2, desde raíz:

```bat
C:\xampp\php\php.exe -S 127.0.0.1:8080 -t frontend
```

Alternativa con PATH: `php -S 127.0.0.1:8080 -t frontend`. En PowerShell use `& 'C:\xampp\php\php.exe' -S 127.0.0.1:8080 -t frontend`. La API default se fija en `frontend/config/config.php`. No cree `.env` bajo el directorio web. El servidor integrado PHP es sólo local; sus límites de carga pueden ser menores que los de FastAPI.

## Ejecución y URLs

```text
clone -> venv -> requirements -> .env -> MySQL -> Alembic -> seed demo -> FastAPI -> PHP -> login
```

| Servicio | URL default |
|---|---|
| Interfaz de usuario | http://127.0.0.1:8080 |
| API/estado básico | http://127.0.0.1:8000 |
| Swagger técnico | http://127.0.0.1:8000/docs |
| Endpoints | http://127.0.0.1:8000/api/v1 |

Abra frontend como ADMIN, consulte el expediente demo y cierre sesión. Repita como RESPONSABLE_AREA: sólo un documento propio y ninguna administración global. Swagger complementa la revisión técnica; no es la interfaz principal.

Después, inicie sesión con las otras dos cuentas del documento privado. La cabecera debe mostrar respectivamente AUDITOR_INTERNO y APROBADOR; el primero consulta sus auditorías asignadas y el segundo su ronda de aprobación asignada. Cierre sesión entre cuentas. En Swagger, `/api/v1/auth/me` confirma el rol de la sesión autenticada; nunca capture ni publique el token. La raíz API `/` es el endpoint público de estado básico; no sustituye la comprobación MySQL de Alembic y del seed.

## SMTP y worker

SMTP genérico ya implementado; no hay proveedor hardcodeado. Nombres reales: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY=starttls|ssl`, `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME`, `SMTP_TIMEOUT_SECONDS`, `PUBLIC_FRONTEND_URL`. No se usan `SMTP_ENABLED`, `SMTP_USER`, `SMTP_FROM` ni `SMTP_USE_TLS`.

Sin host/configuración válida, los flujos que requieren correo responden indisponibilidad. No active debug SMTP. Desde raíz, terminal 3:

```bat
api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --max-jobs 20
```

Es un procesador **por lotes**, no un daemon. Ejecútelo después de solicitar recuperación o aprobar acceso; prográmelo periódicamente si opera el sistema continuamente. El contador significa trabajos procesados, no correos entregados. La cola aplica leases, tres intentos, backoff y tokens reemplazados en retries. SMTP real está **SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS** en esta entrega. [Procedimiento exacto y validación](docs/SMTP_RECUPERACION.md).

## Recuperación y solicitud de acceso

Login ofrece Recuperar contraseña y Solicitar acceso. Solicitud → revisión ADMIN → aprobación/rechazo → correo inicial → contraseña → creación/activación de cuenta al confirmar el enlace (`FULFILLED`). Aprobar por sí solo no crea inmediatamente una cuenta. Los tokens expiran, tienen propósito, se almacenan como SHA-256 y se consumen una sola vez. Reset revoca sesiones y encola aviso de cambio. Las respuestas públicas son genéricas; SMTP habilitado es requisito para el recorrido completo.

## Pruebas actuales

Desde raíz, CMD:

```bat
api\venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c requirements-lock.txt
set PYTHONPATH=%CD%\api
set PYTHONDONTWRITEBYTECODE=1
api\venv\Scripts\python.exe -B -m pytest api/tests_unit -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_unit_nuevo
api\venv\Scripts\python.exe -B -m pytest frontend/tests -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_php_nuevo
set AUTH_MYSQL_TEST=1
set AUTH_BROWSER_TEST=1
api\venv\Scripts\python.exe -B -m pytest api/tests_auth_mysql -q -p no:cacheprovider --basetemp=%TEMP%\trazabilidad_mysql_nuevo
```

MySQL requiere identidad de pruebas con CREATE/DROP schema local y Chrome para browser opt-in. Use carpetas basetemp nuevas y propias. Los fixtures guardan un schema aleatorio distinto de la BD operativa. No ejecute directamente la suite histórica `api/tests`: su regresión segura es `api/tests_auth_mysql/test_6a_regression_mysql.py`. No se contacta SMTP ni Turnstile real en las suites normales.

Baseline histórico Fase 8: **1,212 unit, 1,138 MySQL y 312 frontend**, cero fallos/skips finales; 2,662 ejecuciones, 1,937 contratos distintos. Son cifras del checkpoint, no garantía de los conteos futuros. Fase 9 y fresh clone se registran en [Informe de cierre](docs/FASE_9_CIERRE_ENTREGA.md).

## Seguridad

Argon2id, JWT de 15 minutos con sesión revocable MySQL, rol/actividad comprobados server-side, scopes SQL antes de paginar y controles de actor autenticado. PHP aplica CSRF, cookies HttpOnly/SameSite, escaping y conserva JWT fuera del navegador. Login/reset/acceso tienen rate limiting y presupuestos de Argon2; Turnstile es una segunda capa **opcional**, deshabilitada explícitamente en la demo local.

SHA-256 identifica integridad de archivos, no acredita por sí solo autoría o cumplimiento. Path hardening bloquea escape de storage; uploads son streaming con límites; body limits protegen recepción; eventos se registran con operaciones de dominio. Bloqueos/concurrencia y DB admission limitan trabajo compartido. ADMIN no dispone de operaciones HTTP para reescribir hashes, eventos, versiones o decisiones cerradas. Esto no elimina el poder de una cuenta SQL/filesystem externa: gestione sus privilegios y backups.

## Almacenamiento e integridad

`storage/` privado junto al proyecto; no se sirve estáticamente. Versiones/evidencias FILE se descargan mediante FastAPI y PHP con autorización. El default es 20 MiB por archivo; PHP añade límites propios. El filesystem debe admitir hardlinks. `STORAGE_PATH` no redirige la raíz real. No copie expedientes privados al repo.

La herramienta [verificar_integridad.py](scripts/verificar_integridad.py) es de sólo lectura. Desde raíz consulte `api\venv\Scripts\python.exe scripts/verificar_integridad.py --help` y [Manual técnico](docs/MANUAL_TECNICO.md). No borra huérfanos. Backup requiere DB y storage coordinados.

## Dashboard y análisis documental

Dashboard 7D deriva indicadores, alertas y actividad mediante SQL sobre recursos autorizados. No fabrica ceros cuando la API falla; ratios sin denominador se representan como ausencia de datos. Las alertas se muestran al consultar el dashboard; no se envían automáticamente por correo.

7E es un **motor determinista y explicable**: reglas de anomalías, duplicados por hash, metadatos/versionado y similitud heurística acotada de nombres. No analiza semánticamente el contenido de documentos ni utiliza Ollama, IA generativa, LLM, machine learning o modelos entrenados. Los detalles informan límites/truncación; no garantizan detectar cualquier irregularidad ni todos los documentos faltantes y no constituyen una certificación de auditoría. Una eventual IA local sería una ampliación separada y condicionada a un requerimiento explícito.

## Limitaciones y deuda conocida

Posible huérfano tras interrupción abrupta en la ventana DB/filesystem; reconciliación humana read-only. 7E limita candidatos/storage y el análisis global puede tardar bajo concurrencia extrema. Persisten deprecaciones menores conocidas de librerías de pruebas. No hay CRUD web general de usuarios/áreas, comando HTTP de asociación documento–auditoría, refresh token, hosting productivo ni backup automático. Estado `CANCELLED` existe en DDL de auditorías, pero no se ofrece como transición en el router actual. Preserve datos legacy; no haga limpieza automática.

## Troubleshooting

| Problema | Qué comprobar |
|---|---|
| MySQL no corre | Servicio MySQL 8, puerto, credenciales/schema; descarte MariaDB |
| 8000/8080 ocupado | Identifique proceso dueño; use puertos libres y ajuste URLs coherentemente |
| `.env` ausente/JWT inválido | Copie ejemplo, configure DB y genere secreto privado; reinicie |
| Migraciones | Ejecutar desde `api`, cuenta con DDL y head 005 |
| XAMPP/PHP | Ruta CLI correcta y extensiones; en PowerShell usar `&` |
| SMTP deshabilitado | Completar campos privados y ejecutar worker por lotes |
| Modelo/análisis | No existe modelo; revisar alcance, truncación y consultas de detalle |
| Storage sin permisos | Acceso NTFS y hardlinks; no reubicar mediante enlaces ni borrar datos |

Más casos en [Guía de instalación](docs/GUIA_INSTALACION.md).

## Documentos y uso académico

[Índice documental](docs/README.md), [MVP](MVP.md), [PRD](docs/PRD.md), [Documento técnico](docs/DOCUMENTO_TECNICO.md), [Manual técnico](docs/MANUAL_TECNICO.md), [Manual de usuario](docs/MANUAL_USUARIO.md), [Bitácora](docs/BITACORA.md), [Evidencia](docs/EVIDENCIA_PROYECTO.md).

No se encontró una licencia de distribución en el baseline. El uso académico documentado no concede por sí mismo permisos generales de redistribución. Una decisión de licencia debe ser explícita del titular; esta fase no la inventa. Los PDFs/DOCX finales se entregan fuera de Git en la carpeta específica de Descargas y sus Markdown son la fuente versionable.
