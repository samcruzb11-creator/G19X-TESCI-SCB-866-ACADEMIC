# Fase 7C: rondas de aprobación y decisiones

## Inspección y decisiones previas a la implementación

Checkpoint: main limpio, HEAD = origin/main =
30b3ff40e2ae6dca93aba779f5da4fb2372781ab. MySQL 8.0.46, Alembic current/heads
005. No existe 006. No se modifican modelos ni migraciones 001–005.

El sujeto real es **VersionDocumento**, no Documento ni Auditoria.
RondaAprobacion contiene version_documento_id, numero_ronda, estado,
solicitada_por_id, solicitada_en, resuelta_en y timestamps. UNIQUE versión/número.
Sus estados son PENDING, IN_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED y CANCELLED.
El estado representa también el resultado; un estado terminal requiere resuelta_en.

DecisionAprobacion es asignación y decisión: ronda_aprobacion_id, aprobador_id,
estado, comentario, asignada_en, decidida_en y timestamps. UNIQUE ronda/aprobador.
PENDING exige decidida_en NULL; APPROVED/REJECTED/CHANGES_REQUESTED exigen fecha.
Las FKs existentes son RESTRICT. No existen quorum, mayoría ni tabla adicional
de asignaciones. Los índices versión/estado y aprobador/estado ya cubren el flujo.

Una versión puede pertenecer a varias auditorías mediante DocumentoAuditoria.
Se exige consistencia documento/versión del pivot en backend. Una aprobación es
global para esa versión; no se inventa un auditoria_id persistido. El contexto
opcional auditoria_id valida la relación exacta y el scope. Todas las auditorías
vinculadas se bloquean en orden de ID antes de mutar; cualquier auditoría terminal
bloquea la operación, incluso si se envía otra auditoría como contexto.

Regla mínima: crear PENDING con 1–20 aprobadores activos de rol APROBADOR;
iniciar pasa a IN_REVIEW. Cada asignado confirma una sola decisión propia.
Hasta resolver todas las asignaciones permanece IN_REVIEW; al resolver la última
se cierra atómicamente. Precedencia: REJECTED > CHANGES_REQUESTED > APPROVED.
Cancelar cierra sin cambiar decisiones históricas. Finalizar permite consolidar
una ronda IN_REVIEW legada con todas las decisiones resueltas; nunca admite
resultado del cliente. Solo una ronda activa por versión mediante lock de versión.
Una nueva ronda terminal anterior recibe el siguiente número, sin borrar historia.

7C introduce permisos para operaciones nuevas: ADMIN administra; AUDITOR_INTERNO
inicia/administra rondas de versiones vinculadas exactamente a auditorías propias;
APROBADOR decide solo en su asignación; auditores leen sus contextos,
RESPONSABLE_AREA lee documentos propios y APROBADOR lee rondas asignadas.
AUDITOR_EXTERNO conserva solo lectura. No se amplían permisos 6B.2/7A/7B.
El historial global existente sigue reservado a ADMIN; el historial nuevo de ronda
solo expone eventos de esa ronda con metadata whitelist y scope de ronda.
ADMIN no suplanta aprobadores. No existe prohibición de autoaprobación de negocio;
la selección exige rol APROBADOR, y decidir exige conservar ese rol activo.

No se altera Documento.estado ni IN_REVIEW → COMPLETED: no existe una regla
documentada que exija automatización o una precondición nueva.

La BD sistema_trazabilidad y el storage real se consultan exclusivamente en lectura.
Se capturó una huella de todas las tablas y archivos en TEMP antes de implementar.
Pruebas de escritura se ejecutan únicamente en fixtures SQLite/MySQL temporal.

## Arquitectura implementada

`schemas/aprobacion.py` define comandos estrictos y proyecciones; el router
`routers/aprobaciones.py` utiliza las dependencias existentes de identidad/BD.
`services/aprobacion_service.py` mantiene las transacciones de dominio y reutiliza
`documento_service._log_evento`. `authorization_service.py` agrega únicamente
permisos/scopes del módulo nuevo. Se registró el router en `app/main.py`.
No hay cambios en entidades, archivos de migración, auth, storage, servicios
de evidencias/hallazgos ni workflow de auditoría.

