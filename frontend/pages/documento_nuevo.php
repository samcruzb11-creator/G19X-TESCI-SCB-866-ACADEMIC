<?php if (!isset($values, $availableAreas, $availableUsers)) { http_response_code(404); exit; } ?>
<div class="page-heading"><div><p class="eyebrow">REGISTRO DOCUMENTAL</p><h1>Nuevo documento</h1><p class="page-description">Registrar un nuevo documento en el sistema de trazabilidad.</p></div></div>
<section class="panel new-document-panel" aria-labelledby="new-document-title">
    <div class="panel-heading"><div><h2 id="new-document-title">Datos del documento</h2><p>Los campos marcados con * son obligatorios.</p></div></div>
    <div class="upload-body">
        <?php if ($formError !== null): ?><div class="notice notice-error" role="alert"><?= e($formError) ?></div><?php endif; ?>
        <?php if (!$areaResult['ok'] || !$userResult['ok']): ?><div class="notice" role="status">No fue posible cargar las áreas o los usuarios. El guardado estará disponible cuando se puedan consultar los catálogos.</div>
        <?php elseif ($availableAreas === [] || $availableUsers === []): ?><div class="notice" role="status">Se necesita al menos un área activa y un usuario activo para registrar un documento.</div><?php endif; ?>
        <form action="<?= e(page_url('documento_nuevo')) ?>" method="post">
            <input type="hidden" name="csrf_token" value="<?= e($csrfToken) ?>">
            <div class="form-grid">
                <?php foreach (['codigo' => ['Código', 2, 80], 'tipo' => ['Tipo', 2, 40], 'titulo' => ['Título', 3, 240]] as $field => [$label, $min, $max]): ?>
                <div class="form-field<?= $field === 'titulo' ? ' info-wide' : '' ?><?= isset($fieldErrors[$field]) ? ' has-error' : '' ?>">
                    <label for="<?= e($field) ?>"><?= e($label) ?> *</label>
                    <input id="<?= e($field) ?>" name="<?= e($field) ?>" value="<?= e($values[$field]) ?>" minlength="<?= e($min) ?>" maxlength="<?= e($max) ?>" required<?= isset($fieldErrors[$field]) ? ' aria-invalid="true"' : '' ?> aria-describedby="<?= e($field) ?>-help<?= isset($fieldErrors[$field]) ? ' ' . e($field) . '-error' : '' ?>">
                    <p class="field-help" id="<?= e($field) ?>-help"><?= $field === 'tipo' ? 'Texto libre de 2 a 40 caracteres; utiliza la clasificación de tu organización.' : ($field === 'codigo' ? 'Identificador único de 2 a 80 caracteres.' : 'Nombre del documento, de 3 a 240 caracteres.') ?></p>
                    <?php if (isset($fieldErrors[$field])): ?><p class="field-error" id="<?= e($field) ?>-error"><?= e($fieldErrors[$field]) ?></p><?php endif; ?>
                </div>
                <?php endforeach; ?>
                <div class="form-field info-wide<?= isset($fieldErrors['descripcion']) ? ' has-error' : '' ?>"><label for="descripcion">Descripción <span>(opcional)</span></label><textarea id="descripcion" name="descripcion" rows="3"<?= isset($fieldErrors['descripcion']) ? ' aria-invalid="true" aria-describedby="descripcion-error"' : '' ?>><?= e($values['descripcion']) ?></textarea><?php if (isset($fieldErrors['descripcion'])): ?><p class="field-error" id="descripcion-error"><?= e($fieldErrors['descripcion']) ?></p><?php endif; ?></div>
            </div>
            <div class="form-section-heading"><h2>Asignación y registro</h2><p>Selecciona el área propietaria y los usuarios del catálogo vigente.</p></div>
            <div class="form-grid">
                <?php foreach (['area_id' => 'Área', 'responsable_id' => 'Responsable', 'creador_id' => 'Creador'] as $field => $label): $options = $field === 'area_id' ? $availableAreas : $availableUsers; ?>
                    <div class="form-field<?= isset($fieldErrors[$field]) ? ' has-error' : '' ?>"><label for="<?= e($field) ?>"><?= e($label) ?> *</label><select id="<?= e($field) ?>" name="<?= e($field) ?>" required<?= isset($fieldErrors[$field]) ? ' aria-invalid="true" aria-describedby="' . e($field) . '-error"' : '' ?>><option value="">Selecciona <?= $field === 'area_id' ? 'un área' : 'un usuario' ?></option><?php foreach ($options as $option): ?><option value="<?= e($option['id']) ?>"<?= $values[$field] === positive_id($option['id']) ? ' selected' : '' ?>><?= e($option['nombre'] ?? '') ?></option><?php endforeach; ?></select><?php if (isset($fieldErrors[$field])): ?><p class="field-error" id="<?= e($field) ?>-error"><?= e($fieldErrors[$field]) ?></p><?php endif; ?></div>
                <?php endforeach; ?>
                <div class="form-field<?= isset($fieldErrors['estado']) ? ' has-error' : '' ?>"><label for="estado">Estado</label><select id="estado" name="estado"<?= isset($fieldErrors['estado']) ? ' aria-invalid="true" aria-describedby="estado-error"' : '' ?>><?php foreach (DOCUMENT_STATES as $state => $label): ?><option value="<?= e($state) ?>"<?= $values['estado'] === $state ? ' selected' : '' ?>><?= e($label) ?></option><?php endforeach; ?></select><?php if (isset($fieldErrors['estado'])): ?><p class="field-error" id="estado-error"><?= e($fieldErrors['estado']) ?></p><?php endif; ?></div>
            </div>
            <p class="context-note">Después de guardar podrás adjuntar la primera versión desde la ficha del documento.</p>
            <div class="form-actions"><button class="button button-primary" type="submit"<?= !$canSubmit ? ' disabled' : '' ?>>Guardar documento</button><a class="button button-secondary" href="<?= e(page_url('documentos')) ?>">Cancelar</a></div>
        </form>
    </div>
</section>
