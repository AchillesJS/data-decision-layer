@echo off
setlocal

REM Resolve repo root: scripts\ -> repo root
cd /d "%~dp0.."

set HOST=127.0.0.1
set PORT=8000
if not "%~1"=="" set PORT=%~1

if not exist "data" mkdir data

if not exist "data\ddw.db" type nul > "data\ddw.db"
echo CWD=%cd%

REM Use repo-root-relative sqlite DB in ./data/ddw.db
set "DDW_DB_URL=sqlite+pysqlite:///./data/ddw.db"
echo DDW_DB_URL=%DDW_DB_URL%

echo Running migrations: python -m alembic upgrade head
python -m alembic upgrade head
if errorlevel 1 exit /b 1

echo Starting API: uvicorn api.main:app --reload --host %HOST% --port %PORT%
uvicorn api.main:app --reload --host %HOST% --port %PORT%
