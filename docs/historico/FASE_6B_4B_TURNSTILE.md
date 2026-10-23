# FASE 6B.4B — Turnstile adaptativo

## Objetivo y diagnóstico

Segunda capa contra automatización en tres operaciones públicas: login, solicitud
de acceso y solicitud de recuperación. El login normal no carga un CAPTCHA.
FastAPI es la única autoridad de seguridad. PHP presenta el desafío solicitado
por FastAPI y transporta `turnstile_token`; nunca valida Siteverify.

Base de trabajo: `279e99e3274fb7f9ec9e915d92e0209c94c80c9b`. Este cierre retomó
el working tree parcial, con 27 archivos modificados y 9 nuevos; no partió de un
árbol limpio. Se conservaron los componentes correctos y se revisaron los
limitadores 6B.4A/6C, rutas, esquemas, controladores PHP, CSP, cola/worker de correo
y pruebas existentes. No se reimplementó 6C.

Hallazgo relevante: `AuthLoginLimit.failure_count` incluye fallos **y reservas
en curso**. El éxito existente libera únicamente su propia reserva: no borra
fallos anteriores. Esa semántica se conserva. MySQL y su collation
`utf8mb4_unicode_ci` siguen definiendo la equivalencia de identificadores.

No se crean tablas ni migración 005. Las revisiones 001–004 permanecen intactas.
No se aplica ninguna migración a `sistema_trazabilidad`; las pruebas usan
exclusivamente esquemas aleatorios temporales propiedad del fixture.

### Diagnóstico de `changes9`

Es el décimo parámetro de
`test_success_still_rejects_action_hostname_or_expiry`: `challenge_ts` está
35 segundos en el futuro. Su expectativa **428 es correcta**, porque el margen
aprobado es de 30 segundos, y no se cambió ni esa expectativa ni el margen.

El árbol recibido ya contenía `FIXED_NOW` y `FrozenDatetime`, aplicados tanto a
los parámetros como al reloj del verificador. Antes de editar, los diez casos
pasaron y la suite completa dio **421 passed**. El rojo histórico no se reprodujo
en ese árbol; no se dispone de su traceback completo ni de la fuente anterior.

Se reprodujo de forma determinista el mecanismo de un falso rojo temporal: un
timestamp calculado como `now + 35 s` durante la colección pasa a estar solo
29 segundos en el futuro si el caso corre seis segundos después. En ese momento
aceptarlo es correcto. La regresión
`test_future_sample_ages_between_collection_and_execution` demuestra ese cambio;
las pruebas de frontera verifican -30/300 segundos y un microsegundo fuera de
ambos límites con un único reloj fijo. El desfase colección/ejecución explica el
fallo comunicado y es la hipótesis histórica respaldada por esa reproducción;
se distingue de los fallos de producción reproducidos durante este cierre.

## Threat model

Se cubren bots de credenciales, spraying, repetición de solicitudes públicas,
replay, confusión de acción/hostname, agotamiento de llamadas externas,
encabezados proxy falsos y carreras durante validaciones de red. El estado de
challenge no consulta Usuario, rol, activación, token de recuperación ni correo.

Turnstile no reemplaza Argon2, CSRF, JWT/SID, RBAC, sesiones, presupuestos de
aplicación ni los buckets persistentes. Un ataque dirigido todavía puede consumir
cupos legítimos; no se garantiza disponibilidad bajo ataque. Spraying lento puede
quedar bajo umbrales. La configuración `disabled` pierde esta segunda capa.

Turnstile y rate limiting de aplicación **no son protección DDoS volumétrica**.
Un despliegue público futuro necesita evaluar reverse proxy/CDN/WAF y protección
de infraestructura. No se instala ni contrata esa infraestructura en esta fase.

## Arquitectura y flujo

