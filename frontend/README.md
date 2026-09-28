# Frontend PHP

PHP 8.1 o superior con la extensión cURL. No requiere Composer ni frameworks.
El frontend consume FastAPI; no accede directamente a MySQL.

Desde la raíz del proyecto, en PowerShell:

```powershell
& 'C:\xampp\php\php.exe' -S 127.0.0.1:8080 -t frontend
```

Abrir http://127.0.0.1:8080. Mantener FastAPI disponible en
http://127.0.0.1:8000. La URL de API se configura en `config/config.php`.
El servidor integrado de PHP se utiliza solamente para desarrollo local.

Rutas implementadas: `index.php?pagina=dashboard`,
`index.php?pagina=documentos` e `index.php?pagina=documento&id=1`.
Auditorías, evidencias y nuevo documento
muestran una vista provisional explícita. Las rutas desconocidas devuelven 404.

El dashboard consulta hasta 100 documentos y hasta 50 auditorías (límite
predeterminado de la API); los indicadores muestran ese alcance, sin afirmar
totales globales. Los cinco documentos recientes se ordenan por `updated_at`
dentro de la muestra consultada. Las fechas de la API en UTC se presentan
en horario de Ciudad de México.

Los errores de conexión producen estados de información no disponible,
nunca contadores ficticios de cero. La interfaz no incluye autenticación aún.

La ficha consulta documento, versiones, historial, áreas y usuarios. Las descargas
pasan por PHP y FastAPI, sin acceso directo al storage: PHP recibe el archivo en
un temporal, comprueba la respuesta y lo entrega como adjunto. El temporal se
cierra y elimina al completar la respuesta. El nombre original se conserva.

La carga utiliza el contrato OpenAPI: `archivo` y `subido_por_id` obligatorios;
`comentario_cambio` opcional. Se valida el archivo recibido por PHP y el usuario,
y se protege el formulario con un token CSRF de sesión. Una respuesta 201 produce
una redirección 303 a la ficha, con mensaje de éxito y datos consultados nuevamente.
La elección de usuario identifica al registrador; no sustituye una autenticación.
Las sesiones se guardan en `sistema-trazabilidad-frontend-sessions` dentro del
directorio temporal del sistema, fuera del directorio público del frontend.
Si no es posible abrir una sesión, el envío queda deshabilitado con un mensaje.

Los límites efectivos de carga dependen de `upload_max_filesize` y `post_max_size`
de PHP y se muestran en el formulario. El archivo debe dejar margen para los
campos y las cabeceras del envío multipart dentro de `post_max_size`.
No se envían cargas de validación a la base oficial. Queda pendiente una carga
manual autorizada de un archivo real para validar el flujo completo de escritura.
