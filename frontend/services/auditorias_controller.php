<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
$userResult = can_show_action('usuarios_catalogo')
    ? api_get('/api/v1/usuarios', $page === 'auditoria_nueva' ? ['elegibles_auditoria' => 'true'] : [])
    : ['ok' => true, 'data' => [current_user() + ['activo' => true]]];
$userNames = areas_by_id($userResult['data']);
$availableUsers = active_users($userResult['data']);
$successMessage = null;
if ($page === 'auditoria_nueva') {
    require_once __DIR__ . '/auditoria_form.php';
    $values = ['codigo' => '', 'nombre' => '', 'alcance' => '', 'responsable_id' => null, 'fecha_inicio_prevista' => '', 'fecha_fin_prevista' => ''];
    $fieldErrors = [];
    $formError = $sessionReady ? null : 'No fue posible habilitar el formulario. Recarga la página.';
    $canSubmit = $sessionReady && $userResult['ok'] && $availableUsers !== [];
    if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
        $input = $_POST;
        if (user_has_role('AUDITOR_INTERNO')) $input['responsable_id'] = current_user()['id'];
        $validation = validate_audit_form($input, $availableUsers);
        $values = $validation['values'];
        $fieldErrors = $validation['errors'];
        if (!$sessionReady || !csrf_valid($_POST['csrf_token'] ?? null)) {
            $formError = 'La sesión del formulario no es válida. Recarga la página.';
            http_response_code(403);
        } elseif (!$canSubmit) {
            $formError = 'No hay usuarios disponibles para registrar la auditoría.';
            http_response_code(503);
        } elseif ($fieldErrors) {
            $formError = 'Revisa los campos marcados.';
            http_response_code(422);
        } else {
            $result = api_post_json('/api/v1/auditorias', $validation['body']);
            $newId = positive_id($result['data']['id'] ?? null);
            if ($result['ok'] && $result['status'] === 201 && $newId !== null) {
                $_SESSION['audit_success'][$newId] = 'Auditoría registrada correctamente.';
                $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
                session_write_close();
                header('Location: ' . page_url('auditoria', ['id' => $newId]), true, 303);
                exit;
            }
            $error = record_error($result, 'la auditoría');
            $formError = $error['message']; $fieldErrors = $error['fields'];
            http_response_code(api_http_status($result));
        }
    }
    session_write_close();
    return;
}
$auditResult = api_get_all('/api/v1/auditorias');
$audits = $auditResult['data'];
if ($page === 'auditorias') {
    $auditCount = count($audits);
    $filterValues = ['q' => list_query('q'), 'estado' => list_query('estado')];
    $stateOptions = [];
    foreach (['PLANNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'] as $state) $stateOptions[$state] = audit_status($state)[0];
    $audits = array_values(array_filter($audits, fn(array $row): bool =>
        list_matches($row, $filterValues['q'], ['codigo', 'nombre'])
        && ($filterValues['estado'] === '' || ($row['estado'] ?? '') === $filterValues['estado'])
    ));
}
if ($page === 'auditoria') {
    $audit = null;
    foreach ($audits as $row) if (positive_id($row['id'] ?? null) === $recordId) $audit = $row;
    if (!$auditResult['ok'] || $audit === null) http_response_code($auditResult['ok'] ? 404 : api_http_status($auditResult));
    $successMessage = $_SESSION['audit_success'][$recordId] ?? null;
    unset($_SESSION['audit_success'][$recordId]);
    session_write_close();
}
