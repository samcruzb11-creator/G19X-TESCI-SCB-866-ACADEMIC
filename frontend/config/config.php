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
    // Covers the bounded Siteverify retry (2 x 5 s) plus local authentication.
    if ($value === false) return 15;
    if (!preg_match('/\A[1-9][0-9]*\z/', $value) || (int) $value > 120) {
        throw new RuntimeException('Invalid authentication timeout configuration');
    }
    return (int) $value;
}

/** Public key only. Missing/invalid deployment configuration fails closed on challenge. */
function turnstile_site_key(): ?string
{
    $value = getenv('TURNSTILE_SITE_KEY');
    return is_string($value) && preg_match('/\A[A-Za-z0-9_-]{1,256}\z/', $value) ? $value : null;
}
