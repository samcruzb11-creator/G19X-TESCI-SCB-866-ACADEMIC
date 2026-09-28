<?php if (!isset($values, $availableUsers)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">GESTIÓN DE AUDITORÍAS</p><h1>Nueva auditoría</h1><p class="page-description">Define el alcance, las fechas previstas y los responsables.</p></div></div>
<section class="panel new-document-panel"><div class="panel-heading"><div><h2>Datos de la auditoría</h2><p>Los campos marcados con * son obligatorios.</p></div><span class="badge badge-warning">Estado inicial: planificada</span></div><div class="upload-body">
<?php if ($formError !== null): ?><div class="notice notice-error" role="alert"><?= e($formError) ?></div><?php endif; ?>
<?php if (!$userResult['ok'] || $availableUsers === []): ?><div class="notice" role="status">No hay usuarios disponibles para este formulario.</div><?php endif; ?>
<form action="<?= e(page_url('auditoria_nueva')) ?>" method="post"><input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>"><div class="form-grid">
<?php
form_control('codigo', 'Código', $values, $fieldErrors, 'text', true, 60);
form_control('nombre', 'Nombre', $values, $fieldErrors, 'text', true, 200);
form_control('alcance', 'Alcance', $values, $fieldErrors, 'textarea', true);
form_control('fecha_inicio_prevista', 'Fecha de inicio prevista', $values, $fieldErrors, 'date');
form_control('fecha_fin_prevista', 'Fecha de fin prevista', $values, $fieldErrors, 'date');
form_select('responsable_id', 'Responsable', areas_by_id($availableUsers), $values, $fieldErrors);
form_select('created_by_id', 'Creador', areas_by_id($availableUsers), $values, $fieldErrors);
?>
</div><div class="form-actions"><button type="submit" class="button button-primary"<?= !$canSubmit ? ' disabled' : '' ?>>Guardar auditoría</button><a class="button button-secondary" href="<?= e(page_url('auditorias')) ?>">Cancelar</a></div></form></div></section>
