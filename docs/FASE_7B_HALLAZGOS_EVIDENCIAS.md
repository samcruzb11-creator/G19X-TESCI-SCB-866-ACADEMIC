# Fase 7B — Hallazgos y gestión integral de evidencias

## 1. Entrada y límites

Preflight antes de editar: `main`, working tree limpio; HEAD y `origin/main`
`3684e95f3dff63d2ac72e11b70b3c56994c63c5a` (`feat(audits): implement phase 7A audit lifecycle`).
Alembic en código y BD real: `005 (head)`. Servidor comprobado por lectura:
MySQL 8.0.46, `127.0.0.1:3306`, `sistema_trazabilidad`.
No se modificaron 001–005, modelos de dominio, auth, usuarios reales ni storage real.
No se implementaron 7C, 7D, IA, aprobaciones, alertas ni despliegue.
No se hizo commit, push ni staging.

## 2. Arquitectura encontrada y reutilizada

FastAPI + SQLAlchemy 2 + Pydantic 2, MySQL/InnoDB y Alembic. PHP con sesión
privada, `/auth/me`, cURL con whitelist de rutas, CSRF y templates escapados.
`authorization_service.py` concentra RBAC y scopes SQL. 7A usa bloqueo scoped
de Auditoria con `FOR UPDATE`/`populate_existing` y versión esperada.
EvidenciaService reutiliza StorageService (UUID, rutas controladas, SHA-256,
streaming, rename atómico), file_transaction y los eventos existentes.
Documento/VersionDocumento/DocumentoAuditoria verifican referencias dentro de
la misma auditoría; no existe área directa de Auditoria ni de Usuario.

Hallazgo existente: auditoria_id, numero, titulo, descripcion, categoria,
severidad, estado, responsable_id, detectado_en, fecha_limite, resolucion,
cerrado_por_id, cerrado_en, created_by_id, updated_by_id, created_at y updated_at.
HallazgoEvidencia: PK `(hallazgo_id, evidencia_id)`, vinculada_por_id,
vinculada_en y contexto. Las FKs son RESTRICT; ya existen índices de consulta.
Evidencia no tiene concepto de borrado lógico. EventoAuditoria ya admite actor,
acción, entidad, correlación, fecha y snapshots JSON.

La implementación añade schema/router/service de hallazgos, siguiendo estas
fronteras. EvidenciaService recibe hooks pequeños de asociación y conserva su
propio commit/compensación; no se duplica el almacenamiento ni la descarga.

## 3. Decisiones y ausencia de 006

El schema 005 representa todo el flujo: ninguna columna, índice, estado o tabla
nueva es indispensable. La PK del vínculo resuelve duplicados concurrentes;
la unicidad `(auditoria_id, numero)` protege numeración. No se creó 006.
La consistencia entre auditorías se comprueba bajo locks en el backend; el
schema actual no contiene una FK compuesta para expresar esa igualdad.
Escrituras SQL directas deben seguir siendo operaciones administrativas de confianza.
Las lecturas de vínculos también omiten relaciones legacy inconsistentes.

Número y detección se asignan en backend. Categoría conserva texto libre de
40 caracteres: no se inventa un catálogo. Responsable opcional utiliza el
catálogo existente de auditores activos. No se inventa pertenencia de área.

## 4. Endpoints

Todos bajo `/api/v1`, con `current_user` y dependencias existentes:

| Método / ruta | Función |
| --- | --- |
| GET /hallazgos | Lista scoped; X-Total-Count |
| POST /hallazgos | Crea OPEN; número consecutivo por auditoría |
| GET /hallazgos/{id} | Detalle, responsable seguro y conteo de evidencias |
| PATCH /hallazgos/{id} | Campos editables y updated_at_esperado |
| POST /hallazgos/{id}/estado | Estado destino, esperado, versión y resolución opcional |
| POST /hallazgos/{id}/evidencias | Asocia evidencia_id y contexto opcional |
| GET /hallazgos/{id}/evidencias | Evidencias relacionadas paginadas, sin storage_key |
| GET /hallazgos/{id}/historial | ADMIN; historial paginado y metadata filtrada |
| POST /evidencias/archivo | Endpoint existente; hallazgo_id opcional multipart |
| POST /evidencias/logica | Endpoint existente; hallazgo_id opcional JSON |
| GET /evidencias | Endpoint existente; total scoped y offset limitado |

