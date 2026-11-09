
param(
    [string]$BaseUrl = 'http://localhost:3000',
    [hashtable]$AdminHeaders,
    [hashtable]$CapturistaHeaders,
    [int]$IdActaPrueba = 1
)

$ErrorActionPreference = 'Stop'

function Get-HttpStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$Method = 'GET',
        [hashtable]$Headers,
        [AllowNull()][string]$Body
    )

    $curlArgs = @(
        '--silent',
        '--show-error',
        '--output', 'NUL',
        '--write-out', '%{http_code}',
        '--max-time', '30',
        '--request', $Method
    )

    if ($Headers) {
        foreach ($name in $Headers.Keys) {
            $curlArgs += @('--header', ("{0}: {1}" -f $name, $Headers[$name]))
        }
    }

    if ($PSBoundParameters.ContainsKey('Body')) {
        $curlArgs += @(
            '--header', 'Content-Type: application/json',
            '--data-binary', $Body
        )
    }

    $codigoTexto = & curl.exe @curlArgs $Uri
    $curlExitCode = $LASTEXITCODE

    if ($curlExitCode -ne 0) {
        throw "curl.exe falló en $Method $Uri. Código: $curlExitCode"
    }

    $codigoTexto = ($codigoTexto | Out-String).Trim()
    $codigo = 0

    if (-not [int]::TryParse($codigoTexto, [ref]$codigo)) {
        throw "Código HTTP no válido: $codigoTexto"
    }

    return $codigo
}

$script:tests = @()

function Add-Test {
    param(
        [string]$Nombre,
        [int]$Esperado,
        [int]$Obtenido
    )

    $script:tests += [pscustomobject]@{
        Prueba = $Nombre
        Esperado = $Esperado
        Obtenido = $Obtenido
        Resultado = if ($Esperado -eq $Obtenido) {
            'CORRECTO'
        } else {
            'REVISAR'
        }
    }
}

# Pruebas de autenticación
$invalidHeaders = @{
    Authorization = 'Bearer token-invalido-de-prueba'
}

Add-Test 'Perfil con token alterado' 401 (
    Get-HttpStatus "$BaseUrl/api/auth/perfil" -Headers $invalidHeaders
)

Add-Test 'Auditoria sin token' 401 (
    Get-HttpStatus "$BaseUrl/api/auditoria"
)

Add-Test 'Usuarios sin token' 401 (
    Get-HttpStatus "$BaseUrl/api/usuarios"
)

Add-Test 'Detalle de acta sin token' 401 (
    Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba"
)

Add-Test 'PDF sin token' 401 (
    Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba/documento"
)

# Pruebas del Capturista
if ($CapturistaHeaders) {

    Add-Test 'Auditoria como Capturista' 403 (
        Get-HttpStatus "$BaseUrl/api/auditoria" -Headers $CapturistaHeaders
    )

    Add-Test 'Administracion de usuarios como Capturista' 403 (
        Get-HttpStatus "$BaseUrl/api/usuarios" -Headers $CapturistaHeaders
    )

    Add-Test 'Edicion de acta como Capturista' 403 (
        Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba" `
            -Method 'PUT' -Headers $CapturistaHeaders -Body '{}'
    )

    Add-Test 'Eliminacion de acta como Capturista' 403 (
        Get-HttpStatus "$BaseUrl/api/actas/$IdActaPrueba" `
            -Method 'DELETE' -Headers $CapturistaHeaders
    )
}

# Pruebas del Administrador
if ($AdminHeaders) {

    Add-Test 'Auditoria como Administrador' 200 (
        Get-HttpStatus "$BaseUrl/api/auditoria" -Headers $AdminHeaders
    )

    Add-Test 'Usuarios como Administrador' 200 (
        Get-HttpStatus "$BaseUrl/api/usuarios" -Headers $AdminHeaders
    )

    Add-Test 'DELETE de auditoria como Administrador' 404 (
        Get-HttpStatus "$BaseUrl/api/auditoria/1" `
            -Method 'DELETE' -Headers $AdminHeaders
    )

    Add-Test 'PATCH de auditoria como Administrador' 404 (
        Get-HttpStatus "$BaseUrl/api/auditoria/1" `
            -Method 'PATCH' -Headers $AdminHeaders -Body '{}'
    )
}

# Mostrar resultados
$script:tests | Format-Table -AutoSize

if ($script:tests.Resultado -contains 'REVISAR') {
    Write-Host 'Hay pruebas que requieren revision.' -ForegroundColor Yellow
}
else {
    Write-Host 'Todas las pruebas ejecutadas devolvieron el codigo esperado.' -ForegroundColor Green
}
