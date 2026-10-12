# PRD — Sistema de Trazabilidad Documental para Auditorías

## Contexto y problema

La residencia de Samuel Cruz Barrientos, Ingeniería en Sistemas, TESCI / TecNM, se desarrolla con PluriOne S.A. de C.V. / Develop Talent & Technology entre septiembre de 2026 y enero de 2027. Asesor empresarial: Juan Méndez Herrera. Líder/evaluador: Edgar Loheffelmman.

El producto atiende la dificultad de reconstruir qué documento sustentó una auditoría, quién aportó una evidencia, qué versión se revisó y qué decisión se tomó. Un expediente disperso dificulta el seguimiento y puede producir ambigüedad entre versiones actuales e históricas. Esta justificación describe el problema de producto; no afirma resultados empresariales medidos que no existan.

## Objetivo general

Gestionar el ciclo documental de auditorías con evidencias, responsables, versiones, aprobaciones y bitácoras verificables, apoyado por monitoreo, alertas, indicadores y análisis documental explicable, preservando seguridad, integridad, desempeño y mantenibilidad.

## Objetivos específicos

1. Identificar documentos y conservar versiones con SHA-256 y actor de carga.
2. Registrar auditorías, evidencias y hallazgos con responsabilidades y estados válidos.
3. Revisar versiones concretas mediante rondas y decisiones atribuibles e inmutables al cerrarse.
4. Mostrar indicadores y anomalías únicamente sobre información autorizada.
5. Controlar acceso mediante autenticación, sesiones revocables y permisos server-side.
6. Proporcionar procedimientos reproducibles de instalación, operación, pruebas y entrega académica.

## Stakeholders y actores

Alumno/desarrollador, asesor empresarial, líder/evaluador y usuarios autorizados de auditoría. Los actores operativos son ADMIN, AUDITOR_INTERNO, AUDITOR_EXTERNO, RESPONSABLE_AREA y APROBADOR. El solicitante público puede pedir acceso o recuperación, sin concederse un rol. Los evaluadores usan cuentas locales sintéticas; sus datos no se mezclan con expedientes reales.

## Alcance entregado

Aplicación local PHP/FastAPI/MySQL 8 con almacenamiento de archivos controlado. Incluye ciclo de auditoría, cabeceras/documentos/versiones, evidencias FILE/NOTE/REFERENCE/OTHER, hallazgos, aprobaciones, eventos, dashboard, alertas derivadas y motor 7E determinista. Incluye seed explícito para evaluación, documentación y exports. El backend de recuperación, tokens/controles, cola, worker y configuración SMTP están implementados. **El correo real no está disponible en la demo:** no se configuró un proveedor externo ni se acreditó recepción, y las cuentas ficticias no tienen buzón.

## Fuera de alcance

Funciones pendientes o fuera de alcance: servicio productivo alojado; registro público automático; CRUD HTTP general de usuarios/áreas; reescritura de trazabilidad; creación de vínculo documento–auditoría por comando HTTP; backup automático; firma electrónica certificada; antivirus; certificación normativa automática. No están implementados Ollama, IA local/generativa, LLM, machine learning, modelos entrenados ni análisis semántico general de documentos. Una ampliación de IA exige requerimiento separado, aprobación de alcance y validación propia.

## Requisitos funcionales

