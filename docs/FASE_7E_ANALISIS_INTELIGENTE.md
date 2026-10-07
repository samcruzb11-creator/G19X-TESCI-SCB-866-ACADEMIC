# Fase 7E — Análisis documental explicable

## 1. Objetivo

Apoyar la revisión documental con reglas locales, deterministas y explicables.
Cada resultado identifica recurso autorizado, tipo, clasificación, severidad,
explicación, evidencia técnica, regla versionada, timestamp y destino tipado.
Una detección no equivale a una verdad de negocio ni autoriza una modificación.

## 2. Qué significa análisis inteligente

Combinar hashes existentes, estructura de datos, orden de versiones, relaciones
y similitud matemática de nombres para señalar hechos que merecen revisión.
Todos los resultados permiten responder «¿Por qué se marcó?». La interfaz
expone la regla y sus condiciones; los metadatos inválidos identifican los
campos afectados sin publicar sus valores sensibles.

## 3. Qué no es

No hay IA generativa, entrenamiento ML, clasificación semántica, embeddings,
OCR, Document Intelligence, LLM local/remoto, Azure OpenAI ni llamadas a
OpenAI/Gemini/Claude. El motor no depende de Internet ni de servicios de pago.
No detecta fraude, documentos falsos, incumplimiento legal confirmado ni
autenticidad criptográfica del emisor. No introduce un porcentaje de confianza.
La autenticación y los módulos previos conservan su configuración existente.

## 4. Baseline y arquitectura

Preflight inicial, antes de editar: `main`, working tree CLEAN, staging vacío;
HEAD y origin/main **dc32f6e0c5a06b2e7ae391c38d7039004d2613d6**.
`git ls-remote origin refs/heads/main` confirmó ese hash publicado con mensaje
`feat(dashboard): implement phase 7D alerts indicators and executive dashboard`.
La interrupción dejó únicamente schemas/analisis.py y services/analisis_rules.py;
se inspeccionaron completos y se continuó conservando su contenido válido.

MySQL **8.0.46**, InnoDB, **REPEATABLE READ**; Alembic current y único head **005**.
19 tablas reales y dos archivos reales. Se inspeccionaron entidades,
Documento/VersionDocumento/DocumentoAuditoria/Evidencia/Hallazgo/HallazgoEvidencia,
Auditoria/RondaAprobacion/DecisionAprobacion/EventoAuditoria, servicios de dominio,
storage, authorization_service, dashboard_queries/dashboard_service, frontend,
migraciones e índices reales y fixtures/suites anteriores.

Componentes:

- `schemas/analisis.py`: entradas estrictas y DTOs sin hashes/storage_key.
- `services/analisis_queries.py`: CTEs autorizadas, ventanas, UNION y paginación SQL.
- `services/analisis_rules.py`: normalización, política local y stat seguro.
- `services/analisis_service.py`: explicación, resumen, detalle y barrera de autorización.
- `routers/analisis.py`: cuatro GET autenticados, no-store.
- PHP: controller/helpers, vista Análisis y partial de resultados.

No hay tabla de resultados, cache entre usuarios, jobs de análisis, persistencia
de «analizado», eliminación ni reparación automática. Se deriva en cada consulta.
No se crea migración **006** ni se cambia DDL/índices reales; 005 continúa como head.

## 5. Reglas SQL implementadas

| Código | Condición verificable | Clasificación | Severidad |
| --- | --- | --- | --- |
| DUPLICATE_HASH | SHA-256 hexadecimal válido compartido por versiones visibles de documentos distintos | posible duplicado | INFO |
| HASH_REPETIDO | Versiones visibles distintas del mismo documento comparten hash válido | señal | INFO |
| VERSION_SIN_CAMBIO | Versiones visibles N/N+1 comparten hash válido | señal | INFO |
| SECUENCIA_TEMPORAL | created_at de N+1 anterior a N visible | inconsistencia objetiva | WARNING |
| NUMERO_VERSION_DUPLICADO | COUNT visible por documento/número > 1 | inconsistencia objetiva | WARNING |
| METADATA_INCOMPLETA | Título vacío o estructura de archivo inválida | inconsistencia objetiva | WARNING |
| DOCUMENTO_SIN_VERSION | Documento existente sin versiones; excluye APROBADOR | señal | INFO |
| VERSION_VIGENTE_INCONGRUENTE | Referencia vigente visible pertenece a otro documento; ausencia solo para ADMIN completo | inconsistencia objetiva | WARNING |
| RELACION_INCONGRUENTE | Extremos visibles tienen documento/auditoría incompatibles; referencias incompletas de evidencia para ADMIN | inconsistencia objetiva | WARNING |
| ESTADO_DESCONOCIDO | Estado de documento/tipo de evidencia fuera de whitelist binaria exacta | anomalía | INFO |

