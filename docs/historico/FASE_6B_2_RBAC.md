# Fase 6B.2: autorización / RBAC

Política deny-by-default. Los 17 endpoints de negocio reutilizan `Depends(current_user)` de 6B.1. Las reglas y scopes SQL residen en `api/app/services/authorization_service.py`. No hay migraciones, endpoints nuevos ni cambios PHP.

## Matriz implementada

ADMIN tiene acceso a todas las operaciones existentes, manteniendo validaciones normales de negocio y la consistencia de referencias de evidencias.

| Endpoint bajo /api/v1 | Otros roles autorizados |
| --- | --- |
| GET /auditorias | AUDITOR_INTERNO y AUDITOR_EXTERNO: auditorías propias |
| POST /auditorias | AUDITOR_INTERNO: solo asignándose a sí mismo |
| GET /documentos | Auditores: documentos vinculados a auditorías propias; RESPONSABLE_AREA: documentos propios; APROBADOR: documentos con versiones asignadas |
| POST /documentos | RESPONSABLE_AREA: solo responsable_id propio |
| GET /documentos/{id} | Mismo alcance documental; contenido anidado restringido |
| PATCH /documentos/{id} | RESPONSABLE_AREA: documento propio, sin reasignación |
| POST /documentos/{id}/versiones | RESPONSABLE_AREA: documento propio, comprobado bajo bloqueo |
| GET /documentos/{id}/versiones | Auditores y RESPONSABLE_AREA: versiones de documentos accesibles; APROBADOR: versiones asignadas |
| GET /documentos/{id}/versiones/{version_id}/descargar | Mismo alcance por versión, comprobando la pareja documento/versión |
| GET /documentos/{id}/historial | Solo ADMIN |
| GET /evidencias | Auditores: auditorías propias y referencias consistentes con la misma auditoría |
| POST /evidencias/archivo | Auditores: auditoría propia y referencias consistentes |
| POST /evidencias/logica | Auditores: auditoría propia y referencias consistentes |
| GET /evidencias/{id} | Mismo alcance que listado |
| GET /evidencias/{id}/descargar | Mismo alcance que detalle, antes de resolver ruta física |
| GET /areas | Todos los usuarios autenticados |
| GET /usuarios | AUDITOR_INTERNO: auditores activos elegibles; ADMIN: catálogo completo |

ADMIN puede asignar auditorías a usuarios activos AUDITOR_INTERNO/AUDITOR_EXTERNO. AUDITOR_EXTERNO no puede crear auditorías. No se concede acceso por area_id.

## Relaciones y lecturas

- Auditoría propia: `Auditoria.responsable_id == current_user.id`.
- Documentos para auditor: `EXISTS DocumentoAuditoria JOIN Auditoria`.
- Versiones para auditor: todas las versiones del documento vinculado, según la matriz aprobada; no se limita a la versión del pivot.
- Aprobaciones: `DecisionAprobacion.aprobador_id -> RondaAprobacion.version_documento_id -> VersionDocumento.documento_id`. La asignación concede lectura sin filtro adicional por estado de ronda/decisión.
- Evidencias: auditoría autorizada; documento vinculado a ESA auditoría; versión perteneciente al documento, cuyo documento también debe estar vinculado a ESA auditoría. Aplica también a ADMIN al registrar evidencias. Los registros históricos inconsistentes quedan fuera de las lecturas de auditores.
- Los scopes se aplican en SQL antes de limit/offset. EXISTS evita duplicados por múltiples vínculos/asignaciones.
- Las versiones anidadas se restringen en SQL. Para APROBADOR, versión vigente y su ID son null si esa versión no está asignada. Se refrescan cargas ORM para no reutilizar relaciones previas más amplias.
- El historial completo queda reservado a ADMIN porque los snapshots/eventos pueden incluir otros recursos y versiones.

## Identidad y errores

Los parámetros HTTP legacy creador_id, editor_id, subido_por_id, registrada_por_id y created_by_id son opcionales/deprecated e ignorados. Los routers pasan únicamente current_user.id a los servicios; la persistencia y los eventos usan ese actor. Los IDs de actor en las firmas internas de servicios son argumentos de confianza del backend, nunca parámetros HTTP reenviados.

- 401: identidad, token o sesión ausente/inválida, mediante la dependencia existente.
- 403: rol sin permiso de operación; también las restricciones explícitas de asignación propia y reasignación reservada a ADMIN.
- 404: recurso inexistente o fuera de alcance; pareja documento/versión inexistente/no autorizada; referencia de evidencia ajena a su auditoría; responsable de auditoría no elegible.
- Listados: omiten filas fuera de alcance.
- Las validaciones estructurales existentes conservan 422; por ejemplo, evidencia lógica con versión pero sin documento.

## Frontera de archivos y regresiones

Toda autorización de carga ocurre antes de StorageService.save_file. Las versiones conservan SELECT FOR UPDATE y comprueban responsable con populate_existing=True sobre el documento bloqueado, antes de las validaciones de estado y de escribir archivos.

No se alteran storage físico, compensación, reconciliación, commit incierto ni fronteras transaccionales de 6A. Las pruebas antiguas que creaban documentos con rol auditor ahora usan RESPONSABLE_AREA; las fixtures compartidas de fallos transaccionales usan ADMIN.

## Validación aislada

Desde api, con el entorno virtual existente:

```powershell
$env:AUTH_MYSQL_TEST = '1'
.\venv\Scripts\python.exe -m pytest tests_unit tests_auth_mysql -q -p no:cacheprovider --basetemp=<directorio-temporal-nuevo>
```

La suite unit usa SQLite en memoria con una copia de DDL exclusivamente para tests; no modifica el metadata de producción. Las pruebas MySQL reutilizan la fixture de autenticación que crea un esquema local aleatorio sistema_trazabilidad_test_auth_<16 hex>, verifica su identidad y lo elimina al terminar. La conexión al engine de la aplicación está prohibida. Alembic se ejecuta únicamente en ese esquema temporal.

Las mismas pruebas HTTP RBAC se ejecutan en SQLite y MySQL. El adaptador test_6a_regression_mysql.py ejecuta las pruebas existentes de api/tests contra ese esquema aleatorio sin cargar su conftest ni usar su esquema fijo. La limpieza verifica explícitamente el nombre y SELECT DATABASE() antes de truncar tablas temporales.

No existe GET /auditorias/{id}, ni endpoints para crear DocumentoAuditoria/asignaciones de aprobación. Las pruebas usan relaciones aisladas; no se agregan operaciones nuevas para estos flujos.
