<?php if (!isset($values, $fileMode)) { http_response_code(404); exit; }
$auditOptions = []; foreach ($availableAudits as $row) $auditOptions[$row['id']] = (is_string($row['codigo'] ?? null) ? $row['codigo'] : '') . ' · ' . (is_string($row['nombre'] ?? null) ? $row['nombre'] : '');
$documentOptions = []; foreach ($availableDocuments as $row) { $id = positive_id($row['id'] ?? null); if ($id !== null) $documentOptions[$id] = (is_string($row['codigo'] ?? null) ? $row['codigo'] : '') . ' · ' . (is_string($row['titulo'] ?? null) ? $row['titulo'] : ''); }
$versionOptions = []; foreach ($availableVersions as $row) { $id = positive_id($row['id'] ?? null); if ($id !== null) $versionOptions[$id] = 'v' . (positive_id($row['numero_version'] ?? null) ?? ''); }
?>
<div class="page-heading"><div><p class="eyebrow">REGISTRO PROBATORIO</p><h1><?= $fileMode ? 'Evidencia de archivo' : 'Evidencia lógica' ?></h1><p class="page-description">Registra evidencia asociada a una auditoría existente.</p></div><a class="button button-secondary" href="<?= e(page_url('evidencias', $values['auditoria_id'] !== null ? ['auditoria_id' => $values['auditoria_id'], 'hallazgo_id'=>$findingId] : [])) ?>">Volver a evidencias</a></div>
<section class="panel new-document-panel"><div class="panel-heading"><div><h2>Datos de la evidencia</h2><p>Los campos marcados con * son obligatorios.</p></div></div><div class="upload-body">
<?php if ($findingId!==null): ?><p class="context-note">La evidencia se registrará y asociará al hallazgo #<?= e($finding['numero']??$findingId) ?> en una sola operación.</p><?php endif; ?>
<?php if ($formError !== null): ?><div class="notice notice-error" role="alert"><?= e($formError) ?></div><?php endif; ?>
<?php if (!$auditResult['ok']): ?><div class="notice" role="status">No fue posible consultar las auditorías. Intenta nuevamente.</div>
<?php elseif ($availableAudits === []): ?><div class="notice" role="status">No hay auditorías disponibles para registrar evidencias. <?php if (can_show_action('auditoria_crear')): ?><a class="text-link" href="<?= e(page_url('auditoria_nueva')) ?>">Crear auditoría</a><?php endif; ?></div>
<?php endif; ?>
<?php if (!$documentResult['ok']): ?><div class="notice" role="status">No fue posible consultar los documentos. Puedes registrar la evidencia sin vincular un documento.</div><?php endif; ?>
<form action="<?= e(page_url($page, $findingId===null ? [] : ['hallazgo_id'=>$findingId])) ?>" method="post"<?= $fileMode ? ' enctype="multipart/form-data"' : '' ?> data-evidence-form><input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>"><div class="form-grid">
<?php
form_select('auditoria_id', 'Auditoría', $auditOptions, $values, $fieldErrors);
form_control('titulo', 'Título', $values, $fieldErrors, 'text', true, 200);
if ($fileMode) form_control('archivo', 'Archivo', $values, $fieldErrors, 'file', true);
else form_select('tipo', 'Tipo de evidencia', LOGICAL_EVIDENCE_TYPES, $values, $fieldErrors);
form_control('descripcion', 'Descripción', $values, $fieldErrors, 'textarea');
if (!$fileMode) form_control('referencia_url', 'URL de referencia (obligatoria para Referencia)', $values, $fieldErrors, 'url', false, 2048);
?>
</div><?php if ($fileMode): ?><p class="field-help">El límite de evidencias del servidor es configurable: 20 MiB por defecto. Límites de recepción PHP: <?= e(ini_get('upload_max_filesize')) ?> por archivo y <?= e(ini_get('post_max_size')) ?> por envío completo. Se aplica el límite más restrictivo.</p><?php else: ?><p class="field-help">La URL es obligatoria cuando el tipo es Referencia. Utiliza http o https.</p><?php endif; ?>
<div class="form-section-heading"><h2>Vinculación documental opcional</h2><p>El documento debe estar vinculado a la auditoría seleccionada. Las opciones muestran los documentos que puedes consultar; la relación se valida al guardar. Puedes registrar evidencia sin vinculación documental.</p></div><div class="form-grid">
<?php form_select('documento_id', 'Documento', $documentOptions, $values, $fieldErrors, false); form_select('version_documento_id', 'Versión del documento', $versionOptions, $values, $fieldErrors, false); ?>
</div><p class="field-help" id="version-status" role="status"></p><noscript><p class="field-help">Sin JavaScript puedes vincular un documento; sus versiones se mostrarán al volver a presentar el formulario.</p></noscript>
<div class="form-actions"><button class="button button-primary" type="submit"<?= !$canSubmit ? ' disabled' : '' ?>>Guardar evidencia</button><a class="button button-secondary" href="<?= e(page_url('evidencias', $values['auditoria_id'] !== null ? ['auditoria_id' => $values['auditoria_id'], 'hallazgo_id'=>$findingId] : [])) ?>">Cancelar</a></div></form></div></section>
