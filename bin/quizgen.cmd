@echo off
rem GREYBOX quiz generator: config (YAML) + story (JSON) -> questions.
rem   bin\quizgen --check
rem   bin\quizgen --dry-run
rem   bin\quizgen --count 2
setlocal
python "%~dp0..\tools\quizgen.py" %*