| ID | Requisito y comportamiento actual | Aceptación | Estado |
|---|---|---|---|
| RF-01 | Login con Argon2id, JWT y sesión persistida | Cuenta activa/rol canónico; `/auth/me` válido; logout revoca | Verificable |
| RF-02 | Autorizar rol y recurso en backend | Recursos ajenos rechazados incluso mediante IDs/payloads manuales | Verificable |
| RF-03 | Solicitud de acceso revisada por ADMIN | Recepción de solicitud y revisión/rechazo por ADMIN implementados y verificables; cuenta activa sólo tras confirmar el enlace y establecer contraseña inicial | Recepción/revisión/rechazo: Verificable; activación: SMTP externo |
| RF-04 | Recuperación de contraseña por token temporal | Genérico, propósito correcto, single-use, revoca sesiones; SMTP requerido | SMTP externo |
| RF-05 | Auditorías con responsable elegible y ciclo controlado | PLANNED → IN_PROGRESS → IN_REVIEW → COMPLETED, retorno a progreso desde revisión | Verificable |
| RF-06 | Cabecera de documento y versiones históricas | Número creciente, bytes/hash reales, vigente y descarga autorizada | Verificable |
| RF-07 | Evidencias dentro de auditoría válida | Referencias coherentes, límite de archivo, actor autenticado | Verificable |
| RF-08 | Hallazgos con severidad, responsable y resolución | Transiciones autorizadas y cierre con datos obligatorios | Verificable |
| RF-09 | Rondas sobre versión exacta | Una activa por versión; APROBADOR asignado decide una vez | Verificable |
| RF-10 | Bitácora de operaciones | Evento/operación comparten transacción; sin endpoint de edición histórica | Verificable |
| RF-11 | Dashboard/alertas/actividad | Scope previo a aggregate; ratios sin denominador no inventan porcentajes | Verificable |
| RF-12 | Análisis documental determinista explicable | Reglas/evidencia/contexto; límites visibles; no compara hashes privados fuera del scope | Verificable |
| RF-13 | Evaluación reproducible | Alembic 005 + seed opt-in idempotente en schema nuevo + archivo privado externo de TODO Academy | Verificable |

Estado **Verificable**: implementada y verificable con el código y las pruebas existentes. Estado **SMTP externo**: implementada con dependencia de configuración externa para completar el recorrido por correo; exige proveedor SMTP operativo, worker y buzón autorizado. En RF-03, este estado corresponde a la activación posterior mediante enlace tras la aprobación administrativa; la recepción de solicitudes y su revisión o rechazo por ADMIN son verificables y no dependen de SMTP. Turnstile opcional también depende de claves y servicio externos; los límites locales funcionan sin él. Las funciones del apartado Fuera de alcance están pendientes o no forman parte de la entrega.

El cotejo se apoya en el [inventario de rutas y tablas](INVENTARIO_IMPLEMENTACION.md), `api/tests_auth_mysql/test_account_access_mysql.py` y `api/tests_unit/test_analisis_unit.py` del repositorio. 7E compara hashes y aplica reglas de metadatos/versiones y similitud heurística de nombres; no garantiza detectar cualquier irregularidad ni todos los documentos faltantes.

`CANCELLED` es un estado válido de auditoría en DDL, sin transición pública actual. Las alertas de dashboard se derivan al consultar y no se envían automáticamente por correo. El seed provee vínculos documentales de ejemplo y no sustituye una funcionalidad de asociación HTTP pendiente.

## Requisitos no funcionales

| ID | Requisito | Evidencia/criterio |
|---|---|---|
| RNF-01 | Seguridad de credenciales | Hash Argon2id; secretos privados fuera de Git/exports; JWT no expuesto en navegador |
| RNF-02 | Integridad documental | SHA-256, restricciones DB, versiones preservadas, descargas autorizadas |
| RNF-03 | Concurrencia | Locks y precondiciones, respuestas 409 ante cambios; no doble consumo de token |
| RNF-04 | Desempeño acotado | Streaming, límites de cuerpos/archivos, pool y admisión DB; 7E local acotado |
| RNF-05 | Reproducibilidad | Instalación nueva documentada, schema temporal, storage/venv propios |
| RNF-06 | Mantenimiento | Migraciones y pruebas; fuente Markdown y manual de operación; preservación legacy |
| RNF-07 | Usabilidad local | Formularios claros, errores sanitizados, navegación por rol, layouts responsive probados |

No se establece un SLA productivo ni un rendimiento universal a partir de un benchmark local. La ventana DB/filesystem no es una transacción distribuida frente a corte de energía.

## Historias y casos de uso principales

