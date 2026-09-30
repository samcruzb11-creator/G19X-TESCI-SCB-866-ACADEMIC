# Consistencia MySQL ↔ storage

## Seguimiento de Fase 6A (2026-09-29)

Estado: pendiente de pruebas MySQL; no cerrada. TEST_DATABASE_URL no existe
en el entorno visible de la sesión. No se usó DATABASE_URL como fallback,
no hubo conexión a MySQL ni ejecución sobre la base oficial.

Validación local: 49 pruebas unitarias aprobadas; imports y app.openapi()
correctos; git diff --check sin errores. Storage de pruebas: api/.pytest_temp,
ignorado por Git. Dos avisos de deprecación de dependencias del TestClient.

Correcciones: CommitOutcomeUnknown devuelve HTTP 503 con el código
COMMIT_OUTCOME_UNKNOWN y exige verificar el expediente antes de reintentar;
pytest usa --basetemp=.pytest_temp; el verificador exige --storage-root cuando
se indica --database-url-env, antes de crear cualquier engine.

Los guards se probaron sin conexión: variable ausente, base oficial y cualquier
base distinta de sistema_trazabilidad_test abortan antes de crear el engine.
Solo el nombre exacto autorizado supera el guard lógico; el checkout conserva
la comprobación de SELECT DATABASE(). No se muestran URLs ni contraseñas.

Pre-commit (incluido flush de EventoAuditoria), post-commit/refresh, commit
incierto sin reintentos y conservación de archivos, SHA-256, faltantes,
huérfanos y verificador de solo lectura pasan con sesiones simuladas. Se añadió
el fallo específico de flush del evento a la suite MySQL pendiente.

storage_key: se mantienen los contratos de detalle y alta existentes. La
búsqueda en PHP no encontró consumidores del campo, pero eliminarlo de los
schemas públicos existentes sería un cambio de contrato. Los listados siguen
sin exponerlo; las descargas utilizan identificadores.

Debug HTTP permanece desactivado siempre. settings.debug habilita únicamente
un diagnóstico local del tipo de excepción, sin texto de excepción ni trazas.
Se probó la respuesta saneada con settings.debug activado y desactivado.

No se ejecutó Alembic, no se modificó .env ni se hizo push. Se preservaron
los cambios previos del repositorio. La persistencia real, metadata y
reconciliación en MySQL siguen pendientes de una URL de pruebas autorizada.

## Fronteras de la operación

1. Validar relaciones y, para versiones, bloquear el documento.
2. Escribir un archivo temporal en el directorio de destino, calcular SHA-256
   por bloques, hacer flush/fsync y renombrar al nombre final con UUID.
3. Crear metadatos, actualizar versión vigente y añadir el evento en la misma
   transacción. Hacer flush explícito de todo antes de intentar commit.
4. Si falla la preparación: rollback y compensación únicamente del archivo
   nuevo. Nunca se recorre el storage para borrar otros archivos.
5. Intentar commit una sola vez. No hay reintentos de INSERT/COMMIT.
6. Después de commit confirmado, refrescar las entidades fuera de cualquier
   bloque de compensación. Ningún fallo de refresh/serialización elimina archivos.

Se conservan los refresh porque SessionLocal usa expire_on_commit=True de forma
predeterminada y los servicios devuelven entidades ORM con valores de BD. No se
modifica globalmente la política de sesiones ni el contrato de retorno.

## Commit incierto

Una excepción de transporte durante commit no prueba rollback: el servidor
podría haber confirmado. Se conserva el archivo, se intenta liberar la sesión y
se genera CommitOutcomeUnknown, sin reintentos. El único rechazo clasificado
automáticamente aquí es MySQL 1213 (transacción abortada por deadlock), sin
invalidación de conexión. El resto se considera incierto de forma conservadora.
Un fallo de rollback o de limpieza también exige reconciliación manual.

