<?php
declare(strict_types=1);

function frontend_session_start(): bool
{
    if (session_status() === PHP_SESSION_ACTIVE) return true;
    $path = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'sistema-trazabilidad-frontend-sessions';
    $ready = (is_dir($path) || @mkdir($path, 0700, true)) && @session_start([
        'save_path' => $path,
        'cookie_httponly' => true,
        'cookie_samesite' => 'Lax',
        'use_strict_mode' => true,
    ]);
    if (!$ready) $_SESSION = [];
    header('Cache-Control: no-store');
    return $ready;
}

function csrf_valid(mixed $token): bool
{
    $expected = $_SESSION['csrf_token'] ?? null;
    return session_status() === PHP_SESSION_ACTIVE && is_string($expected)
        && $expected !== '' && is_string($token) && hash_equals($expected, $token);
}
