# Fase 9 — Cierre, documentación, reproducibilidad y entrega

Nota de distribución Fase 9.2: este informe conserva resultados históricos. Los identificadores y contraseñas concretos se retiraron; los comandos de instalación mostrados usan ahora el archivo privado externo. El estado vigente se registra en [Fase 9.2](FASE_9_2_CREDENCIALES_PRIVADAS.md).

Ejecución: 8–9 de octubre de 2026. Alcance: release local y entrega académica; sin funcionalidades arbitrarias ni modelo de IA.

## 1. Baseline obligatorio

Preflight previo a cambios: branch main; HEAD y origin/main `d54a81e2a38b3ae8c57dfe43a3d7f1665bae421e`; mensaje `fix(hardening): complete phase 8 QA security and performance`; working tree limpio; diff check sin errores. No se ejecutan git add/commit/push/reset/rebase ni cambios de historial.

## 2. Fuentes de verdad e inventario

Diez routers, 61 operaciones HTTP en 52 rutas distintas incluyendo raíz, 18 tablas de aplicación y control Alembic, revisiones 001–005, cinco roles canónicos, 23 páginas y 66 PHP. Código, OpenAPI, metadata y reportes de fases determinaron la documentación. [Inventario completo](INVENTARIO_IMPLEMENTACION.md), [configuración](CONFIGURACION.md) y [matriz](MATRIZ_PERMISOS.md) conservan los detalles.

7E es determinista/explicable: no hay modelo entrenado, LLM/ML ni IA local implementada. El frontend es PHP/HTML/CSS/JavaScript; la persistencia actual es MySQL 8 con almacenamiento local. No se añaden servicios cloud descartados.

## 3. Archivos creados/modificados

Fuentes nuevas: README y MVP raíz; docs/README, ACCESOS_PRUEBA, PRD, DOCUMENTO_TECNICO, MANUAL_TECNICO, GUIA_INSTALACION, MANUAL_USUARIO, BITACORA, EVIDENCIA_PROYECTO, CONFIGURACION, MATRIZ_PERMISOS, INVENTARIO_IMPLEMENTACION, SMTP_RECUPERACION, INDICE_ENTREGABLES y este informe. Capturas sintéticas nuevas en docs/capturas.

Código nuevo: `api/app/scripts/__init__.py`, `seed_evaluation_demo.py`; tests `test_evaluation_demo_unit.py` y `test_evaluation_demo_mysql.py`. Reproducibilidad: requirements-dev y requirements-lock. Modificados: api/.env.example (comentarios coherentes, debug false, URL loopback y umbral análisis), api/README y frontend/README para eliminar instrucciones obsoletas. No se cambian routers, algoritmos, permisos ni migraciones del runtime aprobado.

## 4. Seed y credenciales demo

CLI desde api: `python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"`. Sin confirmación sólo muestra plan. Exige development, DB loopback/MySQL 8 y revisión 005, serializa mediante named lock y nunca actualiza registros existentes. Un conflicto de nombre/rol/correo/activo/password aborta con rollback. Repetición conserva filas y bytes; no hay auto-seed en startup.

Cuatro cuentas sintéticas ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO y APROBADOR. La política original de credenciales públicas fue sustituida en Fase 9.2: las cuatro credenciales se entregan exclusivamente mediante el archivo privado externo de TODO Academy. README/ACCESOS contienen únicamente el procedimiento público. Área Demo y dataset opcional: dos auditorías, dos documentos, un archivo TXT/versión, una NOTE, un hallazgo, una ronda y una decisión pendiente, más vínculos/eventos identificables. IDs/timestamps son locales, contenidos y relaciones deterministas. Los vínculos de documento–auditoría se provisionan porque no existe comando HTTP actual de asociación.

El seed **no se ejecuta sobre sistema_trazabilidad** ni sobre usuarios personales. No se cambian passwords/roles/emails/actividad/sesiones de usuarios reales. Los recursos demo se crean sólo en schemas efímeros de validación.

## 5. RBAC y autoridad ADMIN

