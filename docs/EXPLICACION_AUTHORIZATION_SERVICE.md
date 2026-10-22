# Estudio técnico 1: autorización y control de acceso

**Archivo:** [`api/app/services/authorization_service.py`](../api/app/services/authorization_service.py)  
**Proyecto:** Sistema de Trazabilidad Documental para Auditorías  
**Propósito:** comprender y explicar los permisos del backend durante la defensa de residencias.

## ¿Qué problema resuelve?

Este módulo evita que iniciar sesión sea suficiente para consultar o modificar cualquier documento. El sistema maneja auditorías, versiones, evidencias y aprobaciones de distintos responsables; por ello necesita comprobar **qué acción puede realizar cada usuario** y **sobre qué registros concretos**.

## ¿Cómo funciona?

La autenticación ocurre en [`api/app/api/dependencies.py`](../api/app/api/dependencies.py): allí se validan el JWT, la sesión y el usuario activo. Después, `authorization_service.py` trabaja con el usuario identificado y aplica dos controles:

1. **Permiso por rol (RBAC).** `PERMISSIONS` define acciones reconocidas; `require_permission(user, action)` rechaza con **403** las acciones desconocidas, los usuarios inactivos o los roles no autorizados. ADMIN dispone de acceso general a las acciones registradas, pero no queda exento de otras reglas de negocio.
2. **Alcance por recurso.** Funciones como `documento_scope()`, `auditoria_scope()` y `version_scope()` construyen filtros de SQLAlchemy que se incorporan a las consultas. Así, compartir un rol o un área no da acceso automático a los mismos expedientes.

Por ejemplo, para `RESPONSABLE_AREA`, `documento_scope()` exige `Documento.responsable_id == user.id`. Si solicita un documento ajeno, `GET /api/v1/documentos/{documento_id}` devuelve **404**, igual que cuando el documento no existe. Esto evita revelar directamente su existencia.

En las actualizaciones, `authorize_document_update()` comprueba además que un responsable no se reasigne el documento a otra persona: esa modificación se reserva a ADMIN. En determinadas escrituras, `lock_actor()` vuelve a consultar el estado y los permisos del usuario bajo un bloqueo de base de datos, porque podrían cambiar durante la operación. **No vuelve a pedir la contraseña ni valida otra vez el JWT.**

## ¿Por qué aplicar estos controles en FastAPI?

Ocultar un botón desde PHP mejora la interfaz, pero no protege por sí solo los datos: alguien podría enviar solicitudes directamente a la API. Por eso, los permisos y los filtros de acceso se aplican **en el backend**, antes de entregar o modificar información. Separar autenticación, autorización y lógica de negocio también permite reutilizar estas reglas entre módulos.

## ¿Cómo lo demostraría ante Edgar?

- **401:** petición sin autenticación válida; lo gestiona la dependencia de autenticación.
- **403:** usuario autenticado que intenta una acción no permitida, como `RESPONSABLE_AREA` creando una auditoría.
- **404:** documento inexistente o fuera del alcance del usuario, aunque tenga permiso general para leer documentos.

Puedo mostrar las consultas del [router de documentos](../api/app/routers/documentos.py) y los casos de acceso indebido incluidos en [`test_rbac_unit.py`](../api/tests_unit/test_rbac_unit.py), particularmente `test_document_idor` y `test_vertical_denials`. **La existencia de estas pruebas no equivale a haberlas ejecutado durante la preparación de esta ficha.**

**Límite importante:** este servicio no protege por sí solo todas las rutas, ni valida contraseñas, archivos o sesiones; los demás módulos deben llamar correctamente sus verificaciones.

---

*Ficha de estudio redactada con asistencia de ChatGPT, a partir del código publicado, del análisis de Codex y de las respuestas practicadas por el estudiante. Su explicación oral debe reflejar la comprensión personal del estudiante.*
