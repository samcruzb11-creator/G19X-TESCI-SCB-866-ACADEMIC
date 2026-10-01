# Fase 6B.3 — Autenticación y RBAC en PHP

Implementación para revisión, sin commit ni push. Conserva PHP/HTML/CSS/JavaScript
y los módulos existentes. No incorpora trabajo de 6B.4.

## Sesión y flujos

`index.php` inicia la sesión antes de controladores y HTML. Activa modo estricto,
solo cookies, HttpOnly, SameSite=Lax, ruta del directorio de la aplicación y Secure
cuando PHP recibe HTTPS. El almacenamiento permanece fuera del web root, bajo
el temporal del sistema; el directorio debe ser privado para el usuario de PHP.

La sesión autenticada contiene exclusivamente:

```text
auth.access_token
auth.expires_at
auth.user = {id, nombre, rol}
```

Se mantienen CSRF y mensajes de formulario. No se almacena la contraseña. El JWT
no se entrega a HTML, JavaScript, URLs ni cookies; `expires_at` es información
de la respuesta de login, no una renovación ni una interpretación de claims.

1. GET login abre una sesión anónima y presenta correo/contraseña + CSRF.
2. POST valida CSRF y llama `/auth/login` sin Bearer.
3. Con un token válido, borra contexto anterior y regenera el ID con eliminación
   del anterior antes de almacenarlo. Consulta `/auth/me`, conserva solo id,
   nombre y rol, rota CSRF y redirige con 303 al dashboard.
4. Si `/me` falla en ese paso, se elimina toda autenticación parcial.
5. Cada petición PHP protegida verifica `/auth/me` una sola vez y reutiliza su
   resultado durante esa petición. Esto detecta expiración, revocación,
   desactivación y cambio de rol.
6. Logout admite solo POST + CSRF. Llama `/auth/logout`, descarta todos los datos
   del usuario anterior, regenera la sesión anónima y redirige a login. También
   limpia ante 401 o fallo de transporte; este último muestra revocación remota
   no confirmada. No hay refresh token ni extensión artificial de sesión.

## Cliente API y errores

`api_headers()` es el único lugar que incorpora Bearer. El cliente permite rutas
conocidas y no sigue redirecciones; el navegador no puede aportar una URL remota.
Soporta GET, POST JSON, multipart con boundary de cURL, POST sin cuerpo, 204 y
descargas. `api_errors.php` normaliza errores; nunca se muestra el detalle crudo.

| Respuesta | Comportamiento PHP |
|---|---|
| 401 login | Credenciales inválidas, sin distinguir usuario/contraseña/inactividad |
| 401 autenticado | Borra credenciales/contexto, rota ID, 303 login y mensaje genérico |
| 401 selector AJAX | Limpieza idéntica, JSON 401 mínimo; JavaScript lleva a login |
| 403 | Conserva sesión, acceso denegado sin detalles de políticas |
| 404 | Conserva sesión y semántica de recurso no disponible |
| 400/409/422 | Errores saneados de formulario, conservando valores no sensibles |
| 5xx/transporte | Conserva autenticación, informa indisponibilidad y registra solo estado/clase |

Login no ejecuta `require_login()`. Los controladores se ejecutan antes de emitir
HTML, para que cualquier 401 pueda redirigir correctamente. CSRF protege navegador
→ PHP mediante cookie; Bearer autentica PHP → FastAPI. Ninguno reemplaza al otro.

## Presentación por rol

`can_show_action()` solo controla presentación y entrada a páginas. No replica
las relaciones de `authorization_service.py`; FastAPI decide cada acceso por ID.

| Rol | Módulos y acciones visibles |
|---|---|
| ADMIN | Dashboard, documentos, auditorías, evidencias, altas/cargas actuales e historial |
| AUDITOR_INTERNO | Dashboard, documentos de lectura, auditorías propias, alta de auditoría propia y evidencias |
| AUDITOR_EXTERNO | Dashboard, documentos de lectura, auditorías propias y evidencias; sin alta de auditorías |
| RESPONSABLE_AREA | Dashboard, documentos propios, alta propia, cargas y descargas autorizadas |
| APROBADOR | Dashboard, documentos y versiones asignadas, descargas autorizadas |

El dashboard consulta auditorías solo para ADMIN/auditores. Ningún rol consulta
usuarios para métricas. Solo ADMIN consulta historial y directorio para nombres.
Los demás usan su nombre o los identificadores ya devueltos por la API. Los
metadatos de versión vigente ocultos al APROBADOR se muestran «No disponible».

## Formularios

Se retiran selectores y parámetros de actor (`creador_id`, `editor_id`,
`subido_por_id`, `registrada_por_id`, `created_by_id`). No se sustituyen por inputs
ocultos. Los metadatos históricos devueltos por FastAPI pueden seguir mostrándose.
PHP construye responsable propio para RESPONSABLE_AREA al crear documento y
AUDITOR_INTERNO al crear auditoría; ignora un responsable manipulado en esos casos.
ADMIN conserva los selectores autorizados.

