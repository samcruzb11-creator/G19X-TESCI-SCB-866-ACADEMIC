# FASE 6C — Acceso, recuperación y login

Implementación sobre el working tree parcial recibido. Sin commit, push, cambios
a la BD de trabajo ni modificaciones a 001/002/003. No se activa Turnstile ni
infraestructura externa. El estado local 001 informado por el usuario no se migró.

## Auditoría inicial

| Área recibida | Diagnóstico | Tratamiento |
| --- | --- | --- |
| Estrategia B | Correcta: aprobación separada de creación de Usuario | Conservada |
| Solicitud pública | Campos cerrados, normalización, deduplicación y 202 | Conservada; corregida validación de longitud después de trim |
| ADMIN | Listado/detalle/aprobar/rechazar, actor autenticado y bloqueo | Conservados y probados; completado reenvío inexistente |
| Reset anti-relay | LOOKUP_RESET sin destinatario; salida desde Usuario.correo | Conservado y probado con inexistente/inactivo/collation |
| Confirmación | SHA-256, propósito, fingerprint, doble validación, Argon2 y revocación | Conservada; reforzados errores privados y consultas de cancelación |
| SMTP/retries | Cada retry emitía un token independiente todavía válido | Corregido: vínculo con job, reemplazo, vencimiento común y supersesión |
| Estado del envío | Un retry podía autorizar de nuevo credenciales ya cambiadas | Fingerprint persistido también en job; cambio cancela el envío |
| TTL inicial | Dependía de configuración de reset | INITIAL_PASSWORD fija 1800 segundos |
| Migración 004 | Cuatro tablas aisladas, dependencia 003; sin validación real todavía | Ampliadas restricciones/FK/índices; ciclo real en MySQL temporal |
| PHP/layout/SVG | Layout local, CSRF y JWT en servidor ya encaminados | Conservados; completados reenvío, errores y protección del fragmento |
| Pruebas 6C/documentación | Ausentes | Añadidas |

La aprobación no crea una cuenta deshabilitada ni una contraseña temporal. Solo
persiste una autorización; sin consumir INITIAL_PASSWORD no existe el Usuario.

## Contratos y autorización

| Método/ruta API | Acceso | Resultado |
| --- | --- | --- |
| POST /api/v1/auth/access-requests | Público | 202 uniforme; nombre, correo, motivo |
| POST /api/v1/auth/password-reset/request | Público | 202 uniforme; correo como identificador |
| POST /api/v1/auth/password-reset/confirm | Público, token | Nueva contraseña; sin sesión |
| POST /api/v1/auth/initial-password/confirm | Público, token | Creación final de Usuario; sin sesión |
| GET /api/v1/access-requests | ADMIN | Pendientes por defecto; filtros y paginación |
| GET /api/v1/access-requests/{id} | ADMIN | Detalle/resolución |
| POST /api/v1/access-requests/{id}/approve | ADMIN | Rol explícito obligatorio |
| POST /api/v1/access-requests/{id}/reject | ADMIN | Motivo administrativo opcional |
| POST /api/v1/access-requests/{id}/resend | ADMIN | Solo autorizaciones APPROVED sin Usuario |

Otros roles autenticados reciben 403; sin sesión válida, 401. ADMIN se obtiene de
`current_user.id` y se vuelve a validar activo/rol bajo bloqueo antes de resolver.
Los campos públicos adicionales de rol, permisos, password o actor son rechazados.
PHP construye payloads permitidos; los hidden inputs solo indican acción/CSRF.

Una solicitud duplicada equivalente por `utf8mb4_unicode_ci` conserva el registro
original y devuelve el mismo 202. No sobrescribe nombre, motivo ni resolución.
Una solicitud rechazada no se reabre automáticamente por otro POST público.

La resolución guarda estado, administrador, UTC y rol aprobado. Dos resoluciones
simultáneas se serializan por solicitud: una confirma y otra recibe 409.
La unicidad del correo en usuarios sigue siendo el árbitro final del alta.

