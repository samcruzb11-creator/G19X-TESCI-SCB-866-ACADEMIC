# Fase 9.2 — Credenciales privadas, reproducibilidad y cierre de release

Fecha: 12 de octubre de 2026. Proyecto: Sistema de Trazabilidad Documental para Auditorías. Esta fase separa los accesos de evaluación del código público y rota las cuatro cuentas demo locales cuyos accesos anteriores estuvieron documentados. No publica secretos, no modifica funcionalidades de negocio y no crea cuentas personales.

## Baseline y alcance

Preflight: branch `main`, HEAD y origin/main `d54a81e2a38b3ae8c57dfe43a3d7f1665bae421e`, staging vacío. Los cambios existentes corresponden a Fases 9/9.1, incluidos documentación, seed, tests, branding Develop y capturas. Se guardaron manifiestos privados de las fuentes y los entregables antes de editar. No se encontraron cambios desconocidos.

No se ejecutaron git add, commit, push, reset o rebase. No se borraron bases de datos, documentos o expedientes. Los procesos temporales propios de API/PHP/Chrome se detuvieron; los schemas de pruebas se conservaron expresamente. Routers, servicios, core, modelos, migraciones, RBAC, dashboard, 7E y todos los archivos frontend conservaron su fingerprint respecto del preflight 9.2.

## Política de distribución y contrato

GitHub contiene código y documentación pública. El único documento de entrega con las cuatro credenciales concretas es `01_ACCESOS_PRUEBA.md` en `SistemaTrazabilidad_Entregables` de Downloads, fuera del repositorio. Se comparte exclusivamente con Edgar por Accesos de prueba de TODO Academy, sin enlace público ni copia a PDF/DOCX. El documento anterior se archivó como evidencia privada fuera del repositorio y de la carpeta de entrega; sus accesos quedaron invalidados.

Formato: Markdown UTF-8, bloque único `evaluation-credentials-v1`, objeto JSON versión 1 con cuatro objetos role/email/password. Roles exactos: ADMIN, RESPONSABLE_AREA, AUDITOR_INTERNO, APROBADOR. Identidades ficticias generadas en un dominio reservado sin buzón; cada contraseña procede de 32 bytes criptográficos mediante `secrets.token_urlsafe`, es diferente y no reutiliza ningún password anterior. [Contrato completo](CREDENCIALES_EVALUACION.md).

Generación opt-in, creación exclusiva, ruta externa, ACL Windows restringida al SID del operador antes de escribir secretos. No hay impresión de accesos, correo saliente, servicios externos, sobrescritura automática ni altas en startup. Si falta el archivo o falla su contrato, el seed falla seguro; no inventa credenciales distintas. `.gitignore` añade únicamente reglas específicas para documentos privados, sin ocultar código necesario.

Durante la lectura inicial de inventario se mostró accidentalmente el contenido legacy del seed en la salida de herramienta. Después se filtraron las lecturas, se retiraron esos valores del material público y se rotaron todas las contraseñas afectadas. Ningún acceso nuevo se mostró en consola o informes.

## CLI definitiva

Desde `api`, con venv activado, `.env` privado development, MySQL 8 loopback y Alembic 005:

```bat
python -m app.scripts.seed_evaluation_demo --with-dataset
python -m app.scripts.seed_evaluation_demo --confirm-local-demo --with-dataset --credentials-file "%USERPROFILE%\Downloads\SistemaTrazabilidad_Entregables\01_ACCESOS_PRUEBA.md"
```

El primer comando sólo muestra plan. Repetir la ejecución confirmada devuelve cero cuentas nuevas y conserva IDs, hashes, eventos y archivos. Se mantiene named lock, control de colisiones, transacción, guardas de entorno/servidor/migración y dataset opt-in. No existe fallback hardcodeado.

La generación se ejecuta mediante `python -m app.scripts.evaluation_credentials --confirm-generate --output "RUTA_EXTERNA_INEXISTENTE"`. El evaluador que recibió el documento no ejecuta el generador.

Rotación separada: `python -m app.scripts.rotate_evaluation_demo --credentials-file "RUTA_EXTERNA_NUEVA" --previous-credentials-file "RUTA_EXTERNA_ANTERIOR" --demo-user-ids "3,4,5,6"` prepara un plan sin mutaciones. Aplicar requiere además `--expected-fingerprint "FINGERPRINT_DEL_PLAN" --confirm-rotate-demo`. Verifica identidad/nombre/rol/password anterior y referencias del dataset a los cuatro actores; rechaza IDs históricos, colisiones, contraseñas reutilizadas y fingerprint cambiado. Comparación completa de tablas, actores ajenos y conteos de todas las FK antes del commit. No es parte del arranque ni de una instalación limpia.

## Rotación local y preservación

Servidor local MySQL 8.0.46, schema `sistema_trazabilidad`, development, Alembic 005. Snapshot privado completo de filas y fingerprints antes de la operación, con revisión de relaciones y storage. El ID 1 estaba inactivo; el ID 2 ausente.

