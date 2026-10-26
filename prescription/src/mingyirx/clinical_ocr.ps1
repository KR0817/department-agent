param([Parameter(Mandatory=$true)][string]$InputPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
function Await-WinRt($Operation, [Type]$ResultType) {
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}
try {
    $file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($InputPath)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    if ($decoder.PixelWidth -gt 3000 -or $decoder.PixelHeight -gt 3000) { throw 'IMAGE_DIMENSION_LIMIT' }
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw 'OCR_LANGUAGE_UNAVAILABLE' }
    $result = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $lines = @($result.Lines | ForEach-Object { $_.Text })
    @{text=($lines -join "`n"); language=$engine.RecognizerLanguage.LanguageTag} | ConvertTo-Json -Compress
    $bitmap.Dispose()
    $stream.Dispose()
} catch {
    [Console]::Error.WriteLine('LOCAL_OCR_FAILED')
    exit 2
}