```text
Navegador -> POST PHP con CSRF
         -> FastAPI: presupuesto global barato antes de parsear JSON
         -> normalización + transacción corta del bucket MySQL
         -> hard limit: 429 (sin Siteverify ni operación)
         -> soft threshold / presión global:
              no requerido -> admisión existente
              requerido -> rollback (sin transacción ni lock abierto)
                         -> token presente/formato/tamaño
                         -> presupuesto local Siteverify
                         -> POST oficial Siteverify
                         -> success + action + hostname + timestamp
                         -> nueva admisión MySQL bajo lock; revalida hard limits
         -> login: reserva/cupo Argon2 -> hash -> revalidación Usuario -> sesión
         -> acceso: admisión -> solicitud deduplicada, sin crear Usuario
         -> recuperación: admisión -> LOOKUP_RESET ciego, sin recipient
```

Un token opcional enviado cuando no existe presión no genera tráfico a Siteverify.
Un token validado habilita exclusivamente esa ejecución y esa acción; no se
persiste un pase, cookie de bypass ni autorización de sesión para futuros POST.
No se reintenta la operación de negocio ni se hace autologin en recuperación.

## Política adaptativa final

| Flujo | Soft identifier | Soft global en 60 s | Hard identifier | Hard global en 60 s |
| --- | --- | ---: | --- | ---: |
| login | 3 fallos completados en la ventana vigente | 60 solicitudes | 5 fallos/reservas en 600 s; 10 solicitudes/min | 120 solicitudes; 60 Argon2; 2 hashes simultáneos |
| access_request | 1 operación admitida en la ventana | 5 solicitudes | 2/día | 10 |
| password_reset_request | 1 operación admitida en la ventana | 10 solicitudes | 3/hora | 20 |

Se cuentan las solicitudes globales que pasan el middleware, incluida la actual;
la número 60/5/10 ya puede requerir challenge. La comprobación utiliza el techo de
la mitad del presupuesto global configurado. Si se endurece un hard limit hasta
el soft threshold, prevalece el 429: no se promete un cupo extra de challenge.
Los rechazos globales no se agregan a la ventana ni desplazan su vencimiento.

En login, cero, uno y dos fallos permiten la verificación normal; al completar
el tercero, las siguientes solicitudes requieren desafío. Las reservas todavía
en curso se restan exclusivamente para decidir el soft threshold, nunca el hard.
El registro local de reservas se asocia a la **grafía guardada por MySQL**, ventana
y objeto de intento único; no contiene tokens Turnstile. Se registra antes del
commit que libera el lock y se retira al finalizar. Un éxito retira el marcador
dentro del lock de su decremento. Esto evita contar un hash pendiente como fallo
real o perder fallos por una carrera entre commit y bookkeeping.

Una caída abrupta puede dejar reservas durables contabilizadas hasta expirar,
igual que 6B.4A; al reiniciar se tratan conservadoramente como fallos/reservas
abandonados. No se borra historial para recuperar la disponibilidad.

Los desafíos ausentes, incorrectos, expirados, duplicados o indisponibles no
incrementan ni renuevan contadores/ventanas del identifier. Sí consumen su
admisión global barata, y una llamada HTTP real consume presupuesto externo.
Resolver un desafío tampoco borra fallos ni evita ningún hard limit.

## Concurrencia y TOCTOU

La decisión soft y la reserva se serializan con el mismo INSERT/SELECT FOR UPDATE
existente. Si se requiere desafío se revierte la transacción, incluida cualquier
inserción o actualización de ventana; luego se llama a Siteverify fuera de SQL.
Al volver, se repite la admisión completa del bucket: hard limit, ventana actual y
cupo Argon2. No se supone que la cuenta o el bucket permanecieron inmóviles.

La admisión global del middleware ya consumida pertenece al POST actual. No se
consume otra al volver de Siteverify. Los POST siguientes sí pasan nuevamente
por el middleware y sus hard limits. Una validación válida es suficiente si el
soft estado cambió durante la red; el hard siempre vuelve a comprobarse.

Una colisión de dos solicitudes de acceso/reset deja como máximo los cupos duros
admitidos. Dos usos del mismo token dependen del single-use de Cloudflare, no de
un registro local de tokens. No hay transacción durante HTTP ni durante Argon2.

## Contrato HTTP

```json
{
  "detail": "Se requiere verificación adicional.",
  "challenge_required": true,
  "challenge_action": "login"
}
```

