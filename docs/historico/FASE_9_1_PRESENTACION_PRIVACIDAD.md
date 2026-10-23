# Fase 9.1 — Presentación institucional y privacidad

Nota de distribución Fase 9.2: este informe conserva resultados históricos. Los identificadores y contraseñas concretos se retiraron; los comandos de instalación mostrados usan ahora el archivo privado externo. El estado vigente se registra en [Fase 9.2](FASE_9_2_CREDENCIALES_PRIVADAS.md).

Fecha: 12 de octubre de 2026. Proyecto: Sistema de Trazabilidad Documental para Auditorías. Alcance exclusivo: privacidad local, branding Develop, documentación TESCI y validación de entrega. No se añadió funcionalidad ni se modificó runtime backend, RBAC, autenticación, autorización, workflows, modelos, API, migraciones, dashboard o análisis 7E. No se tocó SMTP.

## Estado inicial y recuperación de la interrupción

Precheck original: `main`, HEAD y origin/main `d54a81e2a38b3ae8c57dfe43a3d7f1665bae421e`, staging vacío; working tree con los cambios legítimos de Fase 9 aprobada. PDF/DOCX previos ausentes por eliminación intencional del alumno. Tras la interrupción se verificó el snapshot postprivacidad completo antes de continuar. No se repitió ninguna eliminación ni anonimización.

## Referencias de sólo lectura

| Archivo exacto | Bytes | SHA-256 antes/después |
|---|---:|---|
| `imagen develop.jpg` | 11,217 | `4609eb7d8d13ab33275b4fea85de7255ce3d44f1d8ae287c47169365ac0f1a0d` |
| `Portafolio de Evidencias Final (1).pdf` | 19,039,625 | `ec0c8211135f41ca9555f81c33d4ef48c3683a4d3ccd7b9da966a76e7be72768` |

Formato comprobado: PDF de 615 páginas y JPEG RGB de 595 × 336 px. Se inspeccionaron visualmente portada y páginas institucionales/de contenido del PDF. Se extrajeron del documento únicamente identidad TESCI, franja institucional TecNM/Gobierno del Estado de México/TESCI y geometría vino/negro. No se copiaron materia, docente, grupo, créditos, instrumentación, teléfonos, direcciones, firmas o sellos. Los dos originales permanecen idénticos en nombre, ruta, bytes y SHA-256; no se modificaron, movieron, renombraron ni eliminaron.

## Auditoría de privacidad previa a la modificación

ID 2: cuenta personal local, ADMIN, activa; cinco sesiones y un límite lógico de login; cero relaciones históricas. ID 1: cuenta legacy local, AUDITOR_INTERNO, activa; seis eventos y sus snapshots de identidad, una auditoría, tres documentos y dos versiones. Los identificadores originales se conservan únicamente en el registro privado de auditoría fuera de Git/entregables; se omiten sus correos de este informe público.

Se recorrieron las 22 FK reales a usuarios, no sólo relaciones ORM. Se revisaron además columnas CHAR/TEXT/JSON para encontrar nombre/correo fuera de FK.

| Referencia FK | ID 1 antes | ID 2 antes |
|---|---:|---:|
| `access_requests.resolved_by` | 0 | 0 |
| `access_requests.usuario_id` | 0 | 0 |
| `auditorias.created_by_id` | 1 | 0 |
| `auditorias.responsable_id` | 1 | 0 |
| `auditorias.updated_by_id` | 0 | 0 |
| `auth_action_tokens.usuario_id` | 0 | 0 |
| `auth_mail_jobs.usuario_id` | 0 | 0 |
| `auth_sessions.usuario_id` | 0 | 5 |
| `decisiones_aprobacion.aprobador_id` | 0 | 0 |
| `documentos.created_by_id` | 3 | 0 |
| `documentos.responsable_id` | 3 | 0 |
| `documentos.updated_by_id` | 2 | 0 |
| `documentos_auditoria.asociado_por_id` | 0 | 0 |
| `eventos_auditoria.actor_id` | 6 | 0 |
| `evidencias.registrada_por_id` | 0 | 0 |
| `hallazgos.cerrado_por_id` | 0 | 0 |
| `hallazgos.created_by_id` | 0 | 0 |
| `hallazgos.responsable_id` | 0 | 0 |
| `hallazgos.updated_by_id` | 0 | 0 |
| `hallazgos_evidencias.vinculada_por_id` | 0 | 0 |
| `rondas_aprobacion.solicitada_por_id` | 0 | 0 |
| `versiones_documento.subido_por_id` | 2 | 0 |

