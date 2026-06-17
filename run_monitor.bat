@echo off
REM Anatel Monitor — daily check.
REM Hits Qlik engine for each watched dashboard, compares qLastReloadTime
REM with state.json, emails when any data refresh is detected.
REM Runs every day (incl. weekends) at 09:00 BRT via Task Scheduler.

setlocal
set "PROJECT=%~dp0"
set "PYTHON=C:\Users\Rafael\anaconda3\python.exe"
cd /d "%PROJECT%"

echo. >> "%PROJECT%scheduled_runs.log"
echo ============================================================ >> "%PROJECT%scheduled_runs.log"
echo [%date% %time%] Anatel monitor starting >> "%PROJECT%scheduled_runs.log"
echo ============================================================ >> "%PROJECT%scheduled_runs.log"

"%PYTHON%" -u "%PROJECT%monitor.py" >> "%PROJECT%scheduled_runs.log" 2>&1

echo [%date% %time%] Anatel monitor finished with exit %ERRORLEVEL% >> "%PROJECT%scheduled_runs.log"

endlocal
