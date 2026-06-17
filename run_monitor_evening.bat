@echo off
REM Anatel Monitor — evening (18:00 BRT) trigger.
REM Fires every day, but the Python script exits early unless today falls
REM in the first 7 or last 7 calendar days of the month. Net effect:
REM   - Days 1-7:  scrapes + emails (twice-daily mode)
REM   - Last 7 days of month: scrapes + emails (twice-daily mode)
REM   - All other days: silent no-op
REM
REM Logs to scheduled_runs.log alongside the morning task.

setlocal
set "PROJECT=%~dp0"
set "PYTHON=C:\Users\Rafael\anaconda3\python.exe"
cd /d "%PROJECT%"

echo. >> "%PROJECT%scheduled_runs.log"
echo ============================================================ >> "%PROJECT%scheduled_runs.log"
echo [%date% %time%] Anatel monitor (EVENING) starting >> "%PROJECT%scheduled_runs.log"
echo ============================================================ >> "%PROJECT%scheduled_runs.log"

"%PYTHON%" -u "%PROJECT%monitor.py" --week-window-only >> "%PROJECT%scheduled_runs.log" 2>&1

echo [%date% %time%] Anatel monitor (EVENING) finished with exit %ERRORLEVEL% >> "%PROJECT%scheduled_runs.log"

endlocal
