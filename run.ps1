$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PATH                    = "$dir\node;$env:PATH"
$env:PLAYWRIGHT_BROWSERS_PATH = "$dir\browsers"
$env:PYTHONNOUSERSITE        = "1"
$env:PYTHONPATH              = ""
Set-Location $dir
& "$dir\node_modules\electron\dist\electron.exe" $dir
