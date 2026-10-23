# Manual técnico

Sistema de Trazabilidad Documental para Auditorías. Manual de operación, mantenimiento, pruebas y desarrollo de la entrega local.

## 1. Preparar el entorno

Siga [Guía de instalación](GUIA_INSTALACION.md). Requisitos: Python 3.14, MySQL 8 real, PHP 8.1+ y filesystem con hardlinks. Dependencias runtime en `requirements.txt`; pruebas en `requirements-dev.txt`. Las librerías de DOCX/PDF pertenecen exclusivamente al entorno temporal de exportación, no al runtime.

`api/.env.example → api/.env` privado. Configure DB/JWT antes de startup. API default 8000; frontend 8080. Un solo proceso Uvicorn; PHP built-in sólo para local. `frontend/config/config.php` fija base API; los cambios de puerto requieren ajuste coherente de frontend, URLs, SMTP y CORS. No confíe en overrides de headers del cliente.

## 2. Organización para desarrollo

| Carpeta | Responsabilidad |
|---|---|
| api/app/routers | Transporte HTTP, contratos y dependencias |
| api/app/schemas | Validación/salida Pydantic |
| api/app/models | Entidades y restricciones de metadata |
| api/app/services | Reglas, autorización, transacciones, storage, correo y análisis |
| api/app/core | Settings y primitivas criptográficas |
| api/app/db | Engine/sesión, metadata y migraciones |
| api/app/scripts | Herramientas explícitas de aplicación; no startup |
| scripts | CLI operativas independientes de HTTP |
| frontend/services | Cliente API/controladores, sin acceso SQL |
| frontend/pages e includes | Presentación y componentes compartidos |
| api/tests_unit, api/tests_auth_mysql, frontend/tests | Contratos por nivel |

Antes de modificar una operación localice router, schema, servicio, scope y test. No añada permisos sólo por el nombre del rol. Consulte [Inventario](INVENTARIO_IMPLEMENTACION.md) para todas las tablas/rutas y [Documento técnico](DOCUMENTO_TECNICO.md) para decisiones de diseño.

## 3. Migraciones y cambios de modelos

Desde `api`: `venv\Scripts\python.exe -m alembic current` y `venv\Scripts\python.exe -m alembic upgrade head`. Estado esperado 005. Nunca edite revisiones ya publicadas ni use `stamp` para ocultar DDL incompleto. Una modificación estructural futura requiere nueva revisión, upgrade/downgrade probado en schema efímero y preservación de filas/FK. Demo/documentación no justifican 006.

Mantenga UTC en conexión y DATETIME(6), InnoDB y REPEATABLE READ. Los catálogos usan cinco roles canónicos; aliases/case/padding legacy no conceden permisos. Compare drift en entorno read-only antes de proponer correcciones, sin cambiar DDL real automáticamente.

## 4. Endpoints y RBAC

Swagger local documenta métodos/contratos bajo `/api/v1`. [Inventario de rutas](INVENTARIO_IMPLEMENTACION.md) complementa el contrato. Auth login/me/logout; acceso/reset públicos con controles específicos; recursos privados con Bearer y scopes. No hay DELETE de expedientes/versiones/eventos, CRUD web de usuarios/áreas ni endpoint de asociación documental a auditoría.

Para ampliar un endpoint aplique permiso en servicio y filtro SQL antes de paginar/agregar. Revalide actor durante esperas de locks. Use identidad autenticada para eventos, no IDs de actor del payload. Documentos propios no conceden acceso a auditoría. ADMIN tampoco suple identidad de APROBADOR. [Matriz de permisos](MATRIZ_PERMISOS.md).

## 5. Workflows

Auditoría: PLANNED → IN_PROGRESS → IN_REVIEW → COMPLETED; retorno revisión → progreso. CANCELLED existe como estado persistente, sin transición pública. Hallazgo: OPEN → IN_PROGRESS → PENDING_VERIFICATION → CLOSED, retorno de verificación a progreso y aceptación de riesgo desde estados activos. Rondas: PENDING → IN_REVIEW → resultado derivado/terminal; decisiones pendientes sólo del APROBADOR asignado. El router y los servicios actuales son la fuente de verdad para precondiciones.

