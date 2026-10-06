<?php
declare(strict_types=1);
if (!isset($page, $sessionReady)) { http_response_code(404); exit; }
$publicError = null;
$publicNotice = null;
$isPasswordForm = in_array($page, ['restablecer_password', 'establecer_password'], true);
$publicValues = [];
foreach (['nombre', 'correo', 'motivo'] as $field) $publicValues[$field] = is_string($_POST[$field] ?? null) ? trim($_POST[$field]) : '';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$turnstileAction = turnstile_action_for_page($page);
$turnstileDisplay = $turnstileAction !== null ? turnstile_begin($turnstileAction, $method) : false;
if ($method === 'POST') {
    if (!csrf_valid($_POST['csrf_token'] ?? null)) throw new ApiPageError(403, 'No fue posible validar el formulario. Recarga la página.');
    $paths = ['solicitar_acceso' => '/api/v1/auth/access-requests', 'recuperar_password' => '/api/v1/auth/password-reset/request',
        'restablecer_password' => '/api/v1/auth/password-reset/confirm', 'establecer_password' => '/api/v1/auth/initial-password/confirm'];
    if ($isPasswordForm) {
        $token = is_string($_POST['token'] ?? null) ? $_POST['token'] : '';
        $password = is_string($_POST['password'] ?? null) ? $_POST['password'] : '';
        $confirmation = is_string($_POST['confirmation'] ?? null) ? $_POST['confirmation'] : '';
        if ($password !== $confirmation || mb_strlen($password) < 12 || mb_strlen($password) > 1024) {
            $publicError = 'Las contraseñas deben coincidir y contener entre 12 y 1024 caracteres.';
            http_response_code(422);
        }
        $payload = ['token' => $token, 'password' => $password];
    } else {
        $payload = $page === 'solicitar_acceso' ? $publicValues : ['correo' => $publicValues['correo']];
        $payload = turnstile_transport($payload);
    }
    if ($publicError === null) {
        $result = api_post_json($paths[$page], $payload);
        if ($turnstileAction !== null) $turnstileDisplay = turnstile_update($result, $turnstileAction, $turnstileDisplay);
        if ($result['ok']) {
            if ($isPasswordForm) {
                clear_authentication($page === 'restablecer_password' ? 'password_reset' : 'initial_password');
                redirect_to_login();
            }
            $publicNotice = $page === 'solicitar_acceso'
                ? 'Recibimos tu solicitud. El equipo responsable revisará la información y se pondrá en contacto contigo si procede.'
                : 'Si el correo corresponde a una cuenta habilitada, recibirás instrucciones para restablecer tu contraseña.';
            http_response_code(202);
        } else {
            http_response_code(api_http_status($result));
            if ($result['status'] === 429 && isset($result['retry_after'])) header('Retry-After: ' . $result['retry_after']);
            $publicError = match ($result['status']) {
                400 => 'Este enlace no es válido o ya no está disponible. Solicita uno nuevo.',
                422 => $isPasswordForm ? 'Revisa los campos. La contraseña debe contener entre 12 y 1024 caracteres.' : 'Revisa el correo y los campos de la solicitud.',
                429 => 'Demasiados intentos. Intente nuevamente más tarde.',
                428 => 'Completa la verificación para continuar.',
                503 => 'No podemos completar la verificación en este momento. Intenta más tarde.',
                default => 'No podemos procesar la solicitud en este momento. Intenta más tarde.',
            };
        }
    }
    unset($payload, $password, $confirmation, $token);
} elseif ($method !== 'GET') {
    throw new ApiPageError(405, 'Método no permitido.');
}
if ($turnstileAction !== null) $turnstileWidget = turnstile_widget($turnstileAction, $turnstileDisplay);
$csrfToken = csrf_token();
