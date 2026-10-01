<?php
declare(strict_types=1);
require_once __DIR__ . '/../config/config.php';

function frontend_session_start(): bool
{
    header('Cache-Control: no-store');
    try {
        $secureMode = frontend_cookie_secure_mode();
    } catch (RuntimeException $exception) {
        $_SESSION = [];
        return false; // Do not create a cookie/session with invalid deployment settings.
    }
    if (session_status() === PHP_SESSION_ACTIVE) return true;
    foreach (['session.save_handler' => 'files', 'session.gc_maxlifetime' => '1800',
              'session.gc_probability' => '1', 'session.gc_divisor' => '100'] as $key => $value) {
        if (ini_set($key, $value) === false) { $_SESSION = []; return false; }
    }
    $path = sys_get_temp_dir() . DIRECTORY_SEPARATOR . 'sistema-trazabilidad-frontend-sessions';
    $cookiePath = str_replace('\\', '/', dirname($_SERVER['SCRIPT_NAME'] ?? '/index.php'));
    $cookiePath = rtrim($cookiePath, '/.') . '/';
    $ready = (is_dir($path) || @mkdir($path, 0700, true)) && @session_start([
        'save_path' => $path,
        'cookie_path' => $cookiePath,
        'cookie_domain' => '',
        'cookie_lifetime' => 0,
        'cookie_secure' => $secureMode === 'always' || (isset($_SERVER['HTTPS']) && strtolower((string) $_SERVER['HTTPS']) !== 'off' && $_SERVER['HTTPS'] !== ''),
        'cookie_httponly' => true,
        'cookie_samesite' => 'Lax',
        'use_strict_mode' => true,
        'use_only_cookies' => true,
        'use_trans_sid' => false,
    ]);
    if (!$ready) $_SESSION = [];
    return $ready;
}

function csrf_token(): string
{
    return session_status() === PHP_SESSION_ACTIVE
        ? ($_SESSION['csrf_token'] ??= bin2hex(random_bytes(32))) : '';
}

function csrf_valid(mixed $token): bool
{
    $expected = $_SESSION['csrf_token'] ?? null;
    return session_status() === PHP_SESSION_ACTIVE && is_string($expected)
        && $expected !== '' && is_string($token) && hash_equals($expected, $token);
}
