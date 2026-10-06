# Bootstrap local del primer ADMIN

`scripts/bootstrap_admin.py` es la excepción administrativa inicial para una
instalación local que ya tiene Alembic **004** y **cero ADMIN activos**. Requiere
MySQL 8+, `APP_ENV=development`, loopback, puerto 3306 y la BD exacta
`sistema_trazabilidad`. No es una ruta HTTP ni un mecanismo general de altas.

Desde la raíz del repositorio, en una consola interactiva:

```powershell
.\api\venv\Scripts\python.exe -B scripts\bootstrap_admin.py
```

La CLI solicita nombre (2–160 caracteres), correo, contraseña oculta mediante
`getpass`, repetición y la confirmación literal `CREAR ADMIN LOCAL`. No acepta
datos mediante argumentos. Si la consola no permite entrada oculta, aborta.
No use chat, archivos, variables de entorno ni command history para la contraseña.

Reutiliza `valid_address`, `normalize_email`, `hash_password` y `Usuario`.
La política de contraseña es la vigente: 12–1024 caracteres y Argon2id.
`Usuario` no requiere área; ID y timestamps se generan mediante el modelo.
El correo se guarda normalizado. MySQL y `uq_usuarios_correo_normalizado`, con
`utf8mb4_unicode_ci`, rechazan también equivalencias de mayúsculas y acentos.

El rol siempre es `ADMIN` y la cuenta queda activa. Un named lock MySQL ligado
al schema serializa dos bootstraps concurrentes, con espera máxima de cinco
segundos. Se conserva la misma conexión hasta terminar la transacción y liberar
el lock. Dentro de la transacción se vuelve a comprobar bajo `FOR UPDATE` que
no exista ADMIN activo; las restricciones únicas son la última defensa del correo.
El lock es de conexión y no requiere tablas ni migraciones nuevas.

La creación tiene una sola transacción de usuario y rollback ante fallo. No
modifica cuentas preexistentes, crea solicitudes ficticias, genera sesiones/JWT,
hace autologin ni encola/envía correo. Nunca imprime contraseñas ni hashes.
Un error de driver devuelve un mensaje fijo; ante incertidumbre de commit,
inspeccione el estado antes de repetir. El bootstrap queda **lógicamente
deshabilitado mientras exista al menos un ADMIN activo**; aborta antes de pedir
credenciales. No es un marcador permanente: si todos los ADMIN se desactivan,
la condición vuelve a permitir bootstrap y exige control operativo de la consola.

Para las altas posteriores use solicitudes de acceso, aprobación ADMIN y
`INITIAL_PASSWORD`. Para contraseñas de usuarios existentes use la herramienta
ya disponible `gestionar_usuario.py`, con su confirmación específica.

Antes de operar sobre la BD real, confirmar Git, destino local, revisión 004,
backup validado, inventario de datos/storage y cero ADMIN. Los tests del bootstrap
usan exclusivamente el schema aleatorio propiedad de `tests_auth_mysql`.

JWT local: `api/.env` es privado e ignorado. `JWT_SECRET_KEY` debe ser aleatorio y
cumplir `validate_jwt_config`; `JWT_ALGORITHM=HS256` exige al menos 32 bytes.
No copiar claves a `.env.example`, documentación ni logs. Reiniciar la API después
de cambiar el entorno. Los smoke locales conservan `TURNSTILE_MODE=disabled`, un
solo proceso FastAPI y SMTP/Cloudflare bloqueados; correo únicamente simulado.
