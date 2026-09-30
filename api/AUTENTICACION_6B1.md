# Autenticación backend 6B.1

Estado: Fase 6B.1 cerrada con aprobación del usuario tras validación final aislada.
El cierre comprende exclusivamente autenticación backend; 6B.2 no iniciada.

Implementación limitada a autenticación. Los routers de negocio todavía no
requieren identidad: se protegerán en 6B.2. PHP no se modifica en este bloque.
No hay registro público, refresh tokens ni limitador de login todavía.

## Preparación explícita

La migración aditiva `002` crea únicamente `auth_sessions` en MySQL.
No se ejecuta automáticamente; preparar/revisar su aplicación antes de usar
los endpoints o la herramienta de credenciales. No se modifican tablas existentes.

Configurar `JWT_SECRET_KEY` con un secreto aleatorio privado de al menos 32
bytes para HS256 (48 para HS384, 64 para HS512). Usar un generador criptográfico;
no copiar ejemplos ni contraseñas. El secreto no se incluye en el repositorio.
La validación se realiza en el lifespan al iniciar FastAPI: una configuración
insegura impide el startup (fail-fast), antes de servir peticiones. Imports,
Alembic y herramienta local no necesitan inicializar HTTP. La dependencia
conserva además la comprobación defensiva por petición (503).

Se mantiene `JWT_ALGORITHM`, restringido a HS256/HS384/HS512. Longitud y diversidad
son comprobaciones mínimas; no prueban entropía: el secreto debe ser aleatorio.

## Credenciales de usuarios existentes

Desde la raíz, en una terminal que permita entrada oculta:

```powershell
api/venv/Scripts/python.exe scripts/gestionar_usuario.py --usuario-id 123 --correo usuario@dominio.mx
```

La selección exige ID y correo coincidentes. Solicita contraseña oculta de
12–1024 caracteres, repetición y confirmación explícita. No crea usuarios ni
activa cuentas. Actualiza solo esa contraseña mediante Argon2id y revoca solo
las sesiones de ese usuario en la misma transacción. No admite contraseña CLI.
Rechaza terminales donde getpass tendría que mostrar la contraseña.

El correo se normaliza con strip/lower, sin reglas específicas de proveedores.
La columna existente no contiene un normalizador ejecutable; esta convención
se utiliza en login y en la selección explícita de credenciales, sin transformar
los datos actuales. Hashes antiguos inválidos no autentican: deben aprovisionarse.

## Contrato

- POST `/api/v1/auth/login`: JSON `correo` y `password`; devuelve `access_token`,
  `token_type=bearer`, `expires_in=900`.
- GET `/api/v1/auth/me`: Authorization Bearer; devuelve ID, nombre, correo y
  rol actual de BD, sin hash ni metadatos de sesión.
- POST `/api/v1/auth/logout`: Authorization Bearer; 204 tras revocar únicamente
  ese SID. Repetir con el token revocado devuelve 401 sin modificar otras sesiones.

JWT contiene solo sub/sid/iat/exp. SID aleatorio de 256 bits, sesión persistida
con fechas UTC y comparación exacta con el token. Se validan firma, algoritmo,
tipos y fechas, usuario activo, pertenencia y revocación en cada petición.
No se usa un rol del token. Las respuestas exitosas usan Cache-Control no-store.
Los errores de validación auth no reflejan entradas que puedan contener secretos.

Login serializa creación de sesión con cambios de contraseña y revalida el
usuario bajo bloqueo. No modifica transacciones documentales ni storage.
Logout invalida peticiones posteriores; una petición autenticada previamente
puede estar ya en curso. Fallos de commit no se reintentan automáticamente.

## Pruebas

`venv/Scripts/python.exe -m pytest tests_unit -p no:cacheprovider -q` desde api.
Pruebas auth con dobles en memoria y conexiones SQLAlchemy prohibidas.
Para integración real aislada, desde api:

```powershell
$env:AUTH_MYSQL_TEST='1'
venv/Scripts/python.exe -m pytest tests_auth_mysql -p no:cacheprovider -q -s
```

La suite conecta al servidor MySQL local sin seleccionar la BD de la aplicación,
comprueba MySQL 8+, crea un esquema nuevo con sufijo aleatorio
`sistema_trazabilidad_test_auth_<16 hex>` y confirma la BD en cada checkout.
Alembic recibe una conexión explícita a ese esquema: nunca usa el engine real.
Al terminar elimina únicamente el esquema creado por esa ejecución; aborta si
el nombre ya existía. No trunca tablas, ni usa storage ni datos reales.

Se verificó en MySQL 8.0.46 el ciclo 001 -> 002 -> 001 -> 002, preservando DDL
y registros de prueba de todas las tablas de negocio. Downgrade elimina solo
auth_sessions (incluidas FK e índices); pierde sesiones y deja inválidos sus JWT.
También se verificaron login/logout, revocación, expiración, cambio de contraseña,
dos logins concurrentes y rechazo del login antiguo tras cambio confirmado,
incluyendo rollback de escritura de sesión/credenciales ante fallo precommit.

Validación final: 109 pruebas unitarias y 22 de integración MySQL aprobadas
(131 en conjunto). Dos avisos de deprecación del TestClient; sin cambios de
dependencias. Se verificaron además tipos/claims ausentes, algoritmos permitidos,
rechazo de tokens sin firma, fail-fast y rechazo de entrada visible de contraseña.
No se ejecutaron las suites históricas que truncan tablas ni la BD oficial.
