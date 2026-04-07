# Interactive git commit: title (required) + optional multiline body; end body with a line containing only .
$subject = Read-Host "Commit title (required)"
if ([string]::IsNullOrWhiteSpace($subject)) {
    Write-Host "Aborted: empty title." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Commit body (optional). Multiple lines; finish with a line that is only a dot (.) :"
$lines = @()
while ($true) {
    $line = Read-Host
    if ($line -eq ".") { break }
    $lines += $line
}
$body = ($lines -join [Environment]::NewLine).Trim()

if ($body) {
    git commit -m $subject -m $body
} else {
    git commit -m $subject
}
exit $LASTEXITCODE