| Actor | ID preservado | Resultado |
|---|---:|---|
| ADMIN demo | 3 | Identificador privado nuevo y hash Argon2id nuevo |
| RESPONSABLE_AREA demo | 4 | Identificador privado nuevo y hash Argon2id nuevo |
| AUDITOR_INTERNO demo | 5 | Identificador privado nuevo y hash Argon2id nuevo |
| APROBADOR demo | 6 | Identificador privado nuevo y hash Argon2id nuevo |

Cuatro hashes cambiados, cuatro contraseñas nuevas válidas y cuatro anteriores rechazadas tanto criptográficamente como por HTTP. Se conservaron nombres, roles, actividad, created_at, IDs y referencias. Los identificadores concretos nuevos se registran únicamente en el documento privado de TODO Academy.

Al rotar no había sesiones demo activas: cero revocaciones nuevas y cero tokens de acción pendientes. Las ocho sesiones demo anteriores ya estaban revocadas y permanecieron así. La prueba MySQL aislada abrió cuatro sesiones activas antes de rotar y confirmó después cuatro respuestas 401 con esos tokens. El smoke local creó ocho sesiones nuevas y las revocó al salir; las dieciséis sesiones demo locales finales están revocadas. Ninguna sesión ajena se modificó.

Se conservaron cinco usuarios (cuatro demo activos y un histórico inactivo), tres auditorías, cinco documentos, tres versiones, catorce eventos y tres archivos en storage. Usuario histórico ID 1 idéntico en todas sus columnas; ID 2 ausente; cuenta personal retirada no recreada. Todos los eventos, incluyendo actor_snapshot, permanecieron idénticos: no se reasignaron actores ni se falsificó historial. Sin pérdida de archivos ni modificación/exposición de `.env`. Sólo cambiaron correo/correo normalizado/password_hash/updated_at demo durante la rotación; las pruebas HTTP posteriores cambiaron exclusivamente sesiones y límites de login demo.

## Fresh clone y simulación de Edgar

Clone remoto nuevo de baseline d54a81e en Temp, venv nuevo, instalación sin caché desde requirements/constraints, pip check correcto. Schema y usuario MySQL 8 aislados nuevos con permisos limitados a ese schema; `.env` propio desde ejemplo con password DB/JWT nuevos; storage nuevo junto al clone; Alembic upgrade/current 005. No se reutilizaron venv, dump, storage, usuarios ni secretos de ejecución personales.

Como commit/push están prohibidos, el remoto conserva el baseline. Se aplicó una copia de los archivos públicos pendientes con igualdad de bytes/SHA-256 y manifiesto de overlay; no se afirma que GitHub ya publique la release. La validación corresponde al contenido preparado para publicación tras auditoría.

Entrada del seed: el mismo documento privado de TODO Academy. Primera ejecución: cuatro cuentas y dataset; segunda: cero cuentas nuevas, snapshots completos de filas/DDL y archivos idénticos. Login de los cuatro roles; dashboard ADMIN; documento propio RESPONSABLE_AREA; IDOR 404 y endpoints administrativos 403; escalación rechazada; descarga TXT; consultas de dashboard/análisis/aprobaciones; login PHP y Chrome real ADMIN/RESPONSABLE_AREA y logout. Fresh smoke: 62 comprobaciones correctas. Smoke local rotado: 66 comprobaciones correctas, incluidas las cuatro credenciales anteriores rechazadas.

El evaluador únicamente necesita el código publicado de esta release y el archivo recibido por TODO Academy, además de sus requisitos y credenciales MySQL/JWT locales. La conexión administrativa del equipo se usó sólo para provisionar el entorno aislado; la ejecución fresca usa una identidad SQL propia. Los schemas temporales se conservaron para cumplir la prohibición de borrar bases de datos.

## Pruebas

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Unitarias de contrato, generación y seed | 25 | 0 | 0 |
| MySQL: seed, rotación, auth, RBAC y PHP auth | 111 | 0 | 0 |
| frontend/tests completa | 312 | 0 | 0 |
| Chrome real incluido en frontend, no sumar de nuevo | 49 | 0 | 0 |
| Repetición final de unitarias + seed/rotación MySQL | 41 | 0 | 0 |

Casos cubiertos: archivo ausente/inválido; claves/campos/roles/usuarios inesperados; identidades fuera de evaluación; passwords distintos/no impresos; rechazo de generación en repo o sobrescritura; fallo ACL sin escritura de secretos; idempotencia; dos seeds concurrentes; colisiones; rotación explícita; fingerprint ausente/cambiado; procedencia faltante; protección ID 1; rollback ante fallo de hashing intermedio; revocación de sesiones activas; cuatro logins; RBAC/escalación/IDOR; usuario personal ausente. Los nuevos fixtures generan secretos sintéticos propios, distintos del documento de TODO Academy. No se debilitaron tests existentes.