Referencias lógicas adicionales: `auth_login_limits.identifier`, un registro de la cuenta personal; `eventos_auditoria.actor_snapshot`, seis snapshots con nombre/correo legacy. En tablas de usuarios se encontraron nombre, correo y correo normalizado. No hubo tokens de acción, jobs de correo, solicitudes, evidencias, hallazgos o aprobaciones dependientes de estas cuentas.

## Tratamiento exacto aplicado una sola vez

ID 2: eliminado después de revalidar todas las FK dentro de la transacción; también se eliminaron sus cinco sesiones y su registro de límite de login. No tenía eventos ni historial documental.

ID 1: conserva el ID, rol AUDITOR_INTERNO y todas sus FK. Nombre: `Usuario histórico local 01`; correo y correo normalizado: `usuario_historico_01@local.invalid`; activo: false. Se sustituyó password_hash por el hash de una contraseña aleatoria descartada y se actualizó updated_at. Tenía cero sesiones que revocar. No se publica ese hash ni una credencial histórica.

En los seis eventos sólo se sustituyeron las cadenas de nombre/correo dentro de actor_snapshot por la misma identidad histórica anónima. ID de evento, actor_id=1, acciones, entidad, timestamps y payloads de dominio conservaron sus valores. Se compararon todas las demás columnas antes/después. Ningún actor A se reasignó a B. La limpieza se confirmó en una transacción y el scan de todas las columnas textuales de la BD ya no encontró los dos correos retirados.

Sólo cambiaron las tablas `usuarios`, `auth_sessions`, `auth_login_limits` y la columna de identidad `eventos_auditoria.actor_snapshot`. DDL, documentos, versiones, auditorías, demás datos operativos y archivos permanecen intactos. La BD real mantiene una auditoría, tres documentos, dos versiones, seis eventos y dos archivos; no hay FK huérfanas.

| Fingerprint agregado | Antes | Después |
|---|---|---|
| 15 tablas ajenas a la limpieza, filas + DDL | `3b9cb23fe461609a689ee2c0682dfca734b9d45914e335b4d0fc9da80b471bb9` | `3b9cb23fe461609a689ee2c0682dfca734b9d45914e335b4d0fc9da80b471bb9` |
| Manifiesto de bytes del storage real | `525062162a5b843d3142cfaa6a8b6c9f3a7dde4db061f92651b4c4bc988dde88` | `525062162a5b843d3142cfaa6a8b6c9f3a7dde4db061f92651b4c4bc988dde88` |

El fingerprint privado de api/.env y todos los archivos Python de routers/services/models/schemas/core/db también coincide. No se publican secretos ni hashes individuales de expedientes reales. La comprobación se repitió tras la interrupción y después de las pruebas aisladas.

## ADMIN demo y estado de login local antes del ajuste final

En `sistema_trazabilidad` queda un usuario histórico desactivado, cero usuarios activos y cero ADMIN activos. Samuel no puede iniciar sesión contra esa BD en este estado. Esto es deliberado: la BD privada local no se distribuye con el repo.

`identificador demo suministrado privadamente` no existe en la BD real. Se creó con el seed aprobado en un schema nuevo aislado de evaluación; login HTTP/PHP real comprobado. Se crearon exactamente las cuatro cuentas ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO y APROBADOR, con las contraseñas documentadas en aquel checkpoint, posteriormente retiradas y rotadas en Fase 9.2. Seed ejecutado dos veces: cuatro cuentas nuevas y después cero; ninguna autocreación en startup.

ADMIN consultó dos documentos globales; RESPONSABLE_AREA consultó sólo su documento, recibió 404 para documento ajeno y 403 en endpoints administrativos y ruta PHP de auditorías. Se comprobó logout/revocación. No se ejecutó seed sobre sistema_trazabilidad. Los procesos se detuvieron, y schema/usuario SQL/.env temporal propios se retiraron al acabar, tras comprobar nombres y las cuatro identidades sintéticas. Para levantar una evaluación futura, seguir Guía/README con un schema vacío y seed; no se reintroduce la cuenta personal.

