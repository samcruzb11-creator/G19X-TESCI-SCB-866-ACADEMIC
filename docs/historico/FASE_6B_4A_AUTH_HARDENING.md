# FASE 6B.4A — Hardening local de autenticación

## Alcance

FastAPI conserva JWT de 900 segundos, SID de 256 bits, Argon2id, sesiones
revocables y RBAC. PHP conserva JWT solo en sesión del servidor y CSRF.
No hay registro público, refresh tokens, cambios de leeway ni excepciones ADMIN.
No hay integración Turnstile, widget, token adicional, Siteverify ni modo degradado.
Eso pertenece a 6B.4B y necesita su propia implementación y auditoría.

## Requisito operativo

**Los presupuestos globales requieren UN SOLO PROCESO FastAPI.** MySQL persiste
los buckets por identificador; las ventanas globales y cupos viven en memoria.
Un reinicio pierde solo los límites globales. No usar varios workers/instancias
suponiendo que los presupuestos globales siguen siendo totales. `--reload` es
solo desarrollo y reinicia esos presupuestos al recargar.

PHP llama a FastAPI por loopback; su IP no representa al navegador. No se limita
por IP ni se interpretan X-Forwarded-For, X-Real-IP o CF-Connecting-IP.
`trusted_client_origin` devuelve siempre None. Una futura frontera autenticada
podrá aportar origen real; los encabezados de Internet no son esa frontera.

## Admisión del login

1. Middleware aplica presupuesto global antes de parsear el cuerpo JSON.
2. Pydantic valida el contrato existente; el servicio normaliza con strip().lower().
3. INSERT ON DUPLICATE KEY UPDATE y SELECT FOR UPDATE serializan solo el bucket.
4. Comprueba ventanas, sin consultar usuarios. Antes de confirmar la reserva,
   adquiere presupuesto y cupo Argon2 en memoria, sin esperar por un cupo.
5. Incrementa solicitudes y fallos/reservas, renueva retención y hace commit.
6. Lee el usuario, captura los datos necesarios y cierra incluso esa transacción
   de lectura antes de verificar Argon2 real o dummy.
7. Conserva el bloqueo/revalidación del usuario antes de crear sesión y JWT.
8. Libera cupo global en finally. Un éxito o fallo operativo libera solo su
   reserva; un fallo de credenciales conserva el contador defensivo.

No se mantiene una transacción MySQL durante Argon2. Las secciones críticas
globales solo manipulan contadores/deques; la admisión usa adquisición no bloqueante.
No hay sleeps, colas de hashes ni excepciones por rol. La liberación usa una
sección crítica mínima para no perder cupos.

Si falla el commit de una reserva, se libera el cupo, pero el presupuesto global
ya consumido no se devuelve: comportamiento conservador. Una caída abrupta puede
dejar una reserva contabilizada hasta el fin de ventana. Un fallo operativo
posterior no deshace el presupuesto de solicitudes consumido.

Un identificador se almacena temporalmente como VARCHAR(320), collation explícita
utf8mb4_unicode_ci y clave primaria, igual a la semántica actual del login.
Mayúsculas, espacios exteriores y equivalencias MySQL no crean cuentas/buckets
independientes. No usar hash/HMAC como reemplazo de esa igualdad. No consultar
existencia para decidir la clave. Incluye identificadores inexistentes: son datos
temporales privados, sin logs ni exposición por las CLI.

| Variable FastAPI | Default |
| --- | ---: |
| RATE_LIMIT_LOGIN_REQUESTS_PER_MINUTE | 120 |
| RATE_LIMIT_IDENTIFIER_REQUESTS_PER_MINUTE | 10 |
| RATE_LIMIT_FAILURE_WINDOW_SECONDS | 600 |
| RATE_LIMIT_CHALLENGE_FAILURES | 5 |
| RATE_LIMIT_ARGON2_PER_MINUTE | 60 |
| RATE_LIMIT_ARGON2_CONCURRENCY | 2 |

Las ventanas globales son móviles de 60 segundos, con reloj monotónico. Las de
identificador son fijas desde la primera admisión: solicitudes 60 s y fallos 600 s.
El quinto fallo/reserva ocupa el último cupo local; el siguiente intento obtiene
429 hasta vencer la ventana. El nombre CHALLENGE_FAILURES queda reservado para
6B.4B, pero aquí solo provoca 429. La ventana de fallos configurable no puede
superar los 1200 segundos de retención; los límites cero/negativos son inválidos.

