Param(
  [string]$DbPath = ".\data\ddw.db",
  [int]$Port = 8000,
  [string]$BindHost = "127.0.0.1",
  [switch]$NoMigrations
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve repo root: scripts/ -> repo root
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot

try {
  # Ensure data/ exists
  if (-not (Test-Path -Path "data" -PathType Container)) {
    New-Item -ItemType Directory -Path "data" | Out-Null
  }

  # Build an absolute path WITHOUT requiring the file to exist
  $dbFull = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $DbPath))
  $dbPosix = $dbFull -replace "\\", "/"

  # SQLite will create the file on first connection; but keep it explicit for clarity
  if (-not (Test-Path -Path $dbFull -PathType Leaf)) {
    New-Item -ItemType File -Path $dbFull -Force | Out-Null
  }

  $env:DDW_DB_URL = "sqlite+pysqlite:///$dbPosix"
  Write-Host "DDW_DB_URL = $env:DDW_DB_URL"

  if (-not $NoMigrations) {
    Write-Host "Running migrations: python -m alembic upgrade head"
    python -m alembic upgrade head
  } else {
    Write-Host "Skipping migrations (-NoMigrations)"
  }

  Write-Host "Starting API: uvicorn api.main:app --reload --host $BindHost --port $Port"
  uvicorn api.main:app --reload --host $BindHost --port $Port
}
finally {
  Pop-Location
}
