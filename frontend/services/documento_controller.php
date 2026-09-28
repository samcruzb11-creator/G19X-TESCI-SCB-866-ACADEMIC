<?php
declare(strict_types=1);
if (!isset($route, $documentId) || $documentId === null) { http_response_code(404); exit; }

$sessionPath = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'sistema-trazabilidad-frontend-sessions';
$sessionReady = (is_dir($sessionPath) || @mkdir($sessionPath, 0700, true)) && @session_start([
    'save_path' => $sessionPath,
    'cookie_httponly' => true,
    'cookie_samesite' => 'Lax',
    'use_strict_mode' => true,
]);
if (!$sessionReady) $_SESSION = [];
header('Cache-Control: no-store');
$csrfToken = $sessionReady ? ($_SESSION['csrf_token'] ??= bin2hex(random_bytes(32))) : '';
$successMessage = $_SESSION['version_success'][$documentId] ?? null;
unset($_SESSION['version_success'][$documentId]);
$uploadError = $sessionReady ? null : 'No fue posible habilitar el envío de archivos. Recarga la página e intenta nuevamente.';
$downloadError = null;
$selectedUser = positive_id($_POST['subido_por_id'] ?? null);
$comment = is_string($_POST['comentario_cambio'] ?? null) ? trim($_POST['comentario_cambio']) : '';
$documentResult = api_get_object('/api/v1/documentos/' . $documentId);
$document = $documentResult['data'];
if ($documentResult['ok'] && positive_id($document['id'] ?? null) !== $documentId) {
    $documentResult = api_failure();
}
if (!$documentResult['ok']) {
    http_response_code($documentResult['status'] === 404 ? 404 : 502);
    session_write_close();
    return;
}

$action = is_string($_GET['accion'] ?? null) ? $_GET['accion'] : '';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$versionResult = api_get('/api/v1/documentos/' . $documentId . '/versiones');
$versions = $versionResult['data'];

if ($action === 'descargar' && $method === 'GET') {
    $versionId = positive_id($_GET['version_id'] ?? null);
    $version = null;
    foreach ($versions as $candidate) {
        if ($versionId !== null && positive_id($candidate['id'] ?? null) === $versionId && positive_id($candidate['documento_id'] ?? null) === $documentId) $version = $candidate;
    }
    $download = $version !== null ? api_download('/api/v1/documentos/' . $documentId . '/versiones/' . $versionId . '/descargar') : api_failure($versionResult['ok'] ? 404 : 502);
    if ($download['ok']) {
        $filename = is_string($version['nombre_original'] ?? null) ? $version['nombre_original'] : 'documento';
        $filename = basename(str_replace('\\', '/', $filename));
        $filename = preg_replace('/[\x00-\x1F\x7F]/', '', $filename) ?: 'documento';
        $mime = is_string($version['mime_type'] ?? null) ? $version['mime_type'] : '';
        if (!preg_match('~\A[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+\z~', $mime)) $mime = 'application/octet-stream';
        session_write_close();
        header('Content-Type: ' . $mime);
        header("Content-Disposition: attachment; filename=\"documento\"; filename*=UTF-8''" . rawurlencode($filename));
        header('Content-Length: ' . fstat($download['stream'])['size']);
        fpassthru($download['stream']);
        fclose($download['stream']);
        exit;
    }
    http_response_code($download['status'] === 404 ? 404 : 502);
    $downloadError = $download['status'] === 404 ? 'La versión o el archivo solicitado no existen.' : 'No fue posible descargar la versión. Intenta nuevamente.';
}

$areaResult = api_get('/api/v1/areas');
$userResult = api_get('/api/v1/usuarios');
$historyResult = api_get('/api/v1/documentos/' . $documentId . '/historial');
$areaNames = areas_by_id($areaResult['data']);
$userNames = areas_by_id($userResult['data']);
$uploadUsers = array_values(array_filter($userResult['data'], fn(array $user): bool => positive_id($user['id'] ?? null) !== null && ($user['activo'] ?? false) === true));

if ($method === 'POST') {
    $token = $_POST['csrf_token'] ?? null;
    $file = $_FILES['archivo'] ?? null;
    if (!$sessionReady) {
        $uploadError = 'No fue posible habilitar el envío de archivos. Recarga la página e intenta nuevamente.';
    } elseif (!is_string($token) || !hash_equals($csrfToken, $token)) {
        $uploadError = 'No fue posible validar el envío. Recarga la ficha y selecciona nuevamente el archivo. Si supera el límite de carga, elige un archivo más pequeño.';
    } elseif (!$userResult['ok'] || !in_array($selectedUser, array_column($uploadUsers, 'id'), true)) {
        $uploadError = 'Selecciona un usuario disponible para registrar la versión.';
    } elseif (!is_array($file) || !is_int($file['error'] ?? null) || $file['error'] !== UPLOAD_ERR_OK) {
        $uploadError = 'No fue posible recibir el archivo. Selecciónalo nuevamente y comprueba el límite de tamaño indicado.';
    } elseif (!is_string($file['tmp_name'] ?? null) || !is_uploaded_file($file['tmp_name']) || !is_file($file['tmp_name']) || !is_string($file['name'] ?? null)) {
        $uploadError = 'Selecciona un archivo válido antes de enviar.';
    } else {
        $fields = ['subido_por_id' => (string) $selectedUser];
        if ($comment !== '') $fields['comentario_cambio'] = $comment;
        $result = api_post_multipart('/api/v1/documentos/' . $documentId . '/versiones', $fields, [
            'archivo' => ['path' => $file['tmp_name'], 'name' => $file['name']],
        ]);
        if ($result['ok'] && $result['status'] === 201) {
            $_SESSION['version_success'][$documentId] = 'La nueva versión se cargó correctamente.';
            $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
            session_write_close();
            header('Location: ' . page_url('documento', ['id' => $documentId]), true, 303);
            exit;
        }
        $uploadError = 'No fue posible confirmar la carga de la versión. Consulta el historial antes de volver a enviarla.';
    }
    http_response_code(422);
}
session_write_close();
