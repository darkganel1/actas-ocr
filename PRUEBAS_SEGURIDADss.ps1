param(
    [string]$BaseUrl = 'http://localhost:3000',
    [hashtable]$AdminHeaders,
    [hashtable]$CapturistaHeaders,
    [int]$IdActaPrueba = 1
)

$ErrorActionPreference = 'Stop'

function Get-HttpStatus {
    param(
        [string]$Uri,
        [string]$Method = 'GET',
        [hashtable]$Headers,
        [string]$Body
    )

    $params = @{
        Uri = $Uri
        Method = $Method
        ErrorAction = 'Stop'
    }
    if ($Headers) { $params.Headers = $Headers }
    if ($null -ne $Body) {
        $params.Body = $Body
        $params.ContentType = 'application/json'
    }

    try {
        $response = Invoke-WebRequest @params
        return [int]$response.StatusCode
    }
    catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return [int]$_.Exception.Response.StatusCode.value__
        }
        throw
    }
}

$script:tests = @()
function Add-Test {
    param([string]$Nombre, [int]$Esperado, [int]$Obtenido)
    $script:tests += [pscustomobject]@{
        Prueba = $Nombre
        Esperado = $Esperado
        Obtenido = $Obtenido
        Resultado = if ($Esperado -eq $Obtenido) { 'CORRECTO' } else { 'REVISAR' }
    }
}

# Rutas protegidas sin token.
$invalidHeaders = @{ Authorization = 'Bearer token-invalido-de-prueba' }
Add-Test 'Perfil con token alterado' 401 (Get-HttpStatus "$BaseUrl/api/auth/perfil" -Headers $invalidHeaders)
Add-Test 'Auditoria sin token' 401 (Get-HttpStatus "$BaseUrl/api/auditoria")
Add-Test 'Usuarios sin token' 401 (Get-HttpStatus "$BaseUrl/api/usuarios")
Add-Test 'Detalle de acta sin token' 401 (Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba")
Add-Test 'PDF sin token' 401 (Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba/documento")

if ($CapturistaHeaders) {
    Add-Test 'Auditoria como Capturista' 403 (Get-HttpStatus "$BaseUrl/api/auditoria" -Headers $CapturistaHeaders)
    Add-Test 'Administracion de usuarios como Capturista' 403 (Get-HttpStatus "$BaseUrl/api/usuarios" -Headers $CapturistaHeaders)
    Add-Test 'Edicion de acta como Capturista' 403 (Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba" -Method 'PUT' -Headers $CapturistaHeaders -Body '{}')
    Add-Test 'Eliminacion de acta como Capturista' 403 (Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba" -Method 'DELETE' -Headers $CapturistaHeaders)
}

if ($AdminHeaders) {
    Add-Test 'Auditoria como Administrador' 200 (Get-HttpStatus "$BaseUrl/api/auditoria" -Headers $AdminHeaders)
    Add-Test 'Usuarios como Administrador' 200 (Get-HttpStatus "$BaseUrl/api/usuarios" -Headers $AdminHeaders)
    # La API de auditoría es de solo lectura: DELETE no debe existir.
    Add-Test 'DELETE de auditoría como Administrador' 404 (Get-HttpStatus "$BaseUrl/api/auditoria/1" -Method 'DELETE' -Headers $AdminHeaders)
    Add-Test 'PATCH de auditoría como Administrador' 404 (Get-HttpStatus "$BaseUrl/api/auditoria/1" -Method 'PATCH' -Headers $AdminHeaders -Body '{}')
}

$script:tests | Format-Table -AutoSize
if ($script:tests.Resultado -contains 'REVISAR') {
    Write-Host 'Hay pruebas que no devolvieron el código esperado.' -ForegroundColor Yellow
} else {
    Write-Host 'Todas las pruebas ejecutadas devolvieron el código esperado.' -ForegroundColor Green
}