## Branding frontend

Modificados: `frontend/includes/auth_header.php`, `frontend/includes/sidebar.php`, `frontend/assets/css/auth.css`, `frontend/assets/css/estilos.css`. Nuevos assets: `frontend/assets/branding/develop.jpg` (copia exacta del JPG suministrado) y `develop-logo.jpg` (recorte de coordenadas 136,110–440,207, 304 × 97 px). Se conserva símbolo/texto original, sin redibujo, IA o logos externos.

Presencia clara en acceso y formularios públicos; identidad menor en footer de sidebar autenticada. Texto HTML PluriOne y Develop acompaña al asset, con alt, dimensiones y proporciones conservadas. La superficie existente sigue sobria; no se extendió el gradiente. Breadcrumbs, títulos, logout y menús no se alteraron. Responsive comprobado a 1440, 390 y 320 px; no hay horizontal scroll en las vistas verificadas. Menú móvil, navegación por teclado, mensajes de error, recuperación, solicitud y challenge Turnstile se verificaron con Chrome real.

## Capturas y fuentes Markdown

Se renovaron las 11 capturas principales de docs/capturas con Chrome real y dataset aislado. Se añadieron diez capturas complementarias: login, recuperación, solicitud, dashboard y sidebar a 390/320 px. Total: 21 PNG. Ninguna procede de la BD real.

Manual usuario conserva sus procedimientos y rutas de imagen, con una nota de renovación visual. Evidencia conserva funcionalidades; se corrigió la procedencia de las nuevas capturas y se explicitó el rol de cada vista: pantallas públicas sin sesión, ADMIN en vistas globales y RESPONSABLE_AREA en la restringida. La figura del documento es vista ADMIN de un documento cuyo propietario es Responsable Demo. Las decisiones comprobadas en Fase 9 se identifican como ese resultado histórico, sin atribuir una repetición a esta fase.

Correcciones objetivas adicionales: Bitácora distingue la preservación de Fase 9 de la limpieza autorizada de Fase 9.1; Inventario refleja un usuario histórico inactivo y cero activos. Documento técnico, Guía, Manual técnico y PRD conservan exactamente sus Markdown aprobados. No se modificó README raíz ni se exportó a PDF. No se alteraron procedimientos funcionales ni contenido del análisis determinista.

## Documentos académicos

Se construyeron seis DOCX públicos y siete PDF con portada TESCI/TecNM, proyecto, tipo, Samuel Cruz Barrientos, Ingeniería en Sistemas, PluriOne / Develop, asesor Juan Méndez Herrera y Septiembre 2026 – Enero 2027. No se añadieron identidades o cargos nuevos. Diseño A4, Arial, márgenes consistentes, geometría vino/negro, membrete y pie institucional, headings, índices automáticos donde aplica, campos PAGE/NUMPAGES, tablas con encabezado repetido y figuras centradas con captions.

Los PDF provienen de Word instalado en modo oculto, tras actualizar los campos y repaginar; conservan la misma composición de los DOCX. Para Evidencia se usó un DOCX temporal de maquetación, que no se entrega. No hay Word con Markdown pegado. Los DOCX se validaron como ZIP/OpenXML, con comprobación de portada, estilos, índices, headers, footers, saltos, tablas y media. Las imágenes de captura tienen texto alternativo.

| Documento | Páginas PDF | Bytes PDF | Bytes DOCX público |
|---|---:|---:|---:|
| `02_BITACORA` | 3 | 246,482 | 249,407 |
| `03_DOCUMENTO_TECNICO` | 6 | 403,259 | 253,079 |
| `04_EVIDENCIA_PROYECTO` | 15 | 1,209,721 | No solicitado |
| `05_GUIA_INSTALACION` | 6 | 430,668 | 253,314 |
| `06_MANUAL_USUARIO` | 10 | 983,437 | 972,353 |
| `07_MANUAL_TECNICO` | 6 | 415,120 | 253,516 |
| `09_PRD` | 6 | 410,936 | 254,389 |