Cardinalidades: versión 1:N rondas; ronda 1:N decisiones; usuario 1:N decisiones.
La decisión PENDING preexistente es la asignación explícita. Al crear se congela
la lista; no existe edición, revocación ni eliminación HTTP de decisiones.
ADMIN administra/cancela/inicia sin poder decidir por otra persona. Una identidad
histórica puede haber sido creador/responsable y posteriormente APROBADOR tras
un cambio de rol: no se agrega una prohibición de autoaprobación por negocio.

## Permisos y scope

| Operación nueva | ADMIN | AUDITOR_INTERNO | AUDITOR_EXTERNO | RESPONSABLE_AREA | APROBADOR |
| --- | --- | --- | --- | --- | --- |
| Listar/detalle/decisiones/historial seguro | Todas | Versiones exactas de auditorías propias | Versiones exactas de auditorías propias | Documentos propios | Rondas con asignación propia |
| Crear/iniciar/cancelar/finalizar | Sí | Su mismo scope | No | No | No |
| Catálogos de recursos/aprobadores | Sí | Recursos de su scope; aprobadores activos | No | No | No |
| Emitir decisión | Sin suplantación; necesita rol APROBADOR activo y asignación | No | No | No | Solo asignación propia PENDING en IN_REVIEW |

La lectura documental de 6B.2 se conserva: un auditor puede consultar otras
versiones de un documento vinculado. Para el módulo nuevo de aprobaciones se
requiere la versión exacta del pivot. APROBADOR conserva la lectura histórica
de versiones asignadas, pero no recibe acceso a otras rondas de la misma versión.
No se crea CONSULTA ni área/ownership ficticios. RESPONSABLE_AREA no tiene
escritura nueva; AUDITOR_EXTERNO no obtiene escritura nueva.

Los EXISTS se aplican antes de COUNT/ORDER/OFFSET/LIMIT. Detalle y comandos usan
404 uniforme para inexistencia/fuera de scope. Filtros de documento, versión o
auditoría validan el recurso padre; APROBADOR no recibe auditoria.read mediante
la asignación. Las respuestas de ronda no exponen IDs/nombres de auditorías ajenas.
Decisiones e historial vuelven a incluir el scope en su consulta paginada.
Los vínculos inválidos de DocumentoAuditoria legados impiden mutaciones.

## Endpoints bajo /api/v1

| Método/ruta | Contrato |
| --- | --- |
| GET /aprobaciones | Rondas con X-Total-Count y scope SQL |
| POST /aprobaciones | documento_id, version_documento_id, auditoria_id opcional, aprobadores_ids |
| GET /aprobaciones/recursos | Catálogo paginado de versiones elegibles; filtros documento/auditoría |
| GET /aprobaciones/aprobadores | Usuarios activos APROBADOR; solo id/nombre; búsqueda q y paginación |
| GET /aprobaciones/{id} | Sujeto, solicitante, estado, fechas, conteos, decisión propia y capacidades |
| POST /aprobaciones/{id}/iniciar | PENDING → IN_REVIEW; revisa elegibilidad de asignados |
| POST /aprobaciones/{id}/cancelar | PENDING/IN_REVIEW → CANCELLED |
| POST /aprobaciones/{id}/finalizar | Consolida IN_REVIEW legado, exige todas las decisiones resueltas |
| POST /aprobaciones/{id}/decision | APPROVED/REJECTED/CHANGES_REQUESTED y comentario opcional; actor de sesión |
| GET /aprobaciones/{id}/decisiones | Asignaciones/decisiones paginadas, proyección segura |
| GET /aprobaciones/{id}/historial | Solo eventos de esa ronda, paginados y con whitelist |

No existe PATCH/DELETE genérico de ronda o decisión. Gestión exige
estado_esperado + updated_at_esperado; una decisión exige el updated_at_esperado
de la **asignación propia**, permitiendo decisiones concurrentes de personas
distintas sin exigir que compartan un token mutable de ronda.

Filtros: documento_id, version_documento_id, auditoria_id, estado, q sobre título,
pendientes_propias y orden id/-id. limit 1–100 (20 por defecto), offset 0–10000.
IDs JSON estrictos BIGINT UNSIGNED: no bool, float, string, cero ni overflow.
IDs de path/query aceptan solo enteros decimales, sin coerción de 1.0/1e0.
Extras, identidad/fechas/resultado enviados por cliente y enums inválidos: 422.
Comentario: máximo 16000 caracteres; controles ASCII prohibidos excepto tab/CR/LF.
q ≤100, LIKE escapado; ORDER BY usa exclusivamente columnas whitelist.

## Concurrencia, atomicidad y eventos