Relaciones: pivots documento/auditoría/versión, versión vigente, referencias de
evidencia y HallazgoEvidencia. Ambos extremos se autorizan antes de comparar.
Las relaciones corruptas excluidas por evidencia_scope no se vuelven accesibles
por análisis. ADMIN puede revisar la inconsistencia estructural de esas filas.
No se impone evidencia obligatoria por hallazgo. No se reproducen las alertas
de ronda/decisión pendientes de 7D: las aprobaciones participan en el scope exacto
de versiones y en las pruebas de concurrencia, sin reglas de cumplimiento nuevas.

## 6. Duplicados exactos

Se valida longitud 64 y caracteres hexadecimales ASCII. Se compara LOWER del
hash; mayúsculas/minúsculas representan los mismos bytes del digest. Un hash
ausente, inválido o con padding no es una clave de duplicación válida.

Ventanas sobre el conjunto autorizado calculan extremos por hash, repetición
por documento/hash y LAG por documento/número/ID. No se compara una versión
consigo misma ni se generan todos los pares. Cada versión tiene a lo sumo un
resultado por regla y un representante visible relacionado. Un grupo grande
produce O(n) resultados, no n*(n-1)/2 pares. Los representantes se seleccionan
determinísticamente por documento/ID. No se afirma que todos los pares se listen.

La igualdad descrita es la del SHA-256 **registrado** por las cargas existentes;
el endpoint no abre/rehashea contenidos ni certifica su integridad física actual.
No modifica ni elimina versiones repetidas. Un mismo documento puede tener
HASH_REPETIDO y VERSION_SIN_CAMBIO: explican hechos distintos, no dos documentos.

## 7. Duplicados potenciales

Solo en detalle de documento/versión. Ancla: última versión **visible** del
documento solicitado, o la versión solicitada. Prefiltro SQL sobre versiones
autorizadas de documentos distintos: tamaño registrado exactamente igual,
extensión final igual con LOWER SQL, hashes válidos y distintos, ID ascendente,
LIMIT 65. Solo se comparan los primeros **64** candidatos.

SequenceMatcher local, `autojunk=False`, argumentos ordenados canónicamente
para evitar asimetría. Requiere nombre normalizado de al menos ocho caracteres
y un token completo común. El resultado >= threshold se etiqueta
POSIBLE_DUPLICADO, INFO, con el valor matemático real `similitud_nombre` y
threshold aplicado en la evidencia. No es probabilidad de fraude/confianza IA.
Dos nombres iguales con contenido distinto pueden producir esta señal; no
producen DUPLICATE_HASH. No hay comparación O(n²) global ni embeddings.

## 8. Normalización

Unicode **NFKC**, casefold, puntuación Unicode sustituida por espacios y
colapso de espacios. Se conservan letras, acentos y dígitos; no se borran meses,
números, años ni tokens. La comparación separa stem y extensión final.
`Factura Enero.pdf`, `factura enero.PDF`, `Factura-Enero.pdf` dan similitud 1.
Factura Enero/Febrero, 123/456, extensiones distintas, nombres demasiado cortos
y nombres sin token común se prueban como negativos conservadores.

El prefiltro SQL no realiza NFKC: una extensión escrita con caracteres Unicode
compatibles puede quedar excluida antes de normalizar. Se acepta ese falso
negativo, se documenta y no se amplía el scan para simular cobertura semántica.

## 9. Versionado

El dominio asigna MAX(numero_version)+1 y tiene UNIQUE(documento_id,numero).
Se conserva esa implementación. Legacy puede violar UNIQUE si se altera DDL;
solo se reproduce esa corrupción en el schema temporal protegido y se restaura.
No se denuncia un salto: el motor no inventa una prohibición de saltos legítimos.
LAG solo señala continuidad N/N+1 realmente visible. APROBADOR no puede inferir
una versión oculta a partir de una supuesta ausencia o secuencia.