Login HTTP valida ADMIN y RESPONSABLE_AREA; comparación de documentos globales (dos) vs propios (uno). El restringido recibe 403 en usuarios/access-requests/auditorías/hallazgos y 404 para documento ajeno; payload de rol/user ID/hash/owner y acción administrativa falla. Actor de upload se obtiene del usuario autenticado aunque se envíe ID legacy distinto. La ruta manual PHP de auditorías responde 403.

ADMIN consulta globalmente, gestiona auditorías y solicitudes conforme diseño; no hay CRUD web general de usuarios. Gestiona ronda, pero sólo APROBADOR activo asignado decide; replay y ADMIN no cambian decisión cerrada. No existen endpoints de reescritura/borrado de eventos/hashes/versiones. La integridad descrita es de aplicación, no garantía contra privilegios externos SQL/filesystem.

## 6. Fresh clone y autoauditoría

Clone remoto completamente nuevo fuera del working tree, baseline d54a81e. Dado que el commit está prohibido, se superponen exclusivamente los archivos de release pendientes con igualdad de bytes/SHA-256; no se finge que ya estén en GitHub. No se reutiliza venv, dotenv, cache, storage ni schema operativo. La conexión administrativa local se usa únicamente para provisionar schema/cuenta nueva; el `.env` de ejecución se crea desde ejemplo con password/JWT aleatorios nuevos y privilegios del schema temporal.

Python 3.14.7; MySQL 8.0.46; PHP 8.2.12; Chrome aislado real. Instalación desde requirements sin cache produjo FastAPI 0.143.0, Uvicorn 0.54.0, SQLAlchemy 2.1.4 y demás versiones registradas en requirements-lock. El runtime operativo anterior no se actualiza.

Pruebas frescas: pip check; Alembic upgrade head/current 005; seed plan y dos ejecuciones (cuatro nuevos, después cero); backend 8000 y frontend 8080; login/me; auditorías/documentos/versiones/descarga/hallazgos/dashboard/análisis/aprobaciones; scope e intentos administrativos; recorrido PHP ADMIN/restringido; logout/revocación; ronda iniciada ADMIN y decisión APROBADOR, replay rechazado. Resultado PASS. Los comandos provienen del README/Guía; el harness automatiza creación de schema/secretos que el operador debe completar, sin editar código ni filas para levantar el proyecto.

Se conservaron 11 capturas del estado inicial demo antes de resolver la ronda. Las fuentes finales se sincronizan con el clone y el manifiesto de overlay se revisa antes de cerrar. Los procesos de prueba se detienen y los schemas/usuarios temporales propios se retiran al terminar; no son un servicio permanente para el evaluador.

## 7. SMTP y recuperación

Inspección local sólo de presencia, sin imprimir valores: host/usuario/password/remitente ausentes. Estado **SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS**. SMTP genérico TLS, nombres reales de settings, cola/worker ya existen y se conservan. Tests verifican expiración, single-use, anti-enumeración, tokens alterados/replay, doble petición/consumo y solicitud→revisión→contraseña inicial. No hubo correo real; no se inventan cuentas ni credenciales externas.

[Procedimiento exacto posterior](SMTP_RECUPERACION.md): SMTP privado/buzón autorizado, solicitud aprobada para identidad sintética, worker, contraseña inicial, reset, llegada, cambio, replay y nuevo login. La contraseña demo `.local` no concede acceso a un buzón real.

## 8. Pruebas finales

| Suite | Resultado final | Alcance |
|---|---|---|
| api/tests_unit | 1215 passed; 0 failed/skipped; 2 warnings | Completa, incluye 3 CLI demo nuevas |
| MySQL relevante | 164 passed; 0 failed/skipped; 2 warnings | Demo, account access/mail, RBAC, PHP acceso y E2E sistémico Fase 8 |
| frontend/tests | 312 passed; 0 failed/skipped | Completa, Chrome opt-in real |
| Fresh clone | PASS | HTTP backend/PHP reales, migración/seed/storage y navegador |

