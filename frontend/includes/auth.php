<?php
declare(strict_types=1);

/** The server session contains the token; templates receive only this projection. */
function current_user(): ?array
{
    return $GLOBALS['authenticated_user'] ?? null;
}

function user_has_role(string ...$roles): bool
{
    return in_array(current_user()['rol'] ?? '', $roles, true);
}

/** Presentation only. Resource authorization remains exclusively in FastAPI. */
function can_show_action(string $action): bool
{
    $roles = [
        'aprobaciones' => ['ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO','RESPONSABLE_AREA','APROBADOR'],
        'aprobacion_gestionar' => ['ADMIN','AUDITOR_INTERNO'],
        'aprobacion_decidir' => ['APROBADOR'],
        'hallazgos' => ['ADMIN','AUDITOR_INTERNO','AUDITOR_EXTERNO'],
        'hallazgo_gestionar' => ['ADMIN','AUDITOR_INTERNO'],
        'documentos' => ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR'],
        'auditorias' => ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO'],
        'evidencias' => ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO'],
        'documento_crear' => ['ADMIN', 'RESPONSABLE_AREA'],
        'version_cargar' => ['ADMIN', 'RESPONSABLE_AREA'],
        'auditoria_crear' => ['ADMIN', 'AUDITOR_INTERNO'],
        'auditoria_editar' => ['ADMIN'],
        'auditoria_estado' => ['ADMIN'],
        'evidencia_crear' => ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO'],
        'historial' => ['ADMIN'],
        'usuarios_catalogo' => ['ADMIN'],
        'solicitudes_acceso' => ['ADMIN'],
    ];
    return isset($roles[$action]) && user_has_role(...$roles[$action]);
}

function navigation_items(): array
{
    $items = ['dashboard' => 'Dashboard'];
    if (can_show_action('documentos')) $items['analisis'] = 'Análisis';
    if (can_show_action('aprobaciones')) $items['aprobaciones'] = 'Aprobaciones';
    if (can_show_action('solicitudes_acceso')) $items['solicitudes_acceso'] = 'Solicitudes de acceso';
    foreach (['documentos' => 'Documentos', 'auditorias' => 'Auditorías', 'hallazgos'=>'Hallazgos', 'evidencias' => 'Evidencias'] as $key => $label) {
        if (can_show_action($key)) $items[$key] = $label;
    }
    return $items;
}

function clear_authentication(?string $notice = null): void
{
    unset($GLOBALS['authenticated_user'], $GLOBALS['auth_checked']);
    $_SESSION = [];
    if (session_status() === PHP_SESSION_ACTIVE && !session_regenerate_id(true)) {
        session_destroy();
        throw new RuntimeException('Session rotation failed');
    }
    if ($notice !== null) $_SESSION['auth_notice'] = $notice;
}

function accept_authenticated_user(array $data): bool
{
    if (positive_id($data['id'] ?? null) === null || !is_string($data['nombre'] ?? null)
        || !in_array($data['rol'] ?? null, ['ADMIN', 'AUDITOR_INTERNO', 'AUDITOR_EXTERNO', 'RESPONSABLE_AREA', 'APROBADOR'], true)) return false;
    $user = array_intersect_key($data, array_flip(['id', 'nombre', 'rol']));
    $_SESSION['auth']['user'] = $user;
    $GLOBALS['authenticated_user'] = $user;
    $GLOBALS['auth_checked'] = true;
    return true;
}

function require_login(): void
{
    if ($GLOBALS['auth_checked'] ?? false) return;
    $auth = $_SESSION['auth'] ?? null;
    if (!is_array($auth) || !is_string($auth['access_token'] ?? null) || $auth['access_token'] === '') {
        throw new AuthenticationRequired(false);
    }
    // No JWT parsing or renewal. FastAPI is authoritative for expiry/revocation/role.
    $result = api_get_object('/api/v1/auth/me');
    if (!$result['ok']) throw new ApiPageError(api_http_status($result), $result['message']);
    if (!accept_authenticated_user($result['data'])) {
        error_log('Frontend auth: invalid user response');
        throw new ApiPageError(502, 'No fue posible verificar la sesión. Intenta nuevamente.');
    }
}

function presentation_user_names(): array
{
    $user = current_user();
    return $user === null ? [] : [$user['id'] => $user['nombre']];
}

function redirect_to_login(): never
{
    if (session_status() === PHP_SESSION_ACTIVE) session_write_close();
    header('Location: ' . page_url('login'), true, 303);
    exit;
}
