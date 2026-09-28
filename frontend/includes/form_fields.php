<?php
declare(strict_types=1);

function form_error(string $name, array $errors): void
{
    if (isset($errors[$name])) echo '<p class="field-error" id="' . e($name) . '-error">' . e($errors[$name]) . '</p>';
}

function form_control(string $name, string $label, array $values, array $errors, string $type = 'text', bool $required = false, ?int $max = null): void
{
    $attrs = ' id="' . e($name) . '" name="' . e($name) . '"' . ($required ? ' required' : '');
    if ($max !== null) $attrs .= ' maxlength="' . $max . '"';
    if (isset($errors[$name])) $attrs .= ' aria-invalid="true" aria-describedby="' . e($name) . '-error"';
    echo '<div class="form-field' . ($type === 'textarea' ? ' info-wide' : '') . (isset($errors[$name]) ? ' has-error' : '') . '"><label for="' . e($name) . '">' . e($label) . ($required ? ' *' : ' <span>(opcional)</span>') . '</label>';
    if ($type === 'textarea') echo '<textarea' . $attrs . ' rows="3">' . e($values[$name] ?? '') . '</textarea>';
    else echo '<input type="' . e($type) . '"' . $attrs . ($type !== 'file' ? ' value="' . e($values[$name] ?? '') . '"' : '') . '>';
    form_error($name, $errors);
    echo '</div>';
}

function form_select(string $name, string $label, array $options, array $values, array $errors, bool $required = true): void
{
    echo '<div class="form-field' . (isset($errors[$name]) ? ' has-error' : '') . '"><label for="' . e($name) . '">' . e($label) . ($required ? ' *' : ' <span>(opcional)</span>') . '</label><select id="' . e($name) . '" name="' . e($name) . '"' . ($required ? ' required' : '') . (isset($errors[$name]) ? ' aria-invalid="true" aria-describedby="' . e($name) . '-error"' : '') . '><option value="">' . ($required ? 'Selecciona una opción' : 'Sin vincular') . '</option>';
    foreach ($options as $key => $label) echo '<option value="' . e($key) . '"' . ((string) ($values[$name] ?? '') === (string) $key ? ' selected' : '') . '>' . e($label) . '</option>';
    echo '</select>';
    form_error($name, $errors);
    echo '</div>';
}