Además se repitió la suite unitaria completa dentro del venv fresco fijado por
requirements-lock: **1215 passed**, cero fallos/skips y un warning Starlette/httpx,
en 86.42 s. El comando de instalación runtime con constraints y la instalación de
requirements-dev también se verificaron en ese venv; no se usan paquetes del
venv operativo para ejecutar la aplicación fresca.

MySQL relevante comprende test_evaluation_demo_mysql, test_account_access_mysql, test_auth_mail_mysql, test_rbac_mysql, test_php_account_access_mysql y test_phase8_e2e_mysql. Todos usan schemas aleatorios guardados. Backend registra deprecaciones conocidas Starlette/httpx y BlockingPortal. Se separan estos conteos de los 2,662 históricos Fase 8; no se suman como contratos únicos. No se repite benchmark 250 al no cambiar runtime crítico.

Los fallos iniciales fueron del entorno de validación: Chrome bajo sandbox, permisos de basetemp entre identidades y ruta temporal demasiado larga para la precondición del test UTF-16. Se resolvieron con ejecución autorizada/perfiles nuevos/ruta corta, sin cambiar código ni debilitar tests. Un primer harness fresh omitió crear el directorio de Chrome; se corrigió y el recorrido completo pasó.

## 9. Documentación, exports e integridad

Markdown UTF-8 como fuente; PDF/DOCX generados en venv documental temporal, sin contaminar requirements runtime. Cada export tiene portada académica, márgenes, títulos, numeración y tablas/figuras legibles. PDF debe tener páginas/texto/título, ninguna página vacía inesperada; DOCX ZIP/OpenXML válido, párrafos/headings/tablas e imágenes según fuente. Capturas nuevas en Evidencia/Manual usuario; diagramas técnicos incluyen alternativa textual portable.

Entregables en `C:\Users\samcr\Downloads\SistemaTrazabilidad_Entregables`, sólo archivos propios; no ZIP de código ni binarios PDF/DOCX en Git. Índice 00 con mapeo exacto TODO Academy; SHA256SUMS para cada archivo final salvo sí mismo. La evidencia de validación estructural y hashes se refleja en el cierre de este informe.

## 10. Secret scan y preservación

Scan de fuentes nuevas/modificadas, árbol publicable completo, diff, staging vacío, cinco commits recientes y entregables extraídos de PDF/DOCX. Busca secretos privados reales sin imprimirlos y formatos de tokens/llaves. En este checkpoint histórico se permitían contraseñas DEMO; Fase 9.2 las retiró y rotó. Sólo fixtures sintéticos efímeros y placeholders permanecen permitidos en el código público. `.env`, storage y PDFs reales siguen ignorados y no se exportan. Las capturas sólo contienen datos sintéticos; no hay JWT ni secretos.

Fingerprints read-only de todas las filas/DDL reales, storage y `.env` se comparan sin publicar hashes de usuarios/PDFs. Conteos reales preservados: dos usuarios, una auditoría, tres documentos, dos versiones, seis eventos, cinco sesiones y dos archivos. No se usa «BD idéntica» para schemas demo: allí los cambios son deliberados y están enumerados. Los datos legacy se conservan, no se reclasifican automáticamente como demo ni se eliminan.

## 11. Checklist explícito de dudas

- [x] Q1 — Accesos de prueba: ADMIN + RESPONSABLE_AREA creados reproduciblemente en instalación aislada.
- [x] Q2 — Permisos ADMIN: autoridad operativa global comprobada sin reescribir registros inmutables.
- [x] Q3 — Usuario normal: limitado server-side y escalación rechazada.
- [x] Q4 — Recuperación: flujo seguro existente, contratos negativos/concurrentes probados.
- [x] Q5 — Correo: SMTP configurable, envío real pendiente de credenciales externas.
- [x] Q6 — README: recorrido de otra instalación validado con clone fresco y overlay pendiente.
- [x] Q7 — MVP Markdown: creado para tipo MVP de TODO Academy.
- [x] Q8 — Archivos técnicos: fuentes y versiones finales de entrega.
- [x] Q9 — Descargas: carpeta específica con índice y hashes, sin tocar archivos ajenos.
- [x] Q10 — IA local: no implementada ni falsamente afirmada; ampliación separada condicionada.

