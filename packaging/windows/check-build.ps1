<#
.SYNOPSIS
  Tries a build of renpy-capture for Windows the way a person would, and measures it.

.DESCRIPTION
  Unpacks the zip into a folder whose name has spaces and letters that are not English (a person's Downloads folder),
  starts the programs, captures The Question with the command line program and compares it with a capture made on Linux,
  asks for the progress a program can read, reads a game that ships only compiled scripts (unrpyc runs inside the
  program), opens the window and closes it, and has the window capture The Question through the command line program
  that stands beside it (RENPY_CAPTURE_GUI_AUTORUN). Anything that is not as it should be stops it with an error. What
  it measured goes to the log and, in GitHub Actions, to the summary of the run.

.EXAMPLE
  .\check-build.ps1 -Zip dist\renpy-capture-0.2.1-windows-x64.zip -Reference linux\out
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Zip,
    [Parameter(Mandatory)][string]$Reference,         # the `out` folder of a capture of The Question made on Linux
    [string]$RenpyVersion = '8.3.2',
    [switch]$SkipCompiledScripts,                      # (where unrpyc cannot be downloaded)
    [string]$Work = (Join-Path ([IO.Path]::GetTempPath()) 'renpy-capture-check')
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true      # a program that ends with an error ends this script

$measured = [ordered]@{}
$exe = if ($IsWindows) { '.exe' } else { '' }          # (on Linux the same steps try the Linux build of the program)
function Group($title) { Write-Host "::group::$title" }
function EndGroup { Write-Host '::endgroup::' }
function Fail($message) { Write-Host "::error::$message"; throw $message }
function Secs($stopwatch) { '{0:N2} s' -f $stopwatch.Elapsed.TotalSeconds }
function Utf8($text) { New-Object Text.UTF8Encoding $false }

if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Path $Work | Out-Null

# ---- the zip, unpacked as a person does it
Group 'Unpack the zip (Extract All), into a folder with spaces and letters that are not English'
$name = 'Check ' + (-join (0x41F, 0x430, 0x43F, 0x43A, 0x430 | ForEach-Object { [char]$_ })) + ' (1)'   # "Check Папка (1)"
$unpacked = Join-Path $Work $name
$sw = [Diagnostics.Stopwatch]::StartNew()
Expand-Archive -Path $Zip -DestinationPath $unpacked
$measured['Unpack the zip (Expand-Archive)'] = Secs $sw
$app = Join-Path $unpacked 'renpy-capture'
$command = Join-Path $app "renpy-capture$exe"
$window = Join-Path $app "renpy-capture-gui$exe"
foreach ($f in 'README.txt', 'LICENSE', 'THIRD-PARTY.txt', "renpy-capture$exe", "renpy-capture-gui$exe",
               '_internal/renpy_capture/capture.rpy') {
    if (-not (Test-Path (Join-Path $app $f))) { Fail "the zip has no $f" }
}
if (-not $IsWindows) { chmod +x $command $window }       # (Expand-Archive does not keep what a file may do)
$files = Get-ChildItem $app -Recurse -File
$measured['The zip'] = '{0:N1} MB' -f ((Get-Item $Zip).Length / 1MB)
$measured['Unpacked'] = '{0:N1} MB in {1:N0} files' -f (($files | Measure-Object Length -Sum).Sum / 1MB), $files.Count
EndGroup

# ---- how long it takes to start
Group 'How long the command line program takes to start'
$sw = [Diagnostics.Stopwatch]::StartNew()
$said = & $command --version
$measured["renpy-capture$exe --version, the first time"] = Secs $sw
if ($said -notmatch '^renpy-capture \d+\.\d+') { Fail "--version said: $said" }
$times = 1..5 | ForEach-Object {
    $one = [Diagnostics.Stopwatch]::StartNew()
    & $command --version | Out-Null
    $one.Elapsed.TotalSeconds
} | Sort-Object
$measured["renpy-capture$exe --version, median of the next 5"] = '{0:N2} s' -f $times[2]
Write-Host $said
EndGroup

# ---- the window: up, and closed
Group 'Start the window, wait until it is up, close it'
if ($IsWindows) {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $gui = Start-Process -FilePath $window -PassThru
    $up = $false
    while ($sw.Elapsed.TotalSeconds -lt 90) {
        $gui.Refresh()
        if ($gui.HasExited) { Fail "the window closed by itself, with exit code $($gui.ExitCode)" }
        if ($gui.MainWindowHandle -ne [IntPtr]::Zero -and $gui.MainWindowTitle -eq 'renpy-capture') { $up = $true; break }
        Start-Sleep -Milliseconds 50
    }
    if (-not $up) { $gui.Kill(); Fail 'the window was not up after 90 seconds' }
    $measured['renpy-capture-gui.exe: the window is up after'] = Secs $sw
    Write-Host "the window: '$($gui.MainWindowTitle)', responding: $($gui.Responding)"
    Start-Sleep -Seconds 2
    if (-not $gui.CloseMainWindow()) { $gui.Kill(); Fail 'the window could not be asked to close' }
    if (-not $gui.WaitForExit(20000)) { $gui.Kill(); Fail 'the window did not close when it was asked to' }
    if ($gui.ExitCode -ne 0) { Fail "the window closed with exit code $($gui.ExitCode)" }
} else {
    Write-Host 'skipped: a window handle is a Windows thing (the next steps still run the window, by itself)'
}
EndGroup

# ---- The Question, with the command line program
Group "The Ren'Py $RenpyVersion engine, and The Question out of it"
$sw = [Diagnostics.Stopwatch]::StartNew()
$sdk = & $command sdk --renpy-version $RenpyVersion | Select-Object -Last 1
$measured["The Ren'Py $RenpyVersion engine (0 s when it was kept from an earlier run)"] = Secs $sw
$game = Join-Path $Work 'the_question'
Copy-Item -Recurse (Join-Path $sdk 'the_question') $game
EndGroup

Group 'Capture The Question with the program, and compare it with the capture made on Linux'
$out = Join-Path $Work 'work'
$sw = [Diagnostics.Stopwatch]::StartNew()
& $command capture $game $out --renpy-version $RenpyVersion
$measured["The Question, captured by renpy-capture$exe"] = Secs $sw
& $command compare $Reference (Join-Path $out 'out') --states-only
EndGroup

Group 'The same again, asking for the progress a program can read'
$errors = Join-Path $Work 'progress-text.txt'
$events = @(& $command capture $game $out --renpy-version $RenpyVersion --progress-json 2> $errors)
$parsed = @($events | ForEach-Object { $_ | ConvertFrom-Json })
$done = @($parsed | Where-Object { $_.event -eq 'done' })
if ($done.Count -ne 1) { Fail "$($done.Count) events of the end, not one: $($events -join ' | ')" }
if ($done[0].lines -ne 128 -or $done[0].jobs -ne 3 -or -not $done[0].complete) { Fail "the summary is not The Question's: $($events[-1])" }
$stages = ($parsed | Where-Object { $_.event -eq 'stage' } | ForEach-Object { $_.stage }) -join ' '
if ($stages -ne 'setup capture check export') { Fail "the steps were: $stages" }
if ((Get-Content $errors -Raw) -notmatch 'Done: 128 lines in 3 jobs') { Fail 'the text for a person is not on the standard error' }
Write-Host "$($parsed.Count) events, steps: $stages; the text for a person was on the standard error"
EndGroup

# ---- a game that ships only compiled scripts: unrpyc is fetched and runs inside the program
Group 'A game with only compiled scripts, read by unrpyc inside the program'
if ($SkipCompiledScripts) {
    Write-Host 'skipped, as asked'
} else {
$bare = Join-Path $Work 'the_question_compiled'
Copy-Item -Recurse $game $bare
Get-ChildItem (Join-Path $bare 'game') -Recurse -Filter *.rpy | Remove-Item
if (Get-ChildItem (Join-Path $bare 'game') -Recurse -Filter *.rpy) { Fail 'the copy still has sources' }
$part = Join-Path $Work 'first branch only'                 # a capture of the first branch only: there is something to find
New-Item -ItemType Directory -Path $part | Out-Null
& $command init $game (Join-Path $part 'config.json')
& $command setup $game (Join-Path $part 'run') --renpy-version $RenpyVersion
& $command run (Join-Path $part 'run') (Join-Path $part 'config.json') (Join-Path $part 'out')
$said = Join-Path $Work 'gaps-text.txt'
$with = @(& $command gaps $game (Join-Path $part 'config.json') (Join-Path $part 'out'))[0]
$without = @(& $command gaps $bare (Join-Path $part 'config.json') (Join-Path $part 'out') 2> $said)[0]
Write-Host "with sources:    $with"
Write-Host "compiled only:   $without"
$count = 'not reached: (\d+) in (\d+) labels'
$a, $b = [regex]::Match($with, $count), [regex]::Match($without, $count)
if (-not $a.Success -or [int]$a.Groups[1].Value -lt 1) { Fail "the first branch alone should leave scenes unreached, it said: $with" }
if (-not $b.Success) { Fail "the scenes of a game with only compiled scripts were not counted: $without" }
if ($a.Groups[1].Value -ne $b.Groups[1].Value -or $a.Groups[2].Value -ne $b.Groups[2].Value) {
    Fail 'unrpyc inside the program found other scenes unreached than the sources do'
}
if ((Test-Path $said) -and (Get-Content $said -Raw) -match 'not decompiled') { Fail "some scripts were not decompiled: $(Get-Content $said -Raw)" }
}
EndGroup

# ---- the window runs a capture, through the command line program that stands beside it
Group 'The window captures The Question: the program that stands beside it runs it (RENPY_CAPTURE_GUI_AUTORUN)'
$appdata = Join-Path $Work 'appdata'
New-Item -ItemType Directory -Path (Join-Path $appdata 'renpy-capture') -Force | Out-Null
$guiGame = Join-Path $Work 'gui_game\the_question'
Copy-Item -Recurse (Join-Path $sdk 'the_question') $guiGame
$guiWork = Join-Path $Work 'gui_work'
$last = @{ game = $guiGame; workdir = $guiWork; language = $null; text = $false; version = $RenpyVersion }
[IO.File]::WriteAllText((Join-Path $appdata 'renpy-capture\gui.json'), (@{ last = $last } | ConvertTo-Json -Depth 4), (Utf8))
$env:APPDATA = $appdata                                      # the choices the window starts with
$env:XDG_CONFIG_HOME = $appdata                              # (the same, where there is no APPDATA)
$env:RENPY_CAPTURE_GUI_AUTORUN = '1'                         # press Capture on its own, close when it is over
$sw = [Diagnostics.Stopwatch]::StartNew()
$gui = Start-Process -FilePath $window -PassThru
if (-not $gui.WaitForExit(900000)) { $gui.Kill(); Fail 'the window did not finish in 15 minutes' }
$measured['The Question, captured through the window'] = Secs $sw
Remove-Item Env:RENPY_CAPTURE_GUI_AUTORUN
$log = Join-Path $guiWork 'renpy-capture.log'
if (Test-Path $log) { Get-Content $log -Tail 12 }
if ($gui.ExitCode -ne 0) { Fail "the window ended with exit code $($gui.ExitCode)" }
if (-not (Test-Path (Join-Path $guiWork 'export\index.html'))) { Fail 'the window left no page' }
& $command compare $Reference (Join-Path $guiWork 'out') --states-only
EndGroup

# ---- what it measured
$table = "| What | |`n|---|---|`n" + (($measured.GetEnumerator() | ForEach-Object { "| $($_.Key) | $($_.Value) |" }) -join "`n")
Write-Host $table
if ($env:GITHUB_STEP_SUMMARY) {
    Add-Content -Path $env:GITHUB_STEP_SUMMARY -Value "### The Windows build, measured`n`n$table`n"
}
