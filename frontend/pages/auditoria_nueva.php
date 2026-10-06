<?php if (!isset($values, $availableUsers)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">GESTIÓN DE AUDITORÍAS</p><h1><?= $editing ? 'Editar auditoría' : 'Nueva auditoría' ?></h1><p class="page-description">Define el alcance, las fechas previstas y el responsable.</p></div><a class="button button-secondary" href="<?= e(page_url('auditorias')) ?>">Volver a auditorías</a></div>
<section class="panel new-document-panel"><div class="panel-heading"><div><h2>Datos de la auditoría</h2><p>Los campos marcados con * son obligatorios.</p></div><span class="badge badge-warning"><?= $editing ? 'Edición de datos' : 'Estado inicial: borrador' ?></span></div><div class="upload-body">
<?php if ($formError !== null): ?><div class="notice notice-error" role="alert"><?= e($formError) ?></div><?php endif; ?>
<?php if (!$userResult['ok'] || $availableUsers === []): ?><div class="notice" role="status">No hay usuarios disponibles para este formulario.</div><?php endif; ?>
<form action="<?= e(page_url($page, $editing ? ['id'=>$recordId] : [])) ?>" method="post"><input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>"><?php if ($editing): ?><input type="hidden" name="updated_at_esperado" value="<?= e($expectedUpdate) ?>"><?php endif; ?><div class="form-grid">
<?php
if (!$editing) form_control('codigo', 'Código', $values, $fieldErrors, 'text', true, 60);
else echo '<div class="form-field"><span>Código</span><p>' . e($values['codigo']) . '</p></div>';
form_control('nombre', 'Nombre', $values, $fieldErrors, 'text', true, 200);
form_control('alcance', 'Alcance', $values, $fieldErrors, 'textarea', true, 16000);
form_control('fecha_inicio_prevista', 'Fecha de inicio prevista', $values, $fieldErrors, 'date');
form_control('fecha_fin_prevista', 'Fecha de fin prevista', $values, $fieldErrors, 'date');
if (user_has_role('ADMIN')) form_select('responsable_id', 'Responsable', areas_by_id($availableUsers), $values, $fieldErrors);
else echo '<div class="form-field"><label>Responsable</label><p>' . e(current_user()['nombre']) . '</p></div>';

?>
</div><div class="form-actions"><button type="submit" class="button button-primary"<?= !$canSubmit ? ' disabled' : '' ?>>Guardar auditoría</button><a class="button button-secondary" href="<?= e(page_url('auditorias')) ?>">Cancelar</a></div></form></div></section>
