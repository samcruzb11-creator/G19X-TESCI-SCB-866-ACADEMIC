# Estudio técnico 2: consistencia entre archivos y MySQL

**Archivo:** [`api/app/services/file_transaction.py`](../api/app/services/file_transaction.py)  
**Proyecto:** Sistema de Trazabilidad Documental para Auditorías  
**Propósito:** explicar cómo se manejan los fallos al guardar archivos y sus registros de trazabilidad.

## ¿Qué problema resuelve?

Cuando se carga un PDF, el sistema almacena el archivo en disco y registra en MySQL sus metadatos (como ubicación, tamaño y SHA-256). Estas operaciones **no forman una única transacción atómica**: MySQL puede revertir sus propios registros, pero no controla automáticamente un archivo ya escrito en el sistema de archivos.

Si se produce un fallo, podríamos conservar un archivo sin registro o, más grave, borrar un archivo cuyo registro sí quedó confirmado. Este módulo establece cuándo es seguro intentar una limpieza y cuándo debemos conservar el archivo para verificar lo ocurrido.

## ¿Cómo funciona?

Los servicios de [documentos](../api/app/services/documento_service.py) y [evidencias](../api/app/services/evidencia_service.py) guardan primero el archivo y preparan los metadatos y eventos con `flush()`. Después utilizan estas funciones:

- **`rollback_safely(db)`:** intenta revertir la transacción de MySQL. Si falla, lo registra y devuelve `False`, sin incluir mensajes potencialmente sensibles del controlador.
- **`discard_uncommitted_file(db, storage, key)`:** intenta revertir la transacción y eliminar **sólo el archivo nuevo**, cuando todavía no se intentó confirmar o existe una señal explícita de rechazo del servidor. Si falla el rollback, conserva el archivo para revisión.
- **`commit_stored_file(db, storage, key)`:** intenta ejecutar `commit()`. Reconoce específicamente el error MySQL **1213 (deadlock)**, sin invalidación de conexión, como rechazo explícito: en ese caso intenta compensar el archivo y vuelve a lanzar el error. Ante otros fallos del commit, el resultado se considera incierto; conserva el archivo y lanza `CommitOutcomeUnknown`.

Después de un commit exitoso, los servicios realizan `refresh()` **fuera de la compensación**. Así, un error al refrescar o preparar la respuesta no provoca que se borre un archivo cuyo registro ya se confirmó.

## ¿Por qué se diseñó así?

La regla más importante es **no interpretar una pérdida de conexión como prueba de que el commit falló**. MySQL pudo confirmar los cambios antes de perderse la respuesta. Incluso si luego se logra hacer `rollback()` en la sesión, eso no demuestra que el servidor hubiera rechazado el commit.

Por eso, cuando el resultado es incierto, prefiero conservar el archivo y comprobar su relación con los registros antes de permitir otro intento. Repetir automáticamente la carga podría duplicar documentos o evidencias; eliminarla podría romper una referencia válida.

## Ejemplo para explicar en la defensa

Un responsable sube una nueva versión documental:

1. El PDF se escribe en `storage/` y se calculan sus metadatos.
2. Se preparan la versión y el evento de trazabilidad en MySQL.
3. Durante `commit()`, se pierde la conexión.
4. El sistema **no borra el PDF**: informa que no pudo confirmar el registro mediante `CommitOutcomeUnknown`.
5. Antes de volver a subirlo, es necesario revisar el estado real en MySQL y el almacenamiento.

Si, en cambio, el error ocurre **antes** del commit y la transacción puede revertirse, se intenta eliminar el archivo nuevo. La limpieza puede fallar; el sistema registra esa situación para una reconciliación posterior.

## Pruebas y limitaciones

En [`test_file_consistency_unit.py`](../api/tests_unit/test_file_consistency_unit.py) existen casos para fallo de `flush()`, rechazo explícito por deadlock, resultado incierto del commit y fallo de `refresh()` posterior a un commit exitoso. Son pruebas con simulaciones; **no se volvieron a ejecutar al redactar esta ficha**.

La solución **reduce el riesgo de inconsistencia, pero no garantiza atomicidad entre MySQL y el disco**. Pueden existir archivos huérfanos, por ejemplo, si un proceso se interrumpe inesperadamente. El [escáner de integridad](../api/app/services/storage_integrity.py) permite identificar discrepancias sin eliminarlas automáticamente; la conciliación requiere verificar el estado real.

---

*Ficha preparada con asistencia de ChatGPT a partir del código del repositorio y la práctica de defensa con el estudiante. No sustituye su propia comprensión ni constituye una prueba nueva de ejecución.*
