<?php
declare(strict_types=1);

function e(mixed $value): string
{
    return htmlspecialchars(is_scalar($value) ? (string) $value : '', ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function positive_id(mixed $value): ?int
{
    if (!is_int($value) && !is_string($value)) {
        return null;
    }
    $id = filter_var($value, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
    return $id === false ? null : $id;
}

function page_url(string $page, array $parameters = []): string
{
    return 'index.php?' . http_build_query(['pagina' => $page] + $parameters, '', '&', PHP_QUERY_RFC3986);
}

function document_status(mixed $state): array
{
    $states = [
        'ACTIVE' => ['Activo', 'success'],
        'DRAFT' => ['Borrador', 'neutral'],
        'OBSOLETE' => ['Obsoleto', 'warning'],
        'ARCHIVED' => ['Archivado', 'neutral'],
        'PENDING' => ['Pendiente', 'warning'],
        'REJECTED' => ['Rechazado', 'danger'],
    ];
    return is_string($state) ? ($states[$state] ?? ['Sin clasificar', 'neutral']) : ['Sin clasificar', 'neutral'];
}

function display_date(mixed $value): string
{
    if (!is_string($value) || $value === '') {
        return '—';
    }
    try {
        return (new DateTimeImmutable($value, new DateTimeZone('UTC')))
            ->setTimezone(new DateTimeZone(DISPLAY_TIMEZONE))->format('d/m/Y H:i');
    } catch (Exception $exception) {
        return '—';
    }
}

function areas_by_id(array $areas): array
{
    $map = [];
    foreach ($areas as $area) {
        $id = positive_id($area['id'] ?? null);
        if ($id !== null && is_string($area['nombre'] ?? null)) {
            $map[$id] = $area['nombre'];
        }
    }
    return $map;
}

function area_name(array $document, array $areaNames): string
{
    $id = positive_id($document['area_id'] ?? null);
    return $id === null ? '—' : ($areaNames[$id] ?? 'Área #' . $id);
}

function version_label(array $document): string
{
    $version = $document['version_vigente'] ?? null;
    if (is_array($version)) {
        $number = positive_id($version['numero_version'] ?? null);
        if ($number !== null) {
            return 'v' . $number;
        }
    }
    if (user_has_role('APROBADOR')) return 'No disponible';
    return positive_id($document['version_vigente_id'] ?? null) !== null ? 'Registrada' : 'Sin versión';
}

function user_name(mixed $id, array $users): string
{
    $id = positive_id($id);
    return $id === null ? '—' : ($users[$id] ?? 'Usuario #' . $id);
}

function file_size_label(mixed $size): string
{
    if (!is_numeric($size) || (float) $size < 0) return '—';
    $bytes = (float) $size;
    if ($bytes >= 1048576) return number_format($bytes / 1048576, 2, ',', '.') . ' MB';
    if ($bytes >= 1024) return number_format($bytes / 1024, 1, ',', '.') . ' KB';
    return number_format($bytes, 0, ',', '.') . ' bytes';
}

function download_url(int $documentId, int $versionId): string
{
    return page_url('documento', ['id' => $documentId, 'accion' => 'descargar', 'version_id' => $versionId]);
}

function event_label(mixed $action): string
{
    if (!is_string($action)) return 'Evento registrado';
    return [
        'CREACION_DOCUMENTO' => 'Creación del documento',
        'CREACION_VERSION' => 'Carga de versión',
        'ACTUALIZACION_DOCUMENTO' => 'Actualización del documento',
        'CREACION_AUDITORIA' => 'Creación de la auditoría',
        'ACTUALIZACION_AUDITORIA' => 'Edición de la auditoría',
        'ACTIVACION_AUDITORIA' => 'Activación de la auditoría',
        'REVISION_AUDITORIA' => 'Entrada a revisión',
        'REACTIVACION_AUDITORIA' => 'Regreso a activa',
        'CIERRE_AUDITORIA' => 'Cierre de la auditoría',
    ][$action] ?? str_replace('_', ' ', $action);
}

/** Show only business fields, never raw JSON, storage paths or client network data. */
function event_details(array $event): array
{
    $new = is_array($event['datos_nuevos'] ?? null) ? $event['datos_nuevos'] : [];
    $old = is_array($event['datos_anteriores'] ?? null) ? $event['datos_anteriores'] : [];
    $labels = ['codigo' => 'Código', 'titulo' => 'Título', 'tipo' => 'Tipo', 'estado' => 'Estado',
        'numero_version' => 'Versión', 'nombre_original' => 'Archivo', 'comentario_cambio' => 'Comentario',
        'descripcion' => 'Descripción', 'area_id' => 'Área (ID)', 'responsable_id' => 'Responsable (ID)'];
    $details = [];
    foreach ($labels as $key => $label) {
        if (!array_key_exists($key, $new) || (!is_scalar($new[$key]) && $new[$key] !== null)) continue;
        $value = $new[$key] === null || $new[$key] === '' ? 'Sin valor' : (string) $new[$key];
        if (array_key_exists($key, $old) && (is_scalar($old[$key]) || $old[$key] === null) && $old[$key] !== $new[$key]) {
            $value = ($old[$key] === null ? 'Sin valor' : (string) $old[$key]) . ' → ' . $value;
        }
        $details[] = $label . ': ' . $value;
    }
    if (($new['version_vigente_actualizada'] ?? false) === true) $details[] = 'Asignada como versión vigente';
    return $details ?: ['Cambio registrado en el documento.'];
}