Orden de locks: auditorías vinculadas por ID (consultas puntuales ordenadas),
Documento, VersionDocumento, pivots, RondaAprobacion, decisiones y usuarios por
ID. Los locks de auditoría son los mismos de 7A/7B. El scope se revalida después
de esperar; un cambio de responsable de auditoría revoca la mutación pendiente.
Las filas de usuarios se refrescan/bloquean: un aprobador desactivado mientras
espera no confirma una decisión. Se verifica que el conjunto de pivots no haya
cambiado desde descubrir/bloquear sus padres.

Lock de versión + lecturas FOR UPDATE actuales serializan creación equivalente
y numeración aun con un snapshot REPEATABLE READ anterior. UNIQUEs existentes
son defensa adicional. Resultado se deriva de las decisiones bloqueadas; cierre,
fecha resuelta_en y eventos se confirman en la misma transacción. Timestamp de
concurrencia avanza al menos un microsegundo. 1205/1213 de MySQL se traducen a 409
con rollback, sin replay automático; otros fallos BD usan errores sanitizados.

Eventos: CREACION_RONDA_APROBACION, INICIO_RONDA_APROBACION, DECISION_APROBACION y
CIERRE_RONDA_APROBACION. entidad_tipo = RONDA_APROBACION, entidad_id = ID de ronda.
Actor autenticado, correlation_id, sujeto documento/versión, IDs de auditorías
vinculadas y estado/decisión segura. La decisión confirmada genera un evento;
la última genera además el evento de cierre, sin duplicación en reintentos.
El historial público excluye actor_snapshot, comentarios, lista de aprobadores
y auditorías ajenas. No se almacenan JWT, contraseñas ni rutas físicas en metadata.
Fallo de INSERT/UPDATE/cálculo/evento/commit antes de confirmación: rollback total.
Ante un fallo de conexión durante commit se indica consultar antes de repetir;
los constraints y estados inmutables evitan reescrituras/duplicados en reintento.

## Frontend y seguridad HTTP

Rutas PHP: aprobaciones, aprobacion y aprobacion_nueva. Navegación por rol;
listado paginado/filtros, detalle, conteos, asignados, decisión propia e historial.
Solo las capacidades calculadas por servidor y el rol habilitan controles UX.
FastAPI sigue validando cada comando directo. Catálogos de veinte registros con
paginación explícita; cambiar página reinicia la selección y se informa al usuario.
Desde auditoría/documento se consultan solo cinco rondas y se enlaza al listado.
No se muestran aprobaciones simuladas ni módulos de 7D.

Toda mutación POST + CSRF, PRG 303 tras éxito y rotación CSRF. GET no muta.
JWT exclusivamente en sesión PHP, /auth/me para cada petición, logout/expiración
y 401/403/404 conservados. Rutas de api_client ampliadas solo al módulo exacto;
no URLs del cliente ni redirecciones externas. Todos los valores dinámicos usan e().
Se conserva CSP. UI reutiliza paneles/tablas/cards responsivas existentes.

## Performance

Listado: COUNT scoped, SELECT paginado con solicitante eager, una consulta para
decisiones propias de toda la página y otra para la protección terminal visual.
Prueba de presupuesto ≤5 SELECT con el fixture de identidad. No N+1 en lecturas.
Catálogos, decisiones e historial paginados. Numeración consulta solo el último
número y la existencia de ronda activa usando índices actuales; no carga todo
el historial. Los locks puntuales por auditoría son deliberados para ordenar
mutaciones, no queries de lectura por cada fila del listado. Sin índices nuevos.

## Autoauditoría y regresiones

Se probaron IDOR directo/listados, scope antes de count, RBAC vertical, spoofing,
extras, IDs inválidos, stale timestamps, cross-audit/document/version, asignados
inexistentes/inactivos/ineligibles/duplicados, rondas/auditorías terminales,
decisiones opuestas, XSS, CSRF, GET, ORDER injection, límites y presupuesto SQL.

Correcciones surgidas de la revisión:

- Coerción Pydantic de IDs decimales/flotantes en query/path: se exige decimal entero.
- Inicio legado: vuelve a verificar actividad/rol de todos los asignados.
- Scope tras esperar un lock: se verifica responsable usando la auditoría refrescada,
  incluyendo cambio de rol ADMIN → AUDITOR_INTERNO concurrente con reasignación.
