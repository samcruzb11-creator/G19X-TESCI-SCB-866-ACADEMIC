# Frontend PHP

PHP 8.1 o superior con cURL, mbstring y fileinfo. No requiere Composer ni frameworks.
El frontend consume FastAPI; no accede directamente a MySQL.

6B.4A/6B.4B: el entorno del proceso PHP admite `AUTH_API_TIMEOUT_SECONDS=15` para
login/me/logout y `FRONTEND_COOKIE_SECURE=auto|always` (default `auto`). Valores
inválidos fallan de forma segura; no se leen de encabezados HTTP. `always` es solo
para sitios exclusivamente HTTPS; `auto` conserva HTTP local. No crear un `.env`
bajo el web root. El GC de sesiones se fija a 1800 s, probabilidad 1/100 y archivos
privados; es probabilístico y no garantiza limpieza sin tráfico. En Windows se
requieren permisos NTFS adecuados. Detalles, proxy futuro y mantenimiento:
[FASE_6B_4A_AUTH_HARDENING.md](../docs/FASE_6B_4A_AUTH_HARDENING.md).

Desde la raíz del proyecto, en PowerShell:

```powershell
& 'C:\xampp\php\php.exe' -S 127.0.0.1:8080 -t frontend
```

Abrir http://127.0.0.1:8080. Mantener FastAPI disponible en
http://127.0.0.1:8000. La URL de API se configura en `config/config.php`.
El servidor integrado de PHP se utiliza solamente para desarrollo local.

Rutas implementadas: `index.php?pagina=login`, `index.php?pagina=logout` (solo POST), `index.php?pagina=dashboard`,
`index.php?pagina=documentos`, `index.php?pagina=documento_nuevo`
e `index.php?pagina=documento&id=1`; también `auditorias`, `auditoria_nueva`,
`auditoria&id=1`, `evidencias`, `evidencia_archivo`, `evidencia_logica`
y `evidencia&id=1` mediante el parámetro `pagina`. Las rutas desconocidas
y los identificadores inválidos devuelven 404 después de verificar la sesión.

## Autenticación y permisos — Fase 6B.3

Login usa correo y contraseña contra FastAPI. El JWT permanece únicamente en la
sesión PHP del servidor; el navegador recibe solo la cookie de sesión HttpOnly,
SameSite=Lax y Secure cuando PHP recibe HTTPS. Se regenera el identificador al
iniciar/cerrar sesión y al recibir un 401 autenticado. Cada petición protegida
consulta `/auth/me` una sola vez: FastAPI determina vigencia, revocación y rol.
No hay refresh token, renovación automática ni lectura local de claims.

Logout requiere POST y CSRF, intenta revocar en FastAPI y limpia siempre la
sesión local. Si falla la comunicación se informa que no pudo confirmarse la
revocación remota. Un 403 conserva la sesión; un 404 indica recurso no disponible.
Los errores internos no se muestran como JSON ni como trazas.

La navegación y los formularios siguen el rol validado. ADMIN conserva los
módulos actuales y el historial. Los auditores consultan su alcance y registran
evidencias; solo AUDITOR_INTERNO crea auditorías, asignándose a sí mismo.
RESPONSABLE_AREA crea documentos propios y carga versiones. APROBADOR consulta
las versiones asignadas. FastAPI sigue autorizando cada recurso.

Las sesiones se guardan en `sistema-trazabilidad-frontend-sessions` dentro del
directorio temporal del sistema, fuera del directorio público del frontend.
PHP debe disponer de ese directorio privado; no debe ubicarse bajo el web root.
En despliegues con terminación TLS externa, el servidor debe comunicar a PHP
el HTTPS efectivo; la aplicación no confía en cabeceras de proxy del cliente.
Los formularios que cambian estado, incluido login/logout, conservan CSRF.

Detalle y pruebas: [FASE_6B_3_PHP_AUTH_RBAC.md](../docs/FASE_6B_3_PHP_AUTH_RBAC.md).

El dashboard consulta hasta 100 documentos y, para ADMIN y auditores, hasta 50 auditorías (límite
predeterminado de la API); los indicadores muestran ese alcance, sin afirmar
totales globales. Los cinco documentos recientes se ordenan por `updated_at`
dentro de la muestra consultada. Las fechas de la API en UTC se presentan
en horario de Ciudad de México.

