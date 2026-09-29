<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
$auditResult = api_get_all('/api/v1/auditorias');
$auditCodes = [];
foreach ($auditResult['data'] as $row) $auditCodes[$row['id']] = $row['codigo'];
$auditFilter = positive_id($_GET['auditoria_id'] ?? null);
$rawOffset = $_GET['offset'] ?? '0';
$offset = is_string($rawOffset) ? filter_var($rawOffset, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0, 'max_range' => PHP_INT_MAX - 51]]) : false;
$filterInvalid = (isset($_GET['auditoria_id']) && $_GET['auditoria_id'] !== '' && $auditFilter === null) || $offset === false;
$offset = $offset === false ? 0 : $offset;
$listQuery = $auditFilter === null ? [] : ['auditoria_id' => $auditFilter];
$evidenceResult = $filterInvalid ? api_failure(422) : api_get('/api/v1/evidencias', $listQuery + ['limit' => 51, 'offset' => $offset]);
$hasNext = count($evidenceResult['data']) > 50;
$evidences = array_slice($evidenceResult['data'], 0, 50);
if (!$evidenceResult['ok']) http_response_code($filterInvalid ? 422 : 502);
