# Fase 8 — QA, seguridad, rendimiento y endurecimiento integral

Fecha de ejecución: 8 de octubre de 2026. Repositorio: `G19X-TESCI-SCB-866-ACADEMIC`.

## 1. Objetivo y alcance

Regresión de todas las fases construidas, ataques de autorización y entradas, fallos de transacción/storage, carreras, Chrome real y carga HTTP sobre MySQL efímero. Se corrigieron defectos reproducidos. Se conserva FastAPI/PHP/MySQL, sin servicios nuevos, dependencias nuevas, migración 006 ni cambios de funcionalidad aprobada.

Este documento distingue contratos automatizados, inspección de código y mediciones. Las pruebas de cada fase siguen siendo la especificación de sus reglas; no se interpretan nombres de roles como permisos adicionales.

## 2. Baseline Git

Antes de editar se ejecutaron los seis comandos de preflight. Rama `main`, working tree limpio, `git diff --check` limpio y HEAD idéntico a `origin/main`:

```text
eec566d5a00c63925ef953b4a6a8d4f550168824
feat(analysis): implement phase 7E explainable document anomaly detection
```

Origen verificado: `github.com/samcruzb11-creator/G19X-TESCI-SCB-866-ACADEMIC.git`. No se ejecutó `git add`, `commit`, `push`, `reset` ni `checkout`. El resultado se entrega como working tree para revisión independiente.

## 3. Entorno técnico y protección de recursos

Windows 11, build 26200; 12 procesadores lógicos; 33,461,829,632 bytes de RAM. Python 3.14.7 de `api/venv`; PHP 8.2.12 de XAMPP; Chrome 154.0.8037.98 real mediante CDP. MySQL 8.0.46/InnoDB, aislamiento REPEATABLE READ. Alembic actual/head `005`; upgrades/downgrades 001–005 probados con datos centinela preservados.

Dependencias instaladas: FastAPI 0.141.1, Uvicorn 0.52.4, SQLAlchemy 2.0.54, PyMySQL 1.2.3, Alembic 1.20.0, pydantic-settings 2.15.0, pwdlib 0.3.1, python-jose 3.5.0, httpx 0.28.1 y python-multipart 0.0.32. Todas satisfacen `requirements.txt`; `pip check` verde. No se actualizaron paquetes.

La BD `sistema_trazabilidad` se consultó mediante transacciones explícitas READ ONLY. Sus filas completas y DDL se incluyeron en el fingerprint sin exportar datos personales ni hashes de contraseñas. El storage real sólo se leyó para tamaño y SHA-256.

Las mutaciones usaron schemas aleatorios `sistema_trazabilidad_test_auth_<16 hex>`, migraciones reales, cuentas/sesiones sintéticas y storage temporal. Los fixtures y el benchmark comprueban `SELECT DATABASE()`; abortan ante la BD real o ante un schema distinto del creado por la fábrica. El engine de la aplicación real queda bloqueado para conexiones durante el benchmark. No se llamó a Turnstile ni SMTP externos.

La cuenta del sandbox falló al crear procesos (Windows 1909). Se repitieron las ejecuciones necesarias mediante un runner temporal expresamente autorizado. Los errores iniciales de Chrome por esa cuenta no se confundieron con defectos del producto; Chrome se repitió hasta obtener resultados funcionales.

## 4. Inventario funcional y dependencias

<!-- phase8-inventory -->

Inventario medido: **10 routers, 61 operaciones HTTP (55 privadas), 23 páginas PHP y 66 archivos PHP**. Los cinco endpoints públicos son auth; la operación restante es estado raíz. No hay CRUD de usuarios/áreas ni refresh escondido.

| Módulo | Operaciones y dependencias reales |
|---|---|
| Auth y sesiones | login, me, logout, JWT HS256, sesión persistida, usuario activo y rol canónico; no existe refresh |
| Protección pública | presupuestos globales/por identificador, bloqueo temporal, Argon2 acotado, Turnstile con transporte sustituible |
| Acceso y recuperación | solicitudes genéricas, resolución ADMIN, contraseña inicial, reset single-use, cola y worker de correo |
| Catálogos | lectura de usuarios elegibles y áreas; no hay CRUD de usuarios/áreas expuesto |
| Auditorías | creación, detalle, filtros, actualización ADMIN, transiciones y eventos; responsables elegibles |
| Documentos/versiones | cabecera, ownership, carga en streaming, vigente, versiones y descarga; FK de área/usuario |
| Evidencias | FILE/NOTE/REFERENCE/OTHER; auditoría y vínculos documentales consistentes; asociación a hallazgo |
| Hallazgos | responsable, fechas, cierre/ACCEPTED_RISK, evidencias y estados de auditoría |
| Aprobaciones | rondas de versión exacta, asignaciones, decisiones propias, precedencia y terminales |
| Eventos | actor autenticado, historial autorizado, whitelist de actividad y metadatos de dominio |
| Dashboard 7D | agregación SQL tras scope, resumen, indicadores, alertas y actividad |
| Análisis 7E | reglas deterministas, duplicados sólo visibles, metadata, similitud/storage acotados y barrera fresca de permisos |
| PHP | sesión server-side, cliente API, CSRF, navegación por rol, formularios, descargas y errores sanitizados |

El vínculo documento↔auditoría determina scopes de auditores; las rondas requieren una versión concreta. Dashboard y análisis derivan visibilidad de esos módulos. El frontend depende de API disponible y trata sus fallos como errores, sin fabricar datos.

<!-- phase8-endpoints -->

| Método | Ruta | Autenticación |
|---|---|---|
| POST | /api/v1/documentos | Sí |
| GET | /api/v1/documentos | Sí |
| GET | /api/v1/documentos/{documento_id} | Sí |
| PATCH | /api/v1/documentos/{documento_id} | Sí |
| POST | /api/v1/documentos/{documento_id}/versiones | Sí |
| GET | /api/v1/documentos/{documento_id}/versiones | Sí |
| GET | /api/v1/documentos/{documento_id}/versiones/{version_id}/descargar | Sí |
| GET | /api/v1/documentos/{documento_id}/historial | Sí |
| GET | /api/v1/evidencias | Sí |
| POST | /api/v1/evidencias/archivo | Sí |
| POST | /api/v1/evidencias/logica | Sí |
| GET | /api/v1/evidencias/{evidencia_id} | Sí |
| GET | /api/v1/evidencias/{evidencia_id}/descargar | Sí |
| GET | /api/v1/areas | Sí |
| GET | /api/v1/usuarios | Sí |
| GET | /api/v1/auditorias | Sí |
| POST | /api/v1/auditorias | Sí |
| GET | /api/v1/auditorias/{audit_id} | Sí |
| PATCH | /api/v1/auditorias/{audit_id} | Sí |
| POST | /api/v1/auditorias/{audit_id}/estado | Sí |
| GET | /api/v1/auditorias/{audit_id}/historial | Sí |
| GET | /api/v1/hallazgos | Sí |
| POST | /api/v1/hallazgos | Sí |
| GET | /api/v1/hallazgos/{finding_id} | Sí |
| PATCH | /api/v1/hallazgos/{finding_id} | Sí |
| POST | /api/v1/hallazgos/{finding_id}/estado | Sí |
| POST | /api/v1/hallazgos/{finding_id}/evidencias | Sí |
| GET | /api/v1/hallazgos/{finding_id}/evidencias | Sí |
| GET | /api/v1/hallazgos/{finding_id}/historial | Sí |
| GET | /api/v1/aprobaciones | Sí |
| POST | /api/v1/aprobaciones | Sí |
| GET | /api/v1/aprobaciones/recursos | Sí |
| GET | /api/v1/aprobaciones/aprobadores | Sí |
| GET | /api/v1/aprobaciones/{round_id} | Sí |
| POST | /api/v1/aprobaciones/{round_id}/iniciar | Sí |
| POST | /api/v1/aprobaciones/{round_id}/cancelar | Sí |
| POST | /api/v1/aprobaciones/{round_id}/finalizar | Sí |
| POST | /api/v1/aprobaciones/{round_id}/decision | Sí |
| GET | /api/v1/aprobaciones/{round_id}/decisiones | Sí |
| GET | /api/v1/aprobaciones/{round_id}/historial | Sí |
| GET | /api/v1/dashboard/resumen | Sí |
| GET | /api/v1/dashboard/indicadores | Sí |
| GET | /api/v1/dashboard/alertas | Sí |
| GET | /api/v1/dashboard/actividad | Sí |
| GET | /api/v1/analisis/resumen | Sí |
| GET | /api/v1/analisis/anomalias | Sí |
| GET | /api/v1/analisis/documentos/{resource_id} | Sí |
| GET | /api/v1/analisis/versiones/{resource_id} | Sí |
| POST | /api/v1/auth/login | Público |
| GET | /api/v1/auth/me | Sí |
| POST | /api/v1/auth/logout | Sí |
| POST | /api/v1/auth/access-requests | Público |
| POST | /api/v1/auth/password-reset/request | Público |
| POST | /api/v1/auth/password-reset/confirm | Público |
| POST | /api/v1/auth/initial-password/confirm | Público |
| GET | /api/v1/access-requests | Sí |
| GET | /api/v1/access-requests/{request_id} | Sí |
| POST | /api/v1/access-requests/{request_id}/approve | Sí |
| POST | /api/v1/access-requests/{request_id}/reject | Sí |
| POST | /api/v1/access-requests/{request_id}/resend | Sí |
| GET | / | Público |

Páginas medidas: `access_requests.php`, `analisis.php`, `aprobaciones.php`, `aprobaciones_list.php`, `auditoria.php`, `auditorias.php`, `auditoria_nueva.php`, `dashboard.php`, `dashboard_alertas.php`, `documento.php`, `documentos.php`, `documento_nuevo.php`, `error.php`, `evidencia.php`, `evidencias.php`, `evidencia_nueva.php`, `hallazgo.php`, `hallazgos.php`, `hallazgos_list.php`, `hallazgo_form.php`, `login.php`, `pendiente.php`, `public_auth.php`.

## 5. Suites ejecutadas y calidad de pruebas

Se ejecutaron `api/tests_unit`, `api/tests_auth_mysql` y `frontend/tests` completos con pytest, sin cacheprovider y con basetemp fuera del repositorio. `AUTH_MYSQL_TEST=1` y `AUTH_BROWSER_TEST=1` activaron MySQL y navegador reales. Para 6A se usó `test_6a_regression_mysql.py`, que importa los contratos históricos sobre la fábrica protegida; no se ejecutó el conftest antiguo de schema fijo contra recursos reales.

Baseline de suites del checkpoint: unit 1,192 passed; MySQL 1,069 collected, 1,067 passed y dos fallos de lanzamiento Chrome por sandbox; frontend 312 collected, 263 passed y 49 fallos del mismo entorno. Esos fallos se repitieron con Chrome autorizado. Los defectos de producto se reprodujeron por ataques nuevos y carga; no se adjudicó a la aplicación un fallo de permisos del runner.

Cobertura histórica:

| Fase | Contratos reejecutados |
|---|---|
| 6A | storage, hashes, versiones, evidencias, eventos, rollback/commit y consistencia de archivos |
| 6B.1 | JWT, sesión persistente, expiración, revocación, bootstrap y PHP auth |
| 6B.2 | RBAC/IDOR, actor autenticado, catálogos y scopes documentales |
| 6B.3 | navegación y formularios PHP con permisos efectivos |
| 6B.4A | límites de login, concurrencia Argon2, persistencia y pruning |
| 6B.4B | Turnstile, configuración, transportes negativos, replay y bypass |
| 6C | solicitud, resolución, contraseña inicial, reset, correo y carreras |
| 6D/6D.1 | formularios, registro seguro, metadata de evidencias y regresiones asociadas |
| 7A | auditorías, estados, concurrencia y frontend |
| 7B | hallazgos, fechas/cierre, evidencias, scopes y frontend |
| 7C | aprobaciones, decisiones/rondas, conflictos, E2E y browser |
| 7D | aggregates/ratios/alertas/activity, leakage, budgets, E2E y browser |
| 7E | duplicados/metadatos/legacy, scopes, barrera de revocación, límites, E2E y browser |
| 8 | snapshots obsoletos, entradas inválidas, atomicidad de límites, spills MySQL, colisiones, junctions, admisión y E2E sistémico |

<!-- phase8-tests -->

| Suite | Collected | Passed | Failed | Skipped | Warnings | Duración |
|---|---|---|---|---|---|---|
| api/tests_unit | 1212 | 1212 | 0 | 0 | 2 | 53.783 s |
| api/tests_auth_mysql | 1138 | 1138 | 0 | 0 | 2 | 482.832 s |
| frontend/tests | 312 | 312 | 0 | 0 | 0 | 376.792 s |

**2,662 ejecuciones verdes, 1,937 contratos distintos, 725 ejecuciones importadas/repetidas**. Cero fallos y cero skips finales. Los cuatro warnings registrados corresponden a dos deprecaciones repetidas en las dos suites backend. Reruns de reproducción/diagnóstico no aumentan estos totales.

<!-- phase8-storage-rerun -->

Después del ajuste final UTF-16 se repitió toda la suite unitaria y la regresión MySQL de 6A + Fase 8 sistema/E2E: **91 casos MySQL adicionales verdes**, cero fallos/skips. Es un rerun de contratos ya contados arriba. Frontend y el resto de MySQL se habían ejecutado completos sobre los demás fixes; el ajuste sólo corrige la validación previa a IO de rutas Win32 con Unicode astral.

El conteo de contratos distintos se obtiene por archivo original de la función, nombre y parámetro de pytest. Las importaciones de contratos unitarios en las suites MySQL cuentan como otras ejecuciones del mismo contrato, con evidencia adicional del motor real. No se suman reruns, probes ni suites importadoras como contratos nuevos.

Dos deprecaciones conocidas de Starlette/httpx y el alias BlockingPortal de AnyIO permanecen documentadas. No afectan los resultados y no justifican migrar dependencias en esta fase.

La revisión AST de tests sin `assert` encontró validaciones cuyo fallo es una excepción y wrappers que llaman helpers con aserciones. No son tests vacíos. Se corrigieron fixtures de fallos que dejaban `activo`/estado sin valor y un mock de `scalar` que dependía del número de consultas. Las pruebas críticas de autorización/transacción usan MySQL real; los doubles se reservan para fallos y servicios externos.

## 6. Matriz RBAC efectiva

`S` significa sólo recursos dentro del scope aprobado. ADMIN accede a las operaciones de gestión conocidas; una decisión mantiene la identidad del aprobador asignado.

| Recurso/operación | ADMIN | AUDITOR_INTERNO | AUDITOR_EXTERNO | RESPONSABLE_AREA | APROBADOR |
|---|---|---|---|---|---|
| Login/me/logout | Propia | Propia | Propia | Propia | Propia |
| Solicitudes: listar/resolver | Sí | No | No | No | No |
| Áreas | Sí | Sí | Sí | Sí | Sí |
| Usuarios elegibles | Sí | Sí | No | No | No |
| Auditorías: lectura | Sí | S: responsable | S: responsable | No | No |
| Auditorías: crear | Sí | Responsable propio | No | No | No |
| Auditorías: editar/estado/historial | Sí | No | No | No | No |
| Documentos/versiones: leer/descargar | Sí | S: documento ligado | S: documento ligado | S: propietario | S: versión asignada |
| Documentos: crear/editar/upload | Sí | No | No | Propio; sin reasignarse a otro | No |
| Historial documental | Sí | No | No | No | No |
| Evidencias: leer/crear | Sí | S: auditoría | S: auditoría | No | No |
| Hallazgos: leer | Sí | S: auditoría | S: auditoría | No | No |
| Hallazgos: crear/editar/estado/vínculo | Sí | S: auditoría | No | No | No |
| Historial de hallazgo | Sí | No | No | No | No |
| Aprobaciones: lectura/historial | Sí | S: versión exacta ligada | S: versión exacta ligada | S: documento propio | S: asignación |
| Aprobaciones: gestionar ronda | Sí | S: versión exacta ligada | No | No | No |
| Aprobaciones: decidir | Identidad asignada, sin suplantación | No | No | No | Asignación propia |
| Dashboard/análisis | Recursos legibles | Recursos legibles | Recursos legibles | Recursos legibles | Recursos legibles |

Se revisaron todos los routers activos y se atacaron todas las operaciones privadas sin credenciales: 401, incluso si los cuerpos son inválidos. ID propio/ajeno/inexistente y válido en otro contexto mantienen 403/404 sin revelar recursos. Los tests metamórficos añaden datos privados y comprueban que no alteran resultados visibles.

## 7. Pruebas adversariales globales

| Ataque | Evidencia y resultado |
|---|---|
| RBAC/IDOR | Matrices reales para los cinco roles, asignaciones ajenas, versiones fuera de ronda/auditoría, eventos y contextos dashboard/análisis |
| Actor spoofing | Los parámetros legacy de actor se ignoran; actor de versión, evidencia, hallazgo, transición y decisión deriva de autenticación |
| Mass assignment | Contratos mutativos rechazan campos extra; en documentos se cerró la aceptación silenciosa y se validó estado/null/refs |
| SQLi | Filtros/búsqueda/IDs/códigos con payloads; ORM parametrizado; revisión de text/execute/f-strings. SQL raw de migraciones constante y pruning con tablas internas whitelist |
| XSS | Texto persistente sintético en nombres, área, auditoría, documento, evidencia, hallazgo y comentario; escaping PHP y Chrome sin ejecución |
| CSRF | POST sin token, inválido y de otra sesión; acciones GET no mutan. Token de sesión reutilizable para formularios es el diseño actual |
| Traversal | Separadores Windows/POSIX, absolutos, UNC, codificación, NUL/control, symlink/junction; nunca se lee/escribe fuera de la raíz administrada |
| Entradas extremas | IDs de 401 dígitos retornan error de cliente; paginación acotada; campos/arrays y enums estrictos; Unicode/extensiones y límites de bytes |
| Leakage | Aggregates, ratios, duplicates, hashes privados y actividad condicionados por permisos antes de comparar/paginar |

El fuzzing se complementó con inspección de consultas y schemas. No se confunde el responsable/owner legítimo con el actor de una acción.

## 8. Autenticación, sesiones y enumeración

Usuario inexistente, contraseña incorrecta, inactivo, sesión inexistente/revocada/expirada, JWT malformed/manipulado/firma inválida, claims faltantes y rol legacy inválido fallan cerrados. Logout repetido/revocación se probó. No existe refresh que probar.

Los contratos públicos de login no distinguen inexistente/inactivo/contraseña errónea con mensajes útiles para enumeración. El login usa hash dummy; límites pueden producir 429/428 por estado de protección, sin afirmar existencia. Reset/request responde genéricamente antes del lookup diferido, y access-request no comunica si ya hay usuario o solicitud. Se revisaron status/body/headers/tamaño y diseño de tiempos; no se atribuye relevancia a microdiferencias de tiempo ni se afirma indistinguibilidad criptográfica.

<!-- phase8-enumeration -->

| Ruta | Sujeto sintético | n | HTTP | Bytes | min ms | p50 ms | max ms |
|---|---|---|---|---|---|---|---|
| /auth/login | existing | 4 | 401 | 55 | 34.75 | 35.5 | 36.12 |
| /auth/login | missing | 4 | 401 | 55 | 35.56 | 36.18 | 36.59 |
| /auth/login | inactive | 4 | 401 | 55 | 35.61 | 36.3 | 36.57 |
| /auth/password-reset/request | existing | 2 | 202 | 121 | 5.37 | 9.84 | 14.31 |
| /auth/password-reset/request | missing | 2 | 202 | 121 | 4.77 | 5.25 | 5.74 |
| /auth/password-reset/request | inactive | 2 | 202 | 121 | 4.9 | 5.05 | 5.21 |
| /auth/access-requests | existing | 2 | 202 | 130 | 5.05 | 5.94 | 6.82 |
| /auth/access-requests | missing | 2 | 202 | 130 | 4.97 | 5.46 | 5.94 |
| /auth/access-requests | inactive | 2 | 202 | 130 | 4.9 | 4.93 | 4.97 |

En cada ruta, status, cuerpo exacto, longitud y todos los headers de aplicación coincidieron entre existente/inexistente/inactivo (se excluyeron Date/Server). Login ejecuta Argon2 en los tres casos; los rangos observados se solapan. Reset/access se encolan sin SMTP. Las muestras son una comprobación de diferencias obvias; no sustentan una afirmación sobre microcanales estadísticos.

La revalidación de actor/ownership después de locks corrige permisos obsoletos bajo REPEATABLE READ. La barrera final de análisis comprueba identidad, sesiones y digest de visibilidad en una transacción fresca; si cambió el scope descarta la respuesta con 409. Devuelve primero la conexión original, evitando exigir dos slots simultáneos.

## 9. Rate limiting y Turnstile

Login: buckets MySQL por identificador, ventana/failures temporal, presupuesto global 120/min por defecto, 10/min por identificador, Argon2 60/min y dos hashes simultáneos. Los tests cubren usuarios múltiples, reinicio, expiración, éxito tras bloqueo y carreras. No se confía en un IP suministrado por el cliente.

Reset: tres solicitudes/hora por identificador y 20/min global. Access request: dos/día por identificador y 10/min global. Confirmaciones/hash tienen sus presupuestos existentes. La carga conserva los límites; 429 se contabiliza como respuesta esperada, separada de logins exitosos.

Turnstile usa doubles de transporte: ausente, inválido, respuesta negativa, timeout/servicio caído, action/hostname/challenge_ts, replay, bypass, modo disabled/test/enabled y configuración inválida. No hubo llamadas reales a Siteverify ni reutilización de secretos reales.

## 10. Password reset

Token inexistente/expirado/usado, doble consumo, contraseña débil, usuario desactivado, token de otro sujeto y carreras se rechazan. Dos confirmaciones concurrentes no consumen el token dos veces. Token almacenado como hash y ligado al fingerprint del sujeto; cambios del usuario invalidan el estado esperado. La cola difiere el lookup y no enumera cuentas. No se añadió una regla de contraseña distinta a la anterior que el contrato no exigía.

## 11. Access request y correo

Duplicate/case/Unicode, usuario ya existente, ADMIN inexistente/no elegible, resolución previa, aprobar dos veces, approve/reject concurrentes y alta inicial concurrente mantienen una sola resolución/cuenta. Se verificaron UNIQUE/FK/CHECK en MySQL temporal y errores públicos genéricos.

Worker/cola: claims con lease, retry, fallos de envío/commit, estado cambiado durante entrega, expiración y destinatario autorizado mediante dobles. No se configuró SMTP real. No se guardan passwords/JWT en eventos ni logs; los jobs contienen únicamente el estado necesario para el flujo aprobado.

## 12. Storage y uploads

Paths se validan antes de IO. Se rechazan absolutos, drives/UNC, traversal, porcentaje, NUL/control, symlink y junction, incluso si su destino está dentro del root. Cleanup ahora comparte esa validación. Se probaron junctions Windows reales a destinos sintéticos dentro/fuera del storage; sus archivos permanecen intactos.

Nombre original tiene 255 caracteres como máximo; el sufijo final lowercased se valida incluyendo ambos UUID y `.tmp_`, con 255 bytes por componente. En Windows se comprueba la ruta temporal completa frente a MAX_PATH antes de crear directorios. El fallo con extensión Unicode expandida y rutas largas se reprodujo como 500; ahora es error de cliente sin huérfanos. [Límite Win32 documentado](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation?tabs=cmd).

La última autoauditoría reprodujo también el borde con 40 emojis en la extensión: 245 caracteres Python se convierten en 285 unidades UTF-16. El guard Win32 cuenta ahora unidades UTF-16, incluido el sufijo temporal; rechaza antes de crear directorios. Su test de regresión es específico de Windows.

MIME es metadata declarada, no prueba del contenido. Los archivos permanecen fuera del webroot y se descargan como adjuntos. Extensión doble/MIME falso no convierte el upload en ejecución. Hash/tamaño se calculan desde bytes en streaming.

Documentos antes no tenían un límite equivalente al de evidencias: ahora `MAX_DOCUMENT_FILE_BYTES`, default 20 MiB, se aplica en streaming. Vacío documental conserva el comportamiento aprobado; evidencia FILE vacía se rechaza. Se probaron cero/límite exacto/+1 con límite sintético pequeño para verificar el camino de corte/rollback sin traficar archivos grandes innecesarios. PHP puede tener un límite más restrictivo.

Un archivo multipart adicional, no usado por el handler, eludía el límite del archivo elegido y podía ser spooled sin techo. Ahora el cuerpo completo tiene límite del archivo + 128 KiB de metadatos; JSON/otras mutaciones admiten 1 MiB. El contador efectivo de bytes protege también requests sin longitud declarada o con longitud falsa. El rechazo temprano es 413; el corte multipart durante parsing es 400 y cierra los temporales parciales. Se probó su cleanup con el parser real y chunks separados. Un JSON válido muy profundo causaba RecursionError al serializar errores de validación; ahora el 422 devuelve loc/msg/type sin contenido crudo ni contexto arbitrario.

Colisión forzada de UUID: el archivo existente se conserva y la segunda escritura falla. Temporal exclusivo: una colisión no elimina el temporal del otro escritor. Publicación mediante hardlink atómico, con archivo completo y fsync antes de publicar; elimina el link temporal después. Requiere filesystem con hardlinks (NTFS/ext4). No existe overwrite del archivo final.

## 13. Atomicidad y BD ↔ storage

Se reejecutó 6A y su regresión de consistencia: guardar antes de flush/commit, rollback, fallo de FS/MySQL/refresh, commit durable seguido de fallo, commit de resultado desconocido, cleanup fallido y verificador read-only de archivos ausentes/huérfanos. Un fallo posterior a commit no elimina el archivo confirmado. Estado de commit ambiguo produce `COMMIT_OUTCOME_UNKNOWN`/503 y exige verificar antes de retry.

Las cargas normales/fallidas controladas dejan filas/archivos coherentes. El E2E confirma bytes en storage y FK/version_vigente/evento en BD. La corrección de colisiones protege archivos previos y el cleanup no sigue enlaces.

BD y filesystem no constituyen una transacción distribuida: una interrupción abrupta entre publicación y commit puede dejar un archivo huérfano. El mecanismo aprobado lo detecta con `storage_integrity` read-only; no se hace borrado automático ni se promete atomicidad frente a corte de energía. Esta limitación ya explícita se conserva como deuda operativa LOW.

## 14. Concurrencia e invariantes de dominio

Uploads simultáneos/versiones/vigente usan lock del documento y lectura locking del último número de versión. Se reprodujo la carrera con snapshot anterior a otra carga: ahora ambos commits producen números consecutivos y vigente correcto. Actor/ownership se refrescan tras esperar; inactivación/cambio de rol/reasignación comprometidos no autorizan escrituras obsoletas.

Auditorías: `PLANNED → IN_PROGRESS → IN_REVIEW → COMPLETED`, retorno aprobado `IN_REVIEW → IN_PROGRESS` y cancelación según reglas existentes. Terminales no reabren. Hallazgos: cierre/ACCEPTED_RISK, fechas, responsable, evidencia y auditoría terminal; API no ofrece bypass de PHP. Aprobaciones: decisiones propias single-use, ronda/version/contexto correcto, nueva ronda concurrente, cancelaciones/terminales y precedencia APPROVE/REJECT/CHANGES_REQUESTED.

Access request, reset, logout/revoke y análisis durante cambio de scope se reejecutaron. Los tests controlan interleavings, no dependen del orden de casos ni de datos reales. Alias case-insensitive/padded de terminales legacy bloquean uploads/evidencias/rondas; no se reinterpretan como estados activos.

## 15. Dataset de escala

<!-- phase8-dataset -->

| Entidad | Filas |
|---|---|
| usuarios | 1,001 |
| auditorias | 250 |
| documentos | 2,501 |
| versiones_documento | 5,000 |
| evidencias | 3,000 |
| hallazgos | 2,000 |
| rondas_aprobacion | 2,000 |
| decisiones_aprobacion | 4,000 |
| eventos_auditoria | 5,000 |

Los totales de usuarios y documentos incluyen un centinela de migración además de 1,000/2,500 filas sintéticas.

Cinco roles distribuidos, usuarios sin recursos, 250 auditorías pequeñas/grandes, una auditoría con 500 documentos, documentos compartidos entre auditorías, pares duplicados y datos centinela legacy válidos. 5,000 archivos sintéticos pequeños en storage, con bytes/tamaño/SHA verdaderos. Evidencias de escala NOTE; FILE y sus errores se cubren en regresión/E2E. No se copió ningún PDF ni usuario real.

El dataset pequeño comparable contiene 21 usuarios, dos auditorías, 21 documentos, 40 versiones, 20 evidencias/hallazgos/rondas, 40 decisiones/eventos. Los presupuestos se comparan en ambos schemas migrados, con autenticación HTTP real.

## 16. Metodología de carga HTTP

Cliente httpx → Uvicorn/FastAPI real → MySQL efímero real; sesión JWT obtenida mediante login real, sin override de actor/auth. Sólo get_db/storage se redirigen a los recursos temporales guardados. Pool exactamente igual al de aplicación: 5 + 10 overflow, timeout 30 s. Un proceso de servidor y cliente local en la misma máquina.

Perfiles: 1, 10, 25, 50, 100 y 250 si estables. Cada perfil ejecuta todos los endpoints requeridos; `max(4, concurrencia)` requests por endpoint. Los presupuestos de login se reinician exclusivamente en el schema temporal entre perfiles, sin debilitar la configuración. No se interpreta el dataset de 1,000 usuarios como requisito de 1,000 requests simultáneos. No se intentaron 500/1,000 simultáneos.

El timeout del cliente final es 240 s para observar una ráfaga coordinada en cola; no es un SLA. p50/p95/p99 son estadísticas empíricas de cada lote, no una prueba de capacidad sostenida ni percentiles poblacionales. Login protegido debe leerse separando 200 y 429; su throughput mezcla ambos tipos.

Percentiles finales calculados con interpolación lineal de posiciones `(n−1)q`; p50 corresponde a la mediana. Los lotes de cuatro requests no permiten inferir una cola estadística estable.

PHP real atraviesa todo el E2E. La suite PHP/browser no sustituye la carga directa del backend. No se extrapola el servidor PHP de desarrollo, serial en Windows, a capacidad de Apache en producción.

## 17. Métricas de carga

<!-- phase8-load -->

**4,829 requests: 4,427 éxitos, 402 rechazos 429 esperados de login, cero 5xx y cero timeouts.** Sin errores SQL ni deadlocks en la ejecución final.

| Endpoint | Conc. | Req. | 2xx | 4xx | 5xx | rps | min ms | p50 ms | p95 ms | p99 ms | max ms | timeout | SQL leases máx. | SQL leases final | Threads SQL al cerrar |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| /auth/me | 1 | 4 | 4 | 0 | 0 | 163.781 | 5.09 | 5.39 | 8.0 | 8.36 | 8.45 | 0 | 1 | 0 | 3 |
| /auditorias | 1 | 4 | 4 | 0 | 0 | 82.036 | 10.52 | 11.4 | 14.75 | 15.22 | 15.33 | 0 | 1 | 0 | 3 |
| /auditorias/10 | 1 | 4 | 4 | 0 | 0 | 103.516 | 7.84 | 9.39 | 11.6 | 11.87 | 11.93 | 0 | 1 | 0 | 3 |
| /documentos | 1 | 4 | 4 | 0 | 0 | 131.577 | 6.79 | 7.07 | 9.07 | 9.32 | 9.38 | 0 | 1 | 0 | 3 |
| /hallazgos | 1 | 4 | 4 | 0 | 0 | 66.122 | 12.97 | 13.54 | 19.35 | 20.15 | 20.35 | 0 | 1 | 0 | 3 |
| /aprobaciones | 1 | 4 | 4 | 0 | 0 | 40.706 | 22.73 | 23.47 | 27.83 | 28.37 | 28.5 | 0 | 1 | 0 | 3 |
| /dashboard/resumen | 1 | 4 | 4 | 0 | 0 | 18.306 | 51.95 | 53.24 | 59.0 | 59.8 | 60.0 | 0 | 1 | 0 | 3 |
| /dashboard/alertas | 1 | 4 | 4 | 0 | 0 | 47.537 | 19.66 | 19.9 | 23.89 | 24.45 | 24.59 | 0 | 1 | 0 | 3 |
| /analisis/resumen | 1 | 4 | 4 | 0 | 0 | 2.122 | 455.96 | 458.18 | 504.83 | 511.23 | 512.83 | 0 | 1 | 0 | 3 |
| /analisis/anomalias | 1 | 4 | 4 | 0 | 0 | 2.123 | 467.75 | 471.02 | 474.23 | 474.29 | 474.31 | 0 | 1 | 0 | 3 |
| /auth/login | 1 | 4 | 4 | 0 | 0 | 20.632 | 46.94 | 47.52 | 51.15 | 51.65 | 51.78 | 0 | 1 | 0 | 3 |
| /auth/me | 10 | 10 | 10 | 0 | 0 | 93.346 | 91.11 | 94.84 | 99.73 | 101.01 | 101.33 | 0 | 9 | 0 | 6 |
| /auditorias | 10 | 10 | 10 | 0 | 0 | 91.503 | 93.02 | 99.09 | 103.48 | 104.41 | 104.64 | 0 | 10 | 0 | 6 |
| /auditorias/10 | 10 | 10 | 10 | 0 | 0 | 107.044 | 79.51 | 82.5 | 85.33 | 85.74 | 85.84 | 0 | 10 | 0 | 6 |
| /documentos | 10 | 10 | 10 | 0 | 0 | 101.944 | 82.04 | 87.13 | 91.63 | 93.11 | 93.48 | 0 | 10 | 0 | 6 |
| /hallazgos | 10 | 10 | 10 | 0 | 0 | 90.577 | 90.3 | 98.1 | 102.74 | 103.03 | 103.1 | 0 | 10 | 0 | 6 |
| /aprobaciones | 10 | 10 | 10 | 0 | 0 | 79.843 | 105.74 | 113.38 | 119.48 | 120.47 | 120.72 | 0 | 10 | 0 | 6 |
| /dashboard/resumen | 10 | 10 | 10 | 0 | 0 | 57.618 | 134.45 | 155.01 | 165.22 | 166.45 | 166.76 | 0 | 10 | 0 | 6 |
| /dashboard/alertas | 10 | 10 | 10 | 0 | 0 | 87.028 | 96.83 | 101.42 | 104.92 | 105.4 | 105.52 | 0 | 10 | 0 | 6 |
| /analisis/resumen | 10 | 10 | 10 | 0 | 0 | 3.766 | 565.99 | 1615.81 | 2621.3 | 2637.33 | 2641.33 | 0 | 2 | 0 | 6 |
| /analisis/anomalias | 10 | 10 | 10 | 0 | 0 | 3.729 | 585.05 | 1646.17 | 2628.17 | 2659.09 | 2666.82 | 0 | 2 | 0 | 6 |
| /auth/login | 10 | 10 | 2 | 8 | 0 | 88.736 | 76.8 | 85.97 | 109.85 | 110.1 | 110.16 | 0 | 10 | 0 | 6 |
| /auth/me | 25 | 25 | 25 | 0 | 0 | 122.805 | 165.2 | 172.72 | 180.92 | 181.55 | 181.6 | 0 | 15 | 0 | 6 |
| /auditorias | 25 | 25 | 25 | 0 | 0 | 96.43 | 220.82 | 229.48 | 237.38 | 239.19 | 239.74 | 0 | 15 | 0 | 6 |
| /auditorias/10 | 25 | 25 | 25 | 0 | 0 | 116.992 | 176.45 | 185.17 | 197.69 | 199.47 | 200.02 | 0 | 15 | 0 | 6 |
| /documentos | 25 | 25 | 25 | 0 | 0 | 110.282 | 189.3 | 198.78 | 208.04 | 208.71 | 208.86 | 0 | 15 | 0 | 6 |
| /hallazgos | 25 | 25 | 25 | 0 | 0 | 95.751 | 210.71 | 228.27 | 238.72 | 240.24 | 240.62 | 0 | 15 | 0 | 6 |
| /aprobaciones | 25 | 25 | 25 | 0 | 0 | 86.337 | 163.11 | 254.49 | 267.06 | 268.87 | 269.06 | 0 | 15 | 0 | 6 |
| /dashboard/resumen | 25 | 25 | 25 | 0 | 0 | 60.612 | 321.94 | 378.8 | 391.78 | 395.23 | 396.26 | 0 | 15 | 0 | 6 |
| /dashboard/alertas | 25 | 25 | 25 | 0 | 0 | 74.001 | 295.26 | 305.23 | 316.03 | 317.38 | 317.66 | 0 | 15 | 0 | 6 |
| /analisis/resumen | 25 | 25 | 25 | 0 | 0 | 3.939 | 608.11 | 3491.4 | 5921.29 | 6218.37 | 6307.05 | 0 | 2 | 0 | 6 |
| /analisis/anomalias | 25 | 25 | 25 | 0 | 0 | 3.484 | 628.52 | 3952.28 | 6678.38 | 7027.08 | 7137.02 | 0 | 2 | 0 | 6 |
| /auth/login | 25 | 25 | 4 | 21 | 0 | 98.459 | 204.63 | 219.83 | 241.26 | 244.9 | 245.09 | 0 | 15 | 0 | 6 |
| /auth/me | 50 | 50 | 50 | 0 | 0 | 148.795 | 250.67 | 275.16 | 286.42 | 287.87 | 288.34 | 0 | 15 | 0 | 6 |
| /auditorias | 50 | 50 | 50 | 0 | 0 | 102.551 | 412.25 | 428.69 | 448.74 | 450.09 | 450.5 | 0 | 15 | 0 | 6 |
| /auditorias/10 | 50 | 50 | 50 | 0 | 0 | 123.517 | 292.75 | 340.19 | 351.86 | 353.75 | 354.48 | 0 | 15 | 0 | 6 |
| /documentos | 50 | 50 | 50 | 0 | 0 | 97.546 | 389.77 | 445.22 | 453.97 | 456.18 | 458.09 | 0 | 15 | 0 | 6 |
| /hallazgos | 50 | 50 | 50 | 0 | 0 | 92.7 | 459.56 | 474.72 | 493.93 | 504.53 | 509.92 | 0 | 15 | 0 | 6 |
| /aprobaciones | 50 | 50 | 50 | 0 | 0 | 83.653 | 280.55 | 525.64 | 537.16 | 540.22 | 540.94 | 0 | 15 | 0 | 6 |
| /dashboard/resumen | 50 | 50 | 50 | 0 | 0 | 62.972 | 445.43 | 717.94 | 728.47 | 731.28 | 732.45 | 0 | 15 | 0 | 6 |
| /dashboard/alertas | 50 | 50 | 50 | 0 | 0 | 91.967 | 380.03 | 469.99 | 479.73 | 482.18 | 483.97 | 0 | 15 | 0 | 6 |
| /analisis/resumen | 50 | 50 | 50 | 0 | 0 | 4.121 | 678.85 | 6477.7 | 11537.05 | 11981.49 | 12051.31 | 0 | 2 | 0 | 6 |
| /analisis/anomalias | 50 | 50 | 50 | 0 | 0 | 4.018 | 700.0 | 6540.59 | 11851.19 | 12312.19 | 12367.61 | 0 | 2 | 0 | 6 |
| /auth/login | 50 | 50 | 7 | 43 | 0 | 91.667 | 386.76 | 474.0 | 504.2 | 508.76 | 509.32 | 0 | 15 | 0 | 6 |
| /auth/me | 100 | 100 | 100 | 0 | 0 | 146.48 | 512.62 | 535.64 | 564.87 | 567.7 | 568.51 | 0 | 14 | 0 | 6 |
| /auditorias | 100 | 100 | 100 | 0 | 0 | 100.124 | 730.86 | 848.24 | 864.31 | 869.16 | 870.96 | 0 | 15 | 0 | 6 |
| /auditorias/10 | 100 | 100 | 100 | 0 | 0 | 120.423 | 584.12 | 675.14 | 686.17 | 694.68 | 694.69 | 0 | 15 | 0 | 6 |
| /documentos | 100 | 100 | 100 | 0 | 0 | 112.219 | 483.01 | 729.18 | 755.21 | 761.44 | 762.3 | 0 | 15 | 0 | 6 |
| /hallazgos | 100 | 100 | 100 | 0 | 0 | 103.071 | 738.81 | 805.84 | 841.26 | 845.26 | 845.66 | 0 | 15 | 0 | 6 |
| /aprobaciones | 100 | 100 | 100 | 0 | 0 | 77.067 | 507.84 | 1136.84 | 1151.45 | 1158.65 | 1159.38 | 0 | 15 | 0 | 6 |
| /dashboard/resumen | 100 | 100 | 100 | 0 | 0 | 64.553 | 938.79 | 1389.59 | 1400.07 | 1404.7 | 1407.95 | 0 | 15 | 0 | 6 |
| /dashboard/alertas | 100 | 100 | 100 | 0 | 0 | 96.19 | 525.31 | 875.19 | 885.51 | 891.27 | 891.57 | 0 | 15 | 0 | 6 |
| /analisis/resumen | 100 | 100 | 100 | 0 | 0 | 4.117 | 863.95 | 12566.06 | 23145.88 | 24062.18 | 24135.82 | 0 | 2 | 0 | 6 |
| /analisis/anomalias | 100 | 100 | 100 | 0 | 0 | 4.025 | 811.64 | 12775.39 | 23636.18 | 24605.64 | 24697.15 | 0 | 2 | 0 | 6 |
| /auth/login | 100 | 100 | 10 | 90 | 0 | 122.353 | 506.7 | 661.69 | 684.07 | 695.88 | 696.47 | 0 | 13 | 0 | 6 |
| /auth/me | 250 | 250 | 250 | 0 | 0 | 111.98 | 1347.51 | 1531.45 | 1778.45 | 1818.29 | 1825.19 | 0 | 15 | 0 | 6 |
| /auditorias | 250 | 250 | 250 | 0 | 0 | 89.088 | 1834.39 | 2032.46 | 2299.23 | 2334.28 | 2342.57 | 0 | 15 | 0 | 6 |
| /auditorias/10 | 250 | 250 | 250 | 0 | 0 | 102.206 | 1514.07 | 1725.51 | 2010.08 | 2045.4 | 2050.79 | 0 | 15 | 0 | 6 |
| /documentos | 250 | 250 | 250 | 0 | 0 | 97.692 | 1662.55 | 1861.41 | 2121.65 | 2158.28 | 2168.37 | 0 | 15 | 0 | 6 |
| /hallazgos | 250 | 250 | 250 | 0 | 0 | 86.074 | 2012.03 | 2209.7 | 2467.21 | 2504.14 | 2509.38 | 0 | 15 | 0 | 6 |
| /aprobaciones | 250 | 250 | 250 | 0 | 0 | 66.427 | 2668.26 | 3031.67 | 3305.8 | 3344.01 | 3354.6 | 0 | 15 | 0 | 6 |
| /dashboard/resumen | 250 | 250 | 250 | 0 | 0 | 57.22 | 2141.37 | 3630.64 | 3917.78 | 3953.48 | 3964.81 | 0 | 15 | 0 | 6 |
| /dashboard/alertas | 250 | 250 | 250 | 0 | 0 | 82.692 | 2130.03 | 2303.85 | 2554.04 | 2587.76 | 2595.63 | 0 | 15 | 0 | 6 |
| /analisis/resumen | 250 | 250 | 250 | 0 | 0 | 4.195 | 1134.67 | 30110.98 | 56377.49 | 58709.48 | 59214.97 | 0 | 2 | 0 | 6 |
| /analisis/anomalias | 250 | 250 | 250 | 0 | 0 | 3.977 | 1189.24 | 32307.78 | 59416.82 | 61859.3 | 62439.39 | 0 | 2 | 0 | 6 |
| /auth/login | 250 | 250 | 10 | 240 | 0 | 116.581 | 1081.4 | 1156.77 | 1907.09 | 1937.06 | 1954.37 | 0 | 15 | 0 | 6 |

El resultado previo al fix no se borró conceptualmente: reprodujo 500 por pool, spills y starvation; los ensayos intermedios que agotaron tiempo se retiraron con su schema exacto. Sólo el lote completo final de esta tabla determina el cierre. La cola de análisis mantiene throughput limitado por scans globales; su latencia en ráfaga crece con waiters, sin aumento explosivo por consultas por fila.

## 18. Query budgets y N+1

<!-- phase8-budgets -->

| Endpoint | SELECT pequeño | SELECT escala | Tiempo pequeño s | Tiempo escala s |
|---|---|---|---|---|
| /auth/me | 2 | 2 | 0.0051 | 0.0047 |
| /auditorias | 5 | 5 | 0.0113 | 0.0172 |
| /auditorias/10 | 4 | 4 | 0.006 | 0.0061 |
| /documentos | 3 | 3 | 0.0066 | 0.0078 |
| /hallazgos | 4 | 4 | 0.0114 | 0.0177 |
| /aprobaciones | 6 | 6 | 0.0132 | 0.0272 |
| /dashboard/resumen | 13 | 13 | 0.0254 | 0.0633 |
| /dashboard/alertas | 4 | 4 | 0.0095 | 0.021 |
| /analisis/resumen | 7 | 7 | 0.0336 | 0.4615 |
| /analisis/anomalias | 7 | 7 | 0.0298 | 0.4806 |

Cantidad de SELECT aproximadamente constante: no se detectó N+1 en estos caminos. Esto no promete coste constante de las agregaciones al aumentar las filas.

Se excluye el `SELECT DATABASE()` del guard. El conteo incluye autenticación y barrera fresca cuando aplica. La paginación de análisis calcula count antes de LIMIT en el mismo scan; si offset supera el último resultado consulta un count de respaldo para mantener el total. El presupuesto permanece acotado, sin consultas por cada resultado.

## 19. EXPLAIN e índices

<!-- phase8-explain -->

| Endpoint | Consultas EXPLAIN | Filas de plan | ALL (incluye derived) | Índices utilizados |
|---|---|---|---|---|
| /dashboard/resumen | 13 | 50 | 18 | PRIMARY, ix_auditorias_created_by, ix_auditorias_estado_inicio, ix_documentos_area_id, ix_evidencias_auditoria_tipo, ix_hallazgos_auditoria_estado, ix_rondas_solicitada_por, ix_rondas_version_estado, ix_versiones_documento_subido_por, uq_decisiones_ronda_aprobador, uq_hallazgos_auditoria_numero, uq_versiones_documento_numero |
| /analisis/resumen | 7 | 73 | 26 | <auto_key0>, PRIMARY, ix_auditorias_created_by, ix_documentos_area_id, ix_documentos_auditoria_documento, ix_evidencias_registrada_por, ix_hallazgos_evidencias_vinculada_por, ix_rondas_solicitada_por, ix_versiones_documento_subido_por, uq_hallazgos_auditoria_numero, uq_versiones_documento_numero |
| /analisis/anomalias | 7 | 73 | 26 | <auto_key0>, PRIMARY, ix_auditorias_created_by, ix_documentos_area_id, ix_documentos_auditoria_documento, ix_evidencias_registrada_por, ix_hallazgos_evidencias_vinculada_por, ix_rondas_solicitada_por, ix_versiones_documento_subido_por, uq_hallazgos_auditoria_numero, uq_versiones_documento_numero |

Se instrumentaron y explicaron los SELECT de los diez endpoints. Los planes de análisis incluyen scans de derivados/materializaciones para UNION/ventanas y grupos globales; las correlaciones usan PK e índices existentes. La evidencia justificó corregir estructura/repetición/admisión, sin añadir índices especulativos.

Se conservan índices existentes de PK/FK/scopes, versión/número, rondas y eventos. Los scans de proyecciones globales necesarias no se solucionan con un índice arbitrario. No se creó migración 006 ni se aplicaron migraciones a BD real.

