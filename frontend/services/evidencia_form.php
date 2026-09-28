<?php
declare(strict_types=1);

const LOGICAL_EVIDENCE_TYPES = ['NOTE' => 'Nota', 'REFERENCE' => 'Referencia', 'OTHER' => 'Otra evidencia'];

function validate_evidence_form(array $input, bool $fileMode, array $audits, array $users, array $documents, array $versions): array
{
    $errors = [];
    $values = [
        'titulo' => validated_text($input, 'titulo', $errors, 3, 200),
        'descripcion' => validated_text($input, 'descripcion', $errors, 0, null, true),
        'auditoria_id' => catalog_id($input, 'auditoria_id', $audits, $errors),
        'registrada_por_id' => catalog_id($input, 'registrada_por_id', $users, $errors),
        'documento_id' => catalog_id($input, 'documento_id', $documents, $errors, false),
        'version_documento_id' => catalog_id($input, 'version_documento_id', $versions, $errors, false),
    ];
    if ($values['version_documento_id'] !== null) {
        $matches = array_filter($versions, fn(array $v): bool => positive_id($v['id'] ?? null) === $values['version_documento_id'] && positive_id($v['documento_id'] ?? null) === $values['documento_id']);
        if ($values['documento_id'] === null || !$matches) $errors['version_documento_id'] = 'Selecciona una versión del documento indicado.';
    }
    $body = $values;
    if ($fileMode) {
        // Optional form fields must be omitted, not sent as empty strings or null.
        $body = array_filter($body, fn($value): bool => $value !== null && $value !== '');
        $query = [];
    } else {
        $values['tipo'] = is_string($input['tipo'] ?? null) ? $input['tipo'] : '';
        if (isset($input['tipo']) && !is_string($input['tipo'])) $values['tipo'] = '';
        if (!isset(LOGICAL_EVIDENCE_TYPES[$values['tipo']])) $errors['tipo'] = 'Selecciona un tipo de evidencia lógica válido.';
        $values['referencia_url'] = validated_text($input, 'referencia_url', $errors, 0, 2048);
        if ($values['tipo'] === 'REFERENCE' && $values['referencia_url'] === '') $errors['referencia_url'] = 'La referencia requiere una URL.';
        if ($values['referencia_url'] !== '' && (filter_var($values['referencia_url'], FILTER_VALIDATE_URL) === false || !in_array(strtolower((string) parse_url($values['referencia_url'], PHP_URL_SCHEME)), ['http', 'https'], true))) {
            $errors['referencia_url'] = 'Introduce una URL válida con http o https.';
        }
        $body['tipo'] = $values['tipo'];
        $body['referencia_url'] = $values['referencia_url'] === '' ? null : $values['referencia_url'];
        $body['descripcion'] = $values['descripcion'] === '' ? null : $values['descripcion'];
        unset($body['registrada_por_id']);
        $query = ['registrada_por_id' => $values['registrada_por_id']];
    }
    return ['values' => $values, 'errors' => $errors, 'body' => $body, 'query' => $query];
}