Las restricciones únicas existentes de storage_key y documento/número de versión
se conservan. No constituyen una clave de idempotencia para reenviar una carga:
un reenvío podría producir otra versión o evidencia. Consultar antes de repetir.

## Verificación de solo lectura

Desde la raíz, utilizando el entorno Python del proyecto:

```powershell
& api/venv/Scripts/python.exe scripts/verificar_integridad.py
```

Por defecto consulta la BD y storage configurados, únicamente mediante SELECT
y lecturas de archivos. No crea directorios, ni borra, mueve, repara o actualiza.
No hay opción --fix. No imprime credenciales, URLs de conexión, rutas absolutas
ni trazas. Los archivos sin referencia se identifican mediante claves relativas.

Para un entorno de pruebas ya preparado:

```powershell
& api/venv/Scripts/python.exe scripts/verificar_integridad.py --database-url-env TEST_DATABASE_URL --storage-root C:/ruta/temporal/de/pruebas
```

Debe utilizarse una raíz que corresponda exactamente a la BD seleccionada.
El script examina versiones y evidencias FILE (también detecta referencias físicas
anómalas en evidencias lógicas), y recorre solo documents/ y evidence/. No sigue
symlinks/junctions; los informa. Otros directorios no se consideran gestionados.

Resultados: missing_file, orphan_candidate, hash_mismatch, size_mismatch,
invalid_storage_key, invalid_hash_metadata, unsafe_link, unreadable, etc.
Los temporales se informan como temporary_recent o temporary_abandoned_candidate;
el umbral predeterminado es una hora y puede ajustarse con --temporary-age.
Una antigüedad alta no prueba que un temporal esté abandonado.

Códigos: 0 sin incidencias; 1 discrepancias/candidatos; 2 inspección incompleta
o inaccesible. Todas las incidencias requieren evaluación; ninguna causa borrado.

Pausar cargas durante una verificación concluyente. BD y filesystem no comparten
un snapshot atómico: una carga en curso puede parecer huérfana o faltar en la
primera lectura. No decidir reparaciones basándose en un escaneo concurrente.

## Pruebas seguras

Pruebas sin conexión a ninguna BD, con sesiones simuladas y storage temporal:

```powershell
cd api
& venv/Scripts/python.exe -m pytest tests_unit -p no:cacheprovider -q
```

Las pruebas MySQL requieren TEST_DATABASE_URL explícita, con esquema de pruebas
ya preparado. El conftest rechaza sistema_trazabilidad y el nombre de la BD de
la aplicación, incluso mediante otro host/driver/usuario. No define fallback.
No ejecutar migraciones ni crear tablas automáticamente para estas pruebas.

```powershell
& venv/Scripts/python.exe -m pytest tests/test_file_consistency.py tests/test_storage_and_traceability.py -p no:cacheprovider -q
```

La suite histórica trunca tablas exclusivamente en esa BD de pruebas; la nueva
suite usa registros UUID y elimina únicamente sus propios registros. Ambas usan
storage temporal, nunca el storage oficial. La prueba histórica de commit ahora
simula rechazo MySQL confirmado, no un error genérico de resultado incierto.

Se cubren streaming, flush, commit rechazado, commit incierto antes/después de
persistir, fallo posterior a commit, errores de limpieza, verificador y descargas.

## Contratos y límites

Los listados de documentos y versiones ahora excluyen storage_key, igual que el
listado de evidencias. No cambian las rutas de descarga ni los metadatos necesarios
por PHP. Los contratos de detalle y alta permanecen iguales.

El debug HTTP de FastAPI se deshabilita para que las excepciones de filesystem/BD
usen siempre el mensaje saneado, independientemente de la configuración local.
No se modifica .env.

Una muerte abrupta puede dejar temporales/huérfanos y un commit incierto puede
requerir conciliación. No hay transacción distribuida MySQL/filesystem ni reparación
automática. fsync y rename no sustituyen respaldos ni una restauración probada.