## 10. Metadatos

FILE/versiones: SHA-256 válido, tamaño no nulo y >=0, storage_key/nombre/MIME
no vacíos. Tamaño cero es válido. Documento: título no vacío. Evidencia FILE
se identifica con tipo canónico exacto. La máscara interna señala los campos
inválidos en la evidencia técnica sin devolver hash, ruta, MIME hostil ni valores
desconocidos. MIME es metadata declarada: no se usa como prueba del contenido ni
como detector de archivos maliciosos. Estados legacy de case/padding desconocido
se tratan conservadoramente, sin activar una regla de un estado distinto.

## 11. Storage read-only

El detalle verifica disponibilidad de hasta **100** versiones visibles, en orden
de número/ID descendentes; SQL obtiene 101 para informar alcance parcial.
No recorre storage global ni analiza archivos ajenos. No abre contenido,
rehashea, renombra, mueve, borra ni crea directorios.

Reutiliza StorageService.get_absolute_path después de validar referencias
administradas documents/evidence. Rechaza traversal con ambos separadores,
absolutos, drives, UNC, porcentajes codificados, NUL y symlinks/junctions en los
componentes lexicales. No inspecciona el destino de una referencia rechazada.
La prueba Windows usa symlink si hay privilegio o una junction NTFS temporal.

RUTA_NO_SEGURA es WARNING/inconsistencia objetiva. ARCHIVO_NO_DISPONIBLE es
WARNING/anomalía: stat no confirmó archivo regular, lo que puede significar
ausencia o indisponibilidad temporal. No se afirma pérdida definitiva.
La BD y el filesystem no comparten una transacción: stat describe el instante
de consulta. No protege frente a un administrador local hostil que intercambie
directorios repetidamente durante stat; el servicio no lee contenido y el root
administrado debe mantenerse bajo control del proceso. No se ofrece reparación.

El listado/resumen SQL no incluyen disponibilidad física ni similitud. Esas
comprobaciones se muestran por separado en detalle y no se suman a contadores
globales. `comprobacion_completa`, `candidatos_truncados`, límites y cantidades
permiten reconocer cobertura parcial. Evidencias FILE tienen análisis estructural
SQL; esta fase no recorre sus archivos físicos desde la vista global.

## 12. Severidades

INFO describe igualdad registrada, posible similitud, ausencia de versión de
un documento existente o estado desconocido. WARNING señala incoherencia
estructural/temporal o disponibilidad no comprobada. No se utiliza CRITICAL ni
score global. La interfaz expresa la clasificación y el texto, además del color.

## 13. Thresholds y límites

LocalPolicy centraliza threshold **0.92**, 64 candidatos, 100 versiones y ocho
caracteres mínimos. `ANALYSIS_SIMILARITY_THRESHOLD` configura el threshold al
iniciar la API, entre 0.8 y 1. No se permite configuración por usuario/HTTP.
El resultado cambia explícitamente con la configuración y siempre la declara.
Las pruebas cubren nextafter(threshold,0), threshold, nextafter(threshold,1)
y ratios SequenceMatcher reales 0.88/0.92/0.96. No hay redondeo previo al corte.

## 14. RBAC

| Rol | Alcance conservado |
| --- | --- |
| ADMIN | Lectura completa existente; incluye inconsistencias legacy |
| AUDITOR_INTERNO | Documentos vinculados a sus auditorías, sus versiones legibles y evidencias/hallazgos scoped |
| AUDITOR_EXTERNO | Su scope documental existente, sin escrituras nuevas |
| RESPONSABLE_AREA | Documentos de los que es responsable; Usuario no tiene area_id |
| APROBADOR | Solo versiones asignadas y documentos ya legibles; nunca todas las versiones del documento |
| CONSULTA/inactivo/desconocido | Fail closed; no se introduce ese rol ni permiso nuevo |

No se crea analisis.read global. Se reutilizan las expresiones de autorización
de 6B.2/7C y contexto 7D. Para auditores/responsables, version_scope equivale
al scope del documento padre: el join con documentos autorizados lo aplica sin
repetir el mismo EXISTS. APROBADOR conserva la asignación de versión exacta.
Filtro auditoria_id requiere auditoria.read y padre scoped; inexistente/ajeno
dan el mismo 404. Sin permiso de auditoría, cualquier ID da 403.

## 15. Duplicate leakage, privacidad y concurrencia

