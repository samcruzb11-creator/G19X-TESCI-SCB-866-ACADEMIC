<?php if (!isset($values,$auditId)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">AUDITORÍA <?= e($audit['codigo']??$auditId) ?></p><h1><?= $editing ? 'Editar hallazgo' : 'Nuevo hallazgo' ?></h1></div><a class="button button-secondary" href="<?= e(page_url('auditoria',['id'=>$auditId])) ?>">Volver a auditoría</a></div>
<section class="panel"><div class="panel-heading"><h2>Datos del hallazgo</h2></div><div class="upload-body">
<?php if ($formError!==null): ?><div class="notice notice-error" role="alert"><?= e($formError) ?></div><?php endif; ?>
<form method="post" action="<?= e(page_url($page,$editing ? ['id'=>$recordId] : ['auditoria_id'=>$auditId])) ?>">
<input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>">
<?php if ($editing): ?><input type="hidden" name="updated_at_esperado" value="<?= e($expectedUpdate) ?>"><?php else: ?><input type="hidden" name="auditoria_id" value="<?= e($auditId) ?>"><?php endif; ?>
<div class="form-grid">
<?php
form_control('titulo','Título',$values,$fieldErrors,'text',true,200);
form_control('categoria','Categoría',$values,$fieldErrors,'text',true,40);
form_control('descripcion','Descripción',$values,$fieldErrors,'textarea',true,16000);
form_select('severidad','Severidad',finding_severities(),$values,$fieldErrors);
form_select('responsable_id','Responsable',$ownerOptions,$values,$fieldErrors,false);
form_control('fecha_limite','Fecha límite',$values,$fieldErrors,'date');
if ($editing) form_control('resolucion','Resolución',$values,$fieldErrors,'textarea',false,16000);
?>
</div><div class="form-actions"><button class="button button-primary" type="submit">Guardar hallazgo</button><a class="button button-secondary" href="<?= e(page_url('auditoria',['id'=>$auditId])) ?>">Cancelar</a></div></form></div></section>
