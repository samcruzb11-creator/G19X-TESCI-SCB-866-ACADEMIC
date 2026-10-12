# MVP — Sistema de Trazabilidad Documental para Auditorías

## Problema y entrega mínima

El expediente de una auditoría necesita relacionar documentos, versiones, responsables, evidencias y decisiones. El MVP entrega una aplicación local funcional que permite reconstruir esas relaciones y consultar su seguimiento con permisos por rol.

Proyecto de residencia de Samuel Cruz Barrientos, Ingeniería en Sistemas, TESCI / TecNM, con PluriOne S.A. de C.V. / Develop Talent & Technology, septiembre de 2026 a enero de 2027.

## Funcionalidades incluidas

- Login, JWT y sesiones revocables; control de rol y alcance en FastAPI.
- Solicitud de acceso revisada por ADMIN y recuperación single-use mediante SMTP configurable/worker.
- Auditorías con responsable elegible, estados y bitácora.
- Documentos, cargas de versiones, vigente, SHA-256 y descargas autorizadas.
- Evidencias, hallazgos con severidad/estados y vínculos coherentes.
- Rondas por versión concreta y decisiones de APROBADOR asignado.
- Dashboard, indicadores, alertas derivadas y actividad autorizada.
- Motor determinista explicable de anomalías: hashes, metadatos/versiones y similitud heurística de nombres; sin análisis semántico general, Ollama, IA generativa, ML/LLM ni modelos entrenados.
- Seed explícito idempotente y documentación para evaluación en otra computadora.

## Actores y flujo principal

ADMIN gestiona operaciones y visibilidad global sin reescribir trazabilidad. AUDITOR_INTERNO gestiona hallazgos/rondas dentro de sus auditorías; AUDITOR_EXTERNO consulta/aporta evidencia en su alcance. RESPONSABLE_AREA trabaja con documentos propios. APROBADOR decide sobre versiones asignadas.

```text
Login -> dashboard -> auditoría -> documento/versiones -> hallazgo/evidencia
      -> aprobación de versión -> indicadores/análisis -> logout
```

La demo incluye vínculos documentales provisionados. RESPONSABLE_AREA recorre sólo sus documentos, rondas, dashboard y análisis; no tiene acceso a auditorías ni hallazgos.

## Diseño y seguridad

PHP/HTML/CSS/JavaScript presenta la interfaz; FastAPI Python 3.14 implementa reglas; SQLAlchemy/PyMySQL accede a MySQL 8; Alembic define estructura hasta 005. Archivos privados locales con hash SHA-256. Argon2id, JWT de 15 minutos y sesión MySQL, CSRF PHP, RBAC/IDOR server-side, límites de login/carga/body, actor autenticado y Turnstile opcional. Eventos y versiones no tienen endpoints de reescritura; decisiones terminales no se modifican por API.

## Criterios de aceptación

Instalación nueva sin dump personal; Alembic 005; seed repetible sin duplicar ni sobrescribir cuentas; login ADMIN y RESPONSABLE_AREA; consulta de recursos y descarga; intento administrativo/IDOR rechazado; logout revocado. Pruebas de token expirado/alterado/replay/concurrente; exports válidos y documentación consistente. La validación actual se registra en [Fase 9](docs/FASE_9_CIERRE_ENTREGA.md).

## Estado y límites

MVP implementado para evaluación local. Baseline Fase 8: `d54a81e`; la auditoría final de Fase 9.2 aprobó la release según el dictamen comunicado. El backend de recuperación, tokens/controles, cola, worker y configuración SMTP están implementados, pero el envío real está `SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS` y no está disponible en la demo. Las cuentas ficticias no reciben correo. No hay hosting productivo, CRUD web general de usuarios/áreas, asociación documento–auditoría por HTTP, backup automático ni modelo local de IA. 7E informa límites/truncación; no garantiza detectar cualquier irregularidad ni todos los documentos faltantes y no certifica cumplimiento. Se conserva deuda de reconciliación DB/filesystem frente a interrupción abrupta.

## Ejecutar y demostrar

Siga [README](README.md) o [Guía de instalación](docs/GUIA_INSTALACION.md): clone → venv → requirements → `.env` → MySQL → Alembic → seed con archivo privado → FastAPI → PHP → login. Frontend: http://127.0.0.1:8080. Compare las vistas ADMIN y RESPONSABLE_AREA usando el archivo recibido por TODO Academy; [Accesos de prueba](docs/ACCESOS_PRUEBA.md) explica el procedimiento público. El seed no se ejecuta automáticamente en startup. Credenciales exclusivamente locales, nunca producción.

Este archivo corresponde al tipo **MVP** en TODO Academy; el PRD define los requisitos completos en [docs/PRD.md](docs/PRD.md).

Evaluación Fase 9.2: las cuatro cuentas se provisionan con `--credentials-file` a partir de `01_ACCESOS_PRUEBA.md`, entregado por separado en TODO Academy y conservado fuera del repositorio. README público no contiene identidades ni contraseñas concretas.
