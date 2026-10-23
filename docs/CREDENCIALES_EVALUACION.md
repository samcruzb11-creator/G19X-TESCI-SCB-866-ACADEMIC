# Contrato privado de evaluación y operaciones explícitas

GitHub contiene código y documentación pública. `01_ACCESOS_PRUEBA.md` se entrega exclusivamente a Edgar por Accesos de prueba de TODO Academy, fuera del repositorio. El evaluador necesita únicamente el código de la release y ese documento; genera sus propios secretos de conexión/JWT locales. No necesita datos personales, dumps ni configuración del alumno.

## Contrato v1

Markdown UTF-8 (se acepta BOM de lectura), máximo 64 KiB, con exactamente un bloque cercado cuya etiqueta es `evaluation-credentials-v1`. Su contenido es un objeto JSON con exactamente `schema_version` (entero 1) y `accounts` (cuatro objetos). Cada objeto contiene únicamente `role`, `email`, `password`; no se aceptan claves duplicadas ni campos adicionales.

Roles exactos, uno por cada rol: ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO, APROBADOR. El orden de entrada puede variar; el seed ordena por esos roles. Cada identificador es ficticio: prefijo `eval-`, parte local minúscula de 3–64 caracteres alfanuméricos/guiones después del prefijo, dominio reservado `example.invalid`. Cada contraseña es diferente, de 32–128 caracteres ASCII alfanuméricos, guion o guion bajo. El generador usa 32 bytes aleatorios (256 bits) mediante `secrets.token_urlsafe`, normalmente 43 caracteres; el parser valida formato, no puede probar la entropía de una contraseña escrita por terceros.

No se incluye un bloque ejecutable de ejemplo con cuentas fijas. El generador produce un documento legible, explica los permisos y coloca el contrato en una sola sección. El seed lee únicamente el contrato, sin ejecutar Markdown ni Python. Las cuentas se almacenan con Argon2id; correos/passwords nunca aparecen en stdout ni mensajes de error. El archivo ausente, inválido o dentro del repositorio se rechaza antes de conectar MySQL. No existe credencial de respaldo ni generación automática.

## Evaluador: provisionar con el archivo recibido

Desde `api`, venv activado, MySQL 8 loopback, `APP_ENV=development`, Alembic 005:

```bat
python -m app.scripts.seed_evaluation_demo --with-dataset
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

El primer comando es plan sin cambios. La ejecución confirmada inserta las cuatro cuentas y el dataset una sola vez. Repetir con el mismo archivo devuelve cero cuentas nuevas y conserva IDs, hashes, eventos y bytes. Una identidad existente con nombre/rol/actividad/password distintos aborta sin correcciones silenciosas. No hay seed en startup. [Instalación completa](GUIA_INSTALACION.md).

## Responsable de preparar accesos: generación opt-in

Sólo para una entrega nueva, no para recrear las cuentas del archivo recibido:

```bat
python -m app.scripts.evaluation_credentials --confirm-generate --output "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

El directorio externo debe existir y el archivo no debe existir. Creación exclusiva: nunca sobrescribe ni sigue un archivo existente. ACL Windows: se retira herencia y se concede control sólo al SID de la identidad que ejecuta el comando, antes de escribir secretos; fuera de Windows usa modo 0600. Si falla ACL, no se escribe ningún secreto. No hay creación de usuarios, correo ni servicios externos. La cuenta Windows administradora conserva sus capacidades administrativas inherentes.

## Rotación separada y controlada

Detener los procesos de evaluación y el worker antes del plan, para mantener estable el fingerprint. Conservar un snapshot privado DB/storage/.env fuera de Git. Obtener un contrato privado anterior que corresponda exactamente a las cuentas existentes; el modo de lectura anterior admite exclusivamente el formato nuevo o el dominio ficticio legacy. No publica ni incorpora valores legacy al código.

Desde `api`, preparar el plan con las dos rutas privadas y cuatro IDs verificados en orden ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO, APROBADOR:

```bat
python -m app.scripts.rotate_evaluation_demo --credentials-file "RUTA_EXTERNA_NUEVA" --previous-credentials-file "RUTA_EXTERNA_ANTERIOR" --demo-user-ids "3,4,5,6"
```

El plan comprueba entorno, versión, migración, lock compartido, identidad/nombre/rol/password previos y referencias del dataset del seed a los cuatro actores. Muestra sólo IDs y fingerprint agregado, sin modificar filas. IDs 1 y 2 están protegidos. Si las cuentas tienen otros IDs demo, use sus cuatro IDs reales mayores que 2; no fuerce IDs mediante SQL.

Después de revisar el plan, volver a ejecutar añadiendo `--expected-fingerprint "FINGERPRINT_DEL_PLAN" --confirm-rotate-demo`. Sin confirmación no modifica; sin fingerprint coincidente rechaza. No admite reutilizar ninguna contraseña previa, colisiones con terceros ni intercambios de identidad entre actores.

Una sola transacción cambia correo normalizado/correo, password_hash Argon2id y updated_at de los cuatro actores. Revoca todas sus sesiones aún no revocadas e invalida sus tokens de acción pendientes. Conserva PK, rol, nombre, actividad, created_at, FK y todos los eventos históricos; no reasigna actores ni reescribe snapshots de eventos. Compara todas las tablas ajenas, usuarios históricos/no-demo, sesiones/tokens ajenos y conteos de cada FK a usuarios antes del commit. Un fallo provoca rollback. No crea usuarios, archivos, eventos, correo ni auditorías; registra sólo métricas intencionales y fingerprints en la salida.

La rotación no es idempotencia del seed: es una operación distinta. Tras rotar, el seed usa exclusivamente el documento nuevo y no vuelve a cambiar contraseñas. Verificar login de los cuatro roles, passwords anteriores rechazados, sesiones anteriores revocadas y restricciones RBAC. [Resultado local y fresh clone](historico/FASE_9_2_CREDENCIALES_PRIVADAS.md).