## Migración 004

Snapshot DDL independiente de modelos en tiempo de ejecución, revisión 004 con
`down_revision = "003"`. Crea únicamente:

- `access_requests`: identificador único con collation explícita, nombre/motivo,
  estado, resolución, rol y referencia al Usuario final. CHECK de roles/estados y
  coherencia de resolución; FKs a usuarios con RESTRICT.
- `auth_action_limits`: clave `(action, identifier)`, inicio/conteo/vencimiento;
  collation explícita e índice de expiración.
- `auth_mail_jobs`: tipo, identificador de búsqueda o sujeto autorizado,
  destinatario, fingerprint, vencimiento común, estado, intentos, lease y agenda.
  CHECK impide recipient en LOOKUP_RESET y exige sujeto/fingerprint en outbound.
  Índices de disponibilidad, lease, fecha y `(kind, identifier)`.
- `auth_action_tokens`: hash binario SHA-256 como PK, propósito, job obligatorio,
  sujeto exclusivo, fingerprint, creación, expiración y `consumed_at`.
  CHECK liga INITIAL_PASSWORD a solicitud y PASSWORD_RESET a Usuario.

Todas usan InnoDB; tiempos DATETIME(6) UTC. `consumed_at` representa consumo o
invalidación: cualquier valor impide usar el token. Downgrade elimina las cuatro
tablas en orden de dependencias; pierde únicamente información de 6C.

El fixture crea `sistema_trazabilidad_test_auth_<16 hex aleatorios>`, verifica que
no exista, rechaza el nombre de la BD de trabajo, verifica DATABASE() en cada
checkout y elimina solo su propio esquema. Conserva snapshots DDL/filas de todas
las tablas 003 durante `003 -> 004 -> 003 -> 004`. 001/002/003 permanecen intactas.
Las regresiones 6A históricas se importan en ese fixture; no se ejecutan contra
el esquema de pruebas fijo ni contra la BD de trabajo.

## INITIAL_PASSWORD

1. ADMIN aprueba rol y datos; una transacción registra resolución y job autorizado.
2. El CLI bloquea brevemente solicitud/job, revalida APPROVED y ausencia de Usuario.
3. Genera `secrets.token_urlsafe(32)` (256 bits), persiste solo SHA-256 y fingerprint,
   con TTL fijo de 30 minutos desde la primera preparación. Cierra la transacción.
4. SMTP recibe el enlace; nunca se transporta una contraseña temporal.
5. Confirmación valida token/propósito/vencimiento/consumo/estado antes de Argon2.
6. Argon2 se calcula sin transacción. Bajo bloqueo final se revalida todo, se crea
   Usuario con nombre/correo/rol aprobados y hash Argon2id, se marca FULFILLED y se
   invalidan tokens/jobs pendientes de esa autorización, todo atómicamente.

No hay autologin ni JWT emitido al confirmar. Si vence, ADMIN puede reenviar;
aprobar/rechazar/reenviar no permite al solicitante elegir privilegios.

## PASSWORD_RESET y prueba anti-email-relay

El request normaliza/valida, aplica presupuestos y crea únicamente LOOKUP_RESET.
No consulta usuarios, no tiene recipient, no genera token y no abre SMTP. Su
respuesta admitida siempre es:

> Si el correo corresponde a una cuenta habilitada, recibirás instrucciones para restablecer tu contraseña.

No depende de la disponibilidad/configuración SMTP; el trabajo queda durable.
Validación devuelve 422, presupuesto agotado 429 con Retry-After y falla operativa
503 saneado, independientes de existencia/rol/estado/entrega de una cuenta.

El worker busca por `Usuario.correo_normalizado`, comprueba actividad y solo
entonces crea PASSWORD_RESET. El destinatario se toma **exclusivamente de
Usuario.correo**, también al preparar cada envío. Un recipient adulterado en un
job no se reutiliza. El identificador público nunca pasa al envelope SMTP.