| Actor | Necesidad | Resultado |
|---|---|---|
| ADMIN | Preparar auditoría y responsable | Expediente creado con evento y responsable auditor elegible |
| RESPONSABLE_AREA | Entregar una nueva versión | Versión propia con archivo/hash y vigente; otras versiones preservadas |
| AUDITOR_INTERNO | Registrar hallazgo sustentado | Hallazgo dentro de auditoría propia y evidencia coherente |
| AUDITOR_EXTERNO | Revisar expediente y aportar evidencia | Lectura/registro limitado a sus auditorías; sin gestión global |
| APROBADOR | Revisar versión asignada | Decisión propia y una sola vez durante ronda en revisión |
| ADMIN | Resolver solicitud de acceso | Rol decidido por ADMIN y contraseña inicial mediante correo |
| Usuario activo | Recuperar contraseña | Cambio mediante token de propósito/TTL válido, revocación de sesiones |
| Evaluador | Comparar visibilidad de dos roles | ADMIN global y RESPONSABLE_AREA limitado server-side |

## Flujos de producto

```text
Instalación -> migraciones -> seed opt-in -> login -> dashboard
Auditoría -> documento/versiones -> evidencia -> hallazgo -> seguimiento
Versión -> ronda PENDING -> IN_REVIEW -> decisiones -> resultado terminal
Solicitud -> revisión ADMIN -> aprobación -> correo inicial -> cuenta activa
Reset -> respuesta genérica -> cola/worker -> correo -> confirmación single-use
```

Los dos flujos que incluyen correo sólo pueden completarse con SMTP, worker y buzón autorizado; no están disponibles de principio a fin en la demo. La relación documento–auditoría se conserva en DB y se provisiona en la demo; todavía no hay una acción de asociación HTTP para el usuario final.

## Seguridad y restricciones de autoridad

Los roles no significan acceso irrestricto a cualquier fila. El alcance se aplica antes de paginar/comparar/agregar. ADMIN posee gestión global de operaciones existentes, pero no puede suplantar al aprobador ni reescribir eventos, hashes o decisiones cerradas mediante API. CSRF y sesión PHP protegen formularios; backend verifica autenticación y recurso. Rate limiting, Argon2 acotado, Turnstile opcional y límites de upload/body protegen trabajo costoso. Los tokens de recuperación no se persisten en claro.

## Métricas y criterios de aceptación

Cada requisito se acepta con prueba funcional y, para autorización/integridad, con una prueba negativa server-side. La demo debe poder levantarse sin editar filas SQL ni usar credenciales personales. El seed repetido no duplica usuarios ni cambia filas existentes. README debe cubrir todos los pasos. Los PDFs/DOCX deben abrir, contener texto y conservar títulos/tablas legibles.

El baseline Fase 8 documenta 2,662 ejecuciones verdes, distinguiendo 1,937 contratos únicos. Fase 9 registra sus resultados por separado en [Informe de cierre](FASE_9_CIERRE_ENTREGA.md). No se miden horas ahorradas, reducción porcentual de errores ni adopción real de usuarios: no hay evidencia para esos resultados.

## Riesgos y dependencias

Credenciales SMTP/buzón externos condicionan la validación real de correo. Python/MySQL/PHP y permisos locales condicionan instalación. Privilegios SQL/filesystem externos a la aplicación pueden comprometer integridad. Un corte abrupto puede dejar huérfanos. El análisis global puede degradarse bajo concurrencia extrema; requiere límites y revisión de detalle. Despliegue multiproceso exige presupuestos compartidos antes de operar.

## Roadmap y estado

Fases 6–7 implementaron acceso, RBAC y flujos; Fase 8 endureció y validó seguridad/concurrencia/desempeño; Fase 9 preparó documentación, demo y reproducibilidad. La auditoría final de Fase 9.2 aprobó la release según el dictamen comunicado; la publicación Git y entrega TODO Academy son pasos separados. SMTP real queda pendiente de credenciales externas. Una posible asociación documental por UI, licencia explícita, operación productiva e IA local quedan fuera del alcance entregado y requieren decisión futura.

## Deuda conocida

Huérfanos posibles tras interrupción; candidatos/lecturas acotadas de 7E; deprecaciones menores de tests; análisis pesado extremo; ausencia de algunos comandos de administración general. Los datos legacy se preservan e inventarían antes de cualquier limpieza manual aprobada.
