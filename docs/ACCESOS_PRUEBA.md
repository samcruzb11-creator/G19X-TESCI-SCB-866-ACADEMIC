# Accesos de prueba — procedimiento público

Las cuatro credenciales de evaluación se entregan **por separado a Edgar**, mediante la sección **"Accesos de prueba" del SGPA** (TODO Academy), en `01_ACCESOS_PRUEBA.md`. Este documento público no contiene identificadores ni contraseñas. El documento privado debe permanecer fuera del repositorio y de los PDF/DOCX públicos.

Para la evaluación oficial se utiliza el archivo `01_ACCESOS_PRUEBA.md` provisto en el SGPA, guardado fuera del repositorio en `%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md`, siguiendo la [Guía de instalación](GUIA_INSTALACION.md) y pasando esa ruta externa al seed mediante `--credentials-file`. El script `app.scripts.evaluation_credentials` sólo se emplea si se requiere regenerar el archivo privado en un entorno local aislado cuando no se dispone del entregable del SGPA.

Roles: ADMIN (visibilidad global), RESPONSABLE_AREA (documentos propios), AUDITOR_INTERNO (auditorías asignadas), APROBADOR (decisiones asignadas). [Matriz de permisos](MATRIZ_PERMISOS.md).

Uso exclusivamente local: frontend http://127.0.0.1:8080; API http://127.0.0.1:8000; Swagger http://127.0.0.1:8000/docs. No son cuentas externas reales ni acceso a producción. [Contrato y operaciones explícitas](CREDENCIALES_EVALUACION.md).

**Correo no disponible en la demo:** el backend de recuperación, tokens/controles, cola, worker y configuración SMTP están implementados, pero no se configuró un proveedor externo ni se demostró correo real recibido. Las cuentas ficticias no tienen buzón; evalúe login y permisos con el archivo privado, sin esperar mensajes de recuperación.