Consulta inversa: `GET /hallazgos?evidencia_id={id}`. Primero comprueba la
evidencia scoped; luego filtra vínculos de la misma auditoría y referencias
consistentes. Recursos ajenos/ausentes devuelven el mismo 404.
No hay DELETE ni desasociación: no se agrega un borrado ajeno al flujo requerido.

## 5. Workflow

`OPEN -> IN_PROGRESS -> PENDING_VERIFICATION -> CLOSED`.
`PENDING_VERIFICATION -> IN_PROGRESS` permite corregir antes de verificar.
ADMIN puede pasar desde un estado no terminal a `ACCEPTED_RISK`.
Cerrar o aceptar riesgo exige resolución no vacía y fija cerrado_por_id/cerrado_en
desde el actor y reloj del servidor. No es un workflow de aprobación.
`CLOSED` y `ACCEPTED_RISK` son terminales, incluidas edición y asociación.

Las mutaciones de hallazgos requieren Auditoria IN_PROGRESS o IN_REVIEW.
PLANNED, COMPLETED y CANCELLED rechazan creación, edición, transición y enlaces.
Las cargas independientes conservan 7A: PLANNED admite evidencias; terminales no.
La creación con hallazgo requiere además el estado mutable del hallazgo/auditoría.
7A conserva su ciclo y precondiciones de cierre; no se introduce cierre 7C.

## 6. RBAC y diferencias expresas

| Operación | ADMIN | AUDITOR_INTERNO | AUDITOR_EXTERNO | RESPONSABLE_AREA / APROBADOR |
| --- | --- | --- | --- | --- |
| Leer hallazgos y vínculos | Global | Auditoría propia | Auditoría propia | Denegado |
| Crear, editar, estado, asociar hallazgo | Global, con workflow | Auditoría propia | Denegado | Denegado |
| Aceptar riesgo | Sí | No | No | No |
| Historial de hallazgo | Sí | No | No | No |
| Evidencias independientes | Matriz existente | Matriz existente | Matriz existente | Matriz existente |

Auditoría propia significa responsable_id del usuario autenticado. La matriz
6B.2 no tenía endpoints de hallazgos: se define explícitamente esta nueva política.
No se cambian sus permisos existentes. En particular, AUDITOR_EXTERNO conserva
creación de evidencia independiente, aunque no pueda modificar hallazgos.
Interno solo puede asignar responsable a sí mismo o dejarlo sin asignar;
ADMIN puede asignar un auditor activo. RESPONSABLE_AREA/APROBADOR no reciben
acceso por el responsable opcional del hallazgo. CONSULTA no existe en el CHECK.
Historial reservado a ADMIN, coherente con 6B.2/7A.

## 7. IDOR, validación y relaciones

Scopes SQL preceden filtros, count, orden y paginación. EXISTS evita duplicar
hallazgos al consultar vínculos. ID positivo, enum estricto, extras rechazados
y JSON IDs enteros estrictos (no bool, float ni strings). PATCH vacío, null de
campos obligatorios, actores, número, auditoría, estado directo y timestamps
protegidos se rechazan. Strings trimmed, límites compatibles con TEXT utf8mb4,
controles rechazados y fechas dentro del rango MySQL.
Los IDs nuevos de hallazgos también se limitan al dominio BIGINT UNSIGNED de
MySQL; números superiores reciben 422 antes de llegar al driver SQL.