Scope SQL precede joins de comparación, ventanas, counts, agregados, order,
limit y offset. CTEs DISTINCT sobre IDs únicos fuerzan materialización MySQL
para evitar reevaluar permisos correlacionados por cada candidato.
No se compara global para esconder después. No se devuelven hash completo,
storage_key, rutas, auditorías relacionadas ocultas, nombres/IDs ajenos ni
contadores/flags de coincidencias invisibles.

Pruebas metamórficas agregan un documento/version secreta con hash idéntico;
comparan resumen, listado, detalle, cantidades, flags, páginas y enlaces para
todos los roles limitados. Todo permanece igual salvo timestamp de evaluación.
El E2E usa usuario real sin acceso al duplicado secreto, PHP y FastAPI reales.
No se promete tiempo HTTP criptográficamente constante: SQL/IO/planificadores
pueden variar, pero no hay consultas de coincidencias globales ni indicadores
dependientes de recursos ocultos.

Datos y agregados de una petición usan el snapshot existente REPEATABLE READ.
Antes de emitir la respuesta, una conexión distinta inicia una transacción
READ ONLY: vuelve a leer usuario/sesión y recalcula una huella de los IDs
autorizados. Los IDs se procesan en streaming, sin metadata ni cargar anomalías.
Scope cambiado: **409**, se descarta toda respuesta y se pide volver a consultar.
Usuario inactivo/rol cambiado: 403; sesión revocada/caducada: 401.

Esto evita entregar datos bajo un snapshot viejo tras una revocación confirmada
durante el análisis. No hace commit/refresh del snapshot de negocio, ni usa locks.
Una nueva versión/evidencia también cambia el conjunto visible y produce 409;
edición de metadata/cierre/decisión sin cambio de alcance conserva el snapshot
coherente. La autorización se evalúa en la barrera final; una revocación posterior
afecta la siguiente petición. Su punto de consistencia es el primer SELECT de
la transacción fresca REPEATABLE READ. No hay sistema capaz de revocar bytes ya enviados.
La barrera necesita una segunda conexión libre; provisionar el pool para esa
concurrencia. La aplicación actual permite overflow del pool.

## 16. Endpoints

| GET bajo /api/v1 | Resultado |
| --- | --- |
| /analisis/resumen | Total SQL por regla/severidad, timestamp y alcance |
| /analisis/anomalias | COUNT y página SQL de resultados |
| /analisis/documentos/{id} | Página SQL del documento y comprobaciones locales limitadas |
| /analisis/versiones/{id} | Página SQL de la versión y comprobaciones locales limitadas |

Autenticación existente en los cuatro; no-store; POST/PATCH/DELETE 405.
Entradas Pydantic extra=forbid. IDs ASCII decimales exactos >0 hasta
18446744073709551615; no bool, float, científico ni coerción de Unicode.
Resumen: auditoria_id/documento_id. Listado/detalle: esos filtros, tipo y
severidad whitelist, limit 1..100 (default 20), offset 0..10000.
Orden: WARNING antes de INFO, tipo, recurso e ID ascendentes.
documento_id filtra resultados fuente después de comparar dentro del scope
autorizado completo/contextual; no elimina otros documentos autorizados de la
comparación. El detalle de versión valida la pertenencia si se envía documento_id.
Los tipos exclusivamente locales devuelven cero en listado/resumen SQL;
se deben consultar en detalle. El filtro local se aplica a sus resultados.

## 17. Frontend / dashboard

Vista Análisis empresarial con resumen, severidad, tipo, filtros por ID,
paginación, explicación desplegable, evidencia y enlaces autorizados. Detalle
separa comprobaciones locales e informa cantidades/límites/truncamiento.
Empty state no certifica cumplimiento. Errores no fabrican ceros; 401 limpia
sesión/redirige y 403 se conserva. JWT exclusivamente en sesión PHP.

Dashboard añade panel/enlace separado «Análisis documental»: **cero SELECT
adicionales en resumen 7D**, sin mezclar anomalías con alertas de workflow.
Documento enlaza a su análisis. Todos los textos dinámicos usan e(); destinos
whitelist y validación de ID/permiso de presentación. Sin URLs externas ni JS
para autorizar. CSRF existente de mutaciones/logout no cambia; vista GET-only.

