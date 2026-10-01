<?php
declare(strict_types=1);
if (!isset($recordId) || $recordId === null) { http_response_code(404); exit; }
header('Content-Type: application/json; charset=utf-8');
$result = api_get('/api/v1/documentos/' . $recordId . '/versiones');
if (!$result['ok']) {
    http_response_code(api_http_status($result));
    echo json_encode(['error' => 'No fue posible consultar las versiones.']);
    exit;
}
$rows = [];
foreach ($result['data'] as $row) {
    $id = positive_id($row['id'] ?? null); $number = positive_id($row['numero_version'] ?? null);
    if ($id !== null && $number !== null && positive_id($row['documento_id'] ?? null) === $recordId) $rows[] = ['id' => $id, 'numero_version' => $number];
}
echo json_encode($rows);
exit;
