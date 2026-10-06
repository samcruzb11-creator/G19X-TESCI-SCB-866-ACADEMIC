<?php
declare(strict_types=1);

function active_users(array $rows): array
{
    return array_values(array_filter($rows, fn(array $row): bool => positive_id($row['id'] ?? null) !== null && ($row['activo'] ?? false) === true));
}

function validated_text(array $input, string $key, array &$errors, int $min = 0, ?int $max = null, bool $multiline = false): string
{
    $raw = $input[$key] ?? '';
    if (!is_string($raw) || !mb_check_encoding($raw, 'UTF-8')) { $errors[$key] = 'Introduce un texto válido.'; return ''; }
    $value = $multiline ? trim($raw) : (preg_replace('/\s+/u', ' ', trim($raw)) ?? '');
    $length = mb_strlen($value, 'UTF-8');
    if ($length < $min || ($max !== null && $length > $max)) $errors[$key] = $max === null ? 'Completa este campo.' : "Introduce entre $min y $max caracteres.";
    return $value;
}

function catalog_id(array $input, string $field, array $rows, array &$errors, bool $required = true): ?int
{
    $raw = $input[$field] ?? '';
    if (!$required && ($raw === '' || $raw === null)) return null;
    $id = positive_id($raw);
    if ($id === null || !in_array($id, array_column($rows, 'id'), true)) $errors[$field] = 'Selecciona una opción válida del catálogo.';
    return $id;
}

function record_error(array $result, string $noun): array
{
    $fields = [];
    if (($result['error_code'] ?? '') === 'duplicate_code') return ['message' => 'El código indicado ya existe.', 'fields' => ['codigo' => 'El código indicado ya existe.']];
    if (($result['status'] ?? 0) === 422) {
        foreach ($result['error_fields'] ?? [] as $field) $fields[$field] = 'Revisa este valor; la API no lo aceptó.';
        return ['message' => $fields ? 'Revisa los campos marcados.' : 'La API no aceptó los datos. Revisa los campos y sus relaciones.', 'fields' => $fields];
    }
    $message = match ($result['status'] ?? 0) {
        400 => 'La API no aceptó el registro. Revisa los datos y sus relaciones.',
        404 => 'No se encontró alguno de los registros necesarios. Actualiza los catálogos antes de intentar nuevamente.',
        409 => 'Existe un conflicto con los datos registrados. Revisa la información.',
        default => "No fue posible confirmar el registro de $noun. Comprueba si se guardó antes de volver a enviarlo.",
    };
    return ['message' => $message, 'fields' => []];
}

function audit_status(mixed $state): array
{
    return is_string($state) ? ([
        'PLANNED' => ['Borrador', 'warning'], 'IN_PROGRESS' => ['Activa', 'neutral'],
        'IN_REVIEW' => ['En revisión', 'warning'],
        'COMPLETED' => ['Cerrada', 'success'], 'CANCELLED' => ['Cancelada', 'neutral'],
    ][$state] ?? ['Sin clasificar', 'neutral']) : ['Sin clasificar', 'neutral'];
}

function evidence_type(mixed $type): string
{
    return is_string($type) ? (['FILE' => 'Archivo', 'NOTE' => 'Nota', 'REFERENCE' => 'Referencia', 'OTHER' => 'Otra evidencia'][$type] ?? 'Sin clasificar') : 'Sin clasificar';
}

function calendar_date(mixed $value): string
{
    if (!is_string($value) || !preg_match('/\A\d{4}-\d{2}-\d{2}\z/', $value)) return '—';
    $date = DateTimeImmutable::createFromFormat('!Y-m-d', $value);
    return $date && $date->format('Y-m-d') === $value ? $date->format('d/m/Y') : '—';
}