El transporte PHP conserva BIGINT unsigned como string con JSON_BIGINT_AS_STRING.
Análisis muestra IDs completos y puede filtrarlos; suprime enlaces a detalles
antiguos que dependen de entero nativo PHP si el ID excede PHP_INT_MAX. Esa
limitación previa se conserva explícita; no se emiten enlaces rotos ni floats.
Chrome real: cinco roles x 1440/390/320, sin overflow, Tab/foco visible, labels,
details, filtros, enlaces, XSS script/img/svg y JWT ausente.

## 18. Performance y complejidad

Dataset exclusivamente temporal: **1008 usuarios, 204 auditorías, 2004 documentos,
3605 versiones, 2004 evidencias, 2000 hallazgos, 1804 rondas, 3604 decisiones,
4000 eventos y 1804 pivots**. Grupos grandes de hashes repetidos, nombres
similares y versiones consecutivas iguales. Datos sintéticos sin PDFs reales.

Ventanas/ordenamiento O(n log n) sobre versiones visibles; salida por reglas
O(n). No hay join cartesiano de todos los pares ni comparación Python global.
Prefiltro de similitud puede escanear filas scoped, con LIMIT 65 y <=64
comparaciones de cadenas de longitud limitada por schema. Storage <=100 stats.
Las huellas de scope son lineales y streaming. Counts/paginación se ejecutan
en SQL: no se cargan todas las anomalías para paginar en Python.

Medición representativa local, TestClient + MySQL, cinco roles y cuatro endpoints:

| Rol | Resumen ms | Listado ms | Documento ms | Versión ms |
| --- | ---: | ---: | ---: | ---: |
| ADMIN | 398.42 | 611.49 | 636.01 | 593.70 |
| AUDITOR_INTERNO | 205.00 | 337.05 | 424.24 | 329.65 |
| AUDITOR_EXTERNO | 16.93 | 32.35 | 34.24 | 31.53 |
| RESPONSABLE_AREA | 174.89 | 301.02 | 317.60 | 308.34 |
| APROBADOR | 194.05 | 340.29 | 374.04 | 347.54 |

No es SLA ni prueba de carga multiusuario. El test falla si un endpoint supera
cinco segundos o su presupuesto; el optimizador necesita estadísticas sanas.
El primer intento detectó un listado auditor >5 s: se eliminó scope redundante,
se verificaron estadísticas y se materializaron CTEs scoped para evitar EXISTS
de asignación por fila. ANALYZE TABLE se ejecuta **solo en el schema efímero**
tras bulk load, nunca sobre sistema_trazabilidad. La mejora no depende de índices
nuevos ni de modificar autorización/aislamiento global.

## 19. Query budget

Fixture de identidad: **5 SELECT resumen, 6 listado, 9 detalle**, constantes
con el volumen, incluida la barrera fresca y un SELECT de identidad del fixture.
Sin N+1 por versión/candidato. Checkout SELECT DATABASE() de la guarda de test
no se cuenta como consulta de aplicación; tampoco SET TRANSACTION ni ping.
Auth real agrega la sesión inicial y la comprobación fresca de sesión respecto
al fixture: presupuestos típicos **7/8/11**. Contexto auditoría añade uno;
detalle de versión con documento_id explícito añade otro (máximo 13).
Las pruebas de lectura instrumentan SQL: **0 INSERT/UPDATE/DELETE/DDL**.
El presupuesto 7D permanece intacto; el dashboard solo añade el enlace.

## 20. EXPLAIN e índices

Se capturan y explican todos los SELECT relevantes de los cinco roles en los
cuatro endpoints, incluyendo huellas de scope, counts, CTEs/ventanas y candidatos.
Planes temporales reproducibles generados por el test de volumen; no se suben
SQL con datos privados ni dumps. Se observan PK, uq_versiones_documento_numero,
ix_documentos_responsable, ix_documentos_auditoria_documento,
uq_documentos_auditoria_version, ix_auditorias_responsable,
uq_decisiones_ronda_aprobador, uq_rondas_version_numero,
ix_evidencias_auditoria_tipo y uq_hallazgos_auditoria_numero, además de índices
automáticos de CTE materializada. Materialización/filesort son esperables.

ix_versiones_documento_sha256 existe; el análisis por ventanas recorre el
conjunto autorizado y no depende de buscar hashes globales por ese índice.
El prefiltro tamaño/extensión no tiene un índice dedicado: con el volumen
medido no es crítico. No se crea 006 por intuición. Si el volumen futuro exige
otro índice, medir EXPLAIN/latencia primero y tramitar autorización de migración.