Cambios de estado incluyen timestamp/estado esperado; ante 409 recargue, revise y reintente sólo si la intención sigue siendo válida. Ante `COMMIT_OUTCOME_UNKNOWN` consulte BD/storage antes de repetir. No cambie flags mediante SQL para «desbloquear» una auditoría sin preservar trazabilidad.

## 6. Herramientas locales

```bat
api\venv\Scripts\python.exe scripts/bootstrap_admin.py --help
api\venv\Scripts\python.exe scripts/gestionar_usuario.py --help
api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --help
api\venv\Scripts\python.exe scripts/prune_auth_sessions.py --help
api\venv\Scripts\python.exe scripts/prune_auth_login_limits.py --help
api\venv\Scripts\python.exe scripts/verificar_integridad.py --help
```

Bootstrap inicial crea sólo el primer ADMIN activo en entorno local permitido y pide contraseña oculta; no sustituye seed demo ni modifica usuarios. Gestionar usuario requiere ID+correo confirmados, password oculto y confirmación explícita; sólo cambia contraseña y revoca sesiones. No lo utilice sobre cuentas personales durante pruebas. Consulte [bootstrap histórico](historico/FASE_6D_1_BOOTSTRAP_ADMIN.md).

Seed con credenciales externas desde `api`: `python -m app.scripts.seed_evaluation_demo --with-dataset` muestra plan; añadir `--confirm-local-demo --credentials-file "RUTA_EXTERNA_AL_DOCUMENTO_PRIVADO"` inserta las cuatro cuentas del archivo de TODO Academy. Sin ese archivo falla seguro. Consulte [contrato y rotación](CREDENCIALES_EVALUACION.md); nunca copie contraseñas al código. Repetición valida identidad/password sin actualizar. Conflicto exige revisión; nunca elimine automáticamente la cuenta para forzar resultado. Producción/remoto son rechazados.

Pruning es mantenimiento mutativo acotado de sesiones/buckets vencidos. Revise `--help`, dry-run y política histórica antes de ejecutarlo; no se ejecuta sobre la BD real en Fase 9. No afecta versiones/eventos de dominio. Mantenga privilegios separados de tareas administrativas.

## 7. Storage e integridad

Cada instalación usa `storage/` en la raíz; `STORAGE_PATH` no lo redirige. No ubique archivos bajo frontend ni los sirva estáticamente. Mantenga acceso de la identidad de ejecución, hardlinks y espacio suficiente. No cree junctions/symlinks dentro del árbol administrado. Las descargas autorizadas comprueban archivo disponible antes de streaming.

Desde raíz:

```bat
api\venv\Scripts\python.exe scripts/verificar_integridad.py
```

Exit 0 limpio; 1 discrepancias; 2 incompleto/error. La salida puede contener keys/hashes de expedientes: consérvela privada, no como captura pública. Pausar cargas permite confirmar candidatos a huérfano. La herramienta nunca borra, mueve ni repara.

Para una BD alternativa proporcione URL mediante variable de entorno privada y storage explícito:

```bat
api\venv\Scripts\python.exe scripts/verificar_integridad.py --database-url-env TEST_DATABASE_URL --storage-root storage_temporal
```

No coloque credenciales de URL en argumentos. Revise divergencias comparando referencia/archivo, backup y eventos. Preserve legacy y documente origen antes de cualquier limpieza manual aprobada.

## 8. Mail worker

Configure sólo `.env` privado con SMTP genérico y TLS. Ejecute desde raíz `api\venv\Scripts\python.exe scripts/procesar_correo_auth.py --max-jobs 20` después de solicitudes/reset/aprobaciones. El lote no permanece escuchando: su operación continua requiere planificador. Estados PENDING/PROCESSING/DONE/CANCELLED/FAILED, leases y backoff permiten recuperación ante caídas; hasta tres intentos. Conteo procesado no confirma recepción externa.

El backend de recuperación, tokens/controles, cola, worker y configuración SMTP están implementados. **El envío real no está disponible en la demo:** no se configuró un proveedor externo ni se acreditó recepción; las identidades ficticias no tienen buzón. [Procedimiento para una instalación con buzón autorizado](SMTP_RECUPERACION.md). No imprima contraseña SMTP, raw tokens, destinatarios ni contenido de mails en logs de entrega.