El actor siempre deriva de current_user. Los parámetros legacy de actor de
evidencias conservan el contrato de ser ignorados; JSON extra se rechaza.
El vínculo valida ambos recursos, igualdad de auditoría y consistencia de
Documento/VersionDocumento/DocumentoAuditoria también para ADMIN. Un FILE debe
estar disponible mediante la ruta controlada de storage antes de asociarse.
No se comprueba integridad criptográfica completa en cada enlace: la descarga
y el verificador existente conservan sus garantías y costo de streaming.

401 identidad; 403 permiso; 404 ausencia/scope/referencia; 409 estado,
concurrencia o duplicado; 422 estructura/validación; errores internos saneados.

## 8. Transacciones, eventos y concurrencia

Orden de locks: Auditoria, Hallazgo, evidencia existente. Una primera consulta
scoped localiza el padre; después se relee bajo lock y populate_existing.
La auditoría comparte exactamente la fila bloqueada por cierre 7A y carga 6A.
Cambios de ownership/estado se revalidan en esa lectura actual.

Edición/transición comparan updated_at_esperado; transición también estado_esperado.
El token avanza explícitamente, incluso si el reloj repite un microsegundo.
Una asociación avanza el token para invalidar formularios anteriores.
La numeración usa una lectura actual FOR UPDATE después de bloquear el padre,
evitando snapshots antiguos de REPEATABLE READ. PK y UNIQUE son la última defensa.
No hay retries automáticos ni comprobación previa como única defensa de unicidad.

Eventos: CREACION_HALLAZGO, ACTUALIZACION_HALLAZGO, CAMBIO_ESTADO_HALLAZGO,
ASOCIACION_EVIDENCIA_HALLAZGO. Usan entidad HALLAZGO, actor autenticado,
correlación, snapshots de negocio y resultado SUCCESS. Fallar al generar o
insertar el evento revierte el negocio. Historial no expone actor_snapshot,
correos, secretos, storage_key ni metadata legacy fuera de whitelist.

Crear evidencia con hallazgo produce el evento existente de evidencia y uno
de asociación, con un único commit. No duplica CARGA_EVIDENCIA ni
REGISTRO_EVIDENCIA_LOGICA. Se eliminó storage_key de eventos nuevos de evidencia;
no se reescriben eventos históricos. User-Agent libre no se registra: evita
guardar credenciales inadvertidamente enviadas en headers.

Archivo nuevo: fallo pre-commit compensa; commit incierto conserva archivo y
exige consultar antes de repetir; fallo post-commit jamás borra el confirmado.
Las evidencias lógicas también hacen rollback ante fallos previos al commit.

## 9. Archivos y política conservada

StorageService/file_transaction y descargas no se reescriben. SHA-256 y escritura
siguen en bloques. Nombre se reduce a basename en ambas convenciones de separador,
se valida longitud/control y el UUID decide la ruta física; doble extensión no
controla directorios. Rutas absolutas, traversal y ADS son rechazadas por storage.
Se rechazan archivos vacíos y cargas que superen `MAX_EVIDENCE_FILE_BYTES`
(20 MiB por defecto, configurable entre 1 byte y 1 GiB), compensando temporales.
PHP mantiene sus límites efectivos upload_max_filesize/post_max_size y streaming
de descarga con spool privado. El límite backend se valida durante la escritura;
FastAPI recibe primero el multipart en su spool existente.

No había allowlist MIME ni parser de formato en 6A. Se conserva la política
de archivo opaco: MIME es metadata declarada/inferida, no certificación del
contenido. Se valida su tamaño/control, pero no se inventa detección de PDF,
Office, antivirus ni servicios externos. La descarga es attachment.
Streams fallidos/malformados dejan rollback y compensación, cubiertos por 6A.
Referencias nuevas HTTP/HTTPS sin credenciales; nunca se descargan desde el servidor.
Se conserva la resolución documental desde version_documento_id en archivos;
el contrato JSON lógico sigue exigiendo documento explícito.

## 10. Frontend y sesión