Los errores de conexión producen estados de información no disponible,
nunca contadores ficticios de cero. APROBADOR no recibe métricas de versiones
vigentes fuera de su alcance; los metadatos ocultos se muestran como «No disponible».

La ficha consulta documento, versiones y áreas; solo ADMIN consulta el historial
y el catálogo de usuarios. Las descargas
pasan por PHP y FastAPI, sin acceso directo al storage: PHP recibe el archivo en
un temporal, comprueba la respuesta y lo entrega como adjunto. El temporal se
cierra y elimina al completar la respuesta. Se usa Bearer en la petición al
backend, se sanea el nombre original y se libera la sesión antes del streaming.
`tmpfile()` + `CURLOPT_FILE` + `fpassthru()` evitan cargar todo el archivo en memoria;
se retiran los búferes de salida PHP antes de transmitirlo.

La carga envía `archivo` y, opcionalmente, `comentario_cambio`. No envía actor:
FastAPI utiliza al usuario autenticado. Se valida el archivo recibido por PHP,
y se protege el formulario con un token CSRF de sesión. Una respuesta 201 produce
una redirección 303 a la ficha, con mensaje de éxito y datos consultados nuevamente.
Si no es posible abrir una sesión, se informa indisponibilidad antes de atender
la petición.

Los límites efectivos de carga dependen de `upload_max_filesize` y `post_max_size`
de PHP y se muestran en el formulario. El archivo debe dejar margen para los
campos y las cabeceras del envío multipart dentro de `post_max_size`.
Las pruebas automatizadas utilizan dobles HTTP o un esquema MySQL aleatorio
y storage temporal; no envían cargas de validación a la base oficial.

## Alta de documentos

El formulario de alta envía `POST /api/v1/documentos` con JSON y Bearer:
`codigo`, `titulo`, `descripcion`, `tipo`, `estado`, `area_id`, `responsable_id`.
Según OpenAPI, código tiene entre 2 y 80 caracteres, título entre 3 y 240 y tipo
entre 2 y 40. Tipo es texto libre, sin catálogo ni enum. Descripción es opcional.
Estado usa los valores documentados DRAFT, ACTIVE, OBSOLETE y ARCHIVED, con DRAFT
como predeterminado. ADMIN consulta áreas y usuarios activos; RESPONSABLE_AREA
queda asignado desde el usuario autenticado, sin selector de otro responsable.

PHP valida los campos y el token CSRF antes de enviar. Las sesiones y CSRF se
comparten con la ficha. Un 201 con ID válido produce una redirección 303 a la
ficha y un mensaje de sesión que se consume una sola vez. La primera versión se
adjunta después, mediante el formulario ya disponible en la ficha.

El duplicado de código actualmente responde HTTP 400 con un detalle identificable;
el frontend lo traduce sin mostrar el JSON original. Un 409 genérico se muestra
como conflicto, sin afirmar que sea un duplicado. Los 422 marcan los campos
identificados por la API. Los fallos 500 o de transporte piden consultar el
listado antes de reintentar, porque la respuesta podría fallar después del alta.

Validación controlada realizada: documento ID 3, código
`DEV-PROTOTIPO-PHP-20260928-001`, estado DRAFT, sin versiones. Creado únicamente
mediante el frontend y FastAPI; conserva su evento de creación. Los documentos
anteriores no se modificaron.

## Fase 5: navegación y filtros

Documentos permite buscar por código/título y filtrar por estado y área.
Auditorías permite buscar por código/nombre y filtrar por estado. Son formularios
GET que funcionan sin JavaScript; PHP filtra los registros obtenidos mediante el
cliente central de FastAPI. La búsqueda no distingue mayúsculas y conserva acentos.
Los listados consultan páginas de 200 registros, con el límite de protección
existente de 10 000: si se alcanza, se informa de indisponibilidad en lugar de
mostrar un resultado parcial como completo. Este enfoque está destinado al MVP
con pocos registros; un volumen mayor requerirá filtros en la API.
La autorización se aplica en SQL en FastAPI antes de la paginación. Los filtros
de búsqueda locales operan únicamente sobre registros ya autorizados.

Evidencias conserva el filtro por auditoría y páginas de 50 registros. No se
añadió filtro por tipo porque la API no lo admite: filtrar una sola página
ocultaría resultados de otras páginas. La interfaz distingue entre un módulo
vacío y una búsqueda sin coincidencias.

