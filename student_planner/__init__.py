"""Студенческий органайзер / Student Planner.

Десктопное приложение для Windows 10/11 (x64), полностью офлайн (GEN-01…GEN-05).

Пакет разбит на слои:

* :mod:`student_planner.core` — ядро без интерфейса: схема БД, настройки,
  алгоритмы §31, расчёты. Слой ничего не знает о PySide6 (PLAN-05).
* :mod:`student_planner.ui` — интерфейс PySide6 (этап 4 §1.12).

Требования к версии схемы и приложения — см. ``SCHEMA_VERSION``.
"""

from __future__ import annotations

APP_NAME = "StudentPlanner"
APP_TITLE = "Студенческий органайзер"
APP_VERSION = "1.0.0"

#: Версия схемы БД, известная приложению (DATA-19, Прил. Б).
SCHEMA_VERSION = 2

__all__ = ["APP_NAME", "APP_TITLE", "APP_VERSION", "SCHEMA_VERSION"]