Navegación Hallazgos; detalle de auditoría muestra cinco hallazgos por
ID ascendente, conteo, crear según estado/rol y acceso al listado filtrado.
Listado con título, estado, severidad, responsable, conteo y detalle; filtros y
paginación SQL, no descarga de toda la tabla. Formularios reutilizan helpers
existentes, validación textual, mensajes seguros y catálogos de auditores.
Detalle permite editar, cambiar estado, asociar evidencia existente paginada,
crear archivo/nota y asociar atómicamente, leer relacionados y su historial.
Detalle de evidencia muestra hallazgos vinculados con paginación.

Todas las mutaciones PHP requieren POST + CSRF; GET no ejecuta comandos.
Tokens/versiones esperados no se sustituyen por una lectura nueva al enviar.
Rutas exactas nuevas en api_client, con PATCH/POST restringidos; ningún URL
remoto del cliente ni redirect externo. JWT solo en sesión PHP del servidor.
Se conservan `/auth/me`, expiración, 401/403/404, logout, CSP y escaping HTML.
No hay botones de aprobación simulados. Estética sobria con componentes y CSS
existentes; tablas se convierten en cards en móvil y formularios tienen labels/foco.

## 11. Filtros y performance

Hallazgos: auditoria_id, evidencia_id (consulta inversa), estado, severidad,
responsable_id, q sobre título/descripción (100 caracteres). Comodines LIKE
literales y parámetros bound; orden enum id/-id/numero/-numero, desempate por ID.
limit 1–200, offset 0–10000; evidencias/historial del hallazgo limit 1–100.
PHP usa páginas de 20; tres paginaciones independientes en detalle.
El detalle de auditoría carga solo cinco hallazgos.

Responsable por JOIN y conteo por subquery scoped en una consulta de página;
test asegura máximo tres statements con identidad y count. Sin N+1 de vínculos
ni personas. Índices existentes de auditoría/estado, responsable/estado/fecha,
PK del pivot, índice inverso del pivot y entidad/fecha de eventos bastan.
No se añade índice especulativo. q substring puede escanear el scope; no full-text.

## 12. Validación y autoauditoría

Resultados: 789 unitarias, 610 MySQL temporal, 181 PHP y 16 Chrome:
**1596 pruebas distintas**. Las 336 incorporadas en 7B son 145 unitarias,
161 MySQL, 27 PHP y 3 Chrome; se conservan las 1260 de entrada.
MySQL ejecutó 605 en la regresión completa y después las 161 de 7B con los
cinco casos nuevos de IDs fuera de rango. Su unión es 610, sin duplicar pruebas.
La suite PHP ordinaria omite los 16 tests browser por opt-in; se ejecutaron todos
por separado con AUTH_BROWSER_TEST=1. Verificación final específica de formularios:
27 PHP y 3 Chrome verdes, sin contarlos dos veces. Lint de los 55 PHP válido.
git diff --check y whitespace de todos los archivos nuevos correctos.
Unitarias y HTTP compartidas cubren CRUD funcional, workflow, RBAC, IDOR,
actor spoof, mass assignment, query/order injection, límite de páginas, relación
cross-audit, inexistencias, duplicados, archivo ausente, refs documentales,
legacy inconsistente, eventos, rollback y fallo post-commit sin pérdida de archivo.
MySQL temporal ejecuta el mismo contrato y verifica PK/FKs reales, numeración
con snapshot previo, doble actualización/estado/enlace, cierre contra edición,
estado, creación, asociación, nota y archivo, y carga ganadora contra cierre.
Fixtures generan schemas aleatorios y verifican identidad antes de cleanup;
el engine real está prohibido en tests y Alembic solo opera en schemas temporales.

PHP real con API double: CSRF, whitelist, permisos, expiración, mensajes seguros,
versión esperada, formularios, consulta inversa, filtros, paginación y XSS.
Chrome real aislado: 1440/390/320, overflow, labels, teclado Tab, navegación,
creación/edición/asociación/cierre del hallazgo y ausencia de JWT en DOM.
No se usan doubles de navegador; solo la API y Siteverify tienen doubles locales.