- Orden de locks de varias auditorías: consultas puntuales, independiente del optimizer.
- Numeración: consultas actuales acotadas en lugar de cargar el historial de rondas.
- Deadlock/timeout MySQL: 409 + rollback sin reintentar decisiones automáticamente.

Inyección de fallos reales antes de INSERT decisión, UPDATE ronda/decisión,
INSERT evento y cálculo; fallo de flush/commit: no filas/eventos parciales.
MySQL temporal verifica UNIQUE, FK y CHECK, dos aprobadores, doble decisión,
APPROVE vs REJECT, creación equivalente, doble inicio/finalización, última
decisión vs cierre, cierre/cancelación de auditoría en ambos órdenes, desactivación
y reasignación durante espera, versiones compartidas y snapshots anteriores.

Prueba end-to-end adicional sin API double: PHP real → FastAPI con Uvicorn →
schema MySQL aleatorio; login Argon2/JWT reales, creación/inicio/decisión/cierre,
historial y XSS escapado. BD/storage de producción prohibidos por fixtures.

Chrome real: desktop 1440, móvil 390 y móvil 320, flujo crear/iniciar/decidir,
Tab/focus, ausencia de overflow horizontal, decisión inmutable, JWT ausente y
payload XSS sin ejecución. Capturas revisadas en TEMP. El sandbox interrumpía
DevTools, por lo que Chrome se ejecutó mediante autorización fuera del sandbox,
con perfiles/servidores temporales y sin usar el perfil instalado del usuario.

Las regresiones comprenden 6A, 6B.1, 6B.2, 6B.3, 6B.4A/B, 6C, 6D/6D.1, 7A y 7B.
No se ejecuta directamente el fixture destructivo legacy de api/tests contra
producción: su adapter existente usa exclusivamente el schema temporal guardado.

### Comandos reproducibles (desde api, salvo frontend)

```powershell
.\venv\Scripts\python.exe -m pytest tests_unit -q --basetemp=$env:TEMP\trazabilidad_7c_unit_nuevo
$env:AUTH_MYSQL_TEST='1'
.\venv\Scripts\python.exe -m pytest tests_auth_mysql -q --basetemp=$env:TEMP\trazabilidad_7c_mysql_nuevo
# Desde raíz; browser separado para habilitar Chrome:
.\api\venv\Scripts\python.exe -m pytest frontend/tests -q --basetemp=$env:TEMP\trazabilidad_7c_php_nuevo
$env:AUTH_BROWSER_TEST='1'
.\api\venv\Scripts\python.exe -m pytest frontend/tests/test_aprobaciones_browser.py frontend/tests/test_auth_browser.py frontend/tests/test_turnstile_browser.py frontend/tests/test_auditorias_browser.py frontend/tests/test_hallazgos_browser.py -q --basetemp=$env:TEMP\trazabilidad_7c_browser_nuevo
```

Usar un basetemp NUEVO por ejecución. AUTH_MYSQL_TEST crea y elimina únicamente
schema aleatorio con guardas de nombre, conexión y cleanup; nunca selecciona la
BD real para pruebas destructivas. PHP lint y git diff --check complementan suites.

## Límites y deuda técnica real

- El esquema no soporta rondas independientes por auditoría: son globales por
  versión. Si el negocio exige independencia, debe diseñarse una fase/migración
  posterior; 7C no inventa esa relación ni aplica 006.
- DocumentoAuditoria no tiene FK compuesta documento/versión ni API de edición.
  Se valida la consistencia; cualquier futura mutación de pivots debe compartir
  el orden de locks y las protecciones terminales, no editar referencias libremente.
- No se reasignan decisiones de ronda existente: ante un aprobador inactivo,
  ADMIN cancela y abre otra ronda con asignados elegibles, conservando historia.
- No se agrega quorum, mayoría, autoactivación de Documento ni aprobación obligatoria
  para cerrar auditoría: requieren definición de negocio posterior.
- Una auditoría puede cerrar con rondas pendientes porque se conserva 7A. Esas
  rondas quedan históricas y bloqueadas; no se cancelan automáticamente ni se
  ofrece un bypass ADMIN para mutar recursos de auditorías terminales.
- Tests conservan dos avisos de deprecación existentes de Starlette/httpx/AnyIO.
  No se actualizan dependencias ni se hace refactor global en esta fase.

## Resultado del cierre

