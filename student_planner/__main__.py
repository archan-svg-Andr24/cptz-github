"""Запуск приложения без консоли: ``python -m student_planner`` (§2.1, GEN-12)."""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
