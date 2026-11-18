@echo off
rem Build the Windows installer. Arguments go to build_windows.ps1, e.g. -Upgrade or -SkipTests.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
exit /b %ERRORLEVEL%
