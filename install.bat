@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Установка «Студенческий органайзер»

rem GEN-12: однократная установка — venv + requirements.txt.
rem §2.2: при отсутствии Python сообщение и окно не закрывается до нажатия клавиши.

cd /d "%~dp0"

echo.
echo  ============================================================
echo   Студенческий органайзер - установка
echo  ============================================================
echo.

rem ---------------------------------------------------------------- поиск Python
rem Кириллица в консоли: Python обязан писать вывод в UTF-8.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY="
where py >nul 2>&1 && set "PY=py -3.13"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo  [ОШИБКА] Python не найден в системе.
    echo.
    echo  Что сделать:
    echo    1. Скачайте Python 3.11 или новее с https://www.python.org/downloads/windows/
    echo    2. При установке включите галочку "Add python.exe to PATH".
    echo    3. Запустите install.bat снова.
    echo.
    echo  Приложение не устанавливалось, файлы не изменялись.
    echo.
    pause
    exit /b 1
)

echo  Найден Python: !PY!
for /f "delims=" %%v in ('!PY! -c "import sys; print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
if not defined PYVER (
    echo  [ОШИБКА] Не удалось определить версию Python.
    echo  Проверьте установку и запустите install.bat снова.
    echo.
    pause
    exit /b 1
)
echo  Версия Python: !PYVER!
echo.

rem ------------------------------------------------------- проверка версии Python
!PY! -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo  [ОШИБКА] Требуется Python 3.11 или новее, найден !PYVER!.
    echo  Обновите Python и запустите install.bat снова.
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------- venv
if exist ".venv\Scripts\python.exe" (
    echo  Виртуальное окружение уже существует, используется повторно.
) else (
    echo  Создание виртуального окружения .venv ...
    !PY! -m venv .venv
    if errorlevel 1 (
        echo  [ОШИБКА] Не удалось создать виртуальное окружение.
        echo  Проверьте права на запись в папку приложения.
        echo.
        pause
        exit /b 1
    )
)
echo.

rem --------------------------------------------------------------- зависимости
set "VENV_PY=.venv\Scripts\python.exe"

if exist "wheelhouse" (
    echo  Установка из локального каталога wheelhouse ^(без интернета^) ...
    "%VENV_PY%" -m pip install --disable-pip-version-check --no-index --find-links=wheelhouse -r requirements.txt
) else (
    echo  Установка из интернета ...
    "%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt
)

if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Не удалось установить зависимости.
    echo  Если интернета нет, положите пакеты в папку wheelhouse рядом с
    echo  install.bat и запустите установку снова ^(GEN-04^).
    echo  Самопроверка: .venv\Scripts\python.exe -c "import PySide6"
    echo.
    pause
    exit /b 1
)
echo.

rem ------------------------------------------------------------- самопроверка
echo  Проверка установки ...
"%VENV_PY%" -c "from student_planner.core.schema import TABLE_ORDER; import PySide6; print('  PySide6', PySide6.__version__); print('  таблиц в схеме:', len(TABLE_ORDER))"
if errorlevel 1 (
    echo  [ОШИБКА] Приложение не запускается после установки.
    echo  Запустите start.bat - он выведет подробности.
    echo.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Установка завершена. Запускайте start.bat
echo  ============================================================
echo.
pause
exit /b 0