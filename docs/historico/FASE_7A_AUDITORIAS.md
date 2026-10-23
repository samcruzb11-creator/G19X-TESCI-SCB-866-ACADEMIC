# Fase 7A: ciclo de vida de auditorías

## Contrato encontrado antes de modificar

Entrada verificada: main limpio en ad5b113, igual a origin/main; MySQL Community
8.0.46 local, sistema_trazabilidad en 004; un ADMIN activo; JWT válido; Turnstile
disabled; SMTP sin configurar. Una auditoría PLANNED y storage íntegro.

Auditoria ya contiene código único (60), nombre (200), alcance TEXT, fechas
previstas, iniciada_en, completada_en, responsable_id, created_by_id,
updated_by_id y timestamps UTC. No tiene tipo ni área directa. Area se relaciona
mediante Documento -> DocumentoAuditoria. Usuario no tiene area_id ni rol CONSULTA.
EventoAuditoria admite actor, acción, entidad, fecha, correlación y snapshots JSON.

El CHECK de 001 permite PLANNED, IN_PROGRESS, COMPLETED y CANCELLED. Solo existen
GET listado y POST creación; el listado ya aplica scope SQL antes de limit/offset.
PHP descarga todas las páginas y filtra localmente; detalle busca en ese listado.
No existen edición ni transiciones. created_by_id legacy se acepta e ignora:
el actor siempre proviene de current_user, conforme al contrato 6B.2.

## Necesidad estructural demostrada antes de crear 005

No existe equivalente de EN_REVISION. CANCELLED significa cancelación, no revisión;
reutilizarlo alteraría datos y reglas existentes. IN_REVIEW no satisface el CHECK
vigente. Se necesita exclusivamente ampliar ck_auditorias_estado con IN_REVIEW,
actualizando el modelo en paralelo. No se añaden columnas, tablas ni estados
duplicados; PLANNED, IN_PROGRESS y COMPLETED se conservan.

Upgrade 004 -> 005 sustituirá el CHECK en un solo ALTER TABLE, preservando datos.
Downgrade 005 -> 004 deberá abortar si hay IN_REVIEW; nunca convertir ni borrar
datos para encajar en el CHECK anterior. Si no existen, restaurará el CHECK original.
MySQL 8 puede tomar metadata lock durante ALTER; no hay backfill. 001–004 quedan
intactas. Los ciclos upgrade/downgrade se probarán únicamente en schema temporal.
La aplicación anterior no entiende IN_REVIEW: una reversión requiere comprobar
que no existan filas en revisión antes de cambiar código/schema.

## Workflow y autorización previstos

PLANNED (Borrador) -> IN_PROGRESS (Activa) -> IN_REVIEW (En revisión) -> COMPLETED
(Cerrada). IN_REVIEW -> IN_PROGRESS permite volver a trabajar. COMPLETED y el
CANCELLED histórico son terminales. 7A no incorpora una acción de cancelación.

Se preserva 6B.2: ADMIN lectura global y creación; AUDITOR_INTERNO lectura propia
y creación asignada a sí mismo; AUDITOR_EXTERNO lectura propia. Los nuevos PATCH,
estado e historial quedan reservados a ADMIN. RESPONSABLE_AREA y APROBADOR no
reciben permisos de auditorías por área; CONSULTA no existe. Esta es la diferencia
expresa respecto de la matriz aproximada del pedido: ampliar permisos requiere
una decisión posterior, no una concesión implícita.

No se inventan tipo/área de auditoría ni precondiciones de hallazgos/aprobaciones.
Área se presenta como área documental vinculada, no como propiedad de Auditoria.
El cierre exige estado previo IN_REVIEW, actor autenticado y evento transaccional.

## Endpoints y compatibilidad

Todos bajo `/api/v1`, autenticados con la dependencia existente:

| Método/ruta | Contrato |
| --- | --- |
| GET /auditorias | Lista compatible; total scoped en X-Total-Count |
| POST /auditorias | Crea PLANNED; actor real; legacy created_by_id ignorado |
| GET /auditorias/{id} | Detalle scoped, responsable id/nombre y áreas documentales |
| PATCH /auditorias/{id} | ADMIN; nombre, alcance, fechas y responsable |
| POST /auditorias/{id}/estado | ADMIN; destino, estado_esperado, updated_at_esperado |
| GET /auditorias/{id}/historial | ADMIN; eventos de esa entidad, proyección segura |

Filtros: q (código/nombre, 100 caracteres), estado, responsable_id, area_id
(vía documentos vinculados), inicio_desde/inicio_hasta. Orden enum id, -id,
fecha_inicio, -fecha_inicio con desempate por ID. limit 1–200; offset 0–10000.
Parámetros desconocidos rechazados. Los comodines de búsqueda son literales.
No hay campo tipo ni filtro artificial. No hay DELETE: borrar auditorías reales
contradice el historial y las relaciones existentes.

## Validaciones, edición y concurrencia

Texto trimmed, no vacío ni controles; límites código 60, nombre 200, alcance
16000 (compatible con TEXT utf8mb4). IDs de responsable JSON enteros estrictos.
Responsable activo AUDITOR_INTERNO/AUDITOR_EXTERNO. Fechas MySQL desde año 1000;
fecha_fin >= fecha_inicio, también al combinar PATCH parcial con datos existentes.
PATCH permite limpiar fechas con null, no nombre/alcance/responsable. Código,
estado, IDs de actor y timestamps protegidos. PATCH vacío y extras rechazados.

Edición solo en PLANNED/IN_PROGRESS. IN_REVIEW congela los datos durante revisión;
se puede regresar a activa. COMPLETED y CANCELLED son terminales incluso para ADMIN.
Las mutaciones bloquean la fila scoped con FOR UPDATE y populate_existing, luego
comparan updated_at_esperado; las transiciones comparan también estado_esperado.
Un formulario antiguo y una transición repetida fallan 409. La primera activación
fija iniciada_en; el cierre fija completada_en y updated_by_id. Cada operación
persiste negocio y evento dentro de la misma transacción; errores hacen rollback.
No hay retries automáticos ni éxito simulado ante commit incierto.

La carga de evidencias bloquea la misma auditoría y rechaza COMPLETED/CANCELLED
antes de escribir storage. Esto evita que una evidencia cruce concurrentemente el
cierre. No se implementan los demás workflows de evidencias/hallazgos/aprobaciones.

## Trazabilidad y seguridad

Eventos: CREACION_AUDITORIA, ACTUALIZACION_AUDITORIA, ACTIVACION_AUDITORIA,
REVISION_AUDITORIA, REACTIVACION_AUDITORIA, CIERRE_AUDITORIA. Incluyen actor real,
entidad AUDITORIA, ID, fecha UTC, correlación, resultado SUCCESS y snapshots de
campos de negocio. Historial filtra entidad/ID en SQL y pagina 1–100; no devuelve
actor_snapshot con correo ni JSON legacy fuera de la whitelist.

Scopes SQL preceden filtros, count, orden y paginación. 401 autenticación;
403 rol; 404 indistinguible para recurso ausente/ajeno; 409 conflictos de estado,
concurrencia y código; 422 payload/filtros/referencias inválidos. Mensajes de error
de mutación saneados; no SQL, stack, rutas ni credenciales. No se cambia auth.

PHP conserva CSRF para crear, editar y estado. No reescribe la versión esperada
enviada por el formulario. Usa rutas API fijas, PATCH limitado a auditorias/{id},
whitelist POST estado y escaping HTML. Botones por rol/estado son presentación;
el backend vuelve a comprobar todo. Sesión expirada conserva el redirect de 6B.3.
Hay lista con filtros/paginación server-side, detalle directo, formulario de edición,
estados y acciones explícitas e historial paginado. Móvil usa cards sin romper
el ancho; no hay pestañas futuras con funcionalidad ficticia.

## Consultas y rendimiento

Listado: count scoped, página con JOIN del responsable y una consulta de áreas
para todos los IDs de esa página (máximo 200). No hay N+1; los nombres del listado
y detalle vienen del JOIN. Formularios y filtro de responsable ADMIN reutilizan
el catálogo protegido de auditores activos; otros roles no reciben ese catálogo
desde PHP e interno se asigna a sí mismo. Filtros avanzados se pliegan mediante
details nativo accesible por teclado. Índices existentes:
estado/inicio, responsable, código único, área documental y FKs del pivot; no se
añaden índices especulativos. Búsqueda substring puede escanear el conjunto scoped;
no es full-text. Offset se limita; catálogos existentes pueden requerir búsqueda
paginada en instalaciones grandes. No se ejecutó carga masiva.

## Validación completada en aislamiento

644 unitarias, 449 MySQL temporal, 154 frontend, 13 Chrome: **1260 pruebas**.
7A añade 106 unitarias, 110 MySQL (incluyendo carreras reales y downgrade protegido),
29 PHP y 3 Chrome. Se conservan las 1012 regresiones anteriores.
Incluye IDOR, SQL/order injection, actor spoofing, extras, estados inválidos,
fechas combinadas, roles, total/página scoped, eventos/rollback, doble transición,
mutación de cerrada, bloqueo previo a storage, whitelist legacy, CSRF, errores,
sesión expirada, teclado y 1440/390/320 px. Upgrade/downgrade 005 solo en schema
temporal: conserva filas y rechaza downgrade con IN_REVIEW sin tocar DDL/datos.