El error 1146 se reprodujo con nombres internos `#sql`, no con tablas de aplicación ausentes. Es compatible con [MySQL bug 112704](https://bugs.mysql.com/bug.php?id=112704), relativo a CTE compartidas al usar disco. Se eliminó esa materialización compartida; cinco reglas de versiones comparten una pasada de ventanas, y EXISTS correlacionados usan las tablas/indexes base con los mismos scopes. Tests fuerzan `tmp_table_size=1024` sólo en sesiones temporales y comparan resultados para los cinco roles. No se cambió ningún setting global del servidor. [Uso de temporales MySQL](https://dev.mysql.com/doc/refman/8.0/en/internal-temporary-tables.html).

## 20. Pool, admisión, startup y errores

La fase encontró espera circular reproducible en 7E: lectores retenían su primera conexión mientras esperaban una segunda. La barrera devuelve ahora la conexión original; una prueba con pool de un solo slot confirma cero conexiones prestadas al terminar.

También se reprodujo starvation de workers síncronos por espera del pool con 100 requests. La admisión asíncrona precede a dependencias síncronas y limita trabajo al pool (máximo 32). Cola acotada a capacidad + 256, rechazo 503 genérico/no-store/Retry-After cuando se satura; cancelar un waiter no pierde un permiso. El análisis agrega una admisión de dos scans por proceso, porque 15 scans simultáneos saturaban temporales MySQL y empeoraban throughput. Sus waiters no necesitan workers ni conexiones.

La autoauditoría del fix reprodujo bloqueo con 15 uploads que no terminan de enviar el cuerpo. La admisión SQL se trasladó a una dependencia asíncrona global después del parsing, antes de las dependencias síncronas. El test mantiene abiertos esos receives y comprueba que `/auth/me` sigue respondiendo 401 sin esperar a los uploads; los cupos se liberan después de cerrar la sesión SQL.

<!-- phase8-pool -->

Pool medido: size=5, overflow=10, timeout=30.0 s; máximo de conexiones prestadas=15, final=0. Cero agotamientos, errores SQL y deadlocks finales. Estado al cerrar requests: `Pool size: 5  Connections in pool: 5 Current Overflow: 0 Current Checked out connections: 0`. Threads_connected: 2 al iniciar con monitor, 6 con pool abierto, 1 después de dispose y eliminación del schema (también incluye el monitor). Las conexiones ociosas del pool se cerraron al finalizar; no queda un lease de request retenido.

| Setting MySQL leído | Valor |
|---|---|
| internal_tmp_mem_storage_engine | TempTable |
| max_connections | 151 |
| max_heap_table_size | 16777216 |
| temptable_max_mmap | 1073741824 |
| temptable_max_ram | 1073741824 |
| tmp_table_size | 102760448 |

Los settings son lecturas de servidor; no se modificaron límites globales ni configuración de producción.

Startup valida JWT/Turnstile antes de servir; import/migraciones no inicializan ni borran producción. MySQL unavailable, FS unavailable/desaparición, JSON inválido, timeout/backend caído para PHP, IntegrityError y commit ambiguo usan errores controlados/sanitizados. No se retorna traceback, SQL, credenciales ni paths absolutos. Los errores inyectados 500/503 se distinguen de 5xx bajo carga normal. Cierre y reconexión se cubren con servidores reales y fixtures.

## 21. Frontend PHP, CSRF, cache y sesión

66 archivos PHP, lint cero errores. Formularios mutativos pasan por CSRF central; se revisó inventario de POST literal y formularios cuya función genera el atributo. GET de logout y acciones de negocio no mutan. CSRF absent/inválido/otra sesión se rechaza antes de API. Reutilizar el token de la misma sesión es el contrato actual, no un token de acción single-use.

Páginas autenticadas no-store/no-cache, cookies server-side con opciones existentes, regeneración de sesión y logout probado. JWT no aparece en DOM, URL, JS ni client storage. Descarga conserva filename escapado y controles de autorización. API/backend caído muestra error comprensible y no valores ficticios.

## 22. Chrome y accesibilidad básica

Chrome real en 1440/390/320; cinco roles, navegación/permisos, formularios/botones, dashboard/análisis, errores y XSS. Se corrigió una espera del harness que evaluaba layout antes de completar carga; no se cambió CSS para ocultar una medición transitoria. La suite frontend completa repitió 312 casos verdes después de esa corrección.

Se comprobó teclado, foco, labels y controles con nombres. No se identificó un fallo grave nuevo que requiriera rediseño. Es una revisión básica, no una certificación WCAG completa.

## 23. E2E sistémico

`test_phase8_e2e_mysql.py`: PHP real → FastAPI real → MySQL temporal real → storage real temporal. Login ADMIN → crea/activa auditoría → crea documento → sube versión → hallazgo → evidencia asociada → ronda → login APROBADOR y decisión → dashboard/alertas/análisis → logout. Comprueba bytes, estados, asociación y actor de evento. XSS persistente en campos de todos esos módulos y Chrome para los cinco roles/viewports sin ejecución, JWT en DOM ni overflow.

El API aprobado no ofrece comando de vincular documento↔auditoría. Sólo esa asociación de scope se prepara mediante SQL en el fixture guardado; todos los pasos anteriores usan HTTP real sin mocks. Se explicita esa preparación y no se añade una feature nueva para reemplazarla. E2Es 7C/7D/7E existentes también se reejecutaron.

## 24. Datos legacy y drift

BD real tiene dos usuarios activos, roles canónicos ADMIN y AUDITOR_INTERNO. No se clasificó como cuenta de prueba sólo por su ID/nombre. El histórico id=1 tiene dependencias: una auditoría como creador/responsable, tres documentos como creador/responsable, dos actualizaciones, dos versiones y seis eventos. El id=2 ADMIN tiene cinco sesiones y no esas relaciones de negocio. No se incluyeron nombres/correos en este reporte público.

Fase 9: confirmar procedencia y autorización, inventariar expediente/atribuciones completas y preferir conservación/desactivación o anonimización aprobada cuando corresponda. No asumir que se puede borrar al histórico ni reasignar eventos automáticamente. FKs impiden eliminación casual y preservar actor histórico es parte de trazabilidad.

Comparación de SHOW CREATE TABLE con schema migrado: diferencias NO ACTION vs RESTRICT son equivalentes en InnoDB; eventos real agrega dos CHECK `JSON_VALID` redundantes sobre columnas JSON que validan contenido por tipo. No hay drift de columnas, nullable/defaults, UNIQUE, FK o índices funcionales después de reconocer esas equivalencias. Ningún DDL real se modificó.

Legacy sintético corrupto/estados no canónicos/hash inválido/storage ausente se detecta sin revelar recursos privados. Escrituras ante estados desconocidos fallan cerradas. NO_DATA/NOT_APPLICABLE y denominador cero de dashboard se conservan; LOW/INFO de truncación/candidatos/storage local 7E permanecen acotados.

## 25. Sanity, UTF-8 y limpieza

AST de Python y imports de módulos de aplicación sin error; no se ejecutó compileall que generase bytecode innecesario. Todos los tests se lanzan con `-B`/PYTHONDONTWRITEBYTECODE y caches/logs/screenshots bajo la raíz temporal propia. PHP lint y pip check sin errores. Archivos nuevos/modificados UTF-8, sin BOM, replacement chars ni mojibake.

Revisión de print/var_dump/console.log/TODO/raw SQL/backups: los print encontrados son salidas legítimas del CLI de pruning, no debug HTTP. No se realizó refactor cosmético ni borrado de herramientas operativas aprobadas. No se encontró basura tracked que justificara borrar código.

<!-- phase8-cleanup -->

Sanity final: AST de 134 archivos Python, todos los imports de aplicación y 66 PHP lint sin errores; `pip check`: No broken requirements found. UTF-8/secret formats de entrega y diff, cinco commits recientes y review de assignments sin secretos operativos. Los artefactos efímeros se retiran al cerrar la fase; la verificación de cleanup se registra en el estado final.

## 26. Seguridad del repositorio público

Tracked + untracked justificados + diff de Fase 8 revisados por formatos de secretos y assignments; historial reciente de cinco commits revisado. Candidatos corresponden a credenciales/tokens sintéticos de tests, no secretos operativos. No se publica `.env`, dumps, PDFs reales, llaves privadas, cookies ni sesiones. `api/.env`, `frontend/.env`, `storage/` y bytecode son ignorados. `.env.example` sólo contiene configuración segura/placeholders y límites documentados.

La existencia local de `.env` y PDFs en storage no equivale a publicarlos: se preservaron intactos y fuera de Git. No se copió su contenido al reporte. No se afirma que este scan de patrones sustituya una auditoría de todo el historial remoto.

## 27. Findings reproducidos

| ID | Severidad | Reproducción | Corrección |
|---|---|---|---|
| F8-01 | HIGH | Dos lectores/carga 25 de análisis retienen pool mientras esperan segunda conexión; 11/25 500 | Liberación antes de barrera fresca; prueba con un slot |
| F8-02 | HIGH | Escrituras con snapshot de permisos antiguo sobreviven a owner/role/inactivación comprometidos | Relectura locking del actor y scope tras lock de recurso |
| F8-03 | HIGH | 100 requests ocupan workers esperando conexiones e impiden avance/cierre | Admisión asíncrona y cola bounded antes de workers |
| F8-04 | MEDIUM | Payload documental null/estado inválido/FK/longitud causaba 500 | Schemas estrictos, refs validadas, rollback y 409 de integridad |
| F8-05 | MEDIUM | MAX no locking bajo snapshot previo genera número duplicado/IntegrityError en upload | Lectura locking de última versión bajo lock padre |
| F8-06 | MEDIUM | Upload documental carecía de techo de bytes | Límite streaming equivalente a evidencias y tests borde |
| F8-07 | MEDIUM | Filename NUL/control/enorme o sufijo Unicode expandido causa fallo de FS | Saneamiento y límites reales del temporal/path antes de IO |
| F8-08 | MEDIUM | Alias legacy case/padding de terminales MySQL permite evidencia/ronda/upload | Whitelist exacta de estados activos; rol canónico en auth |
| F8-09 | MEDIUM | Carga de análisis produce MySQL 1146 interno, incluso temporales pequeños | Derived tables sin CTE compartida; una pasada de ventanas |
| F8-10 | MEDIUM | Análisis repite scans/temporales y empeora al paralelizar | EXISTS indexados, filas de ventanas estrechas, total+page mismo scan, dos scans admitidos |
| F8-11 | LOW | UUID repetido sobrescribe archivo; temporal repetido puede limpiarse sin pertenecer al escritor | Publicación sin reemplazo y ownership del temporal |
| F8-12 | LOW | Cleanup sigue junction a otro archivo dentro del root | Reutiliza validación lexical/containment/enlaces |
| F8-13 | LOW | Harness mide antes de terminar CSS y falla overflow de forma transitoria | Espera document.readyState complete, rerun browser |
| F8-14 | INFO | NO ACTION/RESTRICT y JSON_VALID redundante en DDL real | Documentado; sin cambios a producción |
| F8-15 | MEDIUM | Login y catálogos/elegibilidad aceptaban aliases legacy de rol por case/padding | Whitelist de roles en ambas lecturas de login y comparación binaria de elegibilidad |
| F8-16 | MEDIUM | Multipart adicional y JSON enorme se procesaban antes de sus límites de schema/archivo | Límite de cuerpo recibido; corte de parser con cleanup probado |
| F8-17 | MEDIUM | JSON válido muy profundo provoca RecursionError en la respuesta 422 | Errores sin input/ctx crudo; respuesta de cliente controlada |
| F8-18 | HIGH | Autoauditoría: 15 cuerpos incompletos monopolizan la admisión SQL inicial | Dependencia global después del parsing; recibe lento no reserva cupos SQL |

## 28. Fixes y archivos de entrega

Schemas/routers/documento_service; autorización, autenticación y locks de auditoría/hallazgo/aprobaciones/evidencia; storage_service; analisis_queries/service; middleware de admisión y registro en main. Nuevas suites de Fase 8 y ajustes de doubles existentes. `.env.example`/API README explican límite, pool y publicación. Un helper de espera browser se corrigió. No hay archivos de carga/logs/screenshots permanentes.

<!-- phase8-files -->

- `api/.env.example`
- `api/README.md`
- `api/app/api/dependencies.py`
- `api/app/core/config.py`
- `api/app/main.py`
- `api/app/routers/auth.py`
- `api/app/routers/documentos.py`
- `api/app/schemas/documento.py`
- `api/app/services/analisis_queries.py`
- `api/app/services/analisis_service.py`
- `api/app/services/aprobacion_service.py`
- `api/app/services/auditoria_service.py`
- `api/app/services/authorization_service.py`
- `api/app/services/documento_service.py`
- `api/app/services/hallazgo_service.py`
- `api/app/services/storage_service.py`
- `api/tests_unit/test_file_consistency_unit.py`
- `api/tests_unit/test_file_routes_unit.py`
- `api/tests_unit/test_rbac_unit.py`
- `frontend/tests/test_auditorias_browser.py`
- `api/app/services/database_admission.py`
- `api/app/services/request_body_limit.py`
- `api/tests_auth_mysql/test_phase8_e2e_mysql.py`
- `api/tests_auth_mysql/test_phase8_system_mysql.py`
- `api/tests_unit/test_phase8_unit.py`
- `docs/FASE_8_QA_SEGURIDAD_RENDIMIENTO.md`

## 29. Deuda aceptada y límites de la evidencia

- LOW: interrupción abrupta puede dejar huérfano físico; verificador read-only y operación humana, sin borrado automático de expedientes.
- LOW/INFO previamente aprobados de 7E: candidatos/storage bounded, similitud heurística explicable y truncación explícita.
- INFO: warnings deprecados Starlette/httpx/AnyIO; dependencias no actualizadas masivamente.
- INFO: CHECK JSON_VALID redundantes y representación NO ACTION/RESTRICT del esquema inicial.
- INFO: benchmark local de ráfagas coordinadas, un proceso; no SLA, ensayo de larga duración ni capacidad de Apache/cloud/múltiples workers. Análisis global escala con datos y cola; carga login incluye rechazos de seguridad esperados.
- INFO: revisión básica de accesibilidad y scan reciente de secretos; sin certificación completa ni claim de exhaustividad absoluta.

No se aceptan CRITICAL/HIGH/MEDIUM pendientes para declarar lista esta fase.

## 30. Fingerprints inicial y final

<!-- phase8-fingerprints -->

**Comparación exacta inicial == final: BD real intacta; storage real intacto.** MySQL 8.0.46, aislamiento REPEATABLE-READ, Alembic `005`.

Se compara la misma representación JSON canónica. El primer comparador en memoria distinguía tuplas retornadas por MySQL de listas cargadas desde JSON; se corrigió ese defecto del runner y se repitió la captura/comparación completa. Ambos manifiestos persistidos y sus digests ya coincidían; no fue un cambio de recursos reales.

| Recurso | SHA-256 agregado inicial y final |
|---|---|
| BD: DDL + contenido completo de las 19 tablas | 7fb315265b5bf162e9571c080587585a28659f2d0fa2cce93c3b27bd4ef6e08d |
| Storage: rutas relativas + tamaños + SHA-256 individuales | 563a979011e96e8c694a4691fca48a08b55195f54c37fdf7f41f59f001941e48 |

Storage: 2 archivos, 5,991,474 bytes. El manifiesto individual se capturó y comparó en el entorno temporal; se preserva aquí el digest agregado para evitar publicar hashes/rutas de PDFs privados. El fingerprint BD compara filas, constraints/índices/defaults mediante DDL y metadatos, no sólo conteos.

| Tabla real | Filas iniciales y finales | SHA-256 DDL inicial y final |
|---|---|---|
| access_requests | 0 | 7bf5a8a412b75a4148692690840b54643d02b5f7b3d7d192162719f1cf8354d8 |
| alembic_version | 1 | 1bd6666a966a79c5a965e617b20ff29286361278b681c34a0a85e93d7a964ee2 |
| areas | 1 | c25ac80c96422b9db8870334140be2ee665eb53d9727619a04664b74276c1143 |
| auditorias | 1 | 65e5df0c227935a39562b25eecf91e530a6f19a6628700463b1a60cd0ba49553 |
| auth_action_limits | 0 | 62e5652d335edbe78cbbf67d7e929884e4ba75686c758964db4f81db6b728e17 |
| auth_action_tokens | 0 | 313284b79d30bc9a57d8d5be040ca87612e2a7ee0caefe88eb98748408067a1a |
| auth_login_limits | 1 | 328bc3cd830743761af2f0e5536c4b4759deb7b9b72e9b38b334da056fd8d3dd |
| auth_mail_jobs | 0 | e14359ab80970290be3ac7e8d46cbf46c8991ccce3bd2a0ecf69b16f69602d2d |
| auth_sessions | 5 | bb502f6eaa4d6dbc99be72f890db29b19d99297edc4c522799331ff9e3b53a31 |
| decisiones_aprobacion | 0 | fdfcb29daec10395ed2a4d0660d8bc1ccd85ee3355ba3e055c59ff3985ce842f |
| documentos | 3 | e044d7b7f55aa13e895544129fd41698aa7843eb2b49b57ba9c6f8a4d6b0aa7f |
| documentos_auditoria | 0 | 4a69c5aa1fd9b66354a269c2f6bb36bfda959f13ffba9437f47d1ca183c060f4 |
| eventos_auditoria | 6 | 9ba08a628846873e18d9c21ab28b86eae5e5c46a418636efc8c0e0280ec73141 |
| evidencias | 0 | f4fd4580a6e6e97706a23e191194d4b565af8b2bc971c16cb020ff9efa9c0eb9 |
| hallazgos | 0 | 92eb759620afb89c1e4349fe786d3622d0c870f5512a1ff52b68936e2af8c62d |
| hallazgos_evidencias | 0 | d2d5a77f4c421d73ba2421602fa45fc789986c34f690f14405dc77934d982f78 |
| rondas_aprobacion | 0 | f91524d7debf724105991eb025da029b64ed9d465b835dc64bc5860142b67e4b |
| usuarios | 2 | 4f7899c3b4ba080989fff31ce7619833522dcddef4750b8ae2e5b446d46d57eb |
| versiones_documento | 2 | 223db003264ef2a246e1bbc8802b0cdfbc217fc2e063e940f02bb8994e79dc47 |

## 31. Estado final y autoauditoría

Se repitieron ataques prioritarios de autorización, IDOR/actor, traversal, transacciones, carreras, auth/reset, leakage, SQLi/XSS/CSRF, límites y carga después de fixes. Las condiciones de salida se verifican al terminar los ensayos y retirar sus recursos.

<!-- phase8-final -->

Cero CRITICAL/HIGH/MEDIUM abiertos. Regresiones completas verdes; carga final sin 5xx, timeout, agotamiento ni deadlock. RBAC/scopes, atomicidad controlada, frontend, Chrome y E2E validados. Fingerprints idénticos. 6 schemas propios identificados en logs; 0 remanentes de ejecuciones previas retirados al cierre; ninguno queda. Sin procesos QA propios activos. Scripts, storage, perfiles Chrome, screenshots, logs, métricas y caches se eliminaron exclusivamente de la raíz temporal creada por Fase 8. No se borraron caches/configuración/datos locales preexistentes.

Git final: rama main, HEAD=origin/main=eec566d5a00c63925ef953b4a6a8d4f550168824, staging vacío, diff-check limpio. Sin add/commit/push. Working tree contiene únicamente los archivos listados de Fase 8.

FASE 8 LISTA PARA AUDITORÍA INDEPENDIENTE DE ANTIGRAVITY
