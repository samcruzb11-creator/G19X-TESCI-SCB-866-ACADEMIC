<?php
declare(strict_types=1);
if (!isset($page) || !user_has_role('ADMIN')) throw new ApiPageError(403, 'No tiene permiso para realizar esta operación.');
$accessRoles = ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR'];
$accessError = null;
$accessRow = null;
$accessRows = [];
$accessOffset = filter_var($_GET['offset'] ?? 0, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0, 'max_range' => 100000]]);
$accessOffset = $accessOffset === false ? 0 : $accessOffset;
$accessStatus = is_string($_GET['estado'] ?? null) ? $_GET['estado'] : 'PENDING';
if (!in_array($accessStatus, ['PENDING','APPROVED','REJECTED','FULFILLED'], true)) $accessStatus = 'PENDING';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'POST') {
    if ($page !== 'solicitud_acceso' || $recordId === null) throw new ApiPageError(404, 'Recurso no encontrado.');
    if (!csrf_valid($_POST['csrf_token'] ?? null)) throw new ApiPageError(403, 'No fue posible validar el formulario.');
    $action = is_string($_POST['accion'] ?? null) ? $_POST['accion'] : '';
    if ($action === 'approve') {
        $role = $_POST['rol'] ?? null;
        if (!is_string($role) || !in_array($role, $accessRoles, true)) throw new ApiPageError(422, 'Selecciona un rol válido.');
        $payload = ['rol' => $role];
    } elseif ($action === 'reject') {
        $payload = ['motivo' => is_string($_POST['motivo'] ?? null) ? $_POST['motivo'] : ''];
    } elseif ($action === 'resend') {
        $payload = [];
    } else throw new ApiPageError(422, 'Acción inválida.');
    $result = api_post_json('/api/v1/access-requests/' . $recordId . '/' . $action, $payload);
    if ($result['ok']) {
        session_write_close();
        header('Location: ' . page_url('solicitud_acceso', ['id' => $recordId]), true, 303);
        exit;
    }
    http_response_code(api_http_status($result));
    if ($result['status'] === 429 && isset($result['retry_after'])) header('Retry-After: ' . $result['retry_after']);
    $accessError = match ($result['status']) {
        409 => 'La solicitud ya fue resuelta o el correo pertenece a una cuenta. Actualiza la página.',
        429 => 'Demasiados intentos. Intente nuevamente más tarde.',
        default => 'No fue posible completar la operación. Intenta más tarde.',
    };
} elseif ($method !== 'GET') throw new ApiPageError(405, 'Método no permitido.');
if ($page === 'solicitud_acceso') {
    if ($recordId === null) throw new ApiPageError(404, 'Recurso no encontrado.');
    $result = api_get_object('/api/v1/access-requests/' . $recordId);
    if (!$result['ok']) throw new ApiPageError(api_http_status($result), $result['message']);
    $accessRow = $result['data'];
} else {
    $result = api_get('/api/v1/access-requests', ['status'=>$accessStatus, 'limit'=>50, 'offset'=>$accessOffset]);
    if (!$result['ok']) throw new ApiPageError(api_http_status($result), $result['message']);
    $accessRows = $result['data'];
}
