<?php
declare(strict_types=1);

ini_set('display_errors', '0');
ini_set('log_errors', '1');
error_reporting(E_ALL);
require_once __DIR__ . '/config/config.php';
require_once __DIR__ . '/includes/helpers.php';
require_once __DIR__ . '/includes/session.php';
require_once __DIR__ . '/services/api_client.php';
require_once __DIR__ . '/services/turnstile.php';
require_once __DIR__ . '/includes/auth.php';
require_once __DIR__ . '/services/download_response.php';
require_once __DIR__ . '/services/registro_helpers.php';
require_once __DIR__ . '/includes/form_fields.php';
require_once __DIR__ . '/includes/list_filters.php';

$routes = [
    'solicitar_acceso' => ['title' => 'Solicita acceso', 'file' => 'public_auth.php', 'nav' => ''],
    'recuperar_password' => ['title' => 'Recupera tu contraseña', 'file' => 'public_auth.php', 'nav' => ''],
    'restablecer_password' => ['title' => 'Restablece tu contraseña', 'file' => 'public_auth.php', 'nav' => ''],
    'establecer_password' => ['title' => 'Establece tu contraseña', 'file' => 'public_auth.php', 'nav' => ''],
    'solicitudes_acceso' => ['title' => 'Solicitudes de acceso', 'file' => 'access_requests.php', 'nav' => 'solicitudes_acceso'],
    'solicitud_acceso' => ['title' => 'Solicitud de acceso', 'file' => 'access_requests.php', 'nav' => 'solicitudes_acceso'],
    'login' => ['title' => 'Iniciar sesión', 'file' => 'login.php', 'nav' => ''],
    'logout' => ['title' => 'Cerrar sesión', 'file' => 'error.php', 'nav' => ''],
    'dashboard' => ['title' => 'Dashboard', 'file' => 'dashboard.php', 'nav' => 'dashboard'],
    'documentos' => ['title' => 'Documentos', 'file' => 'documentos.php', 'nav' => 'documentos'],
    'auditorias' => ['title' => 'Auditorías', 'file' => 'auditorias.php', 'nav' => 'auditorias'],
    'auditoria_nueva' => ['title' => 'Nueva auditoría', 'file' => 'auditoria_nueva.php', 'nav' => 'auditorias'],
    'auditoria' => ['title' => 'Detalle de auditoría', 'file' => 'auditoria.php', 'nav' => 'auditorias'],
    'evidencias' => ['title' => 'Evidencias', 'file' => 'evidencias.php', 'nav' => 'evidencias'],
    'evidencia_archivo' => ['title' => 'Evidencia de archivo', 'file' => 'evidencia_nueva.php', 'nav' => 'evidencias'],
    'evidencia_logica' => ['title' => 'Evidencia lógica', 'file' => 'evidencia_nueva.php', 'nav' => 'evidencias'],
    'evidencia' => ['title' => 'Detalle de evidencia', 'file' => 'evidencia.php', 'nav' => 'evidencias'],
    'versiones_documento' => ['title' => 'Versiones', 'file' => 'pendiente.php', 'nav' => 'evidencias'],
    'documento_nuevo' => ['title' => 'Nuevo documento', 'file' => 'documento_nuevo.php', 'nav' => 'documentos'],
    'documento' => ['title' => 'Detalle del documento', 'file' => 'documento.php', 'nav' => 'documentos'],
];
$requestedPage = $_GET['pagina'] ?? 'dashboard';
$page = is_string($requestedPage) ? $requestedPage : '';
$publicAuthPages = ['solicitar_acceso', 'recuperar_password', 'restablecer_password', 'establecer_password'];
$authLayout = $page === 'login' || in_array($page, $publicAuthPages, true);
$notFound = !isset($routes[$page]);
$documentId = positive_id($_GET['id'] ?? null);
$recordId = $documentId;
if (in_array($page, ['documento', 'auditoria', 'evidencia', 'versiones_documento'], true) && $recordId === null) {
    $notFound = true;
}
$route = $notFound ? ['title' => 'Página no encontrada', 'file' => 'pendiente.php', 'nav' => ''] : $routes[$page];
if ($notFound) {
    http_response_code(404);
}
header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
if ($authLayout) header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'");
$turnstileWidget = null;

