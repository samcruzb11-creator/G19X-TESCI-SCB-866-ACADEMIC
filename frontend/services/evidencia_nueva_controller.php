<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
require_once __DIR__ . '/evidencia_form.php';
$fileMode = $page === 'evidencia_archivo';
$auditResult = api_get_all('/api/v1/auditorias');
$documentResult = api_get_all('/api/v1/documentos');
$availableAudits = array_values(array_filter($auditResult['data'], fn(array $row): bool => positive_id($row['id'] ?? null) !== null && !in_array($row['estado'] ?? '', ['COMPLETED','CANCELLED'],true)));
$availableDocuments = $documentResult['data'];
$post = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST';
$findingId=positive_id($_GET['hallazgo_id']??null);
if (isset($_GET['hallazgo_id']) && $findingId===null) throw new ApiPageError(422,'Hallazgo inválido.');
$finding=null;
if ($findingId!==null) {
    if (!can_show_action('hallazgo_gestionar')) throw new ApiPageError(403,'No tiene permiso para asociar evidencias.');
    $findingResult=api_get_object('/api/v1/hallazgos/'.$findingId);
    if (!$findingResult['ok']) throw new ApiPageError(api_http_status($findingResult),'El hallazgo no está disponible.');
    $finding=$findingResult['data'];
    if (in_array($finding['estado']??'', ['CLOSED','ACCEPTED_RISK'],true)) throw new ApiPageError(409,'El hallazgo es terminal.');
}
$input = $post ? $_POST : [];
$selectedDocument = positive_id($input['documento_id'] ?? null);
$versionResult = ['ok' => true, 'status' => 200, 'data' => []];
if ($selectedDocument !== null && in_array($selectedDocument, array_column($availableDocuments, 'id'), true)) {
    $versionResult = api_get('/api/v1/documentos/' . $selectedDocument . '/versiones');
}
$availableVersions = $versionResult['data'];
$prefilledAudit = positive_id($_GET['auditoria_id'] ?? null);
if ($finding!==null) $prefilledAudit=positive_id($finding['auditoria_id']??null);
if (!in_array($prefilledAudit, array_column($availableAudits, 'id'), true)) $prefilledAudit = null;
$values = ['titulo' => '', 'descripcion' => '', 'auditoria_id' => $prefilledAudit, 'documento_id' => null, 'version_documento_id' => null, 'tipo' => 'NOTE', 'referencia_url' => ''];
$fieldErrors = [];
$formError = $sessionReady ? null : 'No fue posible habilitar el formulario. Recarga la página.';
$canSubmit = $sessionReady && $auditResult['ok'] && $availableAudits !== [];
if ($post) {
    $validation = validate_evidence_form($input, $fileMode, $availableAudits, $availableDocuments, $availableVersions);
    $values = $validation['values']; $fieldErrors = $validation['errors'];
    $file = $_FILES['archivo'] ?? null;
    if ($fileMode && (!is_array($file) || ($file['error'] ?? null) !== UPLOAD_ERR_OK || !is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name']) || !is_file($file['tmp_name']) || !is_string($file['name'] ?? null))) {
        $fieldErrors['archivo'] = 'Selecciona un archivo válido y comprueba el límite de tamaño.';
    }
    if (!$sessionReady || !csrf_valid($_POST['csrf_token'] ?? null)) {
        $formError = 'No fue posible validar el envío. Recarga la página. Si el archivo supera el límite de carga, selecciona uno más pequeño.';
        http_response_code(403);
    } elseif (!$canSubmit) {
        $formError = 'Se requiere una auditoría disponible para registrar evidencias.';
        http_response_code(503);
    } elseif ((!$documentResult['ok'] && $selectedDocument !== null) || !$versionResult['ok']) {
        $formError = 'No fue posible comprobar el documento o sus versiones. Intenta nuevamente.';
        http_response_code(503);
    } elseif ($fieldErrors) {
        $formError = 'Revisa los campos marcados.';
        http_response_code(422);
    } else {
        if ($findingId!==null) $validation['body']['hallazgo_id']=$findingId;
        $result = $fileMode
            ? api_post_multipart('/api/v1/evidencias/archivo', $validation['body'], ['archivo' => ['path' => $file['tmp_name'], 'name' => $file['name']]])
            : api_post_json('/api/v1/evidencias/logica', $validation['body']);
        $newId = positive_id($result['data']['id'] ?? null);
        if ($result['ok'] && $result['status'] === 201 && $newId !== null) {
            $_SESSION['evidence_success'][$newId] = 'Evidencia registrada correctamente.';
            $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
            session_write_close();
            header('Location: ' . page_url('evidencia', ['id' => $newId]), true, 303);
            exit;
        }
        $error = record_error($result, 'la evidencia');
        $formError = $error['message']; $fieldErrors = $error['fields'];
        http_response_code(api_http_status($result));
    }
}
session_write_close();
