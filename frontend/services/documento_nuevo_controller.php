<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
require_once __DIR__ . '/documento_form.php';

$areaResult = api_get('/api/v1/areas');
$userResult = can_show_action('usuarios_catalogo') ? api_get('/api/v1/usuarios') : ['ok' => true, 'data' => [current_user() + ['activo' => true]]];
$availableAreas = array_values(array_filter($areaResult['data'], fn(array $a): bool => positive_id($a['id'] ?? null) !== null && ($a['activa'] ?? false) === true));
$availableUsers = array_values(array_filter($userResult['data'], fn(array $u): bool => positive_id($u['id'] ?? null) !== null && ($u['activo'] ?? false) === true));
$canSubmit = $sessionReady && $areaResult['ok'] && $userResult['ok'] && $availableAreas !== [] && $availableUsers !== [];
$values = ['codigo' => '', 'titulo' => '', 'descripcion' => '', 'tipo' => '', 'estado' => 'DRAFT', 'area_id' => null, 'responsable_id' => null];
$fieldErrors = [];
$formError = !$sessionReady ? 'No fue posible habilitar el formulario. Recarga la página e intenta nuevamente.' : null;
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST') {
    $input = $_POST;
    if (user_has_role('RESPONSABLE_AREA')) $input['responsable_id'] = current_user()['id'];
    $validation = validate_document_form($input, $availableAreas, $availableUsers);
    $values = $validation['values'];
    $fieldErrors = $validation['errors'];
    if (!$sessionReady || !csrf_valid($_POST['csrf_token'] ?? null)) {
        $formError = 'La sesión del formulario no es válida. Recarga la página antes de guardar.';
        http_response_code(403);
    } elseif (!$canSubmit) {
        $formError = 'No fue posible consultar las áreas o los usuarios disponibles. Intenta nuevamente.';
        http_response_code(503);
    } elseif ($fieldErrors !== []) {
        $formError = 'Revisa los campos marcados.';
        http_response_code(422);
    } else {
        $result = api_post_json('/api/v1/documentos', $validation['body']);
        $newId = positive_id($result['data']['id'] ?? null);
        if ($result['ok'] && $result['status'] === 201 && $newId !== null) {
            $_SESSION['document_success'][$newId] = 'Documento registrado correctamente. Puedes adjuntar su primera versión a continuación.';
            $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
            session_write_close();
            header('Location: ' . page_url('documento', ['id' => $newId]), true, 303);
            exit;
        }
        $error = document_creation_error($result);
        $formError = $error['message'];
        $fieldErrors = $error['fields'];
        http_response_code(api_http_status($result));
    }
}
session_write_close();
