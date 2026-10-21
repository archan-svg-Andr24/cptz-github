"""Точка входа для сборки ``StudentPlanner.exe`` (GEN-12, GEN-17).

PyInstaller запускает этот файл как **самостоятельный скрипт**, а не как модуль
пакета, поэтому относительный импорт здесь невозможен — используется абсолютный.
Для запуска из исходников служит ``python -m student_planner``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# При сборке one-folder корень проекта лежит рядом с exe; при запуске из
# исходников — рядом с этим файлом. Достаточно добавить оба места.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from student_planner.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
