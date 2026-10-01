<?php
if (!isset($route)) { http_response_code(404); exit; }
$documentResult = api_get_all('/api/v1/documentos');
$areaResult = api_get('/api/v1/areas');
$documents = $documentResult['data'];
$areaNames = areas_by_id($areaResult['data']);
$documentCount = count($documents);
$filterValues = ['q' => list_query('q'), 'estado' => list_query('estado'), 'area_id' => list_query('area_id')];
$stateOptions = [];
foreach (['DRAFT', 'ACTIVE', 'OBSOLETE', 'ARCHIVED'] as $state) $stateOptions[$state] = document_status($state)[0];
foreach ($documents as $doc) {
    $id = positive_id($doc['area_id'] ?? null);
    if ($id !== null && !isset($areaNames[$id])) $areaNames[$id] = 'Área #' . $id;
}
$documents = array_values(array_filter($documents, fn(array $doc): bool =>
    list_matches($doc, $filterValues['q'], ['codigo', 'titulo'])
    && ($filterValues['estado'] === '' || ($doc['estado'] ?? '') === $filterValues['estado'])
    && ($filterValues['area_id'] === '' || (string) ($doc['area_id'] ?? '') === $filterValues['area_id'])
));
