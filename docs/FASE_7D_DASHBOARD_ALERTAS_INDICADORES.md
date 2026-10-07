# Fase 7D — Dashboard ejecutivo, alertas e indicadores

## 1. Objetivo

Dashboard PHP y consultas FastAPI deterministas sobre recursos que la cuenta ya
puede leer. KPI, porcentajes y severidades se calculan server-side. No se modifica
el workflow de auditorías, documentos, evidencias, hallazgos o aprobaciones.
No se implementan IA, Power BI, SMTP, autenticación nueva ni score global.

## 2. Baseline y preflight

Branch inicial `main`, working tree limpio y staging vacío.
HEAD y origin/main local: `c002df8936747bfd27046a32e618ad0d1802017e`.
`git ls-remote origin refs/heads/main` confirmó el mismo commit publicado:
`feat(approvals): implement phase 7C approval workflow`.
MySQL **8.0.46**; Alembic current y único head **005**, migraciones 001–005.
No se crea 006 ni se modifica estructura o datos reales.

Se inspeccionaron entidades, authorization_service, servicios 7A/7B/7C,
routers/schemas, índices reales, frontend, navegación, helpers RBAC y suites.
El dashboard anterior contaba páginas descargadas. Los nuevos totales se
agregan en SQL dentro del scope, sin truncarse al tamaño de una página.

Antes de editar se capturó en TEMP una huella mediante transacción MySQL
explícita READ ONLY con snapshot consistente: tablas, counts, SHA-256 de todas
las filas, SHA-256 del DDL e índices. No imprime secretos ni filas sensibles.
`trazabilidad_7d_baseline_c002df8.json` incluye también nombres relativos,
tamaños y SHA-256 de los dos archivos del storage real. Son **19 tablas**.

## 3. Modelo utilizado

| Modelo | Información útil para 7D |
| --- | --- |
| Usuario | ID/rol/activo; current_user existente |
| Area | Relación de Documento; no hay pertenencia usuario-área |
| Auditoria | Estado, responsable, nombre y updated_at |
| Documento | Estado, responsable, título y existencia de versiones |
| VersionDocumento | Documento padre y scope de lectura de versiones |
| DocumentoAuditoria | Contexto auditoría/documento/versión exacta |
| Evidencia | Scope y tipo FILE/REFERENCE/NOTE/OTHER |
| Hallazgo | Estado y auditoría; incluye ACCEPTED_RISK |
| HallazgoEvidencia | Relación existente sin obligatoriedad general |
| RondaAprobacion | Versión, estado, fechas; no es una ronda por auditoría |
| DecisionAprobacion | Ronda/aprobador/estado; PENDING es asignación pendiente |
| EventoAuditoria | Entidad/ID canónico, acción y fecha; metadata excluida |

No existe catálogo de documentos requeridos: no se finge detección de documentos
faltantes. Un documento existente sin versiones sí es verificable.
version_vigente_id NULL no significa ausencia de versiones: se usa NOT EXISTS.
No existe obligación general de evidencia por hallazgo: no hay alerta de evidencia
faltante. Se conserva el dominio implementado, sin nuevas precondiciones.

## 4. Indicadores

| Grupo | Valores |
| --- | --- |
| Auditorías | Total; PLANNED, IN_PROGRESS, IN_REVIEW, COMPLETED, CANCELLED |
| Hallazgos | Total; OPEN, IN_PROGRESS, PENDING_VERIFICATION, CLOSED, ACCEPTED_RISK |
| Rondas | Total; PENDING, IN_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED, CANCELLED |
| Decisiones | Total; PENDING, APPROVED, REJECTED, CHANGES_REQUESTED; resueltas y pendientes propias |
| Documentos | Total, versiones visibles, sin_version si el scope permite interpretación completa |
| Evidencias | Total y distribución por tipo FILE/REFERENCE/NOTE/OTHER |

Un grupo no autorizado es null. Un grupo autorizado vacío tiene total y
categorías cero. Valores legacy desconocidos se normalizan **en SQL antes de
GROUP BY** a DESCONOCIDO, sin reflejar su texto y sin aumentar la proyección.
Las categorías se completan en Python a partir de agregados ya scoped.
Las comparaciones de estados/tipos son binarias exactas en MySQL: minúsculas,
acentos y espacios finales aceptados por CHECK con collation permisiva se tratan
como DESCONOCIDO. No causan errores ni generan alertas de un estado canónico.

