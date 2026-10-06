<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
require_once __DIR__.'/hallazgo_form.php';
$formError=null; $fieldErrors=[]; $successMessage=null;
$userNames=presentation_user_names();

if ($page==='hallazgos') {
    $filterValues=finding_query(['auditoria_id','estado','severidad','responsable_id','q','orden']);
    $pageNumber=finding_page('p');
    $findingResult=api_get('/api/v1/hallazgos',array_filter($filterValues,static fn($v)=>$v!=='')+['limit'=>20,'offset'=>($pageNumber-1)*20]);
    if (!$findingResult['ok']) http_response_code(api_http_status($findingResult));
    $findingCount=$findingResult['total']??count($findingResult['data']);
    $pageCount=max(1,(int)ceil($findingCount/20));
    session_write_close(); return;
}

$editing=$page==='hallazgo_editar';
$finding=null;
if ($page!=='hallazgo_nuevo') {
    $findingResult=api_get_object('/api/v1/hallazgos/'.$recordId);
    if (!$findingResult['ok']) throw new ApiPageError(api_http_status($findingResult),'El hallazgo no está disponible.');
    $finding=$findingResult['data'];
    $auditId=positive_id($finding['auditoria_id']??null);
} else {
    $auditId=positive_id($_GET['auditoria_id']??null);
    if ($auditId===null) throw new ApiPageError(422,'Selecciona una auditoría desde su detalle.');
}
$auditResult=api_get_object('/api/v1/auditorias/'.$auditId);
if (!$auditResult['ok']) throw new ApiPageError(api_http_status($auditResult),'La auditoría no está disponible.');
$audit=$auditResult['data'];
$mutable=can_show_action('hallazgo_gestionar') && in_array($audit['estado']??'', ['IN_PROGRESS','IN_REVIEW'],true)
    && !in_array($finding['estado']??'', ['CLOSED','ACCEPTED_RISK'],true);

if (in_array($page,['hallazgo_nuevo','hallazgo_editar'],true)) {
    if (!$mutable) throw new ApiPageError(409,'La auditoría o el hallazgo no admite cambios.');
    $userResult=user_has_role('ADMIN') ? api_get('/api/v1/usuarios',['elegibles_auditoria'=>'true']) : ['ok'=>true,'data'=>[current_user()]];
    $ownerOptions=areas_by_id($userResult['data']);
    $values=$editing ? $finding : ['titulo'=>'','descripcion'=>'','categoria'=>'','severidad'=>'MEDIUM','fecha_limite'=>'','responsable_id'=>null];
    $expectedUpdate=$finding['updated_at']??'';
    if (($_SERVER['REQUEST_METHOD']??'GET')==='POST') {
        if (!csrf_valid($_POST['csrf_token']??null)) throw new ApiPageError(403,'La sesión del formulario no es válida. Recarga la página.');
        $validation=validate_finding_form($_POST,$editing);
        $values=$validation['values']; $fieldErrors=$validation['errors'];
        $expectedUpdate=$validation['body']['updated_at_esperado']??'';
        if ($fieldErrors) { $formError='Revisa los campos marcados.'; http_response_code(422); }
        else {
            $result=$editing ? api_patch_json('/api/v1/hallazgos/'.$recordId,$validation['body']) : api_post_json('/api/v1/hallazgos',$validation['body']);
            $id=positive_id($result['data']['id']??null);
            if ($result['ok'] && $id!==null) {
                $_SESSION['finding_success'][$id]='Hallazgo guardado correctamente.';
                $_SESSION['csrf_token']=bin2hex(random_bytes(32)); session_write_close();
                header('Location: '.page_url('hallazgo',['id'=>$id]),true,303); exit;
            }
            $error=record_error($result,'el hallazgo'); $formError=$error['message']; $fieldErrors=$error['fields'];
            http_response_code(api_http_status($result));
        }
    }
    session_write_close(); return;
}

if (($_SERVER['REQUEST_METHOD']??'GET')==='POST') {
    if (!can_show_action('hallazgo_gestionar')) throw new ApiPageError(403,'No tiene permiso para gestionar hallazgos.');
    if (!csrf_valid($_POST['csrf_token']??null)) throw new ApiPageError(403,'La sesión del formulario no es válida. Recarga la página.');
    if (!$mutable) throw new ApiPageError(409,'La auditoría o el hallazgo no admite cambios.');
    $command=$_POST['accion']??null;
    if ($command==='estado') {
        $body=[];
        foreach (['estado','estado_esperado','updated_at_esperado'] as $key) $body[$key]=is_string($_POST[$key]??null) ? $_POST[$key] : '';
        if (is_string($_POST['resolucion']??null) && trim($_POST['resolucion'])!=='') $body['resolucion']=trim($_POST['resolucion']);
        $result=api_post_json('/api/v1/hallazgos/'.$recordId.'/estado',$body);
    } elseif ($command==='asociar') {
        $id=positive_id($_POST['evidencia_id']??null);
        if ($id===null) throw new ApiPageError(422,'Evidencia inválida.');
        $body=['evidencia_id'=>$id];
        if (is_string($_POST['contexto']??null) && trim($_POST['contexto'])!=='') $body['contexto']=trim($_POST['contexto']);
        $result=api_post_json('/api/v1/hallazgos/'.$recordId.'/evidencias',$body);
    } else throw new ApiPageError(422,'Acción inválida.');
    if ($result['ok']) {
        $_SESSION['finding_success'][$recordId]='Hallazgo actualizado correctamente.';
        $_SESSION['csrf_token']=bin2hex(random_bytes(32)); session_write_close();
        header('Location: '.page_url('hallazgo',['id'=>$recordId]),true,303); exit;
    }
    $formError=record_error($result,'el hallazgo')['message']; http_response_code(api_http_status($result));
}
$successMessage=$_SESSION['finding_success'][$recordId]??null; unset($_SESSION['finding_success'][$recordId]);
$evidencePage=finding_page('ep'); $catalogPage=finding_page('cp'); $historyPage=finding_page('hp');
$linkedResult=api_get('/api/v1/hallazgos/'.$recordId.'/evidencias',['limit'=>20,'offset'=>($evidencePage-1)*20]);
$catalogResult=$mutable ? api_get('/api/v1/evidencias',['auditoria_id'=>$auditId,'limit'=>20,'offset'=>($catalogPage-1)*20]) : ['ok'=>true,'data'=>[]];
$historyResult=user_has_role('ADMIN') ? api_get('/api/v1/hallazgos/'.$recordId.'/historial',['limit'=>20,'offset'=>($historyPage-1)*20]) : ['ok'=>true,'data'=>[]];
session_write_close();
