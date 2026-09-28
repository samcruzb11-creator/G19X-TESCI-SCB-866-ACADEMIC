<?php
declare(strict_types=1);

// State choices are documented by DocumentoCreate; tipo has no enum in OpenAPI.
const DOCUMENT_STATES = ['DRAFT' => 'Borrador', 'ACTIVE' => 'Activo', 'OBSOLETE' => 'Obsoleto', 'ARCHIVED' => 'Archivado'];

/** Pure validation also allows inspection of the exact request without sending it. */
function validate_document_form(array $input, array $areas, array $users): array
{
    $values = [];
    $errors = [];
    foreach (['codigo' => [2, 80], 'titulo' => [3, 240], 'tipo' => [2, 40]] as $field => [$min, $max]) {
        $raw = $input[$field] ?? '';
        $value = is_string($raw) ? (preg_replace('/\s+/u', ' ', trim($raw)) ?? '') : '';
        $values[$field] = $value;
        if (mb_strlen($value, 'UTF-8') < $min || mb_strlen($value, 'UTF-8') > $max) {
            $errors[$field] = "Introduce entre $min y $max caracteres.";
        }
    }
    $description = $input['descripcion'] ?? '';
    $values['descripcion'] = is_string($description) ? trim($description) : '';
    if (!is_string($description) || !mb_check_encoding($description, 'UTF-8')) {
        $errors['descripcion'] = 'Introduce una descripción de texto válida.';
    }
    $state = $input['estado'] ?? 'DRAFT';
    $values['estado'] = is_string($state) ? trim($state) : '';
    if (!array_key_exists($values['estado'], DOCUMENT_STATES)) $errors['estado'] = 'Selecciona un estado válido.';
    foreach (['area_id', 'responsable_id', 'creador_id'] as $field) {
        $id = positive_id($input[$field] ?? null);
        $values[$field] = $id;
        $catalog = $field === 'area_id' ? $areas : $users;
        if ($id === null || !in_array($id, array_column($catalog, 'id'), true)) {
            $errors[$field] = $field === 'area_id' ? 'Selecciona un área activa del catálogo.' : 'Selecciona un usuario activo del catálogo.';
        }
    }
    return [
        'values' => $values, 'errors' => $errors,
        'query' => ['creador_id' => $values['creador_id']],
        'body' => [
            'codigo' => $values['codigo'], 'titulo' => $values['titulo'],
            'descripcion' => $values['descripcion'] === '' ? null : $values['descripcion'],
            'tipo' => $values['tipo'], 'estado' => $values['estado'],
            'area_id' => $values['area_id'], 'responsable_id' => $values['responsable_id'],
        ],
    ];
}

function document_creation_error(array $result): array
{
    $fields = [];
    $message = 'No fue posible guardar el documento. Intenta nuevamente.';
    switch ($result['error_code'] ?? '') {
        case 'duplicate_code':
            $message = $fields['codigo'] = 'El código indicado ya existe.';
            break;
        case 'creator_not_found':
            $message = $fields['creador_id'] = 'El creador seleccionado no existe.';
            break;
        case 'validation':
            foreach ($result['error_fields'] ?? [] as $field) $fields[$field] = 'Revisa este valor; la API no lo aceptó.';
            $message = $fields ? 'Revisa los campos marcados.' : 'La API no aceptó los datos. Revisa los campos del formulario.';
            break;
        case 'not_found':
            $message = 'No fue posible encontrar el recurso solicitado para registrar el documento.';
            break;
        case 'conflict':
            $message = 'La API informó un conflicto al guardar el documento. Revisa los datos antes de intentar nuevamente.';
            break;
        default:
            if (($result['status'] ?? 0) === 0 || ($result['status'] ?? 0) >= 500 || ($result['status'] ?? 0) === 201) {
                $message = 'No fue posible confirmar la creación. Consulta el listado antes de volver a enviar el formulario.';
            }
    }
    return ['message' => $message, 'fields' => $fields];
}