## 21. Tests y autoauditoría

Suites: tests_unit/test_analisis_unit.py, tests_auth_mysql/test_analisis_mysql.py,
tests_auth_mysql/test_analisis_e2e_mysql.py, frontend/tests/test_analisis.py y
test_analisis_browser.py. Fixtures bloquean conexiones a BD de aplicación,
SMTP y Siteverify reales. MySQL crea/drop solo un nombre aleatorio guardado;
prueba migraciones 001–005 upgrade/downgrade, sin migrar BD real.

Cobertura: hashes iguales/diferentes/case/invalid, no self-pair, duplicados
visibles/secretos por rol, IDOR, filtros cross-audit/cross-document/version,
privacidad de hash/rutas, metadata FILE, fecha/número legacy, estados MySQL con
collation permisiva, referencias ausentes, sin-version/alcance parcial,
normalización/falsos positivos/corte exacto, límites/truncamiento, unsigned BIGINT,
SQLi/whitelist, auth/405, GET read-only, XSS/links, storage temporal y traversal,
symlink/junction, N+1, EXPLAIN/volumen y carreras de scope/rol/asignación/sesión.

Storage temporal contiene A/B idénticos, C distinto, D mismo nombre distinto
contenido, E distinto nombre mismo contenido, archivo ausente y ruta maliciosa.
Se verifica que existencia/lectura no muta las huellas del storage temporal.
Las corrupciones de DB/storage jamás se ejecutan sobre recursos reales.

E2E real: login PHP, crear dos documentos y cargar bytes idénticos vía PHP →
FastAPI → MySQL/storage temporales, consultar análisis y seguir enlace. Otro
usuario real ve un recurso pero no puede inferir el duplicado secreto, y se
comprueba revocación. Tercer E2E usa Chrome real y navega a documento autorizado.
Sin mocks en esos tramos; get_db/storage se configuran con infraestructura temporal.

Regresiones completas 6A, 6B.1/2/3/4A/4B, 6C, 6D/6D.1, 7A/B/C/D: unitarias,
MySQL protegido (6A mediante wrapper que evita conftest legacy), PHP y Chrome.
Los opt-in Chrome se ejecutan por separado cuando la suite normal los omite.
En Windows el sandbox cortó DevTools; se repitieron las mismas pruebas con
autorización fuera del sandbox y perfiles temporales. No se debilitó el test.

Incidencias corregidas en autoauditoría: consulta redundante/CTE fusionada,
estadísticas tras carga masiva temporal, aserción textual de ID que confundía
un fragmento del timestamp con un ID secreto, preservación BIGINT en PHP,
selección del enlace documental correcto en E2E con evidencia legacy visible,
y falso positivo de referencia vigente «ausente» al excluir una versión por
auditoria_id. La ausencia ADMIN consulta su scope completo; el filtro no
transforma una referencia existente en referencia inexistente.
Pruebas afectadas repetidas tras las correcciones. No se modificó el workflow.

## 22. Limitaciones y deuda técnica

Detección basada en metadata registrada; no lee contenido, firmas ni semántica.
Coincidencias pueden ser legítimas. Umbrales conservadores generan falsos
negativos; nombres iguales y tamaño igual pueden generar señales sin duplicidad.
Similitud solo de la última versión visible o versión solicitada, <=64 candidatos;
storage <=100 versiones visibles. No se presentan esos límites como cobertura
global. No hay scanner físico global de evidencias en el endpoint de análisis.
No se amplía acceso a huérfanos de versión sin documento padre legible.

La frescura de permisos necesita segunda conexión y revisión de todas las
identidades scoped; presupuestar pool/latencia si crece el volumen. La lectura
de datos es un snapshot y la disponibilidad física un instante independiente.
No se garantiza tiempo HTTP constante. BIGINT >PHP_INT_MAX no navega a páginas
antiguas que usan enteros nativos; sí se conserva exacto y se analiza/filtra.
Paginación accesible hasta offset 10000; no es una exportación completa.
FastAPI/Starlette emiten warnings de deprecación existentes del test client;
no se actualizan dependencias ajenas a la fase.

## 23. Documentos faltantes

