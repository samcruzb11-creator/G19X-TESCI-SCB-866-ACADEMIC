<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">REGISTRO DOCUMENTAL</p><h1>Documentos</h1><p class="page-description">Gestión y consulta de documentos registrados en el sistema.</p></div><?php if (can_show_action('documento_crear')): ?><a class="button button-primary" href="<?= e(page_url('documento_nuevo')) ?>">Nuevo documento</a><?php endif; ?></div>
<?php if (!$areaResult['ok'] && $documentResult['ok']): ?><div class="notice" role="status">No fue posible cargar los nombres de las áreas. Se muestran sus identificadores.</div><?php endif; ?>
<section class="panel" aria-labelledby="documents-title">
    <?php list_filters('documentos', $filterValues, ['estado' => ['label' => 'Estado', 'all' => 'Todos los estados', 'options' => $stateOptions], 'area_id' => ['label' => 'Área', 'all' => 'Todas las áreas', 'options' => $areaNames]], 'Buscar por código o título'); ?>
    <div class="panel-heading"><div><h2 id="documents-title">Listado de documentos</h2><p>Identificación, estado y versión vigente de cada registro.</p></div><?php if ($documentResult['ok']): ?><span class="record-count"><?= e(count($documents)) ?> registros consultados</span><?php endif; ?></div>
    <?php if (!$documentResult['ok']): ?>
        <div class="empty-state" role="status"><h3>No fue posible cargar los documentos</h3><p><?= e($documentResult['message']) ?></p><a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Volver a intentar</a></div>
    <?php elseif ($documents === []): ?>
        <div class="empty-state" role="status"><h3><?= $documentCount === 0 ? 'No hay documentos registrados.' : 'No hay documentos que coincidan con los filtros.' ?></h3><p><?= $documentCount === 0 ? 'Los documentos disponibles para tu cuenta aparecerán aquí.' : 'Prueba otra búsqueda o limpia los filtros.' ?></p><a class="button button-secondary" href="<?= e(page_url($documentCount === 0 && can_show_action('documento_crear') ? 'documento_nuevo' : 'documentos')) ?>"><?= $documentCount === 0 && can_show_action('documento_crear') ? 'Nuevo documento' : 'Limpiar filtros' ?></a></div>
    <?php else: ?>
        <?php require __DIR__ . '/../includes/document_table.php'; ?>
        <div class="panel-footer"><?= e(count($documents)) ?> resultados de <?= e($documentCount) ?> documentos consultados</div>
    <?php endif; ?>
</section>
<p class="context-note">Las fechas corresponden a la última actualización del registro. “Sin versión” indica que no hay una versión vigente asignada.</p>