`correo-no-registrado@example.com`: 202 idéntico, cero tokens, cero recipient,
cero salida SMTP y cero jobs outbound. Solo queda el trabajo de búsqueda DONE.
Una cuenta inactiva produce el mismo resultado. Un input `jOsÉ@example.invalid`
que resuelve `Jose@Example.invalid` bajo collation usa exactamente el segundo
correo como destinatario; no sustituye la dirección canónica por el input.

Confirmación acepta 12–1024 caracteres. La transacción final revalida propósito,
hash, expiración, consumo, actividad y fingerprint; actualiza password_hash,
invalida todos los tokens PASSWORD_RESET, cancela trabajos pendientes asociados y
revoca **todas** las auth_sessions del usuario. Encola aviso PASSWORD_CHANGED sin
token. No crea sesión. La carrera con login usando la contraseña anterior también
falla por la revalidación del hash que ya existía en 6B.

El fingerprint del Usuario incluye id, hash de contraseña, correo canónico,
correo normalizado, actividad y updated_at. Cambios por la CLI existente, cambio
de correo, desactivación o desactivar/reactivar invalidan tokens y retries.
Cambios adicionales que actualicen updated_at invalidan conservadoramente el enlace.

## Semántica definitiva de correo y reintentos

La idea anterior de enlaces independientes por retry se eliminó porque dejaba
varios enlaces utilizables sin una relación durable con la operación de envío.

- Cada operación outbound conserva su sujeto y fingerprint. Cada token referencia
  ese job por FK; el token original en claro vive solo en memoria y en el correo.
- Claim con FOR UPDATE SKIP LOCKED, lease CSPRNG de 128 bits, vigencia 120 segundos
  e incremento de intentos confirmado antes de trabajar. Los workers pueden ser
  concurrentes; no necesitan compartir el presupuesto en memoria del API.
- Máximo **3 intentos totales**, con reintentos disponibles tras 30 y 60 segundos.
  Se abandona trabajo de enlaces con antigüedad superior a una hora; avisos, 24 h.
- Un retry invalida los tokens anteriores de su job antes de crear el siguiente,
  dentro de la misma transacción y bajo el bloqueo del sujeto. Todos conservan el
  mismo vencimiento inicial: los reintentos no extienden el TTL.
- Una nueva operación del mismo sujeto/propósito cancela trabajos anteriores e
  invalida sus tokens. Una finalización con lease antiguo no puede revivirlos.
- Un cambio de credenciales/estado cancela el retry; no se autoriza nuevamente
  con las credenciales nuevas. Un job vencido no genera otro token.
- SMTP está fuera de request, sesiones SQL y locks. SSL o STARTTLS obligatorio,
  certificados verificados y timeout de socket de 1–10 s (default 5).

No se promete exactly-once SMTP. Un servidor puede aceptar el mensaje y perderse
la respuesta. Si hay retry, el enlace anterior queda inválido aunque llegue más
tarde. Tras el último fallo incierto, el último enlace puede seguir válido hasta
su vencimiento común, pues pudo entregarse. Siempre queda como máximo un enlace
utilizable por sujeto/propósito; un correo tardío nunca vuelve válido un token
consumido, sustituido o ligado a credenciales antiguas.

Una desactivación posterior a la preparación no puede retirar un correo ya en
vuelo, pero la revalidación de actividad/fingerprint impide consumir su enlace.
No hay transacción abierta esperando al SMTP para intentar evitar esa carrera.

## Límites separados de login

| Acción | Identificador durable | Global por proceso API |
| --- | --- | --- |
| Reset request | 3/h | 20/min |
| Access request | 2/día | 10/min |
| Confirmación reset | 5/min por SHA-256 del token | 30/min compartidos con inicial |
| Confirmación inicial | 5/min por SHA-256 del token | mismo presupuesto de confirmación |
| Hash nuevo Argon2 | — | 5/min; concurrencia 1 |
| Aprobación/reenvío inicial | 3/h por identifier, incluyendo aprobación | 20/min compartidos |

