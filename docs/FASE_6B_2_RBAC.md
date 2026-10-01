# Fase 6B.2: autorizaci?n / RBAC

Pol?tica deny-by-default. Los 17 endpoints de negocio reutilizan `Depends(current_user)` de 6B.1. Las reglas y scopes SQL residen en `api/app/services/authorization_service.py`. No hay migraciones, endpoints nuevos ni cambios PHP.

## Matriz implementada

ADMIN tiene acceso a todas las operaciones existentes, manteniendo validaciones normales de negocio y la consistencia de referencias de evidencias.

| Endpoint bajo /api/v1 | Otros roles autorizados |
| --- | --- |
| GET /auditorias | AUDITOR_INTERNO y AUDITOR_EXTERNO: auditor?as propias |
| POST /auditorias | AUDITOR_INTERNO: solo asign?ndose a s? mismo |
| GET /documentos | Auditores: documentos vinculados a auditor?as propias; RESPONSABLE_AREA: documentos propios; APROBADOR: documentos con versiones asignadas |
| POST /documentos | RESPONSABLE_AREA: solo responsable_id propio |
| GET /documentos/{id} | Mismo alcance documental; contenido anidado restringido |
| PATCH /documentos/{id} | RESPONSABLE_AREA: documento propio, sin reasignaci?n |
| POST /documentos/{id}/versiones | RESPONSABLE_AREA: documento propio, comprobado bajo bloqueo |
| GET /documentos/{id}/versiones | Auditores y RESPONSABLE_AREA: versiones de documentos accesibles; APROBADOR: versiones asignadas |
| GET /documentos/{id}/versiones/{version_id}/descargar | Mismo alcance por versi?n, comprobando la pareja documento/versi?n |
| GET /documentos/{id}/historial | Solo ADMIN |
| GET /evidencias | Auditores: auditor?as propias y referencias consistentes con la misma auditor?a |
| POST /evidencias/archivo | Auditores: auditor?a propia y referencias consistentes |
| POST /evidencias/logica | Auditores: auditor?a propia y referencias consistentes |
| GET /evidencias/{id} | Mismo alcance que listado |
| GET /evidencias/{id}/descargar | Mismo alcance que detalle, antes de resolver ruta f?sica |
| GET /areas | Todos los usuarios autenticados |
| GET /usuarios | AUDITOR_INTERNO: auditores activos elegibles; ADMIN: cat?logo completo |

ADMIN puede asignar auditor?as a usuarios activos AUDITOR_INTERNO/AUDITOR_EXTERNO. AUDITOR_EXTERNO no puede crear auditor?as. No se concede acceso por area_id.

## Relaciones y lecturas

- Auditor?a propia: `Auditoria.responsable_id == current_user.id`.
- Documentos para auditor: `EXISTS DocumentoAuditoria JOIN Auditoria`.
- Versiones para auditor: todas las versiones del documento vinculado, seg?n la matriz aprobada; no se limita a la versi?n del pivot.
- Aprobaciones: `DecisionAprobacion.aprobador_id -> RondaAprobacion.version_documento_id -> VersionDocumento.documento_id`. La asignaci?n concede lectura sin filtro adicional por estado de ronda/decisi?n.
- Evidencias: auditor?a autorizada; documento vinculado a ESA auditor?a; versi?n perteneciente al documento, cuyo documento tambi?n debe estar vinculado a ESA auditor?a. Aplica tambi?n a ADMIN al registrar evidencias. Los registros hist?ricos inconsistentes quedan fuera de las lecturas de auditores.
- Los scopes se aplican en SQL antes de limit/offset. EXISTS evita duplicados por m?ltiples v?nculos/asignaciones.
- Las versiones anidadas se restringen en SQL. Para APROBADOR, versi?n vigente y su ID son null si esa versi?n no est? asignada. Se refrescan cargas ORM para no reutilizar relaciones previas m?s amplias.
- El historial completo queda reservado a ADMIN porque los snapshots/eventos pueden incluir otros recursos y versiones.

## Identidad y errores

Los par?metros HTTP legacy creador_id, editor_id, subido_por_id, registrada_por_id y created_by_id son opcionales/deprecated e ignorados. Los routers pasan ?nicamente current_user.id a los servicios; la persistencia y los eventos usan ese actor. Los IDs de actor en las firmas internas de servicios son argumentos de confianza del backend, nunca par?metros HTTP reenviados.

- 401: identidad, token o sesi?n ausente/inv?lida, mediante la dependencia existente.
- 403: rol sin permiso de operaci?n; tambi?n las restricciones expl?citas de asignaci?n propia y reasignaci?n reservada a ADMIN.
- 404: recurso inexistente o fuera de alcance; pareja documento/versi?n inexistente/no autorizada; referencia de evidencia ajena a su auditor?a; responsable de auditor?a no elegible.
- Listados: omiten filas fuera de alcance.
- Las validaciones estructurales existentes conservan 422; por ejemplo, evidencia l?gica con versi?n pero sin documento.

## Frontera de archivos y regresiones

Toda autorizaci?n de carga ocurre antes de StorageService.save_file. Las versiones conservan SELECT FOR UPDATE y comprueban responsable con populate_existing=True sobre el documento bloqueado, antes de las validaciones de estado y de escribir archivos.

No se alteran storage f?sico, compensaci?n, reconciliaci?n, commit incierto ni fronteras transaccionales de 6A. Las pruebas antiguas que creaban documentos con rol auditor ahora usan RESPONSABLE_AREA; las fixtures compartidas de fallos transaccionales usan ADMIN.

## Validaci?n aislada

Desde api, con el entorno virtual existente:

```powershell
$env:AUTH_MYSQL_TEST = '1'
.\venv\Scripts\python.exe -m pytest tests_unit tests_auth_mysql -q -p no:cacheprovider --basetemp=<directorio-temporal-nuevo>
```

La suite unit usa SQLite en memoria con una copia de DDL exclusivamente para tests; no modifica el metadata de producci?n. Las pruebas MySQL reutilizan la fixture de autenticaci?n que crea un esquema local aleatorio sistema_trazabilidad_test_auth_<16 hex>, verifica su identidad y lo elimina al terminar. La conexi?n al engine de la aplicaci?n est? prohibida. Alembic se ejecuta ?nicamente en ese esquema temporal.

Las mismas pruebas HTTP RBAC se ejecutan en SQLite y MySQL. El adaptador test_6a_regression_mysql.py ejecuta las pruebas existentes de api/tests contra ese esquema aleatorio sin cargar su conftest ni usar su esquema fijo. La limpieza verifica expl?citamente el nombre y SELECT DATABASE() antes de truncar tablas temporales.

No existe GET /auditorias/{id}, ni endpoints para crear DocumentoAuditoria/asignaciones de aprobaci?n. Las pruebas usan relaciones aisladas; no se agregan operaciones nuevas para estos flujos.
