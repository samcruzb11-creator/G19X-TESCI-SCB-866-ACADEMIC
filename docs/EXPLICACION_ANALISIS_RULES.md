# Reglas locales de análisis documental

**Módulo:** `api/app/services/analisis_rules.py`

## 1. Responsabilidad del módulo

Este módulo aporta reglas deterministas para señalar posibles coincidencias de nombres, validar el formato de hashes y comprobar rutas y disponibilidad de archivos. Complementa las consultas de anomalías de `analisis_queries.py`; `analisis_service.py` integra sus resultados en el detalle de documentos y versiones dentro del alcance autorizado.

## 2. Implementación

**Normalización y separación del nombre.** `normalized_name()` aplica normalización Unicode NFKC y `casefold()`, sustituye la puntuación por espacios y unifica los espacios repetidos. Conserva acentos y dígitos. `name_parts()` reconoce separadores `/` y `\`, toma el último componente y devuelve el nombre base normalizado y la última extensión. Así, diferencias de mayúsculas, puntuación o caracteres de ancho completo no impiden comparar nombres equivalentes.

**Similitud.** `similarity()` exige extensiones iguales y no vacías, nombres base de al menos ocho caracteres y una palabra normalizada en común. Ordena ambos nombres para evitar que el resultado dependa del orden de los argumentos y calcula `SequenceMatcher(..., autojunk=False).ratio()`. Devuelve la puntuación si alcanza el umbral inclusivo comprobado por `reaches_threshold()`; en otro caso devuelve `None`.

La selección de candidatos ocurre en `analisis_service.detail()`: utiliza una sola versión de referencia, la solicitada o la de mayor número entre las visibles del documento. Busca versiones autorizadas de otros documentos con igual tamaño registrado, extensión compatible y hashes registrados válidos y distintos. Después aplica la comparación de nombres y genera señales `POSIBLE_DUPLICADO`, sujetas a revisión humana.

**Formato del hash.** `valid_hash()` acepta únicamente cadenas de 64 caracteres hexadecimales, con letras mayúsculas o minúsculas. No lee el archivo ni calcula su SHA-256. Las coincidencias de hashes registradas se detectan en las consultas SQL; comprobar la integridad del archivo almacenado requiere leer su contenido y contrastar el hash calculado, como hace `storage_integrity.py`.

**Almacenamiento.** `storage_status()` admite referencias bajo `documents` o `evidence`, rechaza recorridos con `..`, codificación porcentual, caracteres nulos y enlaces simbólicos o junctions. Delega la resolución y las restricciones adicionales de ruta a `storage.get_absolute_path()`. Devuelve `RUTA_NO_SEGURA` ante referencias rechazadas, `ARCHIVO_NO_DISPONIBLE` si no encuentra un archivo regular o hay un error del sistema de archivos, y `None` si la comprobación es satisfactoria. Sólo consulta el estado de la ruta; no abre el contenido ni garantiza su lectura posterior.

**Política local.** `LocalPolicy` es una dataclass inmutable con valores predeterminados de 0.92 para similitud, 64 candidatos, 100 versiones y ocho caracteres mínimos. Valida el umbral entre 0.8 y 1 y ambos límites entre 1 y 100. `POLICY` toma el umbral de la configuración. El servicio aplica los límites a las comparaciones de nombres y comprobaciones locales de versiones, e informa si quedaron candidatos o versiones sin revisar.

## 3. Decisiones de diseño

Las reglas explícitas permiten explicar cada señal sin entrenamiento de modelos. La normalización reduce diferencias de escritura; exigir extensión y palabras comunes restringe comparaciones poco útiles. Los límites acotan el trabajo local sin comparar todas las versiones entre sí. Las verificaciones de rutas restringen la inspección al almacenamiento administrado y evitan seguir enlaces hacia otros destinos.

## 4. Limitaciones

El módulo no utiliza Ollama, LLM ni modelos entrenados y no interpreta semánticamente los documentos. Un nombre parecido no demuestra contenido idéntico; un hash con formato válido tampoco demuestra integridad. Las reglas pueden señalar coincidencias no relevantes u omitir casos por sus restricciones y límites. Estas funciones no constituyen todo el análisis: las consultas, la autorización y la presentación de resultados corresponden a otros módulos.

## 5. Referencias

- [Reglas locales](../api/app/services/analisis_rules.py), [servicio de análisis](../api/app/services/analisis_service.py) y [consultas de análisis](../api/app/services/analisis_queries.py).
- [Configuración](../api/app/core/config.py), [servicio de almacenamiento](../api/app/services/storage_service.py) y [verificación de integridad](../api/app/services/storage_integrity.py).
- [Pruebas unitarias del análisis](../api/tests_unit/test_analisis_unit.py) y [pruebas sobre MySQL](../api/tests_auth_mysql/test_analisis_mysql.py).