Se renderizaron las 52 páginas a PNG y se inspeccionaron todas las portadas y páginas mediante láminas de revisión, con detalles ampliados de frontend. Se corrigió la superposición inicial de portada y se eliminó la entrada del propio índice en la tabla de contenido. Validación final: sin texto fuera del papel, páginas vacías inesperadas, tablas cortadas o títulos solos; figuras/captions dentro de márgenes y numeración consistente. Las láminas temporales se retiran tras revisar.

## Pruebas

| Validación | Passed | Failed | Skipped |
|---|---:|---:|---:|
| frontend/tests completa, AUTH_BROWSER_TEST=1 | 312 | 0 | 0 |
| Chrome real incluido en frontend, no sumar otra vez | 49 | 0 | 0 |
| MySQL: evaluation_demo, auth y RBAC | 100 | 0 | 0 |
| Unit: evaluation_demo | 3 | 0 | 0 |
| PHP lint, 66 archivos | 66 | 0 | 0 |

API/PHP/Chrome demo aislados: PASS. Las dos deprecaciones conocidas del backend se registran como warnings; no son fallos. No se repitió benchmark de Fase 8 ni suite backend completa. El primer intento frontend quedó interrumpido y Chrome falló por permisos/sandbox de GPU; no se cuenta como suite completa válida. Se repitió fuera del sandbox con perfiles nuevos y sin cambios de seguridad o tests, resultando 312 passed en 381.12 s. Las 49 pruebas opt-in se ejecutaron realmente. Los nueve screenshots de challenge generados por tests se revisaron como evidencia temporal del widget con doble determinista; no acreditan una validación Cloudflare de Internet.

## Secret scan y PII

Se escanearon archivos publicables de Git (tracked y nuevos), fuentes Markdown/frontend/fixtures, texto de los siete PDF y XML/relaciones de los DOCX, metadatos/bytes de capturas, entregables y copias auxiliares de Downloads. Comparación exacta contra DB_PASSWORD/JWT_SECRET_KEY operativos en memoria, sin imprimirlos; SMTP y Turnstile privados no están configurados. También se buscaron formatos de JWT, llaves privadas, claves API y los dos correos retirados. No se distribuye ningún archivo .env, venv, dump o storage privado; api/.env.example sigue siendo un ejemplo permitido.

Resultado publicable: cero correos retirados y cero secretos operativos/tokens/llaves encontrados. Ese checkpoint conservaba credenciales demo documentadas. Fase 9.2 las retira del material público y las sustituye por un contrato privado; los fixtures sintéticos/placeholders de pruebas no son accesos de evaluación. Las 21 capturas se revisaron visualmente y proceden del seed; no se usó OCR automatizado. El PDF/JPG de referencia se revisó de sólo lectura por separado: ningún hallazgo textual de los correos/secretos buscados; no se distribuyen ni se garantizan todos los textos rasterizados de las 615 páginas ajenas.

## SHA-256 y carpeta de entrega

Destino: SistemaTrazabilidad_Entregables de Downloads. Nombres exactos 00–09, siete PDF y seis DOCX; 00 índice, 01 accesos y 08 MVP conservados como Markdown, junto con README Markdown. Copias auxiliares mantienen jerarquía para enlaces locales.

SHA256SUMS se genera después de cerrar todos los archivos y se verifica contra el 100% de los bytes copiados. Incluye exclusivamente entregables propios/copias auxiliares finales; excluye su propio hash y los dos archivos de referencia de sólo lectura. Las referencias tienen sus hashes separados en este informe. No se incluyen temporales ni nombres de versiones alternativas.

## Límites y Git final

SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS permanece intacto y no bloquea esta fase. Al cerrar la parte visual, la BD privada real no tenía login activo y la validación usó un schema aislado. El ajuste final autorizado documentado al final de este informe habilita las cuentas demo en la BD local habitual; la instalación nueva sigue usando el seed reproducible. No se implementó IA local ni se cambió 7E. No se afirma publicación remota o despliegue productivo. Los informes históricos de Fase 9 se preservan como registros de aquel momento, no como descripción de la limpieza posterior.

Git final: main; HEAD/origin/main en d54a81e; working tree dirty por Fases 9/9.1; diff check sin errores; staging vacío. Se revisó el diff tracked completo y se registraron los archivos nuevos. No se ejecutaron git add, commit, push, reset o rebase. El material queda para auditoría del alumno.