Autoauditoría corrigió la validación tardía de título vacío de archivo que podía
fallar después de commit, el rollback de lógica ante evento de asociación fallido
y la conservación de resolución de documento desde versión al introducir el DTO
multipart. Verificó también la exclusión de referencias legacy incoherentes en
conteos/lecturas y la conservación del archivo confirmado ante refresh fallido.
Hay regresiones de cada frontera.
La última revisión añadió límites BIGINT UNSIGNED con cinco regresiones HTTP
compartidas para IDs fuera de rango, evitando enviarlos al driver SQL.
Se endurecieron vacío/tamaño/nombre y metadata de headers. No se debilitaron tests.
El primer intento Chrome dentro del sandbox falló al conectar DevTools; las
mismas pruebas pasaron con ejecución autorizada fuera del sandbox.

## 13. BD real y deuda técnica

Solo SELECT/Alembic current real; ningún smoke de escritura, login nuevo,
DELETE/TRUNCATE/DROP ni cambio de usuarios/auditorías existentes. No se requirió
backup ni autorización de migración porque no hubo DDL ni escritura real.
Las tablas de hallazgos, vínculos y evidencias reales continúan vacías y existe
una auditoría; la revisión sigue 005. Storage real no fue utilizado por tests.

Deuda real heredada: catálogos de creación de evidencia aún reutilizan
api_get_all de auditorías/documentos (límite 10000), y PHP no certifica formatos
de archivo. Instalaciones grandes necesitan búsquedas paginadas de esos catálogos.
Multipart tiene spool previo al límite del servicio; límites de ingreso deben
alinearse al operar el servidor. La serialización por auditoría prioriza integridad
y puede limitar throughput de cargas simultáneas largas. No hay benchmarks masivos.
Actor por ID se presenta cuando no hay nombre autorizado. No hay smoke real 7B;
la evidencia de aceptación proviene de suites aisladas, incluida MySQL real temporal.
Dependencias de tests muestran warnings de depreciación Starlette/httpx/anyio.
Queda listo para auditoría independiente de Antigravity, sin commit ni push.

## 14. Comandos de regresión reproducibles

Desde `api`, cada --basetemp debe ser un directorio temporal nuevo:

```powershell
.\venv\Scripts\python.exe -m pytest tests_unit -q -p no:cacheprovider --basetemp=<tmp-nuevo-unit>
$env:AUTH_MYSQL_TEST='1'
.\venv\Scripts\python.exe -m pytest tests_auth_mysql -q -p no:cacheprovider --basetemp=<tmp-nuevo-mysql>
```

Desde la raíz:

```powershell
.\api\venv\Scripts\python.exe -m pytest frontend/tests -q -p no:cacheprovider --basetemp=<tmp-nuevo-php>
$env:AUTH_BROWSER_TEST='1'
.\api\venv\Scripts\python.exe -m pytest frontend/tests/test_auth_browser.py frontend/tests/test_turnstile_browser.py frontend/tests/test_auditorias_browser.py frontend/tests/test_hallazgos_browser.py -q -p no:cacheprovider --basetemp=<tmp-nuevo-browser>
```

Incluye suites 6A, 6B.1, 6B.2, 6B.3, 6B.4A, 6B.4B, 6C, 6D, 6D.1 y 7A.
6A utiliza el adaptador test_6a_regression_mysql.py con schema aleatorio; no
ejecutar `api/tests` directamente con su fixture legacy de schema fijo.
Las pruebas de 7A conservan workflow, terminales, IDOR, locks y eventos;
upgrade/downgrade de 005 y bootstrap solo suceden en schemas temporales.

## 15. Inventario de cambios y Git final

14 archivos nuevos:

```text
api/app/routers/hallazgos.py
api/app/schemas/hallazgo.py
api/app/services/hallazgo_service.py
api/tests_unit/test_hallazgo_unit.py
api/tests_auth_mysql/test_hallazgo_mysql.py
frontend/services/hallazgo_form.php
frontend/services/hallazgos_controller.php
frontend/pages/hallazgos.php
frontend/pages/hallazgos_list.php
frontend/pages/hallazgo.php
frontend/pages/hallazgo_form.php
frontend/tests/test_hallazgos.py
frontend/tests/test_hallazgos_browser.py
docs/FASE_7B_HALLAZGOS_EVIDENCIAS.md
```

