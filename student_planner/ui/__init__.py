"""Интерфейс приложения (§22, UI-01…UI-14).

Тёмная тема, три колонки: навигация, страница, виджеты. Все данные читаются
из локальной базы SQLite; сеть не используется (NFR-01).
"""

from __future__ import annotations

from .main_window import MainWindow

__all__ = ["MainWindow"]