HTTP **428 Precondition Required**, objeto en el nivel superior. Acciones exactas:
`login`, `access_request`, `password_reset_request`. No devuelve existencia,
contadores, umbrales ni Retry-After. Incluye `Cache-Control: no-store` y
`Referrer-Policy: no-referrer`.

Token ausente/inválido: 428. Tipo incorrecto o tamaño superior a 2048 en el
contrato JSON: 422 saneado, sin eco del valor y sin Siteverify. Hard limit: 429 y
Retry-After existente. Dependencia/configuración/respuesta malformada: **503**:
"No podemos completar la verificación en este momento. Intenta más tarde."
No continúa Argon2, sesión, solicitud ni encolado al fallar la verificación.

## Configuración

Backend privado, en entorno de FastAPI o `api/.env` privado:

```dotenv
TURNSTILE_MODE=disabled
TURNSTILE_SECRET_KEY=
TURNSTILE_EXPECTED_HOSTNAMES=
TURNSTILE_VERIFY_TIMEOUT_SECONDS=5
TURNSTILE_VERIFY_GLOBAL_PER_MINUTE=60
TURNSTILE_VERIFY_CONCURRENCY=4
```

Frontend, entorno Apache/PHP:

```dotenv
TURNSTILE_SITE_KEY=
AUTH_API_TIMEOUT_SECONDS=15
```

La clave privada es `SecretStr`, no se incluye en repr de Settings ni frontend.
Sitekey es pública. No se almacena ningún secreto productivo en el repositorio.
No se necesita una copia de la sitekey en FastAPI ni del secret en PHP.

`disabled` conserva 6B.4A/6C sin challenge; la plantilla lo declara explícitamente
para no exigir credenciales a la instalación local. `test` exige un secret dummy
oficial y se rechaza con `APP_ENV=production`. `enabled` rechaza secretos dummy,
secreto vacío, hostname vacío/inválido y configuración numérica inválida.
FastAPI valida al iniciar; un fallo operativo durante verify también cierra con
503. PHP sin sitekey válida ante un challenge muestra 503 seguro. Ni una caída
ni un timeout cambian el modo. Cambiar configuración requiere reinicio de procesos.

Hostnames: CSV de nombres ASCII en minúsculas (IDN en punycode), exactos, sin
esquema, puerto, ruta, wildcard ni punto final. Una entrada vacía invalida la
configuración: no se omite ni se interpreta como wildcard.
Ejemplos explícitos, **no habilitados por defecto**:

| Entorno | Allowlist de ejemplo |
| --- | --- |
| local/test | `localhost,127.0.0.1` |
| staging | `trazabilidad-staging.example.com` |
| producción | `trazabilidad.example.com` |

Estos dominios son ejemplos; el operador debe poner los nombres reales del
frontend. Un subdominio no queda autorizado implícitamente por FastAPI.

## Siteverify y retries

La única URL es `POST https://challenges.cloudflare.com/turnstile/v0/siteverify`.
Payload: `secret`, `response`, `idempotency_key`. No redirects, no proxy heredado
del entorno, ni URL/headers derivados del cliente. Se omite `remoteip`: FastAPI
ve a PHP y no hay cadena confiable para obtener la IP final. No se interpretan
`X-Forwarded-For`, `X-Real-IP`, `CF-Connecting-IP` ni `Forwarded`.

Se comprueban success booleano estricto, ausencia de errores contradictorios,
acción exacta, hostname exacto autorizado y challenge_ts válido. El timestamp
admite fecha/hora extendida con `T`, segundos, fracción opcional de 1–6 dígitos y
zona `Z` o `±HH:MM` válida; no separadores Unicode/controles ni normalización de
minutos inválidos. Edad máxima 300 segundos, sin extenderla; se toleran solo
30 segundos de reloj futuro, con ambos extremos incluidos.
Cloudflare es además la autoridad de expiración y single-use. Cada nuevo POST
debe resolver un token nuevo; no se guardan tokens en MySQL, sesiones ni logs.
El contrato de tokens y parámetros está en la [documentación oficial de
Siteverify](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/).