`git diff --stat` de los 20 archivos previamente tracked (sin staging):

```text
 api/README.md                                    |  3 ++
 api/app/core/config.py                           |  1 +
 api/app/main.py                                  |  2 ++
 api/app/routers/evidencias.py                    | 26 +++++++++-----
 api/app/schemas/evidencia.py                     | 28 +++++++++++++--
 api/app/services/authorization_service.py        | 20 ++++++++++-
 api/app/services/evidencia_service.py            | 44 ++++++++++++++++++++++--
 frontend/README.md                               |  6 ++++
 frontend/assets/css/estilos.css                  |  3 ++
 frontend/includes/auth.php                       |  4 ++-
 frontend/index.php                               |  9 ++++-
 frontend/pages/auditoria.php                     |  5 ++-
 frontend/pages/evidencia.php                     |  3 ++
 frontend/pages/evidencia_nueva.php               |  9 ++---
 frontend/services/api_client.php                 |  8 ++---
 frontend/services/api_errors.php                 |  2 +-
 frontend/services/auditorias_controller.php      |  4 +++
 frontend/services/evidencia_controller.php       |  3 ++
 frontend/services/evidencia_nueva_controller.php | 14 +++++++-
 frontend/tests/conftest.py                       | 17 +++++++++
 20 files changed, 184 insertions(+), 27 deletions(-)
```

Git diff no incluye por diseño los 14 archivos nuevos todavía untracked, que
contienen el módulo y las regresiones: el inventario completo es de **34 archivos**.
`git status --short` final: los 20 anteriores con ` M` y los 14 nuevos con `??`;
ningún archivo staged, sin migraciones, secretos, logs, storage ni artifacts de test.
HEAD y origin/main permanecen en 3684e95; rama main. Se eliminó únicamente el
basetemp propio de la primera prueba dentro del repositorio, verificando su ruta
absoluta; las demás pruebas usaron nuevos directorios del TEMP de Windows.

## 16. Corrección puntual posterior a la auditoría de Antigravity

Se corrigieron siete caracteres sustituidos por `?` en cinco líneas de
frontend/pages/auditoria.php, frontend/pages/evidencia.php, api/README.md y
frontend/README.md: auditoría, Paginación, gestión, migración, Creación,
asociación y atómica. La revisión específica de las líneas añadidas del diff
y de todos los archivos nuevos no detectó más corrupción; se conservaron los
signos legítimos de código y URLs. Los 34 archivos de 7B son UTF-8 sin BOM.

El límite autoritativo de evidencias permanece en MAX_EVIDENCE_FILE_BYTES:
20 * 1024 * 1024 = 20 971 520 bytes (20 MiB). Se verificaron tanto el valor
por defecto del modelo Settings como el valor efectivo del entorno local.
LimitedStream compara contra esa configuración y rechaza cuando el total
es mayor al límite. El test de frontera usa una configuración temporal de
8 bytes para comprobar vacío, exceso y compensación; no redefine la política.

PHP local tiene upload_max_filesize=40M y post_max_size=40M. Son límites de
recepción independientes del límite de negocio. Se ajustó exclusivamente
el texto del formulario de evidencia para distinguir ambos y explicar que
se aplica el más restrictivo; frontend/README.md documenta la misma política.
No se modificaron configuración, lógica backend/frontend, tests ni almacenamiento.
La regresión posterior usa SQLite/storage temporal y PHP con API double;
no se repitió la suite completa ni se escribieron datos reales.

Resultado posterior: 186 unitarias relevantes (hallazgos, consistencia de archivos
y rutas de archivos), 103 frontend (hallazgos, auditorías, descargas y auth/RBAC),
55 archivos PHP con lint válido y git diff --check correcto. Sin commit ni push;
los cambios permanecen sin staging y listos para commit.
