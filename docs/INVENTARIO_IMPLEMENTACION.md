# Inventario de implementación real

Inventario de cierre derivado de OpenAPI, metadata SQLAlchemy, código y Git. No incluye valores privados de `.env` ni contenido de storage.

## Routers y endpoints

Diez routers activos; 61 operaciones HTTP, 52 rutas distintas contando estado raíz. El prefijo default es `/api/v1`.

| Método | Ruta |
|---|---|
| GET | `/api/v1/documentos` |
| POST | `/api/v1/documentos` |
| GET | `/api/v1/documentos/{documento_id}` |
| PATCH | `/api/v1/documentos/{documento_id}` |
| GET | `/api/v1/documentos/{documento_id}/versiones` |
| POST | `/api/v1/documentos/{documento_id}/versiones` |
| GET | `/api/v1/documentos/{documento_id}/versiones/{version_id}/descargar` |
| GET | `/api/v1/documentos/{documento_id}/historial` |
| GET | `/api/v1/evidencias` |
| POST | `/api/v1/evidencias/archivo` |
| POST | `/api/v1/evidencias/logica` |
| GET | `/api/v1/evidencias/{evidencia_id}` |
| GET | `/api/v1/evidencias/{evidencia_id}/descargar` |
| GET | `/api/v1/areas` |
| GET | `/api/v1/usuarios` |
| GET | `/api/v1/auditorias` |
| POST | `/api/v1/auditorias` |
| GET | `/api/v1/auditorias/{audit_id}` |
| PATCH | `/api/v1/auditorias/{audit_id}` |
| POST | `/api/v1/auditorias/{audit_id}/estado` |
| GET | `/api/v1/auditorias/{audit_id}/historial` |
| GET | `/api/v1/hallazgos` |
| POST | `/api/v1/hallazgos` |
| GET | `/api/v1/hallazgos/{finding_id}` |
| PATCH | `/api/v1/hallazgos/{finding_id}` |
| POST | `/api/v1/hallazgos/{finding_id}/estado` |
| GET | `/api/v1/hallazgos/{finding_id}/evidencias` |
| POST | `/api/v1/hallazgos/{finding_id}/evidencias` |
| GET | `/api/v1/hallazgos/{finding_id}/historial` |
| GET | `/api/v1/aprobaciones` |
| POST | `/api/v1/aprobaciones` |
| GET | `/api/v1/aprobaciones/recursos` |
| GET | `/api/v1/aprobaciones/aprobadores` |
| GET | `/api/v1/aprobaciones/{round_id}` |
| POST | `/api/v1/aprobaciones/{round_id}/iniciar` |
| POST | `/api/v1/aprobaciones/{round_id}/cancelar` |
| POST | `/api/v1/aprobaciones/{round_id}/finalizar` |
| POST | `/api/v1/aprobaciones/{round_id}/decision` |
| GET | `/api/v1/aprobaciones/{round_id}/decisiones` |
| GET | `/api/v1/aprobaciones/{round_id}/historial` |
| GET | `/api/v1/dashboard/resumen` |
| GET | `/api/v1/dashboard/indicadores` |
| GET | `/api/v1/dashboard/alertas` |
| GET | `/api/v1/dashboard/actividad` |
| GET | `/api/v1/analisis/resumen` |
| GET | `/api/v1/analisis/anomalias` |
| GET | `/api/v1/analisis/documentos/{resource_id}` |
| GET | `/api/v1/analisis/versiones/{resource_id}` |
| POST | `/api/v1/auth/login` |
| GET | `/api/v1/auth/me` |
| POST | `/api/v1/auth/logout` |
| POST | `/api/v1/auth/access-requests` |
| POST | `/api/v1/auth/password-reset/request` |
| POST | `/api/v1/auth/password-reset/confirm` |
| POST | `/api/v1/auth/initial-password/confirm` |
| GET | `/api/v1/access-requests` |
| GET | `/api/v1/access-requests/{request_id}` |
| POST | `/api/v1/access-requests/{request_id}/approve` |
| POST | `/api/v1/access-requests/{request_id}/reject` |
| POST | `/api/v1/access-requests/{request_id}/resend` |
| GET | `/` |