$sessionReady = frontend_session_start();
try {
    if (!$sessionReady) throw new ApiPageError(503, 'No fue posible habilitar la sesión. Intenta nuevamente.');
    $csrfToken = csrf_token();
    if (!$notFound && in_array($page, ['login', 'logout'], true)) {
        require __DIR__ . '/services/auth_controller.php';
    } elseif (!$notFound && in_array($page, $publicAuthPages, true)) {
        require __DIR__ . '/services/public_auth_controller.php';
    } else {
        require_login();
        $action = [
            'solicitudes_acceso' => 'solicitudes_acceso', 'solicitud_acceso' => 'solicitudes_acceso',
            'dashboard' => null, 'documentos' => 'documentos', 'documento' => 'documentos',
            'documento_nuevo' => 'documento_crear', 'versiones_documento' => 'documentos',
            'auditorias' => 'auditorias', 'auditoria' => 'auditorias', 'auditoria_nueva' => 'auditoria_crear',
            'evidencias' => 'evidencias', 'evidencia' => 'evidencias',
            'evidencia_archivo' => 'evidencia_crear', 'evidencia_logica' => 'evidencia_crear',
        ][$page] ?? null;
        if ($action !== null && !can_show_action($action)) throw new ApiPageError(403, 'No tiene permiso para realizar esta operación.');
        if (!$notFound && in_array($page, ['solicitudes_acceso', 'solicitud_acceso'], true)) require __DIR__ . '/services/access_requests_controller.php';
        if (!$notFound && $page === 'dashboard') require __DIR__ . '/services/dashboard_controller.php';
        if (!$notFound && $page === 'documentos') require __DIR__ . '/services/documentos_controller.php';
        if (!$notFound && $page === 'documento') {
            require __DIR__ . '/services/documento_controller.php';
        }
        if (!$notFound && $page === 'documento_nuevo') {
            require __DIR__ . '/services/documento_nuevo_controller.php';
        }
        if (!$notFound && in_array($page, ['auditorias', 'auditoria', 'auditoria_nueva'], true)) {
            require __DIR__ . '/services/auditorias_controller.php';
        }
        if (!$notFound && in_array($page, ['evidencia_archivo', 'evidencia_logica'], true)) {
            require __DIR__ . '/services/evidencia_nueva_controller.php';
        }
        if (!$notFound && $page === 'evidencia') {
            require __DIR__ . '/services/evidencia_controller.php';
        }
        if (!$notFound && $page === 'evidencias') {
            require __DIR__ . '/services/evidencias_controller.php';
        }
        if (!$notFound && $page === 'versiones_documento') {
            require __DIR__ . '/services/versiones_json.php';
        }

    }
} catch (AuthenticationRequired $exception) {
    clear_authentication($exception->expired ? 'expired' : null);
    if ($page === 'versiones_documento') {
        http_response_code(401);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['error' => 'session_expired']);
        exit;
    }
    redirect_to_login();
} catch (ApiPageError $exception) {
    http_response_code($exception->status);
    $errorMessage = $exception->getMessage();
    $route = ['title' => $exception->status === 403 ? 'Acceso denegado' : 'Información no disponible', 'file' => 'error.php', 'nav' => ''];
    if ($page === 'versiones_documento') {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['error' => $errorMessage]);
        exit;
    }
} catch (Throwable $exception) {
    error_log('Frontend request failed: ' . get_class($exception));
    http_response_code(500);
    $errorMessage = 'No fue posible completar la solicitud. Intenta nuevamente.';
    $route = ['title' => 'Información no disponible', 'file' => 'error.php', 'nav' => ''];
}
if (session_status() === PHP_SESSION_ACTIVE) session_write_close();

// Widen only the three public forms, only after FastAPI required a challenge.
// Password/initial confirmation pages never enter this branch, including errors.
if ($turnstileWidget !== null && turnstile_action_for_page($page) !== null
    && in_array($route['file'], ['login.php', 'public_auth.php'], true)) {
    header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; img-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'");
} else {
    $turnstileWidget = null;
}

require __DIR__ . ($authLayout ? '/includes/auth_header.php' : '/includes/header.php');
require __DIR__ . '/pages/' . $route['file'];
require __DIR__ . ($authLayout ? '/includes/auth_footer.php' : '/includes/footer.php');
