<?php
if (!isset($route)) { http_response_code(404); exit; }
$documentResult = api_get('/api/v1/documentos', ['limit' => 100]);
$auditResult = api_get('/api/v1/auditorias');
$areaResult = api_get('/api/v1/areas');
$allDocuments = $documentResult['data'];
$areaNames = areas_by_id($areaResult['data']);
$currentVersions = count(array_filter($allDocuments, fn(array $doc): bool => positive_id($doc['version_vigente_id'] ?? null) !== null));
$activeAreas = count(array_filter($areaResult['data'], fn(array $area): bool => ($area['activa'] ?? false) === true));
$metrics = [
    ['label' => 'Documentos registrados', 'value' => $documentResult['ok'] ? count($allDocuments) : null, 'note' => 'En la consulta · hasta 100'],
    ['label' => 'Auditorías registradas', 'value' => $auditResult['ok'] ? count($auditResult['data']) : null, 'note' => 'En la consulta · hasta 50'],
    ['label' => 'Áreas activas', 'value' => $areaResult['ok'] ? $activeAreas : null, 'note' => 'Catálogo de áreas'],
    ['label' => 'Con versión vigente', 'value' => $documentResult['ok'] ? $currentVersions : null, 'note' => 'De los documentos consultados'],
];
$documents = $allDocuments;
usort($documents, function (array $a, array $b): int {
    $dateA = is_string($a['updated_at'] ?? null) ? $a['updated_at'] : '';
    $dateB = is_string($b['updated_at'] ?? null) ? $b['updated_at'] : '';
    return strcmp($dateB, $dateA) ?: ((positive_id($b['id'] ?? null) ?? 0) <=> (positive_id($a['id'] ?? null) ?? 0));
});
$documents = array_slice($documents, 0, 5);
?>
<div class="page-heading"><div><p class="eyebrow">CONTROL DOCUMENTAL</p><h1>Resumen general</h1><p class="page-description">Consulta de documentos, auditorías y áreas del sistema.</p></div><a class="button button-primary" href="<?= e(page_url('documentos')) ?>">Consultar documentos</a></div>
<?php if (!$documentResult['ok'] || !$auditResult['ok'] || !$areaResult['ok']): ?>
    <div class="notice" role="status">Parte de la información no pudo cargarse. Los indicadores no disponibles se muestran con un guion.</div>
<?php endif; ?>
<section class="metrics" aria-label="Resumen de registros consultados">
    <?php foreach ($metrics as $metric): ?>
        <div class="metric"><h2><?= e($metric['label']) ?></h2><p class="metric-value"><?= $metric['value'] === null ? '—' : e($metric['value']) ?></p><p class="metric-note"><?= e($metric['value'] === null ? 'Información no disponible' : $metric['note']) ?></p></div>
    <?php endforeach; ?>
</section>
<nav class="module-links" aria-label="Accesos a los módulos"><a class="text-link" href="<?= e(page_url('documentos')) ?>">Ver documentos</a><a class="text-link" href="<?= e(page_url('auditorias')) ?>">Ver auditorías</a><a class="text-link" href="<?= e(page_url('evidencias')) ?>">Ver evidencias</a></nav>
<section class="panel" aria-labelledby="recent-title">
    <div class="panel-heading"><div><h2 id="recent-title">Documentos recientes</h2><p>Últimas actualizaciones entre los documentos consultados.</p></div><a class="text-link" href="<?= e(page_url('documentos')) ?>">Ver listado completo</a></div>
    <?php if (!$documentResult['ok']): ?>
        <div class="empty-state"><h3>Información no disponible</h3><p><?= e($documentResult['message']) ?></p><a class="button button-secondary" href="<?= e(page_url('dashboard')) ?>">Volver a intentar</a></div>
    <?php elseif ($documents === []): ?>
        <div class="empty-state"><h3>No hay documentos registrados.</h3><p>Los documentos aparecerán aquí cuando se incorporen al sistema.</p></div>
    <?php else: ?>
        <?php require __DIR__ . '/../includes/document_table.php'; ?>
        <div class="panel-footer"><?= e(count($documents)) ?> documentos recientes · <?= e(count($allDocuments)) ?> consultados</div>
    <?php endif; ?>
</section>
<p class="context-note">Los indicadores reflejan los registros consultados. No representan totales globales cuando se alcanza el límite de la consulta.</p>