Los cinco POST públicos de autenticación son login, access-requests, password-reset/request, password-reset/confirm e initial-password/confirm. Estado raíz es público. Las demás operaciones requieren autenticación y permisos/alcance propios.

## Modelos y tablas

| Tabla | Columnas | Referencias FK |
|---|---|---|
| usuarios | id, nombre, correo, correo_normalizado, password_hash, rol, activo, created_at, updated_at | Sin FK |
| areas | id, codigo, nombre, activa, created_at, updated_at | Sin FK |
| auditorias | id, codigo, nombre, alcance, estado, fecha_inicio_prevista, fecha_fin_prevista, iniciada_en, completada_en, responsable_id, created_by_id, updated_by_id, created_at, updated_at | usuarios.id, usuarios.id, usuarios.id |
| documentos | id, codigo, titulo, descripcion, tipo, estado, responsable_id, area_id, created_by_id, updated_by_id, version_vigente_id, created_at, updated_at | areas.id, usuarios.id, usuarios.id, usuarios.id, versiones_documento.id |
| versiones_documento | id, documento_id, numero_version, storage_key, nombre_original, mime_type, tamano_bytes, sha256, comentario_cambio, subido_por_id, created_at | documentos.id, usuarios.id |
| documentos_auditoria | id, auditoria_id, documento_id, version_documento_id, proposito, contexto, estado_revision, observaciones, asociado_por_id, created_at, updated_at | versiones_documento.id, usuarios.id, documentos.id, auditorias.id |
| evidencias | id, auditoria_id, tipo, titulo, descripcion, storage_key, nombre_original, mime_type, tamano_bytes, sha256, referencia_url, documento_id, version_documento_id, registrada_por_id, created_at, updated_at | documentos.id, usuarios.id, versiones_documento.id, auditorias.id |
| hallazgos | id, auditoria_id, numero, titulo, descripcion, categoria, severidad, estado, responsable_id, detectado_en, fecha_limite, resolucion, cerrado_por_id, cerrado_en, created_by_id, updated_by_id, created_at, updated_at | usuarios.id, usuarios.id, usuarios.id, auditorias.id, usuarios.id |
| hallazgos_evidencias | hallazgo_id, evidencia_id, vinculada_por_id, vinculada_en, contexto | evidencias.id, usuarios.id, hallazgos.id |
| rondas_aprobacion | id, version_documento_id, numero_ronda, estado, solicitada_por_id, solicitada_en, resuelta_en, created_at, updated_at | usuarios.id, versiones_documento.id |
| decisiones_aprobacion | id, ronda_aprobacion_id, aprobador_id, estado, comentario, asignada_en, decidida_en, created_at, updated_at | rondas_aprobacion.id, usuarios.id |
| eventos_auditoria | id, actor_id, actor_snapshot, accion, entidad_tipo, entidad_id, ocurrido_en, correlation_id, datos_anteriores, datos_nuevos | usuarios.id |
| auth_sessions | sid, usuario_id, created_at, expires_at, revoked_at | usuarios.id |
| auth_login_limits | identifier, request_window, request_count, failure_window, failure_count, expires_at | Sin FK |
| access_requests | id, identifier, nombre, motivo, status, created_at, resolved_at, resolved_by, approved_role, admin_reason, usuario_id | usuarios.id, usuarios.id |
| auth_action_limits | action, identifier, window_start, count, expires_at | Sin FK |
| auth_action_tokens | token_hash, purpose, mail_job_id, usuario_id, access_request_id, state_fingerprint, created_at, expires_at, consumed_at | usuarios.id, auth_mail_jobs.id, access_requests.id |
| auth_mail_jobs | id, kind, identifier, recipient, state_fingerprint, token_expires_at, usuario_id, access_request_id, status, attempts, lease, locked_until, available_at, created_at | usuarios.id, access_requests.id |

Además existe `alembic_version` como control de revisión. SQLAlchemy metadata contiene 18 tablas de aplicación.

## Estados y workflows