Timeout HTTP explícito de 5 s (timeouts de transporte httpx, no garantía de tiempo
total bajo cualquier comportamiento de red). Máximo dos POST: inicial y un retry.
Una UUID v4 nueva por validación se conserva en ese único retry. Solo se reintenta
timeout/error transitorio de transporte, HTTP 408/429/500/502/503/504 o
`internal-error`. No retry por token inválido, duplicado, mismatch ni JSON inválido.
No sleeps ni loops indefinidos. PHP usa 15 s por defecto para cubrir el caso usual
de dos timeouts; un timeout PHP tampoco autoriza la operación.

El body se lee por streaming hasta **16 KiB**, incluyendo respuestas sin
Content-Length o con longitud falsa. Se solicita `Accept-Encoding: identity` y
se rechaza otra codificación antes de descomprimir. Se cierran respuestas y
clientes también al abortar la lectura; los bodies HTTP no exitosos no se
descargan. El tiempo transcurrido se comprueba además en cada chunk para cortar
streams lentos, sin sustituir el timeout de transporte.

JSON debe ser UTF-8 válido, un objeto y sin claves duplicadas ni constantes
NaN/Infinity. El árbol se limita a 16 niveles, 256 nodos y strings de 2048
caracteres; `error-codes` admite como máximo 16 strings ASCII de hasta 64
caracteres. Respuestas contradictorias, excesivas, incompletas o con tipos
incorrectos fallan con 503 genérico, sin retry por parsing. La protección externa
`finally` también captura errores del parser como `RecursionError` y siempre
libera el slot. No se adjunta texto remoto a errores públicos ni logs.

El presupuesto externo contabiliza **cada POST**, incluido retry: 60/minuto y
4 validaciones simultáneas. No existe espera por cupo. Saturación: 503 genérico,
sin invocar red ni devolver presupuestos consumidos. Token vacío, no string,
>2048, controles, whitespace o caracteres ajenos al formato opaco permitido se
rechazan antes de adquirir cupo externo. Tokens y respuestas completas no se loguean.

## PHP, UX, CSP y páginas de tokens

PHP reconoce únicamente 428 con booleano `challenge_required=true` y acción
permitida **correspondiente al formulario**. Un campo oculto cliente no habilita
ni omite seguridad. Guarda solo el estado booleano de presentación de la
interacción. GET nuevo, éxito o hard429 lo limpian; errores recuperables conservan
el widget con un token nuevo. Los valores de correo/nombre/motivo se escapan.
Password nunca se repuebla ni se guarda en URL o sesión; el token tampoco.

El widget utiliza JS local para renderizar explícitamente, ancho flexible,
mensajes accesibles y reset manual. Expiración, timeout y error limpian el valor;
no hay recargas ni reintentos automáticos infinitos. Sin JS, un login sin presión
sigue funcionando; un challenge requerido necesita habilitar JS y no tiene bypass.

Solo un formulario challenged de login/acceso/solicitud de reset carga
`https://challenges.cloudflare.com/turnstile/v0/api.js`. No se descarga, modifica,
proxyfica ni almacena localmente el script oficial. CSP del documento challenged:

```text
default-src 'self'; style-src 'self';
script-src 'self' https://challenges.cloudflare.com;
frame-src https://challenges.cloudflare.com;
img-src 'self'; object-src 'none'; base-uri 'self';
frame-ancestors 'none'; form-action 'self'
```