## 12. Pendientes y límites

SMTP real es el único pendiente externo permitido del cierre: faltan credenciales y buzón autorizados; impacta llegada real/flujo Internet, no demo documental ni contratos automatizados. Publicar Git y subir TODO Academy quedan después de auditoría, conforme prohibición de commit/push de esta fase. No se afirma que GitHub ya incluya Fase 9.

Se conserva deuda aceptada: huérfanos por caída DB/filesystem, candidatos/storage acotados 7E, deprecaciones menores y análisis global costoso bajo concurrencia extrema. No se implementa modelo IA local ni se descargan modelos. «Checklist externo de seguridad pendiente de revisión posterior si el alumno proporciona material adicional». No existe video/revisión externa recibida que permita otras conclusiones.

## 13. Cierre de validación

Resultado final: PASS de instalación/seed/RBAC/recorrido y suites afectadas.
Siete PDF válidos y seis DOCX válidos; enlaces locales sin faltantes, Markdown
UTF-8 sin BOM/mojibake/fences abiertos. Todos los PDFs tienen texto extraíble,
título y páginas no vacías; se renderizaron todas sus páginas, se comprobaron
límites de cajas de texto y se revisó visualmente composición. Los DOCX son ZIP
OpenXML correctos con párrafos/encabezados y tablas/imágenes donde las fuentes
las incluyen; Manual usuario contiene ocho imágenes.

| PDF | Páginas finales |
|---|---|
| 02_BITACORA | 3 |
| 03_DOCUMENTO_TECNICO | 6 |
| 04_EVIDENCIA_PROYECTO | 13 |
| 05_GUIA_INSTALACION | 6 |
| 06_MANUAL_USUARIO | 10 |
| 07_MANUAL_TECNICO | 6 |
| 09_PRD | 6 |

La carpeta específica contiene 67 archivos propios de entrega/copias auxiliares
más SHA256SUMS. Se verifican los 67 hashes; el manifiesto excluye su propio hash.
Las fuentes auxiliares conservan jerarquía para que los enlaces resuelvan; no se
copia venv, storage privado ni dump. Scan de secretos operativos exactos y
formatos de llaves/tokens limpio, con revisión de demo/placeholders y fixtures;
staging vacío. No se afirma que este scan cubra todo el historial remoto o un
pentest externo.

Fingerprints agregados de preservación, iguales antes/después:

| Recurso | SHA-256 del manifiesto agregado |
|---|---|
| Filas/DDL de BD real | 9b35b1292dee52b567087cf3ef78a69de3f86b876700b5d55e74668500716b09 |
| Storage real | be67d1f8021eb8e6549b6df690acf8508c431726307d51face1389f409f41368 |

El fingerprint privado de `.env` también coincide; no se exportan sus valores.
Se eliminaron únicamente los dos schemas/cuentas temporales creados por el
harness fresh, comprobando nombres guardados y usuarios sintéticos antes de
DROP; el `.env` generado del clone también se retiró. Los fixtures MySQL
retiraron sus propios schemas. El validador documental temporal se elimina
después de su última ejecución; sus resultados quedan resumidos aquí.

Revisión completa del diff tracked y fuentes nuevas, AST de Python, enlaces,
capturas y documentos sin defectos pendientes. Son **37 archivos de Fase 9**:
3 modificados y 34 nuevos, sin PDF/DOCX/ZIP o `.env` operativo en el conjunto
publicable. `git diff --check` sin errores; branch/HEAD/origin conservados;
working tree dirty deliberado, staging vacío. Ningún commit ni push.

El único pendiente externo es SMTP real con credenciales/buzón autorizados.
La siguiente acción de release es auditoría independiente, no publicación
automática del código ni carga a TODO Academy desde esta sesión.