El formulario de auditoría ADMIN consulta `/usuarios?elegibles_auditoria=true`.
Es el único ajuste funcional del backend: añade el filtro existente
`eligible_users_scope()` al scope actual, sin ampliar roles ni campos de salida
(`id`, `nombre`, `activo`). Sin parámetro, el catálogo se comporta como antes.

Evidencias ofrece documentos ya autorizados, explica que deben estar vinculados
a la auditoría seleccionada y limpia documento/versión al cambiar la auditoría.
No deduce relaciones a partir de evidencias ni incorpora un endpoint nuevo.
Una combinación cruzada rechazada por FastAPI vuelve al formulario con un error
saneado y conserva el estado HTTP. Nombres, mensajes, títulos y archivos pasan
por `e()`; JavaScript utiliza `textContent` y `Option`.

## Descargas

Navegador → PHP protegido → FastAPI con Bearer → temporal PHP → navegador.
El cliente usa `tmpfile()` y `CURLOPT_FILE`, y solo transmite después de verificar
el estado. Usa `fpassthru()`, sin búferes de salida PHP que puedan copiar el archivo
completo. Libera el bloqueo de sesión antes de transmitir al navegador. Cierra el
temporal en errores y en éxito con `finally`.

Content-Type se valida con una sintaxis restringida. El nombre se extrae de los
formatos soportados, elimina rutas y controles, comprueba UTF-8 y se emite mediante
`filename*` codificado; no se reenvían cabeceras upstream arbitrarias. PHP no abre
rutas del storage. Las denegaciones 401/403/404 se resuelven antes del output.

## Pruebas reproducibles

Requieren el entorno Python existente y PHP con cURL, mbstring y fileinfo. Se puede
indicar el ejecutable PHP con `PHP_TEST_BINARY` (predeterminado local XAMPP).

Desde la raíz, en PowerShell:

```powershell
$phpTests = Join-Path $env:TEMP ('SistemaTrazabilidad_PHP_' + [guid]::NewGuid().ToString('N'))
api/venv/Scripts/python.exe -m pytest frontend/tests -q -p no:cacheprovider --basetemp=$phpTests
```

Las pruebas lanzan PHP real en loopback, con una copia del frontend y sesiones
fuera del web root; la API doble registra las peticiones para verificar Bearer,
payloads, multipart, roles y errores. Incluyen un archivo de 20 MiB bajo un límite
PHP de 16 MiB, fijación de sesión, rotación CSRF, cookies, actor manipulado y XSS.

Desde `api`, en otro proceso pytest para evitar colisiones entre conftests:

```powershell
$env:AUTH_MYSQL_TEST = '1'
$backendTests = Join-Path $env:TEMP ('SistemaTrazabilidad_BACKEND_' + [guid]::NewGuid().ToString('N'))
venv/Scripts/python.exe -m pytest tests_unit tests_auth_mysql -q -p no:cacheprovider --basetemp=$backendTests
```

Se reutiliza el fixture MySQL opt-in de 6B.1/6B.2: esquema aleatorio recién creado,
comprobación del esquema en cada conexión, engine de la aplicación bloqueado y
borrado del esquema exacto al terminar. Sus comprobaciones de migraciones solo
operan en ese esquema temporal; no se añaden migraciones. La integración PHP real
usa HTTP FastAPI, ese MySQL aislado y storage temporal. Comprueba alta con actor
autenticado, descarga, IDOR, revocación efectiva, cambios de rol y desactivación.

## Alcance y revisión

No se modifica autenticación 6B.1, reglas RBAC 6B.2 ni storage/compensación/
reconciliación/transacciones de 6A. Se preservan sus suites. No se introducen
módulos, frameworks, refresh token, CAPTCHA, rate limiting ni otras medidas 6B.4.
Si falla el logout remoto, su revocación no puede confirmarse: PHP informa esa
limitación y elimina igualmente el token local.

Validación local del 1 de octubre de 2026: 47 pruebas PHP/frontend y 317 pruebas
backend (unitarias, 6A, autenticación, RBAC e integración PHP/MySQL), todas
aprobadas. Lint de los 41 archivos PHP y comprobaciones de whitespace aprobados,
incluidos los archivos nuevos. Se verificó que no quedaron esquemas temporales
MySQL. Dos avisos de deprecación corresponden a dependencias del TestClient.

La autoauditoría revisó exposición de JWT, fijación de sesión, loops de login,
CSRF, semántica 401/403/404, descargas, nombres de archivo, actores manipulados,
presentación/consultas por rol y escape de salida. Se corrigieron un búfer PHP
que agotaba memoria en descargas grandes y un enlace de carga aún visible para
roles de lectura. No se encontraron cambios accidentales en reglas backend ni
regresiones de las fases anteriores en las pruebas ejecutadas. Las pruebas HTTP
y de cookies no sustituyen una revisión visual manual en navegadores ni una
validación de la configuración TLS del despliegue definitivo.
