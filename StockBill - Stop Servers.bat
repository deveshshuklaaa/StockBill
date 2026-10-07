@echo off
setlocal
title StockBill - Stop Servers

echo Stopping StockBill development servers...
echo.

set "STOPPED_COUNT=0"

rem Stop Django backend processes on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        echo Stopping backend server [PID %%a]...
        taskkill /PID %%a /F /T >nul 2>&1
        set /a STOPPED_COUNT+=1
    )
)

rem Stop Vite frontend processes on port 5173
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        echo Stopping frontend server [PID %%a]...
        taskkill /PID %%a /F /T >nul 2>&1
        set /a STOPPED_COUNT+=1
    )
)

if %STOPPED_COUNT% gtr 0 (
    echo.
    echo StockBill development servers were successfully stopped.
) else (
    echo No active StockBill servers detected on ports 8000 or 5173.
)

echo.
ping 127.0.0.1 -n 3 >nul
endlocal
exit /b 0