Los settings permiten reducir estos máximos, no elevarlos. El presupuesto global
se aplica antes de parsear el body; incluye variantes de ID y slash final.
Ventanas globales móviles con reloj monotónico; ventanas durables fijas con UTC
de MySQL y collation, sin consultar existencia para decidir el bucket.

**Un único proceso/instancia FastAPI**, como en 6B.4A. Un reinicio pierde ventanas
globales, pero no los buckets MySQL. No usar múltiples API workers suponiendo
límites globales compartidos. No se confía en X-Forwarded-For, X-Real-IP ni
CF-Connecting-IP. ADMIN tiene exactamente las mismas restricciones pertinentes.

## Navegador y PHP

El enlace es `PUBLIC_FRONTEND_URL/index.php?pagina=...#token=...`. El fragmento
no viaja en HTTP. JS local lo lee, aplica history.replaceState, carga únicamente
la propiedad value del campo password del código y lo borra en pagehide.
No se escribe en HTML serializado, sesión PHP, localStorage ni sessionStorage.
Un error obliga a pegar el código de nuevo o reabrir el correo; no se refleja.

Sin JS se ofrece en el correo un enlace alternativo **sin fragmento** para pegar
el código y enviarlo por POST. No se pretende borrar un fragmento con JS desactivado;
la alternativa exige usar ese enlace limpio, como indican correo y pantalla.

Pantallas auth y respuestas API privadas: no-store. Pantallas auth: no-referrer,
CSP local con form-action self, sin analytics ni recursos externos. Formularios
PHP con CSRF, valores escapados y rutas permitidas. Tras éxito se rota la sesión
PHP, se borra su contexto anterior y se redirige a login. JWT sigue server-side.

Layout conservado: formulario máximo 410 px, dos columnas, hero SVG original
local, colores sobrios; una columna y formulario prioritario en móvil. Labels,
autocompletes, foco visible, skip link y teclado. Validado en Chrome real a
1440, 390 y 320 px; sin overflow horizontal y con foco correo -> contraseña.

## Configuración y operación

Variables privadas documentadas en `api/.env.example`: SMTP_HOST, SMTP_PORT,
SMTP_USERNAME, SMTP_PASSWORD (SecretStr), SMTP_SECURITY, SMTP_FROM_ADDRESS,
SMTP_FROM_NAME, SMTP_TIMEOUT_SECONDS, PUBLIC_FRONTEND_URL y PASSWORD_RESET_TTL_SECONDS.

PUBLIC_FRONTEND_URL es el directorio fijo del frontend. Rechaza userinfo, query,
fragmento incluso vacío, backslash, controles y puertos inválidos. HTTPS salvo
localhost/127.0.0.1/::1 en development. Nunca depende de Host ni headers proxy.

Después del despliegue autorizado y configuración privada, el operador puede
programar el procesador mediante su planificador local (no se programó aquí):

```powershell
# Desde la raíz, únicamente cuando la BD de destino ya tenga 004 revisada/aplicada.
.\api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --max-jobs 20
```

Acepta 1–100 jobs por ejecución. Un contador procesado no significa entregado.
El CLI y el boundary de rutas suprimen detalles de excepciones SMTP/SQL: nunca
imprimen destinatarios, tokens, contraseñas ni parámetros. No activar logging de
cuerpos de autenticación ni debug SMTP en el despliegue.

## Autoauditoría y regresiones

Ataques cubiertos: enumeration, reset inexistente/inactivo, collation, arbitrary
recipient, role/actor injection, replay, confusión de propósito, aprobación doble,
consumo doble, claim doble, reinicio tras preparación, lease obsoleto, entrega
incierta, cambio externo de credenciales, revocación incompleta, carrera con login,
CSRF, XSS, fijación de sesión, Host poisoning, bypass de presupuestos, tokens en
DB/HTML/URL/logs, Argon2/SMTP dentro de transacción y SMTP síncrono en request.

