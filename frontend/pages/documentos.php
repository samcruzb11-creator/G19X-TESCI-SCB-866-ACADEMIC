<?php
if (!isset($route)) { http_response_code(404); exit; }
$documentResult = api_get_all('/api/v1/documentos');
$areaResult = api_get('/api/v1/areas');
$documents = $documentResult['data'];
$areaNames = areas_by_id($areaResult['data']);
$documentCount = count($documents);
$filterValues = ['q' => list_query('q'), 'estado' => list_query('estado'), 'area_id' => list_query('area_id')];
$stateOptions = [];
foreach (['DRAFT', 'ACTIVE', 'OBSOLETE', 'ARCHIVED'] as $state) $stateOptions[$state] = document_status($state)[0];
foreach ($documents as $doc) {
    $id = positive_id($doc['area_id'] ?? null);
    if ($id !== null && !isset($areaNames[$id])) $areaNames[$id] = 'Área #' . $id;
}
$documents = array_values(array_filter($documents, fn(array $doc): bool =>
    list_matches($doc, $filterValues['q'], ['codigo', 'titulo'])
    && ($filterValues['estado'] === '' || ($doc['estado'] ?? '') === $filterValues['estado'])
    && ($filterValues['area_id'] === '' || (string) ($doc['area_id'] ?? '') === $filterValues['area_id'])
));
?>
<div class="page-heading"><div><p class="eyebrow">REGISTRO DOCUMENTAL</p><h1>Documentos</h1><p class="page-description">Gestión y consulta de documentos registrados en el sistema.</p></div><a class="button button-primary" href="<?= e(page_url('documento_nuevo')) ?>">Nuevo documento</a></div>
<?php if (!$areaResult['ok'] && $documentResult['ok']): ?><div class="notice" role="status">No fue posible cargar los nombres de las áreas. Se muestran sus identificadores.</div><?php endif; ?>
<section class="panel" aria-labelledby="documents-title">
    <?php list_filters('documentos', $filterValues, ['estado' => ['label' => 'Estado', 'all' => 'Todos los estados', 'options' => $stateOptions], 'area_id' => ['label' => 'Área', 'all' => 'Todas las áreas', 'options' => $areaNames]], 'Buscar por código o título'); ?>
    <div class="panel-heading"><div><h2 id="documents-title">Listado de documentos</h2><p>Identificación, estado y versión vigente de cada registro.</p></div><?php if ($documentResult['ok']): ?><span class="record-count"><?= e(count($documents)) ?> registros consultados</span><?php endif; ?></div>
    <?php if (!$documentResult['ok']): ?>
        <div class="empty-state" role="status"><h3>No fue posible cargar los documentos</h3><p><?= e($documentResult['message']) ?></p><a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Volver a intentar</a></div>
    <?php elseif ($documents === []): ?>
        <div class="empty-state" role="status"><h3><?= $documentCount === 0 ? 'No hay documentos registrados.' : 'No hay documentos que coincidan con los filtros.' ?></h3><p><?= $documentCount === 0 ? 'Registra un documento para comenzar.' : 'Prueba otra búsqueda o limpia los filtros.' ?></p><a class="button button-secondary" href="<?= e(page_url($documentCount === 0 ? 'documento_nuevo' : 'documentos')) ?>"><?= $documentCount === 0 ? 'Nuevo documento' : 'Limpiar filtros' ?></a></div>
    <?php else: ?>
        <?php require __DIR__ . '/../includes/document_table.php'; ?>
        <div class="panel-footer"><?= e(count($documents)) ?> resultados de <?= e($documentCount) ?> documentos consultados</div>
    <?php endif; ?>
</section>
<p class="context-note">Las fechas corresponden a la última actualización del registro. “Sin versión” indica que no hay una versión vigente asignada.</p>
