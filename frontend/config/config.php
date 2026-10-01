<?php
declare(strict_types=1);

const API_BASE_URL = 'http://127.0.0.1:8000';
const API_CONNECT_TIMEOUT = 2;
const API_TIMEOUT = 5;
const APP_NAME = 'Sistema de Trazabilidad';
const DISPLAY_TIMEZONE = 'America/Mexico_City';

// Read only deployment environment, never HTTP headers or request parameters.
function frontend_cookie_secure_mode(): string
{
    $value = getenv('FRONTEND_COOKIE_SECURE');
    $value = $value === false ? 'auto' : $value;
    if (!in_array($value, ['auto', 'always'], true)) {
        throw new RuntimeException('Invalid frontend cookie configuration');
    }
    return $value;
}

function auth_api_timeout_seconds(): int
{
    $value = getenv('AUTH_API_TIMEOUT_SECONDS');
    if ($value === false) return 10;
    if (!preg_match('/\A[1-9][0-9]*\z/', $value) || (int) $value > 120) {
        throw new RuntimeException('Invalid authentication timeout configuration');
    }
    return (int) $value;
}