Las dos deprecaciones backend conocidas permanecen como warnings; no hubo fallos ni skips finales. No se repitió benchmark de Fase 8 ni toda la suite backend ajena al alcance. SMTP real sigue pendiente de credenciales externas y no bloquea este cierre.

## Documentos, capturas y entregables

Actualizados README, MVP, procedimiento público de accesos, contrato, guía de instalación, manuales técnico/usuario, PRD, evidencia, inventario, índices e informes históricos de Fases 9/9.1. Los informes conservan sus resultados históricos y señalan la política vigente sin credenciales concretas. Documento técnico y Bitácora no necesitaban cambios de contenido.

Archivos de código/configuración afectados exclusivamente por esta fase: `.gitignore`, `api/app/scripts/seed_evaluation_demo.py`, nuevos `evaluation_credentials.py` y `rotate_evaluation_demo.py`, `api/tests_unit/test_evaluation_demo_unit.py`, `api/tests_auth_mysql/test_evaluation_demo_mysql.py`, nuevo `test_evaluation_rotation_mysql.py` y la opción de conservación de schema en `api/tests_auth_mysql/conftest.py`. Los cambios visuales frontend preexistentes de Fase 9.1 se conservaron sin editar.

Veintiuna capturas nuevas de Chrome real sobre el fresh clone. Se ocultan identificadores en texto DOM antes de capturar y se vacían campos de acceso; se conserva interfaz/branding Develop sin modificar archivos frontend. Revisión visual y de bytes/metadatos; no se afirma OCR exhaustivo de material ajeno.

Se regeneraron exclusivamente cinco documentos afectados con el mismo builder TESCI, assets institucionales, Arial, geometría vino/negro, membretes, pies, índices y paginación mediante Word oculto: Evidencia (15 páginas PDF), Guía (6), Manual usuario (10), Manual técnico (6), PRD (6). Cinco PDF y cuatro DOCX públicos actualizados; DOCX de Evidencia sólo como intermedio fuera de la entrega. OpenXML válido, todas las páginas renderizadas/revisadas y cajas de texto dentro del papel. Los cuatro PDF/DOCX de Bitácora/Documento técnico conservaron sus bytes.

`Portafolio de Evidencias Final (1).pdf` e `imagen develop.jpg` permanecen en su ruta, nombre y bytes originales; hashes separados coinciden con Fase 9.1. Ninguno se movió, modificó o incluyó en SHA256SUMS.

Carpeta de entrega: 80 archivos propios finales, incluidos contrato/informe nuevos y el único documento privado de accesos. SHA256SUMS excluye su propio hash, temporales y dos referencias originales. Cada hash se verificó independientemente; las copias Markdown y capturas corresponden a sus fuentes finales. No se exportan `.env`, storage, venv, dumps ni archivos de prueba.

## Secret scan y Git final

Comparación exacta en memoria contra secretos DB/JWT operativos, accesos demo anteriores/nuevos y dos correos personales retirados, sin mostrar valores. Scan de todos los archivos publicables tracked/no rastreados, diff, todo el historial Git alcanzable (502 blobs), Markdown, scripts/tests/configuración, capturas, siete PDF y seis DOCX finales con extracción de texto/XML. Detección adicional de JWT, claves API/AWS y material de llaves privadas. Cero secretos operativos, contraseñas demo fijas, identificadores concretos demo o correos personales retirados en el material público final. `.env` operativo permanece local ignorado; no se confunde con contenido publicable.

El documento privado se revisó separadamente: cuatro roles/identidades/passwords distintos, sin reutilización de accesos previos y fuera de cualquier árbol Git. Es el único documento de la carpeta de entrega que contiene credenciales de evaluación. La evidencia privada de auditoría/snapshot legacy en Temp no se distribuye. Los dos originales de referencia se conservaron como material ajeno de sólo lectura, separado del inventario público propio.

Git final: main; HEAD/origin/main d54a81e; working tree con Fases 9/9.1/9.2; staging vacío. `git status`, `git diff --check`, `git diff --stat`, `git diff` y `git diff --cached --name-only` revisados. Sin add, commit, push, reset ni rebase. Los validadores temporales se guardaron fuera del repositorio.

## Límites

No hay publicación remota ni carga a TODO Academy desde esta sesión; ambas corresponden al release posterior a auditoría. El servidor MySQL se comparte localmente, con aislamiento por schema/usuario nuevos; no se afirma una instancia MySQL distinta. Los schemas de pruebas conservados son artefactos locales, sin procesos de evaluación activos. SMTP continúa `SMTP_REAL_PENDIENTE_DE_CREDENCIALES_EXTERNAS`. El scan no constituye pentest ni prueba de todos los textos rasterizados del PDF de referencia de 615 páginas. El formato valida longitud/sintaxis de entradas, no demuestra entropía de secretos externos escritos por terceros.
