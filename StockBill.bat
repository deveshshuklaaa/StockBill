@echo off
setlocal
title StockBill

rem Resolve repository root directory (supports running from any working directory)
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

rem Pre-flight checks
if not exist "%PROJECT_ROOT%" (
    echo [ERROR] Project root directory not found: "%PROJECT_ROOT%"
    echo.
    pause
    exit /b 1
)

if not exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    echo [ERROR] Python virtual environment not found at:
    echo   "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
    echo.
    echo Please make sure the .venv virtual environment is configured.
    echo.
    pause
    exit /b 1
)

if exist "%PROJECT_ROOT%\divya_enterprises\manage.py" (
    set "BACKEND_DIR=%PROJECT_ROOT%\divya_enterprises"
) else if exist "%PROJECT_ROOT%\manage.py" (
    set "BACKEND_DIR=%PROJECT_ROOT%"
) else (
    echo [ERROR] Django manage.py not found in:
    echo   "%PROJECT_ROOT%\divya_enterprises" or "%PROJECT_ROOT%"
    echo.
    pause
    exit /b 1
)

set "FRONTEND_DIR=%PROJECT_ROOT%\frontend"
if not exist "%FRONTEND_DIR%\package.json" (
    echo [ERROR] Frontend configuration not found at:
    echo   "%FRONTEND_DIR%\package.json"
    echo.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 'npm' was not found in your system PATH.
    echo Please install Node.js and ensure npm is accessible.
    echo.
    pause
    exit /b 1
)

rem Check if servers are already running to prevent duplicate processes
set "BACKEND_RUNNING=0"
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 set "BACKEND_RUNNING=1"

set "FRONTEND_RUNNING=0"
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 set "FRONTEND_RUNNING=1"

rem Start backend if not already active
if "%BACKEND_RUNNING%"=="1" (
    echo Backend is already running [port 8000 in use].
) else (
    echo Starting backend...
    start "StockBill - Backend" cmd /k "cd /d "%BACKEND_DIR%" && call "%PROJECT_ROOT%\.venv\Scripts\activate.bat" && python manage.py runserver"
)

rem Start frontend if not already active
if "%FRONTEND_RUNNING%"=="1" (
    echo Frontend is already running [port 5173 in use].
) else (
    echo Starting frontend...
    start "StockBill - Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"
)

rem Brief wait to allow services to initialize
ping 127.0.0.1 -n 4 >nul

rem Open application in default browser
echo Opening StockBill...
start "" "http://localhost:5173"

rem Completion summary
echo.
echo ===================================================
echo   StockBill development environment started!
echo   Frontend URL: http://localhost:5173
echo   Backend API:  http://localhost:8000/api/
echo.
echo   Logs remain visible in their respective windows.
echo ===================================================
ping 127.0.0.1 -n 3 >nul

endlocal
exit /b 0
