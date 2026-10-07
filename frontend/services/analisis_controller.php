<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    throw new ApiPageError(405, 'Esta página admite únicamente consultas.');
}
header('Cache-Control: no-store');
require_once __DIR__.'/analisis_helpers.php';
require_once __DIR__.'/dashboard_helpers.php';
$analysisFilters = ['limit'=>20,'offset'=>dashboard_offset($_GET['offset'] ?? '0')];
foreach (['tipo'=>array_keys(analysis_types()), 'severidad'=>['INFO','WARNING']] as $key=>$allowed) {
    $value = $_GET[$key] ?? '';
    if (!is_string($value) || ($value !== '' && !in_array($value,$allowed,true))) throw new ApiPageError(422,'Filtro de análisis inválido.');
    if ($value !== '') $analysisFilters[$key] = $value;
}
foreach (['auditoria_id','documento_id','version_id'] as $key) {
    $value = $_GET[$key] ?? '';
    if ($value === '') continue;
    $id = analysis_id($value);
    if ($id === null) throw new ApiPageError(422,'Identificador de análisis inválido.');
    if ($key === 'auditoria_id' && !can_show_action('auditorias')) throw new ApiPageError(403,'No tiene permiso para consultar auditorías.');
    $analysisFilters[$key] = $id;
}
$analysisDetail = isset($analysisFilters['documento_id']) || isset($analysisFilters['version_id']);
if ($analysisDetail) {
    $path = isset($analysisFilters['version_id']) ? '/api/v1/analisis/versiones/'.$analysisFilters['version_id']
        : '/api/v1/analisis/documentos/'.$analysisFilters['documento_id'];
    $analysisResult = api_get_object($path, array_diff_key($analysisFilters,['version_id'=>true]));
    $analysisData = $analysisResult['ok'] ? $analysisResult['data']['anomalias'] : null;
    $analysisSummary = null;
} else {
    $analysisSummary = api_get_object('/api/v1/analisis/resumen', array_intersect_key($analysisFilters,['auditoria_id'=>true]));
    $analysisResult = api_get_object('/api/v1/analisis/anomalias',$analysisFilters);
    $analysisData = $analysisResult['ok'] ? $analysisResult['data'] : null;
}
