# Bitácora de desarrollo y entrega

Proyecto: Sistema de Trazabilidad Documental para Auditorías. Alumno: Samuel Cruz Barrientos. Ingeniería en Sistemas, TESCI / TecNM. Empresa: PluriOne S.A. de C.V. / Develop Talent & Technology. Periodo de residencia: septiembre de 2026 a enero de 2027.

## Fuentes y alcance temporal

Reconstrucción a partir de Git y reportes de fases conservados, consultados durante el cierre del 8–9 de octubre de 2026. Se describen resultados de hitos, no horas de trabajo ni reuniones no documentadas. La fecha de commit acredita el registro técnico del hito; no certifica la duración de cada actividad.

## Evolución interpretada

| Fecha registrada | Hito y referencia | Resultado verificable |
|---|---|---|
| 23 sep 2026 | Inicio/análisis técnico y fundamentos: fe2ca65, 0161069 | Repositorio inicial y preparación backend; punto de partida para el modelo documental |
| 24 sep 2026 | Arquitectura de entidades: 7e3a349 | Modelos para relacionar documentos, versiones y auditorías |
| 25 sep 2026 | Persistencia: 3883b3c | Esquema MySQL 8, sincronización UTC y servicios iniciales de almacenamiento |
| 26 sep 2026 | Trazabilidad API: 90c3703 | Avance de operaciones documentales y relaciones de expediente |
| 28 sep 2026 | Estabilización/API y frontend: 767d3a4, bfa08dd, 8ee1096, e3be0b2 | Dashboard inicial PHP, ficha documental y formularios de alta; avances de auditoría/evidencia |
| 29 sep 2026 | Flujos de auditoría/evidencia: dd29441 | Cierre del conjunto inicial de workflows |
| 30 sep 2026 | Consistencia DB/storage: b11e66c | Compensación de archivos y coherencia transaccional; deuda de interrupción abrupta explícita |
| 30 sep 2026 | Frontend Fase 5: 9422649 | Navegación, filtros y formularios PHP completados para alcance de esa fase |
| 30 sep 2026 | Autenticación 6B.1: 4cea1b2, 914f185 | Argon2/JWT, sesiones y validación de secretos; CLI de contraseña con errores seguros |
| 1 oct 2026 | RBAC 6B.2: 8b55598 | Permisos por rol y recurso en backend, con scopes SQL |
| 1 oct 2026 | Integración PHP auth 6B.3: 63fd376 | Sesión server-side, navegación por rol y controles CSRF |
| 1 oct 2026 | Protección local 6B.4A: 66812c9 | Límites/presupuestos de login y trabajo Argon2 acotado |
| 2 oct 2026 | Acceso/recuperación 6C: 279e99e | Revisión ADMIN, tokens single-use, expiración, cola y worker SMTP genérico; envío real no acreditado |
| 5 oct 2026 | Turnstile 6B.4B: a1095d4 | Segunda capa adaptativa configurable, con hostnames y validación server-side |
| 6 oct 2026 | Bootstrap ADMIN: 50d9e84 | Provisionamiento explícito local del primer ADMIN, sin auto-creación al iniciar |
| 6 oct 2026 | Auditorías 7A: 3684e95 | Ciclo de vida, edición ADMIN, precondiciones y eventos; revisión 005 |
| 6 oct 2026 | Hallazgos/evidencias 7B: 30b3ff4 | Severidad, responsables, resolución, transiciones y relaciones consistentes |
| 6 oct 2026 | Aprobaciones 7C: c002df8 | Rondas de versión exacta, asignados, decisiones propias y resultados terminales |
| 7 oct 2026 | Dashboard 7D: dc32f6e | Indicadores/alertas/actividad calculados tras autorización SQL |
| 7 oct 2026 | Análisis 7E: eec566d | Motor determinista de anomalías, explicaciones, duplicados visibles y comprobaciones locales acotadas |
| 8 oct 2026 | Hardening 8: d54a81e | Correcciones reproducidas de seguridad/concurrencia/rendimiento y regresión integral |
| 8–9 oct 2026 | Cierre/entrega 9, working tree pendiente de auditoría | Seed demo opt-in, instalación fresca, documentación, capturas, exports y hashes; sin commit/push |

## Resultados de QA registrados

Fase 8 concluyó con 1,212 unit, 1,138 MySQL y 312 frontend verdes, cero fallos/skips finales. Son 2,662 ejecuciones que incluyen contratos importados/repetidos; el informe distingue 1,937 contratos únicos. El benchmark local incluyó perfiles hasta 250 concurrentes y documenta límites del análisis pesado y de los presupuestos de login.

Fase 9 añade tres unit de CLI y siete pruebas MySQL parametrizadas/de comportamiento de seed/RBAC; el detalle actual se encuentra en [Informe de cierre](historico/FASE_9_CIERRE_ENTREGA.md). La validación fresca incluye API/PHP reales y capturas demo. No se utiliza este registro para inventar cobertura porcentual ni rendimiento universal.

## Decisiones de cierre

Conservar roles y seguridad aprobada; diferenciar diseño técnico de operación; separar PRD de MVP; preservar docs de fases; usar Markdown como fuente; guardar binarios finales en Descargas. No hay modelo local de IA implementado; la futura ampliación se condiciona a un requerimiento explícito. SMTP real queda pendiente de credenciales externas, sin bloquear documentación o demo documental.

Durante Fase 9 se conservaron BD, sesiones y storage reales; la limpieza de identidad quedó pendiente. En Fase 9.1, el 12 de octubre de 2026, se retiró una cuenta sin historial y sus datos efímeros, y se anonimizó/desactivó el mismo actor legacy preservando ID y relaciones. Documentos, versiones, auditorías y archivos reales permanecen intactos; el tratamiento se registra en el informe de privacidad. El material externo de seguridad/video no se recibió ni se inventan conclusiones: «Checklist externo de seguridad pendiente de revisión posterior si el alumno proporciona material adicional».