Decisiones resueltas: APPROVED + REJECTED + CHANGES_REQUESTED. 7C permite leer
decisiones de colegas en una ronda legible; esa agregación conserva el permiso.
pendientes_propias solo se presenta a APROBADOR y cuenta sus asignaciones PENDING
legibles, incluidas las históricas/canceladas. No equivale a comandos disponibles.

## 5. Fórmulas exactas

Conjuntos visibles, y del contexto autorizado si hay filtro.
Redondeo: `round(100 * numerador / denominador, 2)`.

| Indicador | Numerador | Denominador |
| --- | --- | --- |
| auditorias_completadas | COMPLETED | Total auditorías − CANCELLED |
| hallazgos_cerrados | CLOSED | Total hallazgos, incluido ACCEPTED_RISK |
| rondas_resueltas | APPROVED + REJECTED + CHANGES_REQUESTED | Total rondas − CANCELLED |
| documentos_con_version | Documentos con al menos una versión | Total documentos visibles |

CHANGES_REQUESTED resuelve una ronda sin significar aprobación satisfactoria.
ACCEPTED_RISK es terminal pero no CLOSED. Documentos archivados/obsoletos
participan en cobertura histórica, sin alertar como incompletitud operativa.
DESCONOCIDO contribuye al total/denominador, sin considerarse resuelto/completado.
Son medidas separadas de avance/cobertura, no cumplimiento legal absoluto.

## 6. Denominador cero y alcance parcial

Denominador cero: porcentaje null, estado NO_DATA y numerador/denominador cero;
PHP muestra **Sin datos**. No NaN, infinito ni 100% artificial.
Sin permiso/interpretación válida: NOT_APPLICABLE y porcentaje null.

APROBADOR solo lee versiones asignadas. No se ejecuta su subconsulta de
incompletitud: sin_version es null y documentos_con_version NOT_APPLICABLE.
Esto evita inferir versiones ocultas o tratar un conjunto parcial como ausencia.

## 7. Alertas

Derivadas en tiempo real por snapshot, sin tabla/PK persistente, dismiss,
acknowledge, snooze, read/unread o push.

| Tipo | Condición | Severidad |
| --- | --- | --- |
| AUDITORIA_ACTIVA | Auditoría visible IN_PROGRESS | INFO |
| AUDITORIA_REVISION | Auditoría visible IN_REVIEW | INFO |
| HALLAZGO_PENDIENTE | OPEN/IN_PROGRESS/PENDING_VERIFICATION y padre visible IN_PROGRESS/IN_REVIEW | WARNING |
| RONDA_PENDIENTE | Ronda visible PENDING/IN_REVIEW; aviso de estado registrado | INFO |
| DECISION_PROPIA_PENDIENTE | APROBADOR, ronda visible IN_REVIEW y asignación propia PENDING | INFO |
| DOCUMENTO_SIN_VERSION | Documento visible DRAFT/ACTIVE sin versiones; excluye APROBADOR | WARNING |

Un aviso propio sustituye al genérico de ronda. CLOSED/ACCEPTED_RISK y auditorías
PLANNED/COMPLETED/CANCELLED no producen alertas operativas de hallazgos.
Rondas terminales no alertan. Documento ARCHIVED/OBSOLETE sin versiones se cuenta
en cobertura histórica pero no genera alerta operativa.

Límite deliberado de 7C: una auditoría puede cerrar con una ronda pendiente, y una
versión compartida puede tener acciones bloqueadas por otra auditoría terminal.
7D no consulta contextos ocultos para deducir rondas bloqueadas: cambiar el número
de alertas permitiría inferir estados ajenos. Los avisos INFO describen el estado
registrado y enlazan al detalle para conocer disponibilidad. No afirman que se
pueda aprobar/iniciar/cancelar ni instruyen ejecutar esos comandos.

Contrato: clave de presentación tipo:recurso:ID, tipo, severidad, título y breve
explicación, recurso/ID autorizado, nombre legible, updated_at y destino tipado
{pagina,id}. No expone auditorías vinculadas a rondas, comentarios, JWT, passwords,
storage_key, rutas locales ni metadata. La clave no es un ID permanente de BD.

## 8. Severidades

