param(
    [string]$BaseUrl = 'http://localhost:3000',
    [Parameter(Mandatory=$true)][hashtable]$Headers
)

$ErrorActionPreference = 'Stop'
$archivoPrueba = Join-Path $env:TEMP 'actas-pdf-estructura-invalida.pdf'
$respuesta = Join-Path $env:TEMP 'actas-pdf-respuesta.json'

try {
    # Tiene extensión, encabezado y EOF aparentes, pero no contiene estructura PDF válida.
    $contenido = "%PDF-1.7`nEsto no es un documento PDF real.`n%%EOF`n"
    [System.IO.File]::WriteAllBytes($archivoPrueba, [System.Text.Encoding]::ASCII.GetBytes($contenido))

    $token = [string]$Headers.Authorization -replace '^Bearer\s+', ''
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Headers debe contener Authorization = Bearer <token>.'
    }

    $codigo = & curl.exe --silent --show-error --output $respuesta --write-out '%{http_code}' `
        -H "Authorization: Bearer $token" `
        -F "documento=@$archivoPrueba;filename=archivo-invalido.pdf;type=application/pdf" `
        "$BaseUrl/api/documentos/procesar"

    $codigo = [int]$codigo
    Write-Host "HTTP recibido: $codigo"
    if (Test-Path $respuesta) {
        Get-Content $respuesta -Raw
    }

    if ($codigo -eq 400) {
        Write-Host 'CORRECTO: el backend rechazó el PDF falso antes de ejecutar OCR.' -ForegroundColor Green
    } elseif ($codigo -eq 503) {
        Write-Host 'pdfinfo no está disponible. Configura PDFINFO_PATH u OCR_POPPLER_PATH.' -ForegroundColor Yellow
    } else {
        Write-Host 'REVISAR: se esperaba HTTP 400 para un PDF estructuralmente inválido.' -ForegroundColor Red
    }
} finally {
    Remove-Item $archivoPrueba, $respuesta -Force -ErrorAction SilentlyContinue
}
