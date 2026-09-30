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
`index.php?pagina=documentos`, `index.php?pagina=documento_nuevo`
e `index.php?pagina=documento&id=1`; también `auditorias`, `auditoria_nueva`,
`auditoria&id=1`, `evidencias`, `evidencia_archivo`, `evidencia_logica`
y `evidencia&id=1` mediante el parámetro `pagina`. Las rutas desconocidas
y los identificadores inválidos devuelven 404.

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

## Alta de documentos

El formulario de alta envía `POST /api/v1/documentos?creador_id=...` con JSON:
`codigo`, `titulo`, `descripcion`, `tipo`, `estado`, `area_id`, `responsable_id`.
Según OpenAPI, código tiene entre 2 y 80 caracteres, título entre 3 y 240 y tipo
entre 2 y 40. Tipo es texto libre, sin catálogo ni enum. Descripción es opcional.
Estado usa los valores documentados DRAFT, ACTIVE, OBSOLETE y ARCHIVED, con DRAFT
como predeterminado. Los selectores consultan áreas y usuarios activos.

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