Las rutas de alta tienen enlaces de regreso y Cancelar. La cabecera enlaza al
módulo padre. Nueva versión usa los controles reutilizables, errores junto al
campo, CSRF (403), validación (422) y PRG (303). Los mensajes de éxito se consumen
una sola vez. JavaScript enfoca el primer campo inválido y devuelve el foco al
botón Menú al cerrarlo con Escape.

Validación de esta fase: [VALIDACION_FASE5.md](VALIDACION_FASE5.md).

## Fase 6C: acceso y recuperación

El login usa un layout de dos columnas en escritorio y una columna en móvil.
`solicitar_acceso` y `recuperar_password` son formularios públicos con CSRF;
`establecer_password` y `restablecer_password` reciben el código mediante fragmento
local y lo envían por POST. PHP no conserva códigos ni contraseñas en sesión.
`solicitudes_acceso`/`solicitud_acceso` requieren ADMIN; FastAPI vuelve a autorizar
cada operación. El JWT continúa exclusivamente en la sesión del servidor PHP.

Diseño, operación, configuración y validación: [FASE_6C_ACCESO_RECUPERACION.md](../docs/FASE_6C_ACCESO_RECUPERACION.md).

## Fase 6B.4B: verificación adaptativa

Configurar `TURNSTILE_SITE_KEY` en el entorno del proceso PHP (clave **pública**;
no crear `.env` bajo el web root). La clave privada vive exclusivamente en
FastAPI. El widget aparece solo después de un HTTP 428 válido del backend en
login, solicitud de acceso o solicitud de recuperación. PHP transporta
`turnstile_token` por POST; la autoridad de admisión y Siteverify es FastAPI.
Una sitekey ausente o mal formada ante un challenge responde 503 seguro.

La sesión conserva únicamente un booleano de presentación por acción durante
la interacción: nunca el token Turnstile, contraseña o datos del formulario.
Un GET nuevo, operación exitosa o hard limit 429 limpia esa indicación; FastAPI
vuelve a decidir en cada POST. Un challenge exige escribir la contraseña otra
vez. Expiración/error/timeout requieren reinicio manual del widget, sin loops.
Sin JavaScript, el backend sigue rechazando operaciones que requieren challenge;
el formulario explica que debe activarse para completar esa verificación.

Solo una respuesta con widget amplía `script-src` y `frame-src` al origen exacto
`https://challenges.cloudflare.com`. El script oficial se carga directamente
desde `https://challenges.cloudflare.com/turnstile/v0/api.js`; la aplicación
renderiza mediante `turnstile.render` sobre un contenedor sin `cf-turnstile`.
En 320 px se utiliza tamaño compacto para respetar el ancho del formulario.
Las páginas `establecer_password` y `restablecer_password` jamás cargan ese
script, iframe u otro recurso externo, incluso ante un error de backend.
Conservan fragmentos, limpieza de URL/DOM, `no-store` y `no-referrer` de 6C.

El timeout PHP predeterminado sube a 15 s para cubrir dos intentos Siteverify de
5 s y el procesamiento local. Si se cambia el timeout backend, ajustar también
`AUTH_API_TIMEOUT_SECONDS`; un timeout PHP no cancela una operación admitida.

Pruebas normales offline con doble HTTP de FastAPI:
`api/venv/Scripts/python.exe -m pytest frontend/tests -q`.
Para Chrome aislado, establecer `AUTH_BROWSER_TEST=1`; el script oficial se
intercepta mediante DevTools con un stub de prueba, sin conexión a Cloudflare.
La suite incluye JavaScript desactivado, rechazo de challenge, caducidad/reset,
limpieza pagehide/pageshow, teclado y anchuras 1440/390/320 px. Si el sandbox de
Windows impide iniciar los procesos internos de Chrome, ejecutar las mismas
pruebas con autorización fuera del sandbox, manteniendo el perfil temporal.
No usar ese stub en el despliegue. Configuración y operación completas:
[FASE_6B_4B_TURNSTILE.md](../docs/FASE_6B_4B_TURNSTILE.md).

Fase 7A: [Auditorías: listado paginado, detalle, edición y ciclo de vida](../docs/FASE_7A_AUDITORIAS.md).
Los filtros se aplican en la API antes de paginar. PHP conserva CSRF para todas
las mutaciones y muestra controles por rol/estado; FastAPI es la autoridad.
