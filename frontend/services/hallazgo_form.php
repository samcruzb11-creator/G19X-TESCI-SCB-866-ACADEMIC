<?php
declare(strict_types=1);

function finding_states(): array {
    return ['OPEN'=>'Abierto','IN_PROGRESS'=>'En atención','PENDING_VERIFICATION'=>'Pendiente de verificación','CLOSED'=>'Cerrado','ACCEPTED_RISK'=>'Riesgo aceptado'];
}
function finding_severities(): array {
    return ['LOW'=>'Baja','MEDIUM'=>'Media','HIGH'=>'Alta','CRITICAL'=>'Crítica'];
}
function finding_page(string $key): int {
    $value = positive_id($_GET[$key] ?? '1');
    if ($value === null || $value > 501) throw new ApiPageError(422, 'Número de página inválido.');
    return $value;
}
function finding_query(array $keys): array {
    $values=[];
    foreach ($keys as $key) {
        if (isset($_GET[$key]) && !is_string($_GET[$key])) throw new ApiPageError(422, 'Filtros inválidos.');
        $values[$key]=list_query($key);
    }
    return $values;
}
function validate_finding_form(array $input, bool $editing): array {
    $values=[]; $errors=[]; $body=[];
    foreach (['titulo'=>200,'descripcion'=>16000,'categoria'=>40,'severidad'=>16] as $key=>$max) {
        $values[$key]=validated_text($input,$key,$errors,1,$max,$key==='descripcion');
        $body[$key]=$values[$key];
    }
    if (!isset(finding_severities()[$values['severidad']])) $errors['severidad']='Selecciona una severidad válida.';
    foreach (['fecha_limite','responsable_id'] as $key) {
        $values[$key]=is_string($input[$key]??null) ? $input[$key] : '';
        if (isset($input[$key]) && !is_string($input[$key])) $errors[$key]='Valor inválido.';
        $body[$key]=$values[$key]==='' ? null : ($key==='responsable_id' ? positive_id($values[$key]) : $values[$key]);
        if ($key==='responsable_id' && $values[$key]!=='' && $body[$key]===null) $errors[$key]='Responsable inválido.';
    }
    if (!$editing) {
        $body['auditoria_id']=positive_id($input['auditoria_id']??null);
        if ($body['auditoria_id']===null) $errors['auditoria_id']='Auditoría inválida.';
    } else {
        $body['updated_at_esperado']=is_string($input['updated_at_esperado']??null) ? $input['updated_at_esperado'] : '';
        $values['resolucion']=is_string($input['resolucion']??null) ? trim($input['resolucion']) : '';
        $body['resolucion']=$values['resolucion']==='' ? null : $values['resolucion'];
        if (mb_strlen($values['resolucion'])>16000) $errors['resolucion']='Máximo 16000 caracteres.';
    }
    return ['values'=>$values,'errors'=>$errors,'body'=>$body];
}