INFO informa de un estado registrado que puede requerir consulta. WARNING
señala un hallazgo sin resolver en auditoría activa o documento operativo sin
versiones. No estima riesgo. No se usa CRITICAL al no existir fórmula de
criticidad operativa de este módulo. No se transforma arbitrariamente la severidad
de Hallazgo. Severidad exclusivamente backend.
Orden fijo: WARNING, INFO; fecha descendente, tipo e ID como desempate.

## 9. RBAC

| Rol | Alcance existente conservado |
| --- | --- |
| ADMIN | Resumen global autorizado; actividad de auditoría/hallazgo/documento/ronda |
| AUDITOR_INTERNO | Sus auditorías, hallazgos/evidencias, documentos vinculados; rondas de versión exacta de sus pivots |
| AUDITOR_EXTERNO | Su mismo scope de lectura, sin nuevas escrituras |
| RESPONSABLE_AREA | Documentos de los que es responsable, sus versiones/rondas; sin auditorías/hallazgos/evidencias |
| APROBADOR | Rondas asignadas, decisiones legibles de esas rondas, documentos/versiones assigned_version; pendientes propias |
| CONSULTA | Ausente de CHECK/matriz efectiva; denegado sin crear rol nuevo |

Usuario no tiene area_id. RESPONSABLE_AREA no recibe todos los documentos de un
área. Leer un documento no concede otras versiones/rondas de aprobación.
authorization_service.py no cambia; se reutilizan sus expresiones y permisos.

## 10. Scope y aggregate leakage

auditoria_scope, documento_scope, version_scope, hallazgo_scope, evidencia_scope
y ronda_scope se aplican en SQL antes de COUNT/SUM/GROUP BY/EXISTS/ORDER/LIMIT/OFFSET.
Ramas no autorizadas tienen predicado falso. EXISTS evita duplicar contadores por
varios pivots/asignaciones. No se carga global para filtrar en Python, no hay
total_global ni cache compartida entre usuarios.

auditoria_id valida el padre scoped: inexistente/fuera de scope dan el mismo 404,
cuerpo y número de queries. Sin auditoria.read, 403 para cualquier ID.
El contexto documental conserva 6B.2: versiones legibles de documentos vinculados.
El contexto de ronda exige documento/versión exactos.

Pruebas metamórficas agregan recursos/eventos invisibles y comparan las cuatro
respuestas, contadores, porcentajes, orden, paginación y alertas. Todo permanece
igual salvo generado_en. Se atacan pivots repetidos/cruzados y terminales ocultos
de versiones compartidas. No hay N+1 ni queries dependientes del número de datos.
Tiempos medidos como sanity check; no se promete tiempo constante criptográfico
MySQL/HTTP ni se agrega padding artificial.

## 11. Endpoints

| GET bajo /api/v1 | Contrato/filtros |
| --- | --- |
| /dashboard/resumen | generado_en, indicadores, alertas, actividad; auditoria_id, limit, offset |
| /dashboard/indicadores | Indicadores; auditoria_id |
| /dashboard/alertas | total/limit/offset/items; auditoria_id, tipo/severidad whitelist, limit, offset |
| /dashboard/actividad | total/limit/offset/items; auditoria_id, limit, offset |

Entradas y proyecciones tipadas Pydantic, extra=forbid. IDs ASCII decimales
1..18446744073709551615; no bool/float/decimal/notación científica.
limit 1..100 (default 10); offset 0..10000. Extras, identidad/KPI y enums inválidos:
422. Sin q/sort SQL/estado genérico. POST/PATCH/DELETE: 405. GET correcto no-store.
Actividad ordenada por fecha e ID descendentes. No interpolación SQL del usuario.

Resumen comparte limit/offset de ambas páginas. PHP pide limit=5, offset=0.
La página alertas pide limit=20 al endpoint dedicado con filtros/paginación
independientes. La actividad completa está paginada en API; UI muestra cinco.

## 12. Arquitectura y consistencia

schemas/dashboard.py define DTOs/whitelist; dashboard_queries.py compone SQL;
dashboard_service.py agrega/calcula/serializa; routers/dashboard.py expone cuatro
GETs usando current_user/get_db. app/main.py registra el router. Sin auth nueva,
cambio de modelo, migración, storage o workflow.