La ampliación sigue los [requisitos CSP de
Cloudflare](https://developers.cloudflare.com/turnstile/reference/content-security-policy/).
No se añade wildcard, unsafe-eval, unsafe-inline ni nuevos dominios.

`restablecer_password` y `establecer_password` (INITIAL_PASSWORD) conservan la
CSP local original: script-src self, sin frame-src Cloudflare ni api.js. Esa
exclusión se aplica incluso con sesión de challenge previa o respuesta backend
inesperada. No analytics, fuentes ni imágenes externas. Se conservan no-store,
no-referrer, token en fragmento, history.replaceState y limpieza pagehide.
Se mantienen los labels, foco visible, teclado y layout a 320/390/1440 px.

## Invariantes 6C

El request de reset no consulta Usuario. Solo admite el bucket y crea LOOKUP_RESET
sin recipient. El worker sigue obteniendo exclusivamente `Usuario.correo` para
PASSWORD_RESET. Un correo inexistente/inactivo no produce token de recuperación,
recipient SMTP, job outbound ni llamada SMTP, aunque resuelva Turnstile.
El access request conserva la deduplicación sin sobrescribir datos previos y
sin crear Usuario. No se acepta role/recipient/user_id/identidad ADMIN pública.
Confirmación de tokens, aprobaciones, sesiones, RBAC y documentos no usan Turnstile.

## Test mode y pruebas offline

No se emplean secretos reales ni Internet en las suites. Los fixtures generales
bloquean SMTP y `_post`, y bloquean conexiones al engine de la aplicación; las
pruebas de backend sustituyen `_post` o su transporte con respuestas
deterministas. Los fakes de verificación modelan token single-use.
Las pruebas de navegador sustituyen el script oficial en el entorno aislado de
Chrome, conservando su URL para probar CSP. No hay modo HTTP de bypass para tests.

Para desarrollo manual, Cloudflare publica [claves dummy
oficiales](https://developers.cloudflare.com/turnstile/troubleshooting/testing/),
por ejemplo sitekey visible `1x00000000000000000000AA` y secret de éxito
`1x0000000000000000000000000000000AA`. Son valores públicos de prueba, nunca de
producción. Configurar `TURNSTILE_MODE=test`, `APP_ENV=development` y allowlist
explícita. Se conserva validación estricta de acción y hostname incluso en test.
Si el servicio dummy devuelve acción `test` u hostname ajeno, será rechazado;
no cambiar la allowlist ni relajar action para hacer pasar una suite. La prueba
integral normal se hace con doubles de Siteverify. No se ejecuta aquí integración
real contra Cloudflare ni se necesita para aprobar regresiones.

Comandos desde `api/`, siempre con basetemp aleatorio nuevo:

```powershell
$phaseTemp = Join-Path $env:TEMP ('trazabilidad-6b4b-unit-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest tests_unit -q -p no:cacheprovider -o addopts= --basetemp=$phaseTemp
$env:AUTH_MYSQL_TEST='1'
$phaseTemp = Join-Path $env:TEMP ('trazabilidad-6b4b-mysql-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest tests_auth_mysql -q -p no:cacheprovider -o addopts= --basetemp=$phaseTemp
$env:AUTH_BROWSER_TEST='1'
$phaseTemp = Join-Path $env:TEMP ('trazabilidad-6b4b-frontend-' + [guid]::NewGuid().ToString('N'))
.\venv\Scripts\python.exe -B -m pytest ../frontend/tests -q -p no:cacheprovider -o addopts= --basetemp=$phaseTemp
```

6A se ejecuta a través de `tests_auth_mysql/test_6a_regression_mysql.py` contra
el mismo esquema aleatorio seguro; no se usa el conftest histórico de base fija.

## Crear claves y verificar un deployment posterior

1. En Cloudflare, abrir Turnstile, Add widget; asignar nombre y hostnames del
   frontend, elegir Managed y crear. No habilitar pre-clearance para este flujo.
2. Guardar el secret exclusivamente en configuración privada FastAPI; la sitekey
   va al entorno PHP. Producir una pareja distinta para staging/producción.
3. Establecer los hostnames exactos backend. Cloudflare puede incluir subdominios
   al registrar un dominio; esta aplicación sigue exigiendo coincidencia exacta.
4. Configurar `enabled` y reiniciar FastAPI/PHP. Confirmar un solo worker,
   HTTPS público, relojes sincronizados, salida HTTPS hacia Siteverify y acceso
   directo al backend restringido según el despliegue. Revisar 002–004 mediante
   el procedimiento de despliegue posterior; esta fase no migra la BD real.
5. Con cuenta y buzón exclusivos de staging, comprobar login normal sin recurso
   Cloudflare, tres fallos/428, desafío resuelto y éxito. Probar 429 duro incluso
   con token válido y rechazos cuando se interrumpe la salida Siteverify.
6. Revisar en Network/headers las tres acciones y ausencia absoluta de Cloudflare
   en ambas confirmaciones. No usar capturas/HAR con contraseñas/tokens reales.
7. Comprobar CSP, CSRF, cookie, sesión, no-store y no-referrer. Verificar métricas
   de eventos y repetir las suites antes de habilitar usuarios reales.

Pasos de creación basados en [Widget management oficial](https://developers.cloudflare.com/turnstile/get-started/widget-management/dashboard/)
y restricciones de [hostname management](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/).
No se crean recursos Cloudflare ni se realiza deployment durante esta entrega.

## Operación, métricas y troubleshooting

Configurar nivel INFO del logger de servicios para contar eventos saneados:
`event=turnstile_required`, `turnstile_success`, `turnstile_failure`,
`turnstile_unavailable`, `auth_hard_rate_limit`. Solo se incluye acción de allowlist
o scope fijo; no correo, recipient, password, JWT, token, secret ni respuesta
completa. `required` registra decisiones e intentos de verificación, no usuarios
únicos: no tratar ese conteo como número exacto de visitantes. INFO puede estar
deshabilitado por la configuración del proceso; unavailable se emite a WARNING.
No se añade Prometheus ni servicio externo.

| Síntoma | Revisión operativa |
| --- | --- |
| Startup rechaza configuración | Modo, secret correspondiente al entorno, CSV hostnames y rangos; no imprimir valores privados |
| 428 tras resolver | Acción del widget y hostname exactos; token nuevo, reloj y expiración; no reenviar token usado |
| 503 | Secret/sitekey configurados, salida TLS/DNS, disponibilidad Cloudflare y cupos externos; no deshabilitar automáticamente |
| 429 | Esperar Retry-After; Turnstile no modifica el bloqueo |
| Widget ausente en GET | Comportamiento normal adaptativo |
| Widget no carga tras 428 | CSP, bloqueadores, JS y sitekey del entorno PHP |
| Reset sin correo | Mantener respuesta uniforme; revisar worker solo con acceso operativo autorizado, nunca exponer existencia al solicitante |

Las ventanas globales, los cupos HTTP/Argon2 y las reservas en curso requieren
**UN SOLO proceso FastAPI**, como 6B.4A. Reiniciar borra presupuestos globales,
pero no hard buckets MySQL. No desplegar múltiples workers/instancias sin un
rediseño explícito de coordinación; no se incorpora Redis.

## Validación y deuda

La primera comprobación del árbol recibido dio 421 unitarias, 304 MySQL y 125
PHP. Los seis casos Chrome abortaron por restricciones de procesos del sandbox;
los mismos seis pasaron al repetirlos fuera del sandbox con autorización y
perfiles temporales nuevos. No se desactivó la seguridad del navegador.

La autoauditoría posterior reprodujo y corrigió estos hallazgos:

| Hallazgo | Corrección y regresión |
| --- | --- |
| El límite del body se comprobaba después de descargarlo entero | Streaming acotado, sin compresión; pruebas de corte temprano, longitud falsa, cierre, timeout y reset |
| JSON ambiguo o excesivo podía acompañar `success=true` | Rechazo de duplicados, constantes no JSON, profundidad/listas/strings excesivos y Unicode inválido; 503 y slots libres |
| `datetime.fromisoformat` aceptaba separadores como NUL/emoji y offsets normalizados | Formato temporal explícito antes del parseo, fronteras y formas válidas probadas |
| JSON muy anidado podía producir 500 en la ejecución anterior | La captura genérica recibida se conservó; regresión unitaria y HTTP real de los tres flujos confirma 503 sin mutaciones |

También se verificaron bypass/umbrales, reservas pendientes frente a fallos,
collation, replay simultáneo, seis cruces entre acciones, hostname, expiración,
presupuestos HTTP/Argon2, idempotency y liberación de cupos. Las carreras MySQL
cubren bloqueo, éxito paralelo, agotamiento de Argon2 y desactivación de cuenta
durante Siteverify, además de dos challenges concurrentes de acceso/reset.
No se encontró otro bypass ni fuga en esas pruebas.

La evidencia anti-enumeración compara status, body, todos los headers y la
secuencia SQL de los tres flujos para cuenta ausente, activa, inactiva y ADMIN.
Las variantes de casing/espacios/acentos comparten bucket por collation. La
decisión de challenge no consulta `usuarios` ni ejecuta Argon2; la ruta de
ejecución no depende de existencia. Esto evita introducir una diferencia de
timing por consulta de cuenta; no es una afirmación de tiempo constante de red.

La integración real PHP → FastAPI → MySQL, con Siteverify simulado, prueba los
tres formularios. El reset inexistente conserva LOOKUP_RESET sin recipient y
el worker termina con cero PASSWORD_RESET tokens, cero outbound y cero SMTP.
Los tests de 6C preservan destinatario canónico, confirmaciones, retries de
correo, sesiones revocables, RBAC y CSRF. 6A se ejecuta íntegramente mediante el
adaptador `test_6a_regression_mysql.py` dentro del esquema temporal.

Chrome comprueba 1440/390/320 px, layout sin overflow, teclado/foco, error de
challenge, success, expiración/timeout/reset manual, ausencia de loops,
credenciales sin repoblar y limpieza pagehide/pageshow. Cuatro casos adicionales
desactivan JavaScript en el navegador: login normal funciona y los tres flujos
challenged permanecen bloqueados con explicación. Ambas páginas de confirmación
solo hacen requests locales y limpian el fragmento/token sin Cloudflare.

Resultados finales del cierre, 2026-10-05 (sin sumar las repeticiones):

| Suite | Passed | Failed / Errors / Skipped |
| --- | ---: | --- |
| API `tests_unit` | 511 | 0 / 0 / 0 |
| MySQL temporal `tests_auth_mysql` | 328 | 0 / 0 / 0 |
| PHP HTTP y contratos | 125 | 0 / 0 / 0 |
| Chrome real con doubles offline | 10 | 0 / 0 / 0 |
| **Total** | **974** | **0 / 0 / 0** |

Los archivos de pruebas de Turnstile reúnen 215 casos unitarios, 104 MySQL,
27 PHP y 9 browser; el décimo browser es la regresión de autenticación 6C.
El cierre añadió 118 casos sobre el parcial recibido. La suite MySQL también
ejecuta 22 casos 6A, 71 RBAC, 66 acceso/recuperación, 18 correo, 22 autenticación,
22 hardening y 3 recorridos PHP reales. Las pruebas completas finales quedaron
verdes; la última repetición de browser, con capturas completas, dio 10 passed.

`php -l`: **49/49** archivos PHP del proyecto, sin errores.
`git diff --check`: limpio; también se comprueban los nueve archivos nuevos con
`git diff --no-index --check NUL <archivo>`, sin modificar el índice.
La revisión visual inspeccionó las capturas de escritorio y móviles, incluyendo
el widget completo a 320 y 390 px.

MySQL 8.0.46: el fixture final creó exclusivamente
`sistema_trazabilidad_test_auth_0dc54d9f2c7189b7`, probó upgrades/downgrades
001–004 preservando datos/DDL y confirmó su eliminación en el teardown. La BD
`sistema_trazabilidad` no se conectó desde las pruebas ni se migró/modificó.
El engine de aplicación está bloqueado en fixtures; los sender/transportes
externos se sustituyen explícitamente. No se ejecutó SMTP real ni Siteverify
contra Cloudflare. Quedan dos advertencias de deprecación de las dependencias
de test Starlette/httpx y AnyIO, sin fallos ni omisiones; actualizar esas
dependencias requiere su propia validación posterior.

Queda operación posterior: claves y hostnames reales, deployment/HTTPS,
alineación autorizada de la BD local, retención/purga 6C preexistente y protección
volumétrica de infraestructura. No se afirma haber validado Cloudflare en vivo.
No se hizo commit, push, SMTP real ni se creó ningún usuario real. La revisión
independiente es el siguiente paso.
