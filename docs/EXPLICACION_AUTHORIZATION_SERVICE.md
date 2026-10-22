# Servicio de autorización y control de acceso

**Módulo:** `api/app/services/authorization_service.py`

## Responsabilidad

Este servicio concentra las reglas de autorización para las operaciones sobre auditorías, documentos, versiones, evidencias, hallazgos y aprobaciones. Su objetivo es impedir que un usuario acceda a información o ejecute acciones fuera de los permisos asociados con su rol y con los recursos que tiene asignados.

La identificación del usuario se realiza previamente en `api/app/api/dependencies.py`, mediante la validación del JWT, la sesión y el estado de la cuenta. El servicio de autorización recibe el usuario identificado y evalúa sus permisos.

## Implementación

El control de acceso utiliza dos niveles complementarios:

- **Permisos por acción:** el diccionario `PERMISSIONS` define las operaciones admitidas para cada rol. `require_permission()` rechaza con HTTP 403 las acciones no reconocidas, las cuentas inactivas y los roles sin autorización. ADMIN puede realizar las acciones registradas, sujeto a las demás restricciones del sistema.
- **Alcance de los recursos:** funciones como `auditoria_scope()`, `documento_scope()` y `version_scope()` generan expresiones de SQLAlchemy que se incorporan a las consultas. De este modo, tener permiso para consultar documentos no implica poder consultar todos los documentos.

Para `RESPONSABLE_AREA`, `documento_scope()` restringe el acceso a los registros cuyo `responsable_id` coincide con `user.id`. Los auditores consultan documentos vinculados a sus auditorías, mientras que los aprobadores tienen acceso a documentos y versiones relacionados con sus asignaciones. Las reglas concretas dependen del recurso y de la operación.

La función `resource()` combina la comprobación del permiso con la búsqueda por identificador y alcance. Si el usuario puede realizar la acción, pero el registro solicitado no está dentro de su alcance, devuelve HTTP 404. En el router de documentos se aplica el mismo criterio: un documento ajeno y uno inexistente no se distinguen mediante la respuesta de detalle.

Las operaciones de escritura incluyen verificaciones adicionales. Por ejemplo, `authorize_document_update()` impide que un responsable cambie la asignación del documento a otra persona. `lock_actor()` vuelve a consultar el estado y los permisos del usuario bajo un bloqueo compartido de base de datos, para reducir el riesgo de operar con permisos que hayan cambiado durante la transacción.

## Criterios de diseño y límites

La autorización se aplica en FastAPI y no depende de ocultar controles en la interfaz PHP. Esto permite comprobar las restricciones incluso cuando se realizan solicitudes directas a la API. La separación entre permisos generales y alcance de registros también facilita reutilizar las reglas en distintos servicios.

El módulo no autentica usuarios ni protege automáticamente cualquier consulta: cada router o servicio debe aplicar las comprobaciones correspondientes. La autenticación inválida produce HTTP 401 desde las dependencias; una acción prohibida produce HTTP 403 y un recurso fuera del alcance puede producir HTTP 404.

**Referencias de implementación:** [dependencias de autenticación](../api/app/api/dependencies.py), [router de documentos](../api/app/routers/documentos.py) y [pruebas de autorización](../api/tests_unit/test_rbac_unit.py). Estas pruebas están incorporadas al repositorio; este documento no presenta una nueva ejecución de ellas.
