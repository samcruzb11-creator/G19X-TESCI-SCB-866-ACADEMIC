# Servicio de transacciones de archivos

**Módulo:** `api/app/services/file_transaction.py`

## Responsabilidad

Este servicio define cómo manejar errores durante el registro de archivos de documentos y evidencias. Al cargar un archivo, el sistema escribe su contenido en el almacenamiento local y registra sus metadatos y eventos en MySQL. Como el sistema de archivos y la base de datos no comparten una transacción atómica, un fallo entre ambas operaciones puede dejar información inconsistente.

El objetivo del módulo es limitar las compensaciones a los casos en los que es seguro realizarlas y conservar los archivos cuando no se puede determinar si el registro en MySQL quedó confirmado.

## Implementación

Los servicios `documento_service.py` y `evidencia_service.py` guardan el archivo y preparan los registros asociados mediante `flush()` antes de intentar `commit()`. `file_transaction.py` proporciona tres funciones:

- **`rollback_safely(db)`:** intenta revertir la transacción de MySQL y devuelve si la operación se completó. Si falla, registra una advertencia operativa sin incluir mensajes potencialmente sensibles del controlador.
- **`discard_uncommitted_file(db, storage, key)`:** ejecuta el rollback y, si se completa, intenta eliminar el archivo recién creado. Sólo debe utilizarse antes de intentar el commit o después de un rechazo explícito que demuestre la reversión del lado de MySQL.
- **`commit_stored_file(db, storage, key)`:** realiza el commit. Si MySQL informa un deadlock mediante el error 1213 en las condiciones previstas, trata el commit como rechazado e intenta compensar el archivo. Ante otros errores, el resultado se considera incierto: conserva el archivo y lanza `CommitOutcomeUnknown`.

Una pérdida de conexión durante el commit no permite establecer si MySQL confirmó o rechazó la transacción. Por ello, la política evita borrar el archivo o repetir automáticamente la operación. La revisión del estado de MySQL y del almacenamiento debe preceder a cualquier nuevo intento.

Tras un commit exitoso, los servicios consumidores ejecutan `refresh()` fuera de la sección de compensación. Un fallo al recuperar los datos para construir la respuesta no provoca la eliminación de un archivo que ya puede estar asociado a registros persistidos.

## Criterios de diseño y límites

La separación de errores previos y posteriores al commit evita confundir un fallo de respuesta con un fallo de persistencia. También permite mantener el archivo cuando la eliminación sería más arriesgada que su conservación.

Este mecanismo reduce las inconsistencias, pero no garantiza atomicidad entre MySQL y el sistema de archivos. Una interrupción imprevista puede dejar archivos sin referencias; además, las operaciones de rollback y limpieza pueden fallar. El servicio de [integridad de almacenamiento](../api/app/services/storage_integrity.py) permite detectar referencias faltantes, archivos candidatos a huérfanos y discrepancias de hash o tamaño, sin eliminarlos automáticamente.

**Referencias de implementación:** [carga de versiones](../api/app/services/documento_service.py), [carga de evidencias](../api/app/services/evidencia_service.py) y [pruebas de consistencia](../api/tests_unit/test_file_consistency_unit.py). Estas pruebas describen escenarios simulados de fallo; no se ejecutaron nuevamente al preparar este documento.
