<?php
declare(strict_types=1);

ini_set('display_errors', '0');
ini_set('log_errors', '1');
error_reporting(E_ALL);
require_once __DIR__ . '/config/config.php';
require_once __DIR__ . '/includes/helpers.php';
require_once __DIR__ . '/includes/session.php';
require_once __DIR__ . '/services/api_client.php';
require_once __DIR__ . '/services/download_response.php';
require_once __DIR__ . '/services/registro_helpers.php';
require_once __DIR__ . '/includes/form_fields.php';
require_once __DIR__ . '/includes/list_filters.php';

$routes = [
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
header("Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");

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

require __DIR__ . '/includes/header.php';
require __DIR__ . '/pages/' . $route['file'];
require __DIR__ . '/includes/footer.php';
