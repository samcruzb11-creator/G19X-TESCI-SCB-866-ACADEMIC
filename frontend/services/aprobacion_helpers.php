<?php
declare(strict_types=1);
function approval_states(): array {
    return ['PENDING'=>'Pendiente','IN_REVIEW'=>'En revisión','APPROVED'=>'Aprobada','REJECTED'=>'Rechazada','CHANGES_REQUESTED'=>'Cambios solicitados','CANCELLED'=>'Cancelada'];
}
function approval_page(string $key): int {
    $p=positive_id($_GET[$key]??'1');
    if ($p===null || $p>501) throw new ApiPageError(422,'Página inválida.');
    return $p;
}
function approval_error(array $result): string {
    return ($result['status']??0)===409 ? 'La ronda cambió o no admite esta operación. Recarga el detalle antes de continuar.'
        : (($result['status']??0)===422 ? 'Revisa los valores del formulario.' : $result['message']);
}
function approval_finish(array $result,string $message): void {
    $id=positive_id($result['data']['id']??null);
    if ($result['ok'] && $id!==null) {
        $_SESSION['approval_success'][$id]=$message;
        $_SESSION['csrf_token']=bin2hex(random_bytes(32));session_write_close();
        header('Location: '.page_url('aprobacion',['id'=>$id]),true,303);exit;
    }
}
function approval_pagination(string $page,array $params,string $key,int $number,array $result): void {
    ?><nav class="audit-pagination" aria-label="Paginación de aprobaciones"><?php
    if ($number>1): ?><a class="button button-secondary" href="<?= e(page_url($page,[$key=>$number-1]+$params)) ?>">Anterior</a><?php endif;
    if ($number<501 && ($result['total']??(($number-1)*20+count($result['data'])))>$number*20): ?><a class="button button-secondary" href="<?= e(page_url($page,[$key=>$number+1]+$params)) ?>">Siguiente</a><?php endif;
    ?></nav><?php
}