**No implementable con certeza sin catálogo/regla de negocio explícita.**
No se inventa que falten Contrato, Factura ni otros documentos obligatorios.
DOCUMENTO_SIN_VERSION describe un Documento que sí existe. ARCHIVO_NO_DISPONIBLE
describe disponibilidad de una referencia existente; ninguno demuestra ausencia
de un documento requerido ni incumplimiento.

## 24. Futuras capacidades

La separación consultas/reglas/DTO permite añadir posteriormente embeddings,
OCR, modelos ML, LLM o catálogo de requerimientos con autorización, evidencia,
versionado de reglas, límites y pruebas de leakage. Esas capacidades no están
implementadas ni son necesarias para el motor determinista de esta fase.

## 25. Resultado y protección del repositorio público

Implementación sin commit/push/staging. Únicamente cambios 7E; README raíz final
no creado. No se versionan passwords, JWT secretos, SMTP/Turnstile secrets,
API keys/tokens reales, PII, PDFs, contenido analizado, dumps ni artefactos de
test/Chrome. Los hashes sintéticos de tests son fixtures, no archivos reales.
Nombres/correos de fixtures usan example.invalid.

La huella inicial se capturó fuera del repo, en TEMP, con transacción explícita
READ ONLY y snapshot consistente. Incluye lista de tablas, counts, digest de
filas/DDL/índices/Alembic y nombres relativos/tamaños/SHA-256 de storage real.
Se compara la misma huella al cierre sin publicar contenido ni hashes reales.
Los schemas creados se eliminan por finally de sus fixtures; temporales de esta
ejecución se limpian después de resumir mediciones. No se toca storage real.

El resultado de verificaciones y estado Git definitivo se registra en el
reporte de cierre siguiente, que debe leerse junto con estas limitaciones.

## 26. Registro final de verificación

| Verificación | Resultado |
| --- | --- |
| Unitarias completas definitivas | **1192 passed**; incluyen **125** contratos 7E |
| MySQL completo 6A–7E | **1060 passed, 2 skipped**; los dos Chrome opt-in se ejecutaron aparte |
| MySQL 7E tras última corrección | **138 passed**; corrupción, 8 carreras, sesión revocada, EXPLAIN/volumen |
| PHP completo final | **263 passed, 49 skipped**; skips Chrome opt-in cubiertos aparte |
| Frontend completo con Chrome | **311 passed**; recogido antes del test BIGINT PHP añadido, cubierto por PHP final |
| Regresión PHP transporte/Análisis/dashboard/auth/downloads después de BIGINT | **103 passed** |
| Chrome específico 7E | **15 passed**, cinco roles x tres anchos |
| E2E 7E definitivo con auth/SQL reales | **3 passed**, incluye Chrome; 0 DML/DDL, presupuestos 7/8/11 |
| E2E regresión 7D con Chrome | **2 passed** |
| PHP lint | **66 archivos**, sin errores |
| Último volumen tras corrección del filtro | **17.41–658.17 ms**, 5/6/9 SELECT; dataset descrito arriba |
| Fingerprint BD real | **Idéntico**: 19 tablas, filas, DDL, índices y Alembic 005 |
| Fingerprint storage real | **Idéntico**: dos nombres relativos, tamaños y SHA-256 |
| Schemas efímeros restantes | **0** |
| Revisión de repo público | 25 archivos de código/docs; sin secretos reales, PII, PDFs, dumps, logs ni imágenes |
| Git | `main`; HEAD/origin/main sin cambio; solo 7E, staging vacío, sin commit/push; diff check limpio |

Los tests terminan con warnings de deprecación de Starlette existentes. No hay
tests funcionales pendientes ni skips Chrome sin cubrir. El primer intento de
regresión 6A por tests/conftest.py se detuvo por su guarda TEST_DATABASE_URL;
6A se ejecutó completo por el wrapper MySQL efímero previsto por el proyecto,
sin tocar una base persistente de pruebas ni la BD real.

### Reporte solicitado, puntos 1–38

