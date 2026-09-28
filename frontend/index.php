<?php
declare(strict_types=1);

ini_set('display_errors', '0');
ini_set('log_errors', '1');
error_reporting(E_ALL);
require_once __DIR__ . '/config/config.php';
require_once __DIR__ . '/includes/helpers.php';
require_once __DIR__ . '/includes/session.php';
require_once __DIR__ . '/services/api_client.php';

$routes = [
    'dashboard' => ['title' => 'Dashboard', 'file' => 'dashboard.php', 'nav' => 'dashboard'],
    'documentos' => ['title' => 'Documentos', 'file' => 'documentos.php', 'nav' => 'documentos'],
    'auditorias' => ['title' => 'Auditorías', 'file' => 'pendiente.php', 'nav' => 'auditorias'],
    'evidencias' => ['title' => 'Evidencias', 'file' => 'pendiente.php', 'nav' => 'evidencias'],
    'documento_nuevo' => ['title' => 'Nuevo documento', 'file' => 'documento_nuevo.php', 'nav' => 'documentos'],
    'documento' => ['title' => 'Detalle del documento', 'file' => 'documento.php', 'nav' => 'documentos'],
];
$requestedPage = $_GET['pagina'] ?? 'dashboard';
$page = is_string($requestedPage) ? $requestedPage : '';
$notFound = !isset($routes[$page]);
$documentId = positive_id($_GET['id'] ?? null);
if ($page === 'documento' && $documentId === null) {
    $notFound = true;
}
$route = $notFound ? ['title' => 'Página no encontrada', 'file' => 'pendiente.php', 'nav' => ''] : $routes[$page];
if ($notFound) {
    http_response_code(404);
}
header('Content-Type: text/html; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");

if (!$notFound && $page === 'documento') {
    require __DIR__ . '/services/documento_controller.php';
}
if (!$notFound && $page === 'documento_nuevo') {
    require __DIR__ . '/services/documento_nuevo_controller.php';
}

require __DIR__ . '/includes/header.php';
require __DIR__ . '/pages/' . $route['file'];
require __DIR__ . '/includes/footer.php';
