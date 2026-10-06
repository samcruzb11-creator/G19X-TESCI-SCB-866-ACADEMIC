<?php
declare(strict_types=1);
if (!isset($route)) { http_response_code(404); exit; }
require_once __DIR__.'/aprobacion_helpers.php';
$formError=null;
$successMessage=null;
$states=approval_states();
$filters=[];
foreach (['documento_id','auditoria_id','version_documento_id','estado','q','orden','pendientes_propias'] as $key) {
    if (isset($_GET[$key]) && !is_string($_GET[$key])) throw new ApiPageError(422,'Revisa los filtros indicados.');
    $filters[$key]=list_query($key);
}
$pageNumber=approval_page('p');
if ($page==='aprobaciones') {
    $query=array_filter($filters,static fn($v):bool=>$v!=='')+['limit'=>20,'offset'=>($pageNumber-1)*20];
    $approvalResult=api_get('/api/v1/aprobaciones',$query);
    if (!$approvalResult['ok']) http_response_code(api_http_status($approvalResult));
    $approvalCount=$approvalResult['total']??count($approvalResult['data']);
    $pageCount=max(1,(int)ceil($approvalCount/20));
    session_write_close(); return;
}
if ($page==='aprobacion_nueva') {
    $resourcePage=approval_page('rp'); $approverPage=approval_page('ap');
    $context=[];
    foreach (['documento_id','auditoria_id'] as $key) {
        if ($filters[$key]!=='') {
            $id=positive_id($filters[$key]);
            if ($id===null) throw new ApiPageError(422,'Referencia inválida.');
            $context[$key]=$id;
        }
    }
    $resourceResult=api_get('/api/v1/aprobaciones/recursos',$context+['limit'=>20,'offset'=>($resourcePage-1)*20]);
    $approverResult=api_get('/api/v1/aprobaciones/aprobadores',['limit'=>20,'offset'=>($approverPage-1)*20]);
    if (!$resourceResult['ok']) throw new ApiPageError(api_http_status($resourceResult),$resourceResult['message']);
    if (!$approverResult['ok']) throw new ApiPageError(api_http_status($approverResult),$approverResult['message']);
    $selectedVersion=$filters['version_documento_id']; $selectedApprovers=[];
    if (($_SERVER['REQUEST_METHOD']??'GET')==='POST') {
        if (!csrf_valid($_POST['csrf_token']??null)) throw new ApiPageError(403,'La sesión del formulario no es válida. Recarga la página.');
        $selectedVersion=is_string($_POST['version_documento_id']??null)?$_POST['version_documento_id']:'';
        $selectedApprovers=is_array($_POST['aprobadores_ids']??null)?$_POST['aprobadores_ids']:[];
        $ids=[]; $selected=null;
        foreach ($resourceResult['data'] as $candidate) if (positive_id($candidate['version_documento_id']??null)===positive_id($selectedVersion)) $selected=$candidate;
        foreach ($selectedApprovers as $raw) {
            $id=positive_id($raw);
            if ($id===null || !in_array($id,array_column($approverResult['data'],'id'),true)) { $ids=[]; break; }
            $ids[]=$id;
        }
        if ($selected===null || count($ids)<1 || count($ids)>20 || count(array_unique($ids))!==count($ids)) {
            $formError='Selecciona una versión y entre uno y veinte aprobadores de esta página.'; http_response_code(422);
        } else {
            $payload=['documento_id'=>$selected['documento_id'],'version_documento_id'=>$selected['version_documento_id'],'aprobadores_ids'=>$ids];
            if (isset($context['auditoria_id'])) $payload['auditoria_id']=$context['auditoria_id'];
            $result=api_post_json('/api/v1/aprobaciones',$payload);
            approval_finish($result,'Ronda creada correctamente.');
            $formError=approval_error($result); http_response_code(api_http_status($result));
        }
    }
    session_write_close(); return;
}
$roundResult=api_get_object('/api/v1/aprobaciones/'.$recordId);
if (!$roundResult['ok']) throw new ApiPageError(api_http_status($roundResult),$roundResult['message']);
$round=$roundResult['data'];
if (positive_id($round['id']??null)!==$recordId) throw new ApiPageError(502,'Respuesta no disponible.');
if (($_SERVER['REQUEST_METHOD']??'GET')==='POST') {
    if (!csrf_valid($_POST['csrf_token']??null)) throw new ApiPageError(403,'La sesión del formulario no es válida. Recarga la página.');
    $action=is_string($_POST['accion']??null)?$_POST['accion']:'';
    $stamp=is_string($_POST['updated_at_esperado']??null)?$_POST['updated_at_esperado']:'';
    if ($action==='decision') {
        if (!can_show_action('aprobacion_decidir')) throw new ApiPageError(403,'No tiene permiso para decidir.');
        $payload=['estado'=>is_string($_POST['estado']??null)?$_POST['estado']:'','updated_at_esperado'=>$stamp];
        if (!is_string($_POST['comentario']??'')) throw new ApiPageError(422,'Comentario inválido.');
        $payload['comentario']=trim($_POST['comentario']??'');
    } elseif (in_array($action,['iniciar','cancelar','finalizar'],true)) {
        if (!can_show_action('aprobacion_gestionar')) throw new ApiPageError(403,'No tiene permiso para gestionar rondas.');
        $payload=['estado_esperado'=>is_string($_POST['estado_esperado']??null)?$_POST['estado_esperado']:'','updated_at_esperado'=>$stamp];
    } else throw new ApiPageError(422,'Operación inválida.');
    $result=api_post_json('/api/v1/aprobaciones/'.$recordId.'/'.$action,$payload);
    approval_finish($result,'Operación de aprobación confirmada.');
    $formError=approval_error($result); http_response_code(api_http_status($result));
}
$decisionPage=approval_page('dp'); $historyPage=approval_page('hp');
$decisionsResult=api_get('/api/v1/aprobaciones/'.$recordId.'/decisiones',['limit'=>20,'offset'=>($decisionPage-1)*20]);
$approvalHistory=api_get('/api/v1/aprobaciones/'.$recordId.'/historial',['limit'=>20,'offset'=>($historyPage-1)*20]);
$successMessage=$_SESSION['approval_success'][$recordId]??null;unset($_SESSION['approval_success'][$recordId]);
session_write_close();
