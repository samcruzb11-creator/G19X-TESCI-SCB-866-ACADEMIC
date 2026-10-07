<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    header('Allow: GET');
    throw new ApiPageError(405, 'Esta página admite únicamente consultas.');
}
header('Cache-Control: no-store');
require_once __DIR__ . '/dashboard_helpers.php';
if ($page === 'alertas') {
    $alertOffset = dashboard_offset($_GET['offset'] ?? '0');
    $alertFilters = ['limit' => 20, 'offset' => $alertOffset];
    foreach (['tipo' => array_keys(dashboard_alert_types()), 'severidad' => ['INFO', 'WARNING']] as $key => $allowed) {
        $value = $_GET[$key] ?? '';
        if (!is_string($value) || ($value !== '' && !in_array($value, $allowed, true))) {
            throw new ApiPageError(422, 'Filtro de alerta inválido.');
        }
        if ($value !== '') $alertFilters[$key] = $value;
    }
    $dashboardResult = api_get_object('/api/v1/dashboard/alertas', $alertFilters);
    $alertData = $dashboardResult['ok'] ? $dashboardResult['data'] : null;
} else {
    // One transaction supplies counters, formulas, alerts and activity.
    $dashboardResult = api_get_object('/api/v1/dashboard/resumen', ['limit' => 5]);
    $dashboard = $dashboardResult['ok'] ? $dashboardResult['data'] : null;
    $indicatorData = $dashboard['indicadores'] ?? [];
    $alertData = $dashboard['alertas'] ?? null;
    $activityData = $dashboard['actividad'] ?? null;
}
