@echo off
title vibe-check Launcher
echo ====================================================
echo  vibe-check: Zero-Dependency Code Quality Scanner
echo ====================================================
echo.
set /p TARGET_DIR="Drag and drop your project directory here and press ENTER: "

:: Strip wrapping quotes if any
set TARGET_DIR=%TARGET_DIR:"=%

python "%~dp0vibe_check.py" "%TARGET_DIR%" --out "%~dp0vibe-report.json" --html "%~dp0vibe-report.html"

echo.
echo [Scan Complete]
echo   JSON report: "%~dp0vibe-report.json"
echo   HTML report: "%~dp0vibe-report.html"
echo.
echo Opening HTML report in your browser...
start "" "%~dp0vibe-report.html"
echo.
pause
