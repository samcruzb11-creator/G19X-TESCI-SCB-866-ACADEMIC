<?php
declare(strict_types=1);
if (!isset($recordId, $route) || $recordId === null) { http_response_code(404); exit; }
$evidenceResult = api_get_object('/api/v1/evidencias/' . $recordId);
$evidence = $evidenceResult['data'];
if ($evidenceResult['ok'] && positive_id($evidence['id'] ?? null) !== $recordId) $evidenceResult = api_failure();
if (!$evidenceResult['ok']) { http_response_code($evidenceResult['status'] === 404 ? 404 : 502); return; }
$downloadError = null;
if (($_GET['accion'] ?? null) === 'descargar' && ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'GET') {
    $download = ($evidence['tipo'] ?? '') === 'FILE' ? api_download('/api/v1/evidencias/' . $recordId . '/descargar') : api_failure(400);
    if ($download['ok']) send_api_download($download, $evidence);
    $downloadError = match ($download['status']) { 400 => 'Esta evidencia no contiene un archivo descargable.', 404 => 'El archivo de la evidencia no está disponible.', default => 'No fue posible descargar la evidencia. Intenta nuevamente.' };
    http_response_code(in_array($download['status'], [400, 404], true) ? $download['status'] : 502);
}
$userResult = api_get('/api/v1/usuarios');
$userNames = areas_by_id($userResult['data']);
$sessionReady = frontend_session_start();
$successMessage = $_SESSION['evidence_success'][$recordId] ?? null;
unset($_SESSION['evidence_success'][$recordId]);
session_write_close();