- Auditoría: PLANNED, IN_PROGRESS, IN_REVIEW, COMPLETED, CANCELLED. El router permite progreso/revisión/cierre y retorno revisión→progreso; no transición a CANCELLED.
- Documento: DRAFT, ACTIVE, OBSOLETE, ARCHIVED. Versiones numeradas y vigente, sin reescritura HTTP histórica.
- Revisión de vínculo documental: PENDING, REVIEWED, ACCEPTED, REJECTED; existe en DB, sin CRUD HTTP propio.
- Evidencia: FILE, REFERENCE, NOTE, OTHER. Hallazgo: OPEN, IN_PROGRESS, PENDING_VERIFICATION, CLOSED, ACCEPTED_RISK; severidad LOW/MEDIUM/HIGH/CRITICAL.
- Ronda: PENDING, IN_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED, CANCELLED. Decisión: PENDING, APPROVED, REJECTED, CHANGES_REQUESTED.
- Acceso: PENDING, APPROVED, REJECTED, FULFILLED. Correo: PENDING, PROCESSING, DONE, CANCELLED, FAILED.

## Migraciones

| Revisión | Archivo | Alcance |
|---|---|---|
| 001 | 001_initial_schema.py | Dominio documental |
| 002 | 002_auth_sessions.py | Sesiones revocables |
| 003 | 003_auth_hardening.py | Login limits/índices de sesiones |
| 004 | 004_account_access_recovery.py | Acceso, tokens y correo |
| 005 | 005_audit_review.py | Estado de auditoría IN_REVIEW |

## Componentes y scripts

### routers

`account_access.py`, `analisis.py`, `aprobaciones.py`, `auditorias.py`, `auth.py`, `catalogos.py`, `dashboard.py`, `documentos.py`, `evidencias.py`, `hallazgos.py`.

### schemas

`account_access.py`, `analisis.py`, `aprobacion.py`, `auditoria.py`, `auth.py`, `catalogo.py`, `dashboard.py`, `documento.py`, `evento.py`, `evidencia.py`, `hallazgo.py`.

### models

`account_access.py`, `auth.py`, `entities.py`.

### services

`account_actions.py`, `analisis_queries.py`, `analisis_rules.py`, `analisis_service.py`, `aprobacion_service.py`, `auditoria_service.py`, `authorization_service.py`, `auth_action_protection.py`, `auth_mail.py`, `auth_pruning.py`, `dashboard_queries.py`, `dashboard_service.py`, `database_admission.py`, `documento_service.py`, `evidencia_service.py`, `file_transaction.py`, `hallazgo_service.py`, `login_protection.py`, `request_body_limit.py`, `storage_integrity.py`, `storage_service.py`, `turnstile.py`.

Scripts operativos: `bootstrap_admin.py`, `gestionar_usuario.py`, `procesar_correo_auth.py`, `prune_auth_login_limits.py`, `prune_auth_sessions.py`, `verificar_integridad.py`.

Seed explícito: `api/app/scripts/seed_evaluation_demo.py`, con archivo privado externo. Generación opt-in: `evaluation_credentials.py`. Rotación transaccional separada: `rotate_evaluation_demo.py`. Ninguno llamado desde startup.

Frontend: 23 páginas PHP, includes/helpers, controladores/cliente API, CSS y JavaScript. Sin SQL directo, Composer ni Node.

## Pruebas

### api/tests_unit

17 módulos: `test_account_access_unit.py`, `test_analisis_unit.py`, `test_aprobacion_unit.py`, `test_auditoria_unit.py`, `test_auth_unit.py`, `test_bootstrap_admin.py`, `test_dashboard_unit.py`, `test_evaluation_demo_unit.py`, `test_file_consistency_unit.py`, `test_file_routes_unit.py`, `test_hallazgo_unit.py`, `test_integrity_cli_unit.py`, `test_login_protection_unit.py`, `test_mysql_guard_unit.py`, `test_phase8_unit.py`, `test_rbac_unit.py`, `test_turnstile_unit.py`.

### api/tests_auth_mysql

