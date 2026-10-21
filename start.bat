@echo off
chcp 65001 >nul
setlocal
title Студенческий органайзер

rem GEN-12: основной способ запуска. Ошибки не «молчат»: при сбое окно остаётся
rem открытым, чтобы сообщение можно было прочитать.

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo  [ОШИБКА] Приложение не установлено.
    echo.
    echo  Сначала запустите install.bat — он создаст окружение .venv и
    echo  установит зависимости.
    echo.
    pause
    exit /b 1
)

rem pythonw не создаёт консольного окна; ошибки пишутся в журнал
rem %APPDATA%\StudentPlanner\logs\student_planner.log (NFR-05).
start "" ".venv\Scripts\pythonw.exe" -m student_planner
exit /b 0