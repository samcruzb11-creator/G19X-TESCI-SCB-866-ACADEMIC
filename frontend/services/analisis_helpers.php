<?php
declare(strict_types=1);

function analysis_types(): array
{
    return ['DUPLICATE_HASH'=>'Coincidencia entre documentos','HASH_REPETIDO'=>'Contenido repetido',
        'VERSION_SIN_CAMBIO'=>'Versión sin cambio','SECUENCIA_TEMPORAL'=>'Orden temporal',
        'NUMERO_VERSION_DUPLICADO'=>'Número de versión repetido','METADATA_INCOMPLETA'=>'Metadatos incompletos',
        'DOCUMENTO_SIN_VERSION'=>'Documento sin versiones','VERSION_VIGENTE_INCONGRUENTE'=>'Versión vigente incongruente',
        'RELACION_INCONGRUENTE'=>'Relación incongruente','ESTADO_DESCONOCIDO'=>'Estado no reconocido',
        'POSIBLE_DUPLICADO'=>'Posible duplicado por nombre','ARCHIVO_NO_DISPONIBLE'=>'Archivo no disponible',
        'RUTA_NO_SEGURA'=>'Ruta no segura'];
}

function analysis_id(mixed $value): ?string
{
    if (is_int($value)) $value = (string)$value;
    if (!is_string($value) || !preg_match('/\A[1-9][0-9]{0,19}\z/', $value)) return null;
    $max = '18446744073709551615';
    return strlen($value) < 20 || strcmp($value, $max) <= 0 ? $value : null;
}

function analysis_destination(mixed $destination): ?string
{
    if (!is_array($destination)) return null;
    $module = ['documento'=>'documentos','hallazgo'=>'hallazgos','evidencia'=>'evidencias'];
    $page = $destination['pagina'] ?? null;
    $id = analysis_id($destination['id'] ?? null);
    if (!is_string($page) || !isset($module[$page]) || $id === null || !can_show_action($module[$page])) return null;
    // Existing detail pages use native PHP integers; do not emit broken huge-ID links.
    if (positive_id($id) === null) return null;
    return page_url($page, ['id'=>$id]);
}