22 módulos: `test_6a_regression_mysql.py`, `test_account_access_mysql.py`, `test_analisis_e2e_mysql.py`, `test_analisis_mysql.py`, `test_aprobacion_e2e_mysql.py`, `test_aprobacion_mysql.py`, `test_auditoria_mysql.py`, `test_auth_hardening_mysql.py`, `test_auth_mail_mysql.py`, `test_auth_mysql.py`, `test_bootstrap_admin_mysql.py`, `test_dashboard_e2e_mysql.py`, `test_dashboard_mysql.py`, `test_evaluation_demo_mysql.py`, `test_evaluation_rotation_mysql.py`, `test_hallazgo_mysql.py`, `test_phase8_e2e_mysql.py`, `test_phase8_system_mysql.py`, `test_php_account_access_mysql.py`, `test_php_auth_mysql.py`, `test_rbac_mysql.py`, `test_turnstile_mysql.py`.

### frontend/tests

17 módulos: `test_account_access.py`, `test_analisis.py`, `test_analisis_browser.py`, `test_aprobaciones.py`, `test_aprobaciones_browser.py`, `test_auditorias.py`, `test_auditorias_browser.py`, `test_auth_browser.py`, `test_auth_hardening.py`, `test_auth_rbac.py`, `test_dashboard.py`, `test_dashboard_browser.py`, `test_downloads.py`, `test_hallazgos.py`, `test_hallazgos_browser.py`, `test_turnstile.py`, `test_turnstile_browser.py`.

### api/tests

2 módulos: `test_file_consistency.py`, `test_storage_and_traceability.py`.

`api/tests` es histórica; ejecución protegida de 6A mediante wrapper MySQL. La cantidad de archivos no equivale a contratos distintos o cobertura porcentual.

## Configuración, storage, seguridad y documentación

[Variables completas](CONFIGURACION.md), [permisos](MATRIZ_PERMISOS.md), [seguridad/diseño](DOCUMENTO_TECNICO.md), [SMTP](SMTP_RECUPERACION.md). Storage fijo privado con SHA-256; sesiones PHP en temporal privado; JWT en servidor; DB UTC/InnoDB; rate limiting, body/upload limits, CSRF y Turnstile opcional.

Documentación previa conservada: `historico/FASE_6B_2_RBAC.md`, `historico/FASE_6B_3_PHP_AUTH_RBAC.md`, `historico/FASE_6B_4A_AUTH_HARDENING.md`, `historico/FASE_6B_4B_TURNSTILE.md`, `historico/FASE_6C_ACCESO_RECUPERACION.md`, `historico/FASE_6D_1_BOOTSTRAP_ADMIN.md`, `historico/FASE_7A_AUDITORIAS.md`, `historico/FASE_7B_HALLAZGOS_EVIDENCIAS.md`, `historico/FASE_7C_APROBACIONES.md`, `historico/FASE_7D_DASHBOARD_ALERTAS_INDICADORES.md`, `historico/FASE_7E_ANALISIS_INTELIGENTE.md`, `historico/FASE_8_QA_SEGURIDAD_RENDIMIENTO.md`.

Estado local tras la limpieza y el ajuste de acceso autorizados de Fase 9.1: cinco usuarios, cuatro activos demo y un histórico desactivado; tres auditorías, cinco documentos, tres versiones, catorce eventos y tres archivos. La cuenta personal sin historial sigue retirada y el actor histórico conserva su ID y relaciones con identidad anónima. Las cuatro cuentas y el dataset sintético se añadieron a sistema_trazabilidad mediante el seed opt-in existente, por autorización expresa del alumno; todos los registros y archivos preexistentes permanecen intactos. El [informe de privacidad y acceso local](historico/FASE_9_1_PRESENTACION_PRIVACIDAD.md) registra las altas exactas, la idempotencia y la validación de ADMIN/RESPONSABLE_AREA. Una instalación nueva sigue usando el mismo seed reproducible.

Actualización Fase 9.2: seed exige contrato privado externo; generación y rotación son CLIs separadas. IDs demo 3–6 e histórico ID 1 se preservan. [Validación vigente](historico/FASE_9_2_CREDENCIALES_PRIVADAS.md).
