# Matriz de permisos efectiva

Derivada de `authorization_service.py`, servicios de auditoría/hallazgo/aprobación, dependencias auth y frontend. `S` indica un recurso dentro del alcance SQL autorizado; el permiso de rol por sí solo no basta.

| Operación | ADMIN | AUDITOR_INTERNO | AUDITOR_EXTERNO | RESPONSABLE_AREA | APROBADOR |
|---|---|---|---|---|---|
| Login/me/logout | Propia | Propia | Propia | Propia | Propia |
| Revisar/aprobar/rechazar solicitudes | Sí | No | No | No | No |
| Áreas: lectura | Sí | Sí | Sí | Sí | Sí |
| Usuarios elegibles: lectura | Todos | Auditores activos | No | No | No |
| Auditorías: lectura | Global | S: responsable | S: responsable | No | No |
| Auditorías: crear | Responsable auditor elegible | Para sí | No | No | No |
| Auditorías: editar/estado/historial | Sí | No | No | No | No |
| Documentos/versiones: leer/descargar | Global | S: vínculo con auditoría propia | S: vínculo con auditoría propia | S: propietario | S: versión asignada |
| Documentos: crear/editar/upload | Sí | No | No | Propios; no reasignar a otro | No |
| Historial documental de eventos | Sí | No | No | No | No |
| Evidencias: consultar/registrar | Global | S: auditoría propia | S: auditoría propia | No | No |
| Hallazgos: consultar | Global | S: auditoría propia | S: auditoría propia | No | No |
| Hallazgos: crear/editar/estado/vínculos | Sí | S: auditoría propia | No | No | No |
| Historial de hallazgo | Sí | No | No | No | No |
| Rondas: lectura/historial | Global | S: versión exacta vinculada | S: versión exacta vinculada | S: documento propio | S: asignación |
| Rondas: crear/iniciar/cancelar/finalizar | Sí | S: versión exacta vinculada | No | No | No |
| Decisión de aprobación | No: requiere APROBADOR asignado | No | No | No | Propia, pendiente, ronda en revisión |
| Dashboard/análisis | Recursos globales legibles | Recursos legibles | Recursos legibles | Documentos propios | Versiones asignadas |

## Autoridad e integridad

ADMIN tiene máxima autoridad sobre las operaciones implementadas. No tiene endpoints para cambiar hashes, editar eventos, sustituir archivos de versiones, borrar usuarios ni sobrescribir decisiones terminales. El servicio de decisión exige explícitamente rol APROBADOR activo y asignado: ADMIN administra la ronda, pero no firma por otro actor. La inmutabilidad descrita se aplica a la interfaz/API; un operador con privilegios SQL/filesystem debe someterse a controles de operación y backup.

Los cambios de usuarios personales no se incluyen en el seed. `gestionar_usuario.py` sólo establece contraseña para una identidad confirmada y revoca sesiones; no es CRUD de usuarios ni gestión de roles. Las FK `RESTRICT` preservan atribuciones históricas. Desactivar/conservar es preferible a borrar, pero no hay una UI general de desactivación documentada como implementada.

## Demostración server-side

Los tests demo inician sesión por HTTP real, comparan listados, llaman endpoints administrativos desde RESPONSABLE_AREA, manipulan ID/rol/responsable y prueban actor de upload. La vista reducida PHP complementa estas verificaciones; esconder controles no concede seguridad.

RESPONSABLE_AREA puede consultar sus rondas y dashboard/análisis propios. No ve una auditoría aunque su documento esté vinculado a ella: son permisos distintos. APROBADOR no obtiene automáticamente todas las versiones de un documento. Auditores gestionan scopes por auditoría responsable, no por nombre de área.