1. HEAD inicial: dc32f6e0c5a06b2e7ae391c38d7039004d2613d6.
2. origin/main inicial: mismo hash, verificado además en GitHub.
3. Estado inicial: main CLEAN, staging vacío, cierre 7D publicado.
4. MySQL: 8.0.46, REPEATABLE READ.
5. Alembic: current/head 005.
6. Migración nueva: no; sin cambios de schema/índices reales.
7. Arquitectura: CTEs scoped, ventanas, reglas locales, DTOs, servicio/router y PHP.
8. Reglas: diez tipos SQL y tres tipos locales, detallados en secciones 5–13.
9. Exactos: SHA-256 existente válido, self excluido, peers autorizados y salida lineal.
10. Potenciales: SequenceMatcher local, última ancla visible, prefiltro y <=64 pares.
11. Threshold: 0.92 por defecto, configurable 0.8–1, corte inclusivo sin redondeo.
12. Metadata: campos estructurales FILE/versiones y título; evidencia del campo inválido.
13. Versionado: repetición, N/N+1 idéntico, temporalidad y numeración duplicada legacy.
14. Storage: stat limitado/read-only, sin abrir contenidos ni reparar.
15. Documentos faltantes obligatorios: no soportados sin catálogo; sin-version sí.
16. RBAC: permisos/scopes existentes; APROBADOR exacto, CONSULTA fail closed.
17. Duplicate leakage: metamórficos de siete identidades limitadas y E2E real verde.
18. Endpoints: cuatro GET /analisis, auth, no-store y filtros estrictos.
19. Frontend: vista Análisis, filtros/resumen/explicación/detalle/enlaces/empty/error.
20. Dashboard: panel/enlace diferenciado, cero consultas adicionales 7D.
21. Query budget: fixture 5/6/9; auth real 7/8/11, sin N+1, 0 DML/DDL.
22. Performance: último rango 17.41–658.17 ms por endpoint/rol local.
23. EXPLAIN: cinco roles/cuatro endpoints; materialización/índices existentes revisados.
24. Volumen: 1008 usuarios, 204 auditorías, 2004 documentos, 3605 versiones y miles de recursos asociados.
25. Unit tests: 1192 completos, 125 de 7E.
26. MySQL tests: suite completa 1060 passed; 138 de 7E definitivos; opt-ins cubiertos.
27. Frontend tests: PHP final 263 passed; 103 regresiones posteriores al cambio BIGINT.
28. Chrome: 15 escenarios 7E y suite frontend completa con 311 passed; 1440/390/320.
29. E2E: tres 7E reales, dos de regresión 7D, todos verdes.
30. Regresiones: 6A–7D completas, incluyendo auth, RBAC, documentos, evidencias, hallazgos, aprobaciones, dashboard y alertas.
31. Autoauditoría: leakage, IDOR, traversal, cross-context, hash privacy, complejidad, XSS/SQLi, legacy, carreras, missing y threshold; corregido/reprobado lo encontrado.
32. BD real: fingerprint inicial/final idéntico; cero modificaciones.
33. Storage real: fingerprint inicial/final idéntico; cero modificaciones.
34. Secretos: revisión del diff y archivos nuevos sin credenciales/PII/contenido real.
35. Archivos: 10 modificados y 15 nuevos, enumerados abajo.
36. Deuda técnica: límites de detalle, no semántica/catálogo, segunda conexión, stat sin snapshot FS y páginas antiguas con entero PHP; sección 22.
37. Diff check: limpio, más comprobación de whitespace/UTF-8 de archivos nuevos.
38. Git final: main, HEAD/origin/main sin cambio, solo 7E, staging vacío; sin add/commit/push.

### Archivos de la fase

Modificados: api/README.md; api/app/core/config.py; api/app/main.py;
frontend/README.md; frontend/assets/css/estilos.css; frontend/includes/auth.php;
frontend/index.php; frontend/pages/dashboard.php; frontend/pages/documento.php;
frontend/services/api_client.php.

Nuevos: api/app/routers/analisis.py; api/app/schemas/analisis.py;
api/app/services/analisis_queries.py; api/app/services/analisis_rules.py;
api/app/services/analisis_service.py; api/tests_auth_mysql/test_analisis_mysql.py;
api/tests_auth_mysql/test_analisis_e2e_mysql.py; api/tests_unit/test_analisis_unit.py;
docs/FASE_7E_ANALISIS_INTELIGENTE.md; frontend/includes/analisis_list.php;
frontend/pages/analisis.php; frontend/services/analisis_controller.php;
frontend/services/analisis_helpers.php; frontend/tests/test_analisis.py;
frontend/tests/test_analisis_browser.py.

FASE 7E LISTA PARA AUDITORÍA INDEPENDIENTE DE ANTIGRAVITY
