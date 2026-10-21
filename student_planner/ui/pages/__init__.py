"""Страницы приложения (§22: UI-06).

Каждая страница — самостоятельный виджет с методами ``refresh()`` и, если ей
нужна дата, ``set_date(value)``. Сигнал ``changed`` сообщает главному окну, что
данные изменились и виджеты правой панели нужно перечитать.
"""

from __future__ import annotations

from .expenses import ExpensesPage
from .homework import HomeworkPage
from .schedule import SchedulePage
from .settings import SettingsPage
from .trips import TripsPage

__all__ = [
    "SchedulePage",
    "TripsPage",
    "ExpensesPage",
    "HomeworkPage",
    "SettingsPage",
]