Una autoauditoría encontró la mutación de evidencias tras cierre y la corrigió
bajo lock con regresiones. El primer fallo de duplicado SQLite se corrigió sin
alterar el contrato MySQL. Dos errores de fixtures (título demasiado corto y GET
logout sin CSRF) se corrigieron en tests. Chrome necesitó carpeta temporal nueva
accesible fuera del sandbox; las 13 pruebas reales pasaron sin tráfico externo.
El harness de Chrome ahora espera que DevToolsActivePort termine de escribirse:
Windows puede mantener un lock breve o exponer contenido parcial. Se reintenta
únicamente esa lectura durante el arranque; no se cambian auth ni el navegador.

## Operación real y preparación de 7B/7C

Se recibió autorización explícita para aplicar exclusivamente 004 -> 005 local.
La revisión real es **005 (head)**; se comprobó que solo cambió el CHECK esperado,
sin pérdida de filas ni cambios en las huellas de datos. No se ejecutó downgrade,
stamp ni upgrade head sobre la BD real. 001–004 y bootstrap permanecen intactos.

Backup final previo a 005, fuera del repositorio y del storage:
`C:\Users\samcr\Desktop\SistemaTrazabilidad_Backups\pre_7a_sistema_trazabilidad_20261006_022844.sql`.
Tamaño: **42488 bytes**. SHA-256:
`2812de891c95644786e4fbc8c7605356c83687673ae0c55f2967e6af91c8fb58`.
Se restauró en un schema nuevo aleatorio: todas las tablas, metadata estructural,
counts y huellas determinísticas coincidieron en 004. El schema temporal se eliminó.
El hash del dump se verificó otra vez después del smoke.

Hubo un login del usuario después del primer backup pre-7A: solo cambiaron tablas
de sesiones/límites. Se detuvo la operación, se confirmó esa actividad con el usuario
y se generó el backup actualizado anterior. Nunca se revocó esa sesión preexistente.

Smoke real con contraseña del ADMIN existente mediante getpass, solo en memoria:
API `/`, `/docs`, `/openapi.json`, login y `/auth/me`: 200. PHP autenticado: listado
y detalle de la auditoría existente, creación identificable, edición y transiciones
PLANNED -> IN_PROGRESS -> IN_REVIEW -> IN_PROGRESS -> IN_REVIEW -> COMPLETED.
Se comprobaron siete eventos con actor real, timestamps de inicio/cierre y rechazo
de transición directa a cierre, mass assignment y modificación posterior al cierre.
Logout API: 204; el mismo JWT ya revocado recibió 401. Logout PHP: 303.
Las dos sesiones propias de este smoke quedaron revocadas; las tres preexistentes
se conservaron sin cambios. No se modificaron usuarios, roles ni contraseñas.
El AUDITOR_INTERNO existente no se autenticó porque no se conoce su credencial;
sus permisos y los demás roles se cubrieron en suites temporales.

Solicitud pública de prueba: 202, PENDING y visible al ADMIN. Reset inexistente:
202 uniforme, LOOKUP_RESET sin recipient, cero tokens y cero SMTP. Reset del ADMIN:
resolución del recipient canónico y transporte exclusivamente simulado, sin cambiar
la contraseña. Se verificó lectura de documentos/evidencias y descarga documental
con SHA-256 coincidente. Turnstile disabled; cero SMTP/Cloudflare reales.

Se limpiaron exclusivamente auditoría, eventos, solicitud, jobs, tokens y límites
identificados como propios de este smoke. Las filas preexistentes conservan counts
y huellas: áreas 1, auditorías 1, usuarios 2, documentos 3, versiones 2, eventos 6;
las demás tablas de dominio siguen vacías. Storage conserva sus dos archivos,
5991474 bytes y las mismas huellas. API/PHP propios se detuvieron. No se apuntó
pytest destructivo a sistema_trazabilidad. Los secretos siguen fuera de Git.

Como efecto normal de crear y limpiar datos propios, AUTO_INCREMENT avanzó una
posición en auditorías y access_requests, siete en eventos y tres en mail_jobs.
No se reajustaron contadores. También pueden variar las estimaciones Cardinality
de SHOW INDEX; no son definiciones de índices. La comparación semántica final
verificó columnas, índices, constraints, engines y collations sin otros cambios.
php -l: 49 archivos válidos; git diff --check, incluidos archivos nuevos: correcto.
No hubo commit ni push. Los cambios quedan pendientes de auditoría independiente.

7B puede gestionar enlaces documentales/evidencias, sin convertir área documental
en una propiedad directa inventada. 7C puede endurecer check_close dentro del lock
existente, manteniendo endpoint, transacción y eventos. No se implementan todavía
hallazgos/aprobaciones completos, IA, notificaciones ni nuevos componentes.
El bootstrap permanece sin cambios y exige 004: en una instalación nueva provisionar
el primer ADMIN en 004 antes de 005; no usar downgrade real como workaround.