MySQL/InnoDB del entorno validado usa **REPEATABLE READ**. Cada respuesta comparte
la sesión/transacción de request, incluida la identidad existente. Lecturas
consistentes utilizan el mismo snapshot; 7D no hace commit, escritura ni locks de
negocio. Cierre de sesión revierte lectura. Entre requests se recalcula.

Cinco pruebas pausan tras la primera agregación, confirman en otra conexión una
mutación real y verifican que la respuesta completa conserva el snapshot anterior;
la siguiente lectura observa el cambio. Cierre de hallazgo, decisión final,
cierre de auditoría, nueva versión y reasignación. No se requiere serializable ni
se bloquea el workflow. Mantener REPEATABLE READ al desplegar; cambiar aislamiento
exige revalidar coherencia. No se cambia el aislamiento global del servidor.

## 13. Consultas y actividad segura

Indicadores: hasta siete SELECT agregados. Alertas: COUNT del UNION ALL scoped y
SELECT paginado. Actividad: COUNT y SELECT de entidades/acciones autorizadas.
No se accede a relaciones ORM por cada registro.

Actividad usa permisos de historial además del scope. ADMIN ve los tipos
documentados; otros roles solo historial de rondas permitido por 7C.
auditoria.read/hallazgo.read no otorga history. Whitelist de acciones por entidad.
Proyección mínima: ID evento, acción, título fijo, fecha, destino autorizado.
No se seleccionan metadata, actor_snapshot, actor_id o correlation_id.

entidad_id es string. Comparación con ID canónico, RHS binario MySQL para evitar
coerción y conflictos de collation. 01/1.0/1e0/1junk/1-space no equivalen a 1.
Eventos huérfanos/fuera de scope no contribuyen a count ni página. Metadata hostil
no se carga, interpreta o renderiza; no hay URLs externas derivadas de ella.
La whitelist de entidad/acción también exige coincidencia binaria exacta:
variantes de case, acentos o padding quedan excluidas. type_coerce conserva el
procesamiento de parámetros string de PyMySQL sin alterar el CAST SQL binario.

## 14. Rendimiento

Presupuesto de datos: resumen **11 SELECT** ADMIN/auditores, **8**
RESPONSABLE_AREA/APROBADOR. Contexto auditoria_id válido añade una consulta.
Auth real añade dos SELECT existentes (sesión revocable + usuario): hasta
**13/14** por resumen completo, sin contar ping. Fixture de identidad mide 12/9
porque consulta Usuario una vez. No son doce consultas adicionales a auth real.

Dataset exclusivamente temporal: **809 usuarios, 204 auditorías, 2005 documentos,
3605 versiones, 2020 hallazgos, 2004 evidencias, 1804 rondas, 3604 decisiones,
4008 eventos y 1804 pivots**. No escribe archivos sintéticos en storage real.
Tres mediciones por rol con limit=5; test falla si supera cinco segundos o
presupuesto SQL. Primera medición detectó APROBADOR ~2.09 s por cobertura inútil;
se eliminó esa consulta. Segunda: 15–81 ms por rol; APROBADOR 46–55 ms.
Son tiempos locales TestClient/MySQL, no SLA ni prueba final de carga.
Mediciones/planes definitivos se guardan en JSON en TEMP por el test de volumen.

Medición definitiva tras exigir estados/acciones binarios canónicos en SQL
(mínimo–máximo de tres consultas, TestClient local): ADMIN 39.7–40.9 ms;
AUDITOR_INTERNO 52.5–56.4 ms; AUDITOR_EXTERNO 11.6–14.1 ms;
RESPONSABLE_AREA 36.1–37.2 ms; APROBADOR 38.4–41.3 ms.
SELECT por fixture: 12/12/12/9/9, respectivamente.
Artefacto reproducible de esta ejecución:
`TEMP/trazabilidad_7d_mysql_final_03/test_volume_query_budget_scope0/dashboard-volume-explain.json`.

## 15. Índices / EXPLAIN / migración

Índices reales inspeccionados antes de editar. EXPLAIN de todos los SELECT
capturados de los cinco roles, incluidos counts/UNION/actividad. Artefacto temporal
con SQL parametrizado/planes, sin dumps sensibles.

