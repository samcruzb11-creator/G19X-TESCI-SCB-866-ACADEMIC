# Referencia de configuración

Copie `api/.env.example` a `api/.env` privado. Settings lee UTF-8 en esa ubicación; variables del proceso prevalecen. Reinicie al cambiar configuración. No cree dotenv bajo el web root PHP. Contraseñas demo no equivalen a DB/JWT/SMTP secrets.

## Aplicación, DB y JWT — obligatorio

| Variable | Uso/default y condición |
|---|---|
| APP_NAME | Título: Sistema de Trazabilidad Documental |
| APP_ENV | development para seed local; production deshabilita seed y claves challenge test |
| DEBUG | false; true registra sólo tipo de error, no trazas HTTP |
| API_V1_PREFIX | /api/v1; cambiar exige adaptar consumidores, no recomendado en demo |
| DB_HOST | 127.0.0.1; MySQL 8 real; seed sólo loopback |
| DB_PORT | 3306, puerto del servidor |
| DB_NAME | Schema migrado; usar uno independiente para evaluación |
| DB_USER | Cuenta local del schema; root default no es recomendación productiva |
| DB_PASSWORD | Secreto operativo privado; no demo ni valor inventado |
| JWT_SECRET_KEY | CSPRNG privado obligatorio, placeholder rechazado; mínimo 32/48/64 bytes para HS256/384/512 |
| JWT_ALGORITHM | HS256 default; sólo HS256/384/512 |

## Login — presupuestos de un proceso

| Variable | Default | Función |
|---|---|---|
| RATE_LIMIT_LOGIN_REQUESTS_PER_MINUTE | 120 | Requests globales de login/minuto |
| RATE_LIMIT_IDENTIFIER_REQUESTS_PER_MINUTE | 10 | Requests por identificador/minuto |
| RATE_LIMIT_FAILURE_WINDOW_SECONDS | 600 | Ventana persistida; máximo 1200 s |
| RATE_LIMIT_CHALLENGE_FAILURES | 5 | Umbral de bloqueo/challenge; no se evita con challenge válido |
| RATE_LIMIT_ARGON2_PER_MINUTE | 60 | Presupuesto de trabajo caro global |
| RATE_LIMIT_ARGON2_CONCURRENCY | 2 | Hashes simultáneos, rango 1–32 |

Un solo proceso API; los presupuestos en memoria no se comparten entre workers. No aumente límites para esconder fallos.

## Turnstile — opcional para evaluación

| Variable | Default | Función |
|---|---|---|
| TURNSTILE_MODE | disabled | disabled/test/enabled; test prohibido en production; disabled conserva límites locales |
| TURNSTILE_SECRET_KEY | vacío | Secreto privado backend, requerido enabled |
| TURNSTILE_EXPECTED_HOSTNAMES | vacío | Allowlist exacta por comas, sin esquema/puerto/ruta/wildcard |
| TURNSTILE_VERIFY_TIMEOUT_SECONDS | 5 | Timeout externo, 0.1–10 s |
| TURNSTILE_VERIFY_GLOBAL_PER_MINUTE | 60 | POST externos, incluido retry acotado |
| TURNSTILE_VERIFY_CONCURRENCY | 4 | Verificaciones simultáneas, 1–32 |

PHP recibe sólo `TURNSTILE_SITE_KEY` pública mediante entorno del proceso. FastAPI decide y verifica desafíos. [Fase Turnstile](historico/FASE_6B_4B_TURNSTILE.md).

## Acceso y recuperación

| Variable | Default/máximo | Función |
|---|---|---|
| RESET_REQUEST_PER_HOUR | 3 | Reset por identificador/hora |
| RESET_REQUEST_GLOBAL_PER_MINUTE | 20 | Requests globales de reset |
| ACCESS_REQUEST_PER_DAY | 2 | Solicitudes por identificador/día |
| ACCESS_REQUEST_GLOBAL_PER_MINUTE | 10 | Solicitudes globales/minuto |
| ACTION_CONFIRM_PER_MINUTE | 5 | Confirmaciones por acción/identificador |
| ACTION_CONFIRM_GLOBAL_PER_MINUTE | 30 | Presupuesto global de confirmación |
| ACTION_HASH_PER_MINUTE | 5 | Trabajo caro de acciones de cuenta |
| PASSWORD_RESET_TTL_SECONDS | 1800 | TTL reset, rango 60–1800; inicial fijo 1800 |

Los presupuestos de 6C sólo pueden reducirse desde sus máximos; ADMIN no los evita.

## SMTP — requerido para correo, opcional para recorrido documental

| Variable | Default | Función |
|---|---|---|
| SMTP_HOST | vacío | Servidor genérico; ausente equivale a servicio no disponible |
| SMTP_PORT | 587 | Puerto del servidor TLS, 1–65535 |
| SMTP_USERNAME | vacío | Identidad de autenticación si el relay la requiere |
| SMTP_PASSWORD | vacío | SecretStr privado; nunca imprimir/exportar/loggear |
| SMTP_SECURITY | starttls | Sólo starttls/ssl; no envío en claro |
| SMTP_FROM_ADDRESS | vacío | Remitente autorizado validado |
| SMTP_FROM_NAME | Sistema de Trazabilidad | Nombre público sin saltos de línea |
| SMTP_TIMEOUT_SECONDS | 5 | Timeout, rango 1–10 s |
| PUBLIC_FRONTEND_URL | http://127.0.0.1:8080 en ejemplo | Base fija; HTTPS salvo development loopback, sin query/fragment/userinfo |

No hay SMTP_ENABLED/USER/FROM/USE_TLS. Ejecute worker separado; [procedimiento y estado real pendiente](SMTP_RECUPERACION.md). El ejemplo sólo contiene placeholders/campos vacíos. No se crea una cuenta externa para completar configuración.

## Storage y análisis

| Variable | Default | Función |
|---|---|---|
| STORAGE_PATH | storage | Compatibilidad; validador fija storage/ junto a raíz y no permite reubicarlo |
| MAX_DOCUMENT_FILE_BYTES | 20971520 | 20 MiB por versión; rango 1–1 GiB |
| MAX_EVIDENCE_FILE_BYTES | 20971520 | 20 MiB por FILE; mismo rango |
| ANALYSIS_SIMILARITY_THRESHOLD | 0.92 | Similitud determinista, 0.8–1; no configura modelo ML |

PHP puede limitar más por upload_max_filesize/post_max_size. Body JSON mutativo: 1 MiB; multipart añade 128 KiB de margen al máximo del archivo. No son variables adicionales de dotenv.

## PHP y pruebas

| Variable/configuración | Uso |
|---|---|
| AUTH_API_TIMEOUT_SECONDS | Default 15, 1–120; sólo entorno PHP para auth |
| FRONTEND_COOKIE_SECURE | auto/always; always requiere HTTPS |
| TURNSTILE_SITE_KEY | Clave pública del entorno PHP; requerida ante challenge |
| API_BASE_URL en config.php | Constante http://127.0.0.1:8000; no env actual |
| PHP_TEST_BINARY / CHROME_TEST_BINARY | Ejecutables alternativos para tests |
| AUTH_MYSQL_TEST / AUTH_BROWSER_TEST | 1 opt-in de schemas efímeros y Chrome aislado |
| PYTHONPATH | Raíz api para pytest desde raíz |
| PYTHONDONTWRITEBYTECODE | 1 evita bytecode durante verificación |

Producción requiere HTTPS, gestión privada de secretos, privilegios separados, programación del worker y backup/restauración probado. Ese despliegue no se ha ejecutado como parte de la entrega local.
