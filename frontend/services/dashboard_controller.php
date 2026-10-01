<?php
if (!isset($route)) { http_response_code(404); exit; }
$documentResult = api_get('/api/v1/documentos', ['limit' => 100]);
$auditResult = can_show_action('auditorias') ? api_get('/api/v1/auditorias') : ['ok' => true, 'data' => []];
$areaResult = api_get('/api/v1/areas');
$allDocuments = $documentResult['data'];
$areaNames = areas_by_id($areaResult['data']);
$currentVersions = count(array_filter($allDocuments, fn(array $doc): bool => positive_id($doc['version_vigente_id'] ?? null) !== null));
$activeAreas = count(array_filter($areaResult['data'], fn(array $area): bool => ($area['activa'] ?? false) === true));
$metrics = [
    ['label' => 'Documentos registrados', 'value' => $documentResult['ok'] ? count($allDocuments) : null, 'note' => 'En la consulta · hasta 100'],
    ['label' => 'Auditorías registradas', 'value' => $auditResult['ok'] ? count($auditResult['data']) : null, 'note' => 'En la consulta · hasta 50'],
    ['label' => 'Áreas activas', 'value' => $areaResult['ok'] ? $activeAreas : null, 'note' => 'Catálogo de áreas'],
    ['label' => 'Con versión vigente', 'value' => $documentResult['ok'] ? $currentVersions : null, 'note' => 'De los documentos consultados'],
];
if (!can_show_action('auditorias')) unset($metrics[1]);
if (user_has_role('APROBADOR')) unset($metrics[3]);
$documents = $allDocuments;
usort($documents, function (array $a, array $b): int {
    $dateA = is_string($a['updated_at'] ?? null) ? $a['updated_at'] : '';
    $dateB = is_string($b['updated_at'] ?? null) ? $b['updated_at'] : '';
    return strcmp($dateB, $dateA) ?: ((positive_id($b['id'] ?? null) ?? 0) <=> (positive_id($a['id'] ?? null) ?? 0));
});
$documents = array_slice($documents, 0, 5);