Índices usados según consulta/cardinalidad: ix_auditorias_responsable,
ix_auditorias_estado_inicio; ix_hallazgos_auditoria_estado,
uq_hallazgos_auditoria_numero; ix_documentos_responsable;
uq_versiones_documento_numero; uq_documentos_auditoria_version e índices
documento/versión; ix_evidencias_auditoria_tipo; ix_rondas_version_estado,
uq_rondas_version_numero; ix_decisiones_aprobador_estado,
uq_decisiones_ronda_aprobador y PKs.

Agregados globales autorizados pueden recorrer índices/filas completos. UNION
puede materializar/usar filesort; ciertos planes de actividad prefieren hash
join/scan. No es N+1. Cardinalidad/tiempos no muestran índice crítico ausente.
ix_eventos_entidad_fecha existe, pero el plan final de actividad prioriza scan/
hash join; las comparaciones binarias explícitas aseguran corrección ante legacy.
No se crea 006, índice nuevo ni migración; **005 permanece head**.

## 16. Frontend

Dashboard con KPIs, porcentajes explicados, distribución por estados/tipos,
pendientes propias, versiones, alertas y actividad. alertas ofrece filtros y
navegación anterior/siguiente. Controller/helpers y partial de lista; api_client
solo amplía cuatro rutas exactas, server-side. Una respuesta para resumen.

Valores dinámicos siempre e(). Destinos page_url mediante whitelist/ID y permiso
de presentación; nunca URL arbitraria o JS para autorización. JWT en sesión PHP,
/auth/me por petición, GET-only/no-store. Error de API no fabrica ceros; 401
redirige/limpia sesión, 403 se conserva, errores sanitizados. CSP y CSRF de logout
y módulos previos conservados. Formularios de filtros no mutan.

Se actualiza el doble HTTP de tests al contrato nuevo. Prueba previa que esperaba
listar auditorías para contar ahora exige una única llamada a resumen, sin listas
ni catálogos; conserva comprobaciones de roles, navegación y sesión.

## 17. Responsive y accesibilidad

Chrome real, cinco roles, 1440/390/320 px: móvil con una columna, dl por estados,
listas de alertas/actividad y texto con wrapping. Sin tablas anchas en dashboard,
overflow horizontal, tarjetas cortadas, neón ni gráficos decorativos.
Paleta/paneles empresariales existentes.
Pruebas de headings, labels, Tab/foco visible, destinos legibles, JWT ausente
y XSS inocuo. Severidad expresada con INFO/Información y WARNING/Atención, sin
depender únicamente del color. Contrastes/focus existentes conservados; no es
certificación WCAG completa. Capturas y perfiles solo TEMP.

## 18. Tests y E2E

Contratos HTTP compartidos SQLite/MySQL protegido: fórmulas/estados/cero,
scope/roles, aggregate leakage, paging, filtros/SQLi/extras/role spoofing, IDs
extremos, incompletitud, decisiones propias/históricas, terminales, history,
metadata maliciosa, IDs/eventos legacy, estados corruptos, relaciones cruzadas,
errores seguros, GET-only, query budget. DDL para corrupción solo en schema
temporal guardado, restaurado al finalizar la prueba.

PHP: cinco roles, tarjetas, escapes script/img/svg/quotes/entities/Unicode,
URLs hostiles, filtros/paginación, errores/expiración y CSRF. Chrome: cinco roles
por tres anchos, teclado, overflow, navegación y XSS. Fixtures bloquean la
conexión de aplicación a producción, SMTP y Siteverify reales.

mysql_factory crea schema aleatorio con guardas de nombre/conexión, prueba
upgrade/downgrade 001–005 exclusivamente temporal y elimina solo su schema.
E2E sin mocks: PHP → Uvicorn/FastAPI → MySQL temporal, Argon2/JWT/sesión real.
20 hallazgos, 12 alertas y 20% cerrados → navegar desde alerta → cerrar hallazgo
PENDING_VERIFICATION por workflow real → 25% y 11 alertas. Verifica otros roles.
Variante Chrome real a 320 px recorre el mismo flujo y XSS inocuo.

Regresiones: 6A, 6B.1, 6B.2, 6B.3, 6B.4A/B, 6C, 6D/6D.1, 7A, 7B y 7C.
Nunca ejecutar fixture destructivo legacy api/tests contra producción: adapter
6A existente utiliza exclusivamente schema temporal protegido.

Comandos PowerShell, usando basetemp NUEVO cada vez:

```powershell
# Desde api:
.\venv\Scripts\python.exe -m pytest tests_unit -q --basetemp=$env:TEMP\trazabilidad_7d_unit_nuevo
$env:AUTH_MYSQL_TEST='1'
.\venv\Scripts\python.exe -m pytest tests_auth_mysql -q --basetemp=$env:TEMP\trazabilidad_7d_mysql_nuevo
# Desde raíz:
.\api\venv\Scripts\python.exe -m pytest frontend/tests -q --basetemp=$env:TEMP\trazabilidad_7d_php_nuevo
$env:AUTH_BROWSER_TEST='1'
.\api\venv\Scripts\python.exe -m pytest frontend/tests/test_dashboard_browser.py frontend/tests/test_aprobaciones_browser.py frontend/tests/test_auth_browser.py frontend/tests/test_turnstile_browser.py frontend/tests/test_auditorias_browser.py frontend/tests/test_hallazgos_browser.py -q -p no:cacheprovider --basetemp=$env:TEMP\trazabilidad_7d_browser_nuevo
# Desde api, E2E Chrome/MySQL:
.\venv\Scripts\python.exe -m pytest tests_auth_mysql/test_dashboard_e2e_mysql.py -q -p no:cacheprovider --basetemp=$env:TEMP\trazabilidad_7d_e2e_nuevo
```

Chrome necesita autorización fuera del sandbox Windows y perfil temporal, sin
perfil habitual del usuario ni servicios externos. No mezclar frontend/MySQL en
una invocación: conftest legacy comparte nombre. -p no:cacheprovider evita avisos
del cache del runner Chrome. Capturas/dumps no se añaden al repo.

## 19. Autoauditoría

Correcciones: comparación binaria canónica de eventos; cobertura inútil de
APROBADOR eliminada; normalización SQL de estados desconocidos; EXISTS frente a
pivots repetidos/cruzados; history separado de resource.read y metadata omitida.
La revisión final añadió ocho contratos SQLite/MySQL para variantes legacy de
case/acentos/padding en estados y en acciones/entidades. MySQL detectó un error
del procesador de binds binarios al introducir el CAST; se corrigió preservando
binds string y se repitieron los contratos, suites completas y E2E reales.
No se encontraron bypasses de IDOR/RBAC, aggregate leakage funcional, SQLi,
ejecución XSS, escrituras del dashboard o N+1 en las pruebas definitivas.

Browser: una espera buscaba un heading inexistente en 7C; se corrige el test al
heading real. E2E espera readyState complete para medir después de cargar CSS.
No se modifica workflow ni se oculta overflow mediante clipping.

## 20. Limitaciones y deuda técnica

- Sin IA, análisis semántico, clasificación automática, predicción, Power BI,
  correo real, scoring de riesgo ni detección de documentos requeridos ausentes.
- Rondas por versión compartida/históricas y bloqueos de 7C intactos. Sin contador
  de bloqueo usando auditorías ocultas.
- Actividad no ADMIN solo de rondas; ampliar history requiere definición RBAC.
- UI de actividad muestra cinco eventos, API sí pagina. Alertas hasta offset 10000.
- PHP usa helpers existentes de enteros signed: IDs fuera del rango nativo omiten
  enlace, sin convertir overflow en otro recurso. Backend admite BIGINT UNSIGNED;
  ampliar navegación de todos los módulos requiere trabajo futuro.
- Mantener REPEATABLE READ. Sin garantía de tiempo constante o prueba final de
  carga multiusuario; revisar tiempos/EXPLAIN a mayor cardinalidad.
- Actividad puede usar hash join/scan y filesort; no justifica 006 en este volumen.
- Dos deprecaciones previas Starlette/httpx/AnyIO, sin actualizar dependencias ni
  refactor masivo.

## 21. Resultado de cierre

