# Генерация иконок приложения (mobile/assets) — PowerShell + System.Drawing
# Запуск: pwsh -File mobile/assets/gen-icons.ps1
Add-Type -AssemblyName System.Drawing
$size = 1024

function New-Icon([string]$path, [bool]$adaptive) {
  $bmp = New-Object System.Drawing.Bitmap($size, $size)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  if ($adaptive) { $g.Clear([System.Drawing.Color]::Transparent) } else { $g.Clear([System.Drawing.Color]::White) }
  $blue = [System.Drawing.Color]::FromArgb(255, 37, 99, 235)
  $brush = New-Object System.Drawing.SolidBrush($blue)
  if ($adaptive) { $w = 500 } else { $w = 640 }
  $x = ($size - $w) / 2
  $y = ($size - $w) / 2
  $r = 120
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $p.AddArc($x, $y, 2*$r, 2*$r, 180, 90)
  $p.AddArc($x+$w-2*$r, $y, 2*$r, 2*$r, 270, 90)
  $p.AddArc($x+$w-2*$r, $y+$w-2*$r, 2*$r, 2*$r, 0, 90)
  $p.AddArc($x, $y+$w-2*$r, 2*$r, 2*$r, 90, 90)
  $p.CloseFigure()
  $g.FillPath($brush, $p)
  # хвостик пузыря
  $tail = @(
    (New-Object System.Drawing.Point([int]($x+180), [int]($y+$w))),
    (New-Object System.Drawing.Point([int]($x+180), [int]($y+$w+90))),
    (New-Object System.Drawing.Point([int]($x+300), [int]($y+$w)))
  )
  $g.FillPolygon($brush, $tail)
  # три белые точки «текста»
  $dotBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
  $dot = 56
  $cy = $y + $w/2 - $dot/2
  $g.FillEllipse($dotBrush, $x+230, $cy, $dot, $dot)
  $g.FillEllipse($dotBrush, $x+$w/2-$dot/2, $cy, $dot, $dot)
  $g.FillEllipse($dotBrush, $x+$w-230-$dot, $cy, $dot, $dot)
  $g.Dispose()
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Host "saved $path"
}

New-Icon (Join-Path $PSScriptRoot 'icon.png') $false
New-Icon (Join-Path $PSScriptRoot 'adaptive-icon.png') $true