## 9. Pruebas y debugging

Comandos e identidad MySQL de prueba en [Guía de instalación](GUIA_INSTALACION.md). `PYTHONPATH` debe incluir `api`; instale requirements-dev. `AUTH_MYSQL_TEST=1` y `AUTH_BROWSER_TEST=1` son opt-in; Chrome utiliza perfil temporal. Un basetemp nuevo y corto evita choques de permisos y deja margen al test Win32 de longitud de ruta. Las suites de integración usan únicamente su schema aleatorio guardado. Para conservarlo sin borrar bases de datos, establezca `AUTH_MYSQL_KEEP_SCHEMA=1`; es la opción usada en Fase 9.2.

No ejecute directamente `api/tests` contra BD operativa: use el wrapper protegido `test_6a_regression_mysql.py`. Fallos de sandbox/Chrome deben reproducirse con el entorno autorizado, sin atribuir automáticamente el error al producto. Los servicios externos se sustituyen en tests; un pass de sender SMTP doble no demuestra llegada real.

Debug de aplicación sólo registra tipo de excepción; no habilite logging de cuerpos auth ni SQL con parámetros privados. Uvicorn informa startup/HTTP local; PHP debe ocultar trazas y mensajes driver al usuario. Si falla una consulta, no interprete ausencia como cero. Para 401 revise sesión/expiración; 403 permiso; 404 recurso/alcance; 409 cambio concurrente; 429 presupuesto; 503 indisponibilidad/admisión/correo.

## 10. Backup y mantenimiento

No se instala backup automático. Para respaldo coherente pause mutaciones/cargas y el worker, registre revisión/fecha y copie DB **y** storage. Con una identidad local autorizada:

```bat
mysqldump -h 127.0.0.1 -P 3306 -u usuario_backup -p --single-transaction --routines --triggers trazabilidad_evaluacion > respaldo_privado.sql
```

La contraseña se solicita, no va en argumentos. Mantenga el dump y la copia de storage fuera de Git, con control de acceso. Compare hashes y pruebe restauración sólo en schema/directorio alternativos, aplicando la misma revisión. Respaldar sólo DB pierde bytes; sólo storage pierde atribuciones. No haga un restore sobre expedientes reales sin decisión operativa explícita.

No borre usuarios históricos por ID/nombre: tienen FK y atribuciones. Inventario legacy baseline: dos usuarios activos canónicos, una auditoría, tres documentos, dos versiones, seis eventos y dos archivos privados; no se publican identidades. Fase 9 conserva esos datos y sesiones existentes. El seed de validación vive en schemas separados.

## 11. Dependencias y release

`requirements.txt` conserva rangos soportados; `requirements-lock.txt` fija el conjunto runtime verificado para evaluación reproducible. Use `pip install -r requirements.txt -c requirements-lock.txt` para ese checkpoint. Actualizaciones requieren nueva validación; no cambie algoritmos/queries sin defecto demostrado. PHP no necesita Composer. Los exports documentales se regeneran desde Markdown en un venv temporal y se entregan fuera de Git.

Antes de publicar una release revise staging/diff, tests afectados, instalación nueva, secret scan y hashes de entregables. La auditoría final de Fase 9.2 aprobó la release según el dictamen comunicado; la publicación Git es un paso separado a cargo del responsable. El README remoto debe contener la misma fuente validada. El índice de TODO Academy mapea cada tipo y no requiere ZIP del código.

## 12. Deuda y troubleshooting

Huérfano por corte abrupto requiere reconciliación; 7E limita candidatos/storage; deprecaciones menores de librerías de tests permanecen; análisis global pesado bajo concurrencia extrema. 7E aplica reglas, hashes, metadatos/versiones y similitud heurística de nombres; no garantiza detectar cualquier irregularidad ni todos los documentos faltantes. No realiza análisis semántico general ni utiliza Ollama, IA generativa, LLM, machine learning o modelos entrenados. Un servicio multiproceso, administración web ampliada, notificaciones generales y modelo local de IA necesitan diseño aparte. [Troubleshooting de instalación](GUIA_INSTALACION.md) contiene puertos, SMTP, env, PHP y MySQL.
