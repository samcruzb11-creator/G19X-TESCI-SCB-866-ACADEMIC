<?php if (!isset($route)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">CONTROL DOCUMENTAL</p><h1>Resumen general</h1><p class="page-description">Resumen de los registros disponibles para tu cuenta.</p></div><a class="button button-primary" href="<?= e(page_url('documentos')) ?>">Consultar documentos</a></div>
<?php if (!$documentResult['ok'] || !$auditResult['ok'] || !$areaResult['ok']): ?>
    <div class="notice" role="status">Parte de la información no pudo cargarse. Los indicadores no disponibles se muestran con un guion.</div>
<?php endif; ?>
<section class="metrics" aria-label="Resumen de registros consultados">
    <?php foreach ($metrics as $metric): ?>
        <div class="metric"><h2><?= e($metric['label']) ?></h2><p class="metric-value"><?= $metric['value'] === null ? '—' : e($metric['value']) ?></p><p class="metric-note"><?= e($metric['value'] === null ? 'Información no disponible' : $metric['note']) ?></p></div>
    <?php endforeach; ?>
</section>
<nav class="module-links" aria-label="Accesos a los módulos"><?php foreach (navigation_items() as $key => $label): if ($key === 'dashboard') continue; ?><a class="text-link" href="<?= e(page_url($key)) ?>"><?= e($label) ?></a><?php endforeach; ?></nav>
<section class="panel" aria-labelledby="recent-title">
    <div class="panel-heading"><div><h2 id="recent-title">Documentos recientes</h2><p>Últimas actualizaciones entre los documentos consultados.</p></div><a class="text-link" href="<?= e(page_url('documentos')) ?>">Ver listado completo</a></div>
    <?php if (!$documentResult['ok']): ?>
        <div class="empty-state"><h3>Información no disponible</h3><p><?= e($documentResult['message']) ?></p><a class="button button-secondary" href="<?= e(page_url('dashboard')) ?>">Volver a intentar</a></div>
    <?php elseif ($documents === []): ?>
        <div class="empty-state"><h3>No hay documentos disponibles.</h3><p>Los documentos aparecerán aquí cuando estén disponibles para tu cuenta.</p></div>
    <?php else: ?>
        <?php require __DIR__ . '/../includes/document_table.php'; ?>
        <div class="panel-footer"><?= e(count($documents)) ?> documentos recientes · <?= e(count($allDocuments)) ?> consultados</div>
    <?php endif; ?>
</section>
<p class="context-note">Los indicadores reflejan los registros consultados. No representan totales globales cuando se alcanza el límite de la consulta.</p>
