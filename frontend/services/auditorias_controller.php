<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
require_once __DIR__ . '/auditoria_form.php';
$stateOptions = [];
foreach (['PLANNED','IN_PROGRESS','IN_REVIEW','COMPLETED','CANCELLED'] as $state) $stateOptions[$state] = audit_status($state)[0];
$userNames = presentation_user_names();
$userResult = ['ok' => true, 'data' => []];
$successMessage = null;
$formError = null;
$historyResult = ['ok' => true, 'data' => []];
$audit = null;
$editable = false;

if (in_array($page, ['auditoria', 'auditoria_editar'], true)) {
    $auditResult = api_get_object('/api/v1/auditorias/' . $recordId);
    $audit = $auditResult['ok'] ? $auditResult['data'] : null;
    if (!$auditResult['ok']) http_response_code(api_http_status($auditResult));
    if ($page === 'auditoria_editar' && $audit === null) throw new ApiPageError(api_http_status($auditResult), 'La auditoría no está disponible.');
    if ($audit !== null) {
        $editable = can_show_action('auditoria_editar') && in_array($audit['estado'] ?? '', ['PLANNED', 'IN_PROGRESS'], true);
        $reference = $audit['responsable'] ?? null;
        if (is_array($reference)) $userNames += areas_by_id([$reference]);
    }
}

if (in_array($page, ['auditoria_nueva', 'auditoria_editar'], true)) {
    $editing = $page === 'auditoria_editar';
    if ($editing && !$editable) throw new ApiPageError(409, 'La auditoría no admite edición en su estado actual.');
    $userResult = user_has_role('ADMIN') ? api_get('/api/v1/usuarios', ['elegibles_auditoria'=>'true'])
        : ['ok'=>true, 'data'=>[current_user() + ['activo'=>true]]];
    $availableUsers = active_users($userResult['data']);
    $values = $editing ? array_intersect_key($audit, array_flip(['codigo','nombre','alcance','responsable_id','fecha_inicio_prevista','fecha_fin_prevista']))
        : ['codigo'=>'','nombre'=>'','alcance'=>'','responsable_id'=>null,'fecha_inicio_prevista'=>'','fecha_fin_prevista'=>''];
    $expectedUpdate = $editing ? ($audit['updated_at'] ?? '') : '';
    $fieldErrors = [];
    $canSubmit = $sessionReady && $userResult['ok'] && $availableUsers !== [];
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
        $input = $_POST;
        if (user_has_role('AUDITOR_INTERNO')) $input['responsable_id'] = current_user()['id'];
        if ($editing) $input['codigo'] = $audit['codigo'];
        $validation = validate_audit_form($input, $availableUsers);
        $values = $validation['values'];
        $fieldErrors = $validation['errors'];
        if ($editing) $expectedUpdate = is_string($_POST['updated_at_esperado'] ?? null) ? $_POST['updated_at_esperado'] : '';
        if (!$sessionReady || !csrf_valid($_POST['csrf_token'] ?? null)) {
            $formError = 'La sesión del formulario no es válida. Recarga la página.'; http_response_code(403);
        } elseif (!$canSubmit) {
            $formError = 'No hay responsables elegibles disponibles.'; http_response_code(503);
        } elseif ($fieldErrors) {
            $formError = 'Revisa los campos marcados.'; http_response_code(422);
        } else {
            $body = $validation['body'];
            if ($editing) { unset($body['codigo']); $body['updated_at_esperado'] = $expectedUpdate; }
            $result = $editing ? api_patch_json('/api/v1/auditorias/' . $recordId, $body) : api_post_json('/api/v1/auditorias', $body);
            $newId = positive_id($result['data']['id'] ?? null);
            if ($result['ok'] && $newId !== null) {
                $_SESSION['audit_success'][$newId] = $editing ? 'Auditoría actualizada correctamente.' : 'Auditoría registrada correctamente.';
                $_SESSION['csrf_token'] = bin2hex(random_bytes(32)); session_write_close();
                header('Location: ' . page_url('auditoria', ['id'=>$newId]), true, 303); exit;
            }
            $error = record_error($result, 'la auditoría'); $formError = $error['message']; $fieldErrors = $error['fields'];
            if (($result['status'] ?? 0) === 409) $formError = 'La auditoría cambió o no admite esta operación. Recarga el detalle antes de continuar.';
            http_response_code(api_http_status($result));
        }
    }
    session_write_close(); return;
}

if ($page === 'auditorias') {
    $filterValues = [];
    foreach (['q','estado','area_id','responsable_id','inicio_desde','inicio_hasta','orden'] as $key) {
        if (isset($_GET[$key]) && !is_string($_GET[$key])) throw new ApiPageError(422, 'Revisa los filtros indicados.');
        $filterValues[$key] = list_query($key);
    }
    $pageNumber = positive_id($_GET['p'] ?? '1');
    if ($pageNumber === null || $pageNumber > 501) throw new ApiPageError(422, 'Número de página inválido.');
    $query = array_filter($filterValues, static fn($value):bool=>$value !== '');
    $query += ['limit'=>20, 'offset'=>($pageNumber-1)*20];
    $auditResult = api_get('/api/v1/auditorias', $query); $audits = $auditResult['data'];
    if (!$auditResult['ok']) http_response_code(api_http_status($auditResult));
    $auditCount = $auditResult['total'] ?? count($audits);
    $areaResult = api_get('/api/v1/areas'); $areaOptions = areas_by_id($areaResult['data']);
    $ownerOptions = [];
    if (user_has_role('ADMIN')) {
        $userResult = api_get('/api/v1/usuarios', ['elegibles_auditoria'=>'true']);
        $ownerOptions = areas_by_id($userResult['data']);
    }
    $pageCount = max(1, (int)ceil($auditCount/20));
    session_write_close(); return;
}

if ($page === 'auditoria') {
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && $audit !== null) {
        if (!can_show_action('auditoria_estado')) throw new ApiPageError(403, 'No tiene permiso para cambiar el estado.');
        if (!csrf_valid($_POST['csrf_token'] ?? null)) {
            $formError = 'La sesión del formulario no es válida. Recarga la página.'; http_response_code(403);
        } else {
            $body = [];
            foreach (['estado','estado_esperado','updated_at_esperado'] as $key) $body[$key] = is_string($_POST[$key] ?? null) ? $_POST[$key] : '';
            $result = api_post_json('/api/v1/auditorias/' . $recordId . '/estado', $body);
            if ($result['ok']) {
                $_SESSION['audit_success'][$recordId] = 'Estado actualizado correctamente.';
                $_SESSION['csrf_token'] = bin2hex(random_bytes(32)); session_write_close();
                header('Location: ' . page_url('auditoria', ['id'=>$recordId]), true, 303); exit;
            }
            $formError = ($result['status'] ?? 0) === 409 ? 'El estado cambió o la transición no está permitida. Recarga antes de continuar.' : record_error($result, 'la auditoría')['message'];
            http_response_code(api_http_status($result));
        }
    }
    $successMessage = $_SESSION['audit_success'][$recordId] ?? null; unset($_SESSION['audit_success'][$recordId]);
    if ($audit !== null && user_has_role('ADMIN')) {
        $historyPage = positive_id($_GET['hp'] ?? '1');
        if ($historyPage === null || $historyPage > 501) throw new ApiPageError(422, 'Página de historial inválida.');
        $historyResult = api_get('/api/v1/auditorias/' . $recordId . '/historial', ['limit'=>20,'offset'=>($historyPage-1)*20]);
    }
    session_write_close();
}
