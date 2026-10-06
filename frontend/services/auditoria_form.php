<?php
declare(strict_types=1);

function validate_audit_form(array $input, array $users): array
{
    $errors = [];
    $values = [
        'codigo' => validated_text($input, 'codigo', $errors, 1, 60),
        'nombre' => validated_text($input, 'nombre', $errors, 1, 200),
        'alcance' => validated_text($input, 'alcance', $errors, 1, 16000, true),
        'responsable_id' => catalog_id($input, 'responsable_id', $users, $errors),
    ];
    foreach (['fecha_inicio_prevista', 'fecha_fin_prevista'] as $field) {
        $value = $input[$field] ?? '';
        $values[$field] = is_string($value) ? trim($value) : '';
        if (!is_string($value) || ($value !== '' && calendar_date($value) === '—')) $errors[$field] = 'Introduce una fecha válida.';
    }
    if (!isset($errors['fecha_inicio_prevista']) && !isset($errors['fecha_fin_prevista']) && $values['fecha_inicio_prevista'] !== '' && $values['fecha_fin_prevista'] !== '' && $values['fecha_fin_prevista'] < $values['fecha_inicio_prevista']) {
        $errors['fecha_fin_prevista'] = 'La fecha final no puede ser anterior a la inicial.';
    }
    $body = $values;
    foreach (['fecha_inicio_prevista', 'fecha_fin_prevista'] as $field) $body[$field] = $body[$field] === '' ? null : $body[$field];
    return ['values' => $values, 'errors' => $errors, 'body' => $body];
}