Un éxito libera únicamente su reserva, condicionada al inicio de ventana al que
pertenece, sin borrar fallos previos. Los éxitos consumen solicitudes y Argon2.
Los rechazos no reinician ventanas ni expires_at, incluso cuando falta presupuesto
global Argon2: la transacción del bucket se revierte. Retención: 20 minutos desde
la última admisión. Una finalización tardía no decrementa una ventana nueva.

HTTP 429 tiene cuerpo estable:

```json
{"detail":{"code":"login_rate_limited","message":"Demasiados intentos. Intente nuevamente más tarde."}}
```

Retry-After es entero positivo, redondeado hacia arriba al vencimiento requerido;
para saturación de concurrencia/contención breve se indica 1 segundo. No revela
existencia, actividad del usuario ni resultado de una contraseña no verificada.
Los 401 de credenciales mantienen su cuerpo anterior. Los rechazos no ejecutan
Argon2; los intentos admitidos inexistentes/hash inválido mantienen DUMMY_HASH.
No se promete tiempo constante entre un rechazo barato y una verificación.

Todas las respuestas /api/v1/auth/* llevan Cache-Control: no-store, incluidos
validación, HTTPException y errores internos saneados. No cambia la semántica RBAC.

## Migración 003

Crear auth_login_limits con identifier, request_window, request_count,
failure_window, failure_count y expires_at; índice ix_auth_login_limits_expires_at.
Añadir ix_auth_sessions_expires_at. No modifica registros, usuarios ni roles.
Downgrade elimina solo la tabla y el índice añadidos. Downgrade pierde el historial
de límites; no elimina sesiones. Las migraciones 001 y 002 no se modifican.

La migración debe desplegarse antes del código que utiliza la tabla. Para esta
entrega solo se aplica y revierte en esquemas temporales de pruebas; aplicar a la
base de trabajo es una operación de despliegue posterior.

## Pruning

Desde la raíz, utilizando el entorno privado existente de la API:

```powershell
.\api\venv\Scripts\python.exe -m scripts.prune_auth_sessions --dry-run
.\api\venv\Scripts\python.exe -m scripts.prune_auth_sessions --batch-size 500 --max-batches 20
.\api\venv\Scripts\python.exe -m scripts.prune_auth_login_limits --dry-run
.\api\venv\Scripts\python.exe -m scripts.prune_auth_login_limits --batch-size 500 --max-batches 20
```

Sesiones: expires_at <= UTC now - 24 horas. Incluye revocadas que ya expiraron;
no necesita segunda regla por revoked_at. Buckets: expires_at <= UTC now.
Cutoff fijo por ejecución, orden expires_at + clave primaria, commit por lote,
rollback del lote fallido, máximo 500 filas x 20 lotes por defecto. Los lotes
confirmados sobreviven a un fallo posterior; repetir es seguro e idempotente.
Dry-run cuenta hasta la capacidad de esa ejecución, no modifica y no enumera
identificadores/SIDs. Los límites CLI evitan argumentos desmesurados.

Programar sesiones diariamente y buckets cada 10 minutos con Task Scheduler/cron,
cuenta de servicio adecuada y directorio de trabajo en la raíz. No se registra
ninguna tarea automáticamente. Sin programación, la expiración lógica funciona
pero los registros antiguos permanecen hasta ejecutar la CLI. No hay DELETE
oportunista en login ni transacción masiva sin límite.

## PHP

Configurar mediante entorno del proceso Apache/PHP, no encabezados HTTP ni .env
bajo frontend/:

* AUTH_API_TIMEOUT_SECONDS=10: entero 1..120; login/me/logout. Uploads/downloads y
  demás POST conservan sus timeouts previos (120 s para operaciones largas).
* FRONTEND_COOKIE_SECURE=auto|always: valores exactos; omisión = auto; valores
  inválidos impiden iniciar sesión PHP. auto conserva HTTPS directo/local HTTP;
  always exige que el sitio se opere exclusivamente por HTTPS.

PHP traduce 429 a texto genérico, preserva la sesión anónima/CSRF y reenvía solo
Retry-After numérico saneado. No redirige ni refleja errores crudos del backend.

Antes de session_start se fijan save_handler=files, gc_maxlifetime=1800,
gc_probability=1, gc_divisor=100. Directorio dedicado fuera del web root.
GC probabilístico: no garantiza borrado puntual y puede dejar archivos sin tráfico.
session_gc() podrá ejecutarse operativamente en el futuro con la misma configuración
y directorio. No hay borrador manual de sess_* ni eliminación propia en requests.
En Windows deben configurarse permisos NTFS privados para la cuenta de PHP.
La escritura/cierre normal conserva actividad; JWT sigue expirando a los 900 s.

Con reverse proxy futuro: sobrescribir encabezados del cliente, aceptar señal HTTPS
solo del proxy autorizado, transmitirla a Apache/PHP y bloquear acceso directo al
backend. PHP no confía directamente en X-Forwarded-Proto. always evita depender de
esa detección para la cookie en un sitio exclusivamente HTTPS. No se monta proxy
ni se activa HSTS en HTTP local. CSP y Referrer-Policy se conservan.

## Medición aislada Argon2 (máquina de desarrollo, 2026-10-01)

6 verificaciones por nivel, alternando contraseña válida y DUMMY_HASH, sin tocar
parámetros: Argon2id v19, m=65536 KiB, t=3, p=4.

| Concurrencia | Mediana | Rango | Duración total |
| --- | ---: | ---: | ---: |
| 1 | 29.3 ms | 27.6–31.4 ms | 0.18 s |
| 2 | 39.2 ms | 37.2–41.5 ms | 0.12 s |

Memoria algorítmica aproximada: 64 MiB por hash, 128 MiB para dos, más sobrecarga
del proceso; no es una medición de RSS. Los valores 2 simultáneos y 60/min resultan
razonables en esta máquina. Repetir una medición breve al cambiar hardware.

## Pruebas y límites

Pruebas unitarias sin BD; MySQL solo mediante fixture opt-in que crea y elimina
un esquema aleatorio protegido. Comprueba 003->002->003, equivalencias reales de
collation, reservas, concurrencia, transacciones cerradas durante hashes, presupuestos,
reinicio global, no-store, pruning y rollback. PHP se ejecuta en copia temporal
con API doble o FastAPI conectado al esquema temporal. Regresiones incluyen 6A,
6B.1, 6B.2 y 6B.3. No usar la suite histórica contra una base fija para esta fase:
tests_auth_mysql/test_6a_regression_mysql.py incorpora esas pruebas aisladamente.

Ejemplos desde api/ (elegir directorios temporales nuevos fuera del repositorio):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\venv\Scripts\python.exe -B -m pytest tests_unit -q -p no:cacheprovider -o addopts= --basetemp=<temp-unico>
$env:AUTH_MYSQL_TEST='1'
.\venv\Scripts\python.exe -B -m pytest tests_auth_mysql -q -p no:cacheprovider -o addopts= --basetemp=<otro-temp-unico>
.\venv\Scripts\python.exe -B -m pytest ../frontend/tests -q -p no:cacheprovider -o addopts= --basetemp=<otro-temp-unico>
```

El límite por cuenta puede ser consumido por terceros durante un ataque activo.
No hay bloqueo permanente almacenado, pero no se garantiza disponibilidad bajo
ataque dirigido continuo. Ventanas fijas admiten ráfagas en la frontera; presupuestos
globales móviles y concurrencia limitan el coste. Spraying lento puede permanecer
bajo umbrales. No limita operaciones de sesiones ya autenticadas ni DDoS volumétrico.
Esos controles necesitan políticas específicas/perímetro futuro, no Redis o nueva
infraestructura obligatoria para este MVP.

## Resultado de validación de la entrega

215 pruebas unitarias, 139 MySQL/regresiones y 63 PHP: **417 aprobadas**.
41 archivos PHP pasan php -l. git diff --check sin errores. Dos advertencias
preexistentes de deprecación Starlette/httpx/AnyIO; no se instalaron paquetes.
Los esquemas aleatorios se eliminaron (consulta posterior: cero pendientes).

La base de trabajo inspeccionada reporta revisión Alembic **001** y no contiene
auth_sessions ni auth_login_limits. No se modificó: antes de ejecutar el backend
nuevo deben revisarse y aplicar 002 y 003 en esa base mediante el procedimiento
de despliegue aprobado. Publicación de código y aplicación de migraciones son
operaciones distintas; las pruebas de esta entrega no migran la base de trabajo.
