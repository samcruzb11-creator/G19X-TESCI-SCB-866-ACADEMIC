<?php
declare(strict_types=1);

/** Presentation state only; FastAPI independently authorizes every admission. */
function turnstile_action_for_page(string $page): ?string
{
    return match ($page) {
        'login' => 'login',
        'solicitar_acceso' => 'access_request',
        'recuperar_password' => 'password_reset_request',
        default => null,
    };
}

function turnstile_begin(string $action, string $method): bool
{
    // A fresh GET starts a new interaction. No counters or security decisions in PHP.
    if ($method !== 'POST') unset($_SESSION['turnstile_display'][$action]);
    return ($_SESSION['turnstile_display'][$action] ?? false) === true;
}

function turnstile_transport(array $payload): array
{
    if (isset($_POST['turnstile_token'])) {
        $payload['turnstile_token'] = is_string($_POST['turnstile_token']) ? $_POST['turnstile_token'] : '';
    }
    unset($_POST['turnstile_token']);
    return $payload;
}

/** Only a strict backend 428 may activate the widget. Never trust submitted flags. */
function turnstile_update(array &$result, string $action, bool $display): bool
{
    if ($result['status'] === 428) {
        if (($result['challenge_required'] ?? false) !== true || ($result['challenge_action'] ?? null) !== $action) {
            $result = api_failure(502);
            unset($_SESSION['turnstile_display'][$action]);
            return false;
        }
        $display = true;
    } elseif ($result['ok'] || $result['status'] === 429) {
        $display = false;
    }
    if ($display) $_SESSION['turnstile_display'][$action] = true;
    else unset($_SESSION['turnstile_display'][$action]);
    return $display;
}

function turnstile_widget(string $action, bool $display): ?array
{
    if (!$display) return null;
    $siteKey = turnstile_site_key();
    if ($siteKey === null) {
        // No token bypass and no secret/configuration details in the public response.
        throw new ApiPageError(503, 'No podemos completar la verificación en este momento. Intenta más tarde.');
    }
    return ['action' => $action, 'site_key' => $siteKey];
}