| Verificación | Resultado |
| --- | --- |
| Suite unitaria completa | 906 passed |
| Suite MySQL temporal completa | 756 passed |
| Batería final ampliada 7C MySQL + end-to-end | 148 passed; incluye 2 carreras agregadas después de la suite completa |
| Contratos MySQL distintos verificados | 758: 610 previos + 148 de 7C |
| Suite PHP HTTP sin browser | 207 passed |
| Regresiones Chrome | 19 passed: 1440/390/320 para 7C y fases previas |
| Pruebas distintas, sin contar repeticiones | 1890 passed |
| PHP lint | 59 archivos, sin errores |
| git diff --check | Sin errores |
| Archivos del cambio | 14 modificados + 13 nuevos; UTF-8 válido, sin BOM |
| Alembic final | 005 (head), sin 006 |
| Huella BD real | Todas las tablas/filas iguales a la captura inicial |
| Huella storage real | Los 2 archivos conservan sus SHA-256 y nombres relativos |
| Git final | main; HEAD = origin/main = 30b3ff4; sin commit/push ni staging |

La suite completa MySQL precedió las últimas dos pruebas de scope; la batería
final de 148 ejecutó todos los contratos de 7C sobre la implementación definitiva.
La suite completa PHP pasó antes del ajuste puntual del breadcrumb; después se
validó con lint y el end-to-end PHP real. No se contabilizan repeticiones como
pruebas adicionales. Los perfiles y capturas de browser permanecen en TEMP;
un intento de copiarlos al basetemp legacy ignorado no tuvo permiso, y se revisaron
directamente con el visor de imágenes. No se añadieron artefactos al repositorio.

Inventario nuevo: schemas/aprobacion.py, routers/aprobaciones.py,
services/aprobacion_service.py; tests_unit/test_aprobacion_unit.py;
tests_auth_mysql/test_aprobacion_mysql.py y test_aprobacion_e2e_mysql.py;
frontend/pages/aprobaciones.php y aprobaciones_list.php;
frontend/services/aprobaciones_controller.php y aprobacion_helpers.php;
frontend/tests/test_aprobaciones.py y test_aprobaciones_browser.py; este documento.

Inventario modificado: api/app/main.py y services/authorization_service.py;
api/README.md y frontend/README.md; frontend/index.php, includes/auth.php,
includes/header.php, assets/css/estilos.css, pages/auditoria.php, pages/documento.php,
services/api_client.php, services/auditorias_controller.php,
services/documento_controller.php y tests/conftest.py.

`git diff --stat` (archivos tracked; los nuevos siguen untracked):

```text
 api/README.md                               |  4 ++++
 api/app/main.py                             |  2 ++
 api/app/services/authorization_service.py   | 27 +++++++++++++++++++++++++
 frontend/README.md                          |  6 ++++++
 frontend/assets/css/estilos.css             |  3 +++
 frontend/includes/auth.php                  |  4 ++++
 frontend/includes/header.php                |  4 ++--
 frontend/index.php                          |  7 ++++++-
 frontend/pages/auditoria.php                |  1 +
 frontend/pages/documento.php                |  1 +
 frontend/services/api_client.php            |  4 ++--
 frontend/services/auditorias_controller.php |  2 ++
 frontend/services/documento_controller.php  |  2 ++
 frontend/tests/conftest.py                  | 31 +++++++++++++++++++++++++++++
 14 files changed, 93 insertions(+), 5 deletions(-)
```

`git status --short` final:

```text
 M api/README.md
 M api/app/main.py
 M api/app/services/authorization_service.py
 M frontend/README.md
 M frontend/assets/css/estilos.css
 M frontend/includes/auth.php
 M frontend/includes/header.php
 M frontend/index.php
 M frontend/pages/auditoria.php
 M frontend/pages/documento.php
 M frontend/services/api_client.php
 M frontend/services/auditorias_controller.php
 M frontend/services/documento_controller.php
 M frontend/tests/conftest.py
?? api/app/routers/aprobaciones.py
?? api/app/schemas/aprobacion.py
?? api/app/services/aprobacion_service.py
?? api/tests_auth_mysql/test_aprobacion_e2e_mysql.py
?? api/tests_auth_mysql/test_aprobacion_mysql.py
?? api/tests_unit/test_aprobacion_unit.py
?? docs/FASE_7C_APROBACIONES.md
?? frontend/pages/aprobaciones.php
?? frontend/pages/aprobaciones_list.php
?? frontend/services/aprobacion_helpers.php
?? frontend/services/aprobaciones_controller.php
?? frontend/tests/test_aprobaciones.py
?? frontend/tests/test_aprobaciones_browser.py
```