## Archivos Markdown principales y cierre del manifiesto

| Archivo | Formato | Bytes | Páginas |
|---|---|---:|---|
| `00_INDICE_ENTREGABLES.md` | Markdown | 1,655 | No aplica |
| `01_ACCESOS_PRUEBA.md` | Markdown | 823 | No aplica |
| `08_MVP.md` | Markdown | 3,917 | No aplica |
| `README.md` | Markdown | 16,693 | No aplica |

Manifiesto final: 78 archivos propios; verificación SHA-256 del 100% tras copiar. Los 13 PDF/DOCX y las 21 capturas están incluidos. Referencias excluidas y comprobadas separadamente.

## Ajuste final autorizado — acceso demo en la BD local

12 de octubre de 2026, posterior al cierre visual/documental. El alumno autorizó expresamente ejecutar el seed existente en `sistema_trazabilidad` para sustituir su acceso personal por cuentas ficticias. Este apartado actualiza el estado de login descrito antes del ajuste; no repite la limpieza ni la regeneración visual.

### Guardas y ejecución

api/.env y settings efectivos: MySQL loopback, DB_NAME=sistema_trazabilidad, APP_ENV=development; servidor MySQL 8.0.46 y Alembic 005. Valores privados no impresos; .env no modificado. El usuario histórico ID 1 estaba desactivado y el ID 2 ausente. No existían cuentas, área, códigos o marcador demo conflictivos. Se comprobó el plan mediante CLI sin confirmación, sin inserciones.

Desde api, con el venv existente:

```text
python -B -m app.scripts.seed_evaluation_demo --with-dataset
python -B -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

Primera ejecución confirmada: cuatro cuentas nuevas y dataset. Repeticiones: cero cuentas nuevas; snapshot de todas las filas, DDL estructural y bytes idéntico. No se modificó el seed ni se creó SQL alternativo de alta, autocreación en startup o nuevas contraseñas. La comprobación del DDL excluye únicamente el contador AUTO_INCREMENT, que avanza normalmente por las inserciones; no se reinició ni se forzó ningún ID.

### Altas exactas del seed

| Tabla | Registro nuevo / referencias |
|---|---|
| `usuarios` | `id=3; correo=identificador demo suministrado privadamente; nombre=Administrador Demo; rol=ADMIN; activo=1` |
| `usuarios` | `id=4; correo=identificador demo suministrado privadamente; nombre=Responsable Demo; rol=RESPONSABLE_AREA; activo=1` |
| `usuarios` | `id=5; correo=identificador demo suministrado privadamente; nombre=Auditor Demo; rol=AUDITOR_INTERNO; activo=1` |
| `usuarios` | `id=6; correo=identificador demo suministrado privadamente; nombre=Aprobador Demo; rol=APROBADOR; activo=1` |
| `areas` | `id=2; nombre=Área Demo; codigo=EVAL-DEMO` |
| `auditorias` | `id=4; nombre=Auditoría Demo 2026; codigo=EVAL-AUD-2026; estado=PLANNED; responsable_id=5` |
| `auditorias` | `id=5; nombre=Auditoría Demo de alcance restringido; codigo=EVAL-AUD-PRIVADA; estado=PLANNED; responsable_id=5` |
| `documentos` | `id=4; codigo=EVAL-DOC-2026; estado=DRAFT; tipo=EVIDENCIA; responsable_id=4` |
| `documentos` | `id=5; codigo=EVAL-DOC-PRIVADO; estado=DRAFT; tipo=EVIDENCIA; responsable_id=3` |
| `versiones_documento` | `id=3; documento_id=4; numero_version=1` |
| `documentos_auditoria` | `id=1; documento_id=4; auditoria_id=4; version_documento_id=3` |
| `eventos_auditoria` | `id=14; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=AUDITORIA; entidad_id=4` |
| `eventos_auditoria` | `id=15; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=AUDITORIA; entidad_id=5` |
| `eventos_auditoria` | `id=16; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=DOCUMENTO; entidad_id=4` |
| `eventos_auditoria` | `id=17; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=DOCUMENTO; entidad_id=5` |
| `eventos_auditoria` | `id=18; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=HALLAZGO; entidad_id=1` |
| `eventos_auditoria` | `id=19; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=EVIDENCIA; entidad_id=1` |
| `eventos_auditoria` | `id=20; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=RONDA_APROBACION; entidad_id=1` |
| `eventos_auditoria` | `id=21; actor_id=3; accion=SEED_EVALUATION_DATASET; entidad_tipo=EVALUACION; entidad_id=v1` |
| `evidencias` | `id=1; tipo=NOTE; documento_id=4; auditoria_id=4; version_documento_id=3` |
| `hallazgos` | `id=1; estado=OPEN; auditoria_id=4; responsable_id=5` |
| `hallazgos_evidencias` | `hallazgo_id=1; evidencia_id=1` |
| `rondas_aprobacion` | `id=1; estado=PENDING; version_documento_id=3` |
| `decisiones_aprobacion` | `id=1; estado=PENDING; aprobador_id=6; ronda_aprobacion_id=1` |

Un archivo TXT sintético nuevo de 67 bytes, con el contenido definido por el seed. Ningún archivo anterior cambió. Los ocho eventos nuevos pertenecen al actor demo ID 3 y están marcados como SEED_EVALUATION_DATASET; no se alteraron los seis eventos históricos ni se reasignó su actor.

Estado actual: cinco usuarios totales, cuatro activos demo y un histórico desactivado. ADMIN demo ID 3; RESPONSABLE_AREA ID 4; AUDITOR_INTERNO ID 5; APROBADOR ID 6. El ID 2 continúa ausente y la identidad personal retirada no se recreó. Tres auditorías, cinco documentos, tres versiones, catorce eventos y tres archivos en storage: cada incremento corresponde únicamente al seed registrado arriba.

### Validación del acceso habitual y preservación

API 127.0.0.1:8000 y frontend del repo en 127.0.0.1:8080, sin cambios de configuración ni interfaz. Login/me/logout HTTP correcto para los cuatro roles demo. Login por PHP y Chrome real correcto para ADMIN y RESPONSABLE_AREA. ADMIN consultó los cinco documentos y tres auditorías globales y accedió a usuarios/administración. RESPONSABLE_AREA consultó sólo EVAL-DOC-2026; los otros cuatro documentos devolvieron 404, y auditorías, hallazgos, usuarios y solicitudes devolvieron 403. Las rutas manuales PHP y Chrome administrativas también fueron rechazadas para ese rol. Se comprobó logout/revocación.

Smoke local: **89 comprobaciones passed, 0 failed, 0 skipped**. Creó exclusivamente ocho sesiones demo, todas revocadas al salir, y cuatro registros efímeros de límite de login de las identidades demo. No se publican SID/JWT. Los procesos API/PHP/Chrome arrancados por el validador se detuvieron al finalizar; no se detuvieron servicios ajenos. Las cuentas permanecen en la BD y funcionan al iniciar los servicios habituales.

Tests afectados: test_evaluation_demo_unit y test_evaluation_demo_mysql, **10 passed, 0 failed, 0 skipped**, con las dos deprecaciones backend conocidas. Las pruebas MySQL usaron sus schemas temporales propios. No se repitieron suites visuales, benchmark o exports académicos.

Fingerprint final: todas las filas anteriores al seed conservan su misma PK y digest; todas las tablas conservan DDL estructural; los archivos originales, el usuario histórico ID 1, todas sus relaciones y api/.env mantienen sus bytes/valores. Después del smoke sólo cambiaron auth_sessions y auth_login_limits respecto al snapshot del seed, por la autenticación demo descrita. Backend e interfaz siguen idénticos. Se corrigió únicamente el validador temporal para registrar también claves primarias compuestas; no fue un fallo del seed ni de sus guardas.

### Documentación, entrega y Git

Se actualizan únicamente este informe y el estado actual del Inventario; sus copias Markdown en Downloads se sincronizan y SHA256SUMS se recalcula sobre los mismos 78 archivos propios. Los trece PDF/DOCX y las veintiuna capturas conservan sus bytes finales ya auditados. Los dos archivos de referencia siguen intactos y excluidos del manifiesto propio.

git diff --check sin errores; staging vacío; main y HEAD/origin/main d54a81e preservados. Sin git add, commit, push, reset o rebase. SMTP, 7E, workflows, RBAC y runtime no cambiaron.