| Verificación | Resultado |
| --- | --- |
| HEAD inicial/final | c002df8936747bfd27046a32e618ad0d1802017e, main |
| origin/main inicial/final local | Mismo hash; publicación inicial confirmada con ls-remote |
| Git inicial | Limpio, sin staging |
| MySQL | 8.0.46, REPEATABLE-READ confirmado también al cierre |
| Alembic inicial/final | 005 current y único head; sin 006 |
| Suite unitaria definitiva completa | **1067 passed** (906 previas + 161 de 7D) |
| Suite MySQL definitiva completa | **927 passed, 1 skipped** (opt-in Chrome ejecutado por separado) |
| Contratos MySQL distintos aprobados | **928**, incluyendo el E2E Chrome separado; 758 previos + 170 de 7D |
| PHP HTTP completo definitivo | **235 passed**, 34 browser opt-in skipped y cubiertos por separado |
| PHP 7D repetido al cierre | **28 passed**, después de las correcciones UTF-8 |
| Chrome frontend definitivo | **34 passed**: 19 regresiones + 15 casos 7D (5 roles × 3 anchos) |
| E2E PHP/API/MySQL + Chrome/API/MySQL definitivo | **2 passed**, sin mocks en el tramo crítico |
| Pruebas distintas, sin sumar repeticiones | **2264 passed**: 1067 + 928 + 235 + 34 |
| Concurrencia 7D | Cinco carreras reales incluidas en suite MySQL |
| Volumen y EXPLAIN | Dataset indicado, cinco roles, sin N+1, 12–57 ms finales |
| PHP lint | **62 archivos**, sin errores |
| UTF-8 | **23 archivos** nuevos/modificados válidos, sin BOM ni mojibake |
| Integridad BD real | Las 19 tablas, todas sus filas/counts, DDL e índices coinciden con la huella inicial |
| Integridad storage real | Mismos 2 archivos, nombres/tamaños/SHA-256; **5991474 bytes** |
| Schemas temporales | Cero schemas test_auth restantes |
| git diff --check | Limpio |
| Staging/commit/push | Cero; HEAD intacto |
| Working tree | Solo 7D: 10 archivos modificados y 13 nuevos |

Counts reales iniciales/finales: usuarios 2, áreas 1, auditorías 1, documentos 3,
versiones 2, eventos 6, auth_sessions 5, auth_login_limits 1 y alembic_version 1.
access_requests, auth_action_limits, auth_action_tokens, auth_mail_jobs,
documentos_auditoria, hallazgos, hallazgos_evidencias, evidencias, rondas y decisiones
permanecen a cero. SHA-256 de **filas completas** verifica más que esos counts.
Archivo final de comparación tras todas las suites en TEMP:
`trazabilidad_7d_final_c002df8_02.json`.
BD/storage reales se utilizaron exclusivamente en lectura, sin pruebas de escritura.

Las suites completas definitivas de backend incluyen las comparaciones binarias
canónicas finales y los ocho contratos legacy añadidos en la autoauditoría.
La suite PHP completa se repitió con el árbol definitivo: 235 aprobados.
También pasaron lint, los 28 contratos PHP 7D, los 34 Chrome y ambos E2E reales.
El skip de Chrome en la suite MySQL normal se cubrió con AUTH_BROWSER_TEST=1:
no representa un escenario pendiente. Los 34 skips de la suite PHP corresponden
a 19 regresiones browser y 15 casos 7D opt-in, cubiertos por la batería separada
de 34. Se retiraron dos prints de diagnóstico del test de volumen y se repitió
ese test con éxito; no cambió la lógica de aplicación validada por las suites.

Inventario modificado (10):

```text
api/README.md
api/app/main.py
frontend/README.md
frontend/assets/css/estilos.css
frontend/index.php
frontend/pages/dashboard.php
frontend/services/api_client.php
frontend/services/dashboard_controller.php
frontend/tests/conftest.py
frontend/tests/test_auth_rbac.py
```

Inventario nuevo (13):

```text
api/app/routers/dashboard.py
api/app/schemas/dashboard.py
api/app/services/dashboard_queries.py
api/app/services/dashboard_service.py
api/tests_auth_mysql/test_dashboard_e2e_mysql.py
api/tests_auth_mysql/test_dashboard_mysql.py
api/tests_unit/test_dashboard_unit.py
docs/FASE_7D_DASHBOARD_ALERTAS_INDICADORES.md
frontend/includes/dashboard_alert_list.php
frontend/pages/dashboard_alertas.php
frontend/services/dashboard_helpers.php
frontend/tests/test_dashboard.py
frontend/tests/test_dashboard_browser.py
```

Sin git add, commit o push; README raíz de entrega intacto. Capturas, perfiles,
logs y planes permanecen en TEMP; ningún dump/imagen se añade al repositorio.
Fase preparada para revisión independiente de Antigravity.
