<?php
if (!isset($route)) { http_response_code(404); exit; }
$documentResult = api_get('/api/v1/documentos', ['limit' => 100]);
$areaResult = api_get('/api/v1/areas');
$documents = $documentResult['data'];
$areaNames = areas_by_id($areaResult['data']);
?>
<div class="page-heading"><div><p class="eyebrow">REGISTRO DOCUMENTAL</p><h1>Documentos</h1><p class="page-description">Gestión y consulta de documentos registrados en el sistema.</p></div><a class="button button-primary" href="<?= e(page_url('documento_nuevo')) ?>">Nuevo documento</a></div>
<?php if (!$areaResult['ok'] && $documentResult['ok']): ?><div class="notice" role="status">No fue posible cargar los nombres de las áreas. Se muestran sus identificadores.</div><?php endif; ?>
<section class="panel" aria-labelledby="documents-title">
    <div class="panel-heading"><div><h2 id="documents-title">Listado de documentos</h2><p>Identificación, estado y versión vigente de cada registro.</p></div><?php if ($documentResult['ok']): ?><span class="record-count"><?= e(count($documents)) ?> registros consultados</span><?php endif; ?></div>
    <?php if (!$documentResult['ok']): ?>
        <div class="empty-state" role="status"><h3>No fue posible cargar los documentos</h3><p><?= e($documentResult['message']) ?></p><a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Volver a intentar</a></div>
    <?php elseif ($documents === []): ?>
        <div class="empty-state"><h3>Aún no hay documentos registrados</h3><p>El listado se mostrará cuando existan documentos en el sistema.</p></div>
    <?php else: ?>
        <?php require __DIR__ . '/../includes/document_table.php'; ?>
        <div class="panel-footer">Mostrando <?= e(count($documents)) ?> registros · Consulta limitada a 100 documentos</div>
    <?php endif; ?>
</section>
<p class="context-note">Las fechas corresponden a la última actualización del registro. “Sin versión” indica que no hay una versión vigente asignada.</p>
