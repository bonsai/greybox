@echo off
rem GREYBOX: run every consistency check that CI runs.
setlocal
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

python tools\sync_story.py --check || exit /b 1
python tools\validate_story.py --verbose || exit /b 1
python tools\validate_quiz.py || exit /b 1
python tools\quizgen.py --check || exit /b 1
python -m unittest discover -s tools -p "test_*.py" || exit /b 1

echo.
echo all checks passed
