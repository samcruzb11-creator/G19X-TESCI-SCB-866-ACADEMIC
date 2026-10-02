<?php
declare(strict_types=1);
if (!isset($page, $sessionReady)) { http_response_code(404); exit; }

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($page === 'logout') {
    if ($method !== 'POST') {
        header('Allow: POST');
        throw new ApiPageError(405, 'Esta acción requiere enviar el formulario.');
    }
    if (!csrf_valid($_POST['csrf_token'] ?? null)) throw new ApiPageError(403, 'No fue posible validar el formulario. Recarga la página.');
    $notice = 'signed_out';
    if (is_string($_SESSION['auth']['access_token'] ?? null)) {
        $result = api_request('POST', '/api/v1/auth/logout');
        if ($result['status'] !== 204 && $result['status'] !== 401) $notice = 'remote_logout_unconfirmed';
    }
    clear_authentication($notice);
    redirect_to_login();
}

$loginError = null;
$loginEmail = is_string($_POST['correo'] ?? null) ? trim($_POST['correo']) : '';
$noticeCode = $_SESSION['auth_notice'] ?? null;
unset($_SESSION['auth_notice']);
$loginNotice = match ($noticeCode) {
    'password_reset' => 'Contraseña actualizada. Por seguridad cerramos tus sesiones anteriores. Inicia sesión con tu nueva contraseña.',
    'initial_password' => 'Contraseña establecida. Ya puedes iniciar sesión.',
    'expired' => 'La sesión expiró. Inicie sesión nuevamente.',
    'signed_out' => 'La sesión se cerró correctamente.',
    'remote_logout_unconfirmed' => 'La sesión local se cerró. No pudo confirmarse la revocación remota.',
    default => null,
};
if ($method === 'POST') {
    if (!csrf_valid($_POST['csrf_token'] ?? null)) {
        http_response_code(403);
        $loginError = 'No fue posible validar el formulario. Recarga la página.';
    } elseif ($loginEmail === '' || !is_string($_POST['password'] ?? null) || $_POST['password'] === '') {
        http_response_code(422);
        $loginError = 'Introduce el correo y la contraseña.';
    } else {
        $result = api_post_json('/api/v1/auth/login', ['correo' => $loginEmail, 'password' => $_POST['password']]);
        if ($result['ok'] && is_string($result['data']['access_token'] ?? null)
            && $result['data']['access_token'] !== '' && ($result['data']['token_type'] ?? null) === 'bearer'
            && is_int($result['data']['expires_in'] ?? null) && $result['data']['expires_in'] > 0) {
            // Rotate before storing credentials; discard any previous user's context.
            clear_authentication();
            $_SESSION['auth'] = ['access_token' => $result['data']['access_token'], 'expires_at' => time() + $result['data']['expires_in']];
            try {
                $me = api_get_object('/api/v1/auth/me');
                if (!$me['ok'] || !accept_authenticated_user($me['data'])) {
                    throw new ApiPageError(503, 'No fue posible verificar la sesión. Intenta nuevamente.');
                }
                $_SESSION['csrf_token'] = bin2hex(random_bytes(32));
                session_write_close();
                header('Location: ' . page_url('dashboard'), true, 303);
                exit;
            } catch (Throwable $exception) {
                // A token without a verified user must never survive in PHP.
                error_log('Frontend login verification failed: ' . get_class($exception));
                clear_authentication();
                http_response_code(503);
                $loginError = 'No fue posible verificar la sesión. Inicie sesión nuevamente.';
            }
        } else {
            http_response_code(api_http_status($result));
            if ($result['status'] === 429 && isset($result['retry_after'])) {
                header('Retry-After: ' . $result['retry_after']);
            }
            $loginError = match ($result['status']) {
                401 => 'Credenciales inválidas.',
                429 => 'Demasiados intentos. Intente nuevamente más tarde.',
                default => 'No fue posible iniciar sesión. Intenta nuevamente.',
            };
        }
    }
} elseif ($method !== 'GET') {
    header('Allow: GET, POST');
    throw new ApiPageError(405, 'Método no permitido.');
}
$csrfToken = csrf_token();
