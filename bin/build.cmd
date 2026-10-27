@echo off
rem GREYBOX: build a pc distribution (Windows/macOS/Linux zip).
rem Requires RENPY_SDK, e.g. set RENPY_SDK=C:\tools\renpy-8.5.3-sdk
setlocal
if "%RENPY_SDK%"=="" (
  echo error: RENPY_SDK is not set.
  echo        set RENPY_SDK=C:\path\to\renpy-8.5.3-sdk
  exit /b 1
)
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

"%RENPY_SDK%\renpy.exe" "%CD%" compile || exit /b 1
"%RENPY_SDK%\renpy.exe" "%CD%" lint || exit /b 1
"%RENPY_SDK%\renpy.exe" "%RENPY_SDK%\launcher" distribute "%CD%" --package pc --destination "%CD%\dist" || exit /b 1

echo.
echo built:
dir /b dist\*.zip