Correcciones adicionales verificadas:

- Empty command PHP se serializa como `{}`; `[]` impedía usar reenvío real.
- Los errores 6C se convierten en HTTP saneado antes de llegar al logger del servidor.
- Cancelación de jobs por predicados separados e indexados evita un OR amplio
  que podría bloquear jobs de otros usuarios.
- El fixture SQLite de RBAC copiaba ahora las nuevas tablas MySQL, fallando por
  collation. Conserva su alcance original excluyendo tablas de autenticación,
  igual que hacía con 6B. No se omitió ninguna prueba RBAC ni se simuló collation:
  6C se prueba en MySQL real y RBAC también mantiene su regresión MySQL completa.

Comandos reproducibles desde api, con directorios temporales nuevos por ejecución:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$testTemp = Join-Path $env:TEMP ('trazabilidad-6c-unit-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest tests_unit -q -p no:cacheprovider -o addopts= --basetemp=$testTemp
$env:AUTH_MYSQL_TEST='1'
$testTemp = Join-Path $env:TEMP ('trazabilidad-6c-mysql-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest tests_auth_mysql -q -p no:cacheprovider -o addopts= --basetemp=$testTemp
$testTemp = Join-Path $env:TEMP ('trazabilidad-6c-php-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest ../frontend/tests --ignore=../frontend/tests/test_auth_browser.py -q -p no:cacheprovider -o addopts= --basetemp=$testTemp
$env:AUTH_BROWSER_TEST='1'
$testTemp = Join-Path $env:TEMP ('trazabilidad-6c-browser-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest ../frontend/tests/test_auth_browser.py -q -p no:cacheprovider -o addopts= --basetemp=$testTemp
```

El navegador usa un perfil desechable y PHP aislado en loopback. En el sandbox
Windows se bloqueó el proceso gráfico; pasó al ejecutarlo con el permiso requerido
fuera del sandbox. Ninguna prueba envía correo de Internet: SMTP está sustituido
o bloqueado explícitamente por fixture.

## Resultado de validación

Validación final del código (2026-10-01, hora local): **619 pruebas aprobadas**.

| Suite | Existentes conservadas | Nuevas 6C | Total aprobado |
| --- | ---: | ---: | ---: |
| Unitarias API | 215 | 81 | 296 |
| MySQL temporal, incluidas regresiones 6A–6B.4A y PHP/FastAPI/MySQL | 139 | 85 | 224 |
| PHP HTTP/JavaScript | 63 | 35 | 98 |
| Chrome headless real | 0 | 1 | 1 |
| Total | 417 | 202 | 619 |

47 archivos PHP pasan `php -l`. `git diff --check` sin errores. MySQL 8.0.46:
ciclo `001 -> 002 -> 001 -> 002 -> 003 -> 002 -> 003 -> 004 -> 003 -> 004`
ejecutado en esquema aleatorio, con preservación comprobada de DDL/filas anteriores.
Los fixtures eliminan sus esquemas al terminar, incluso si falla una aserción.
No hubo envío SMTP real, migración de la BD local, commit ni push.

## Límites operativos y deuda

No hay funciones 6C pendientes de implementación conocidas. El despliegue real
requiere revisar/aplicar migraciones 002–004, configurar SMTP/URL y programar el
CLI; deliberadamente no se realizaron esas operaciones sobre el sistema local.
La política y automatización de purga de históricos 6C (jobs, tokens vencidos,
buckets y solicitudes) queda como deuda operativa: actualmente se conservan.
No afecta expiración, uso único ni topes de intentos, pero requiere gestionar
retención y volumen de datos antes de una operación prolongada.

Permanecen las restricciones ya documentadas: un solo proceso API para presupuestos
globales, disponibilidad limitada ante consumo malicioso de cupos y ausencia de
garantía exactly-once en SMTP. Hay dos avisos de deprecación Starlette/httpx/AnyIO
del entorno existente; no se cambiaron dependencias para ocultarlos.
