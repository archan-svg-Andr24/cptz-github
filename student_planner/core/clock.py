"""Единственная точка получения «сегодня» (подменяется в тестах).

Просрочка ДЗ (HW-08), остаток «Стрелки» и дата якоря (DATA-21) зависят от
текущей даты. Чтобы тесты слоя 1 были детерминированными, а UI — честным,
все места берут дату отсюда.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime

_provider: Callable[[], date] = date.today


def today() -> date:
    """Текущая дата по действующему провайдеру."""
    return _provider()


def today_iso() -> str:
    return today().strftime("%Y-%m-%d")


def now() -> datetime:
    """Текущие дата и время; дата берётся у провайдера, время — системное."""
    return datetime.combine(today(), datetime.now().time().replace(microsecond=0))


def now_iso() -> str:
    """Метка ``created_at``: ``ГГГГ-ММ-ДД ЧЧ:ММ:СС``."""
    return now().strftime("%Y-%m-%d %H:%M:%S")


def set_provider(provider: Callable[[], date] | None) -> None:
    """Установить провайдер даты; ``None`` — вернуть системный."""
    global _provider
    _provider = provider or date.today


@contextmanager
def freeze(value: date) -> Iterator[None]:
    """Временно зафиксировать дату: ``with freeze(date(2026, 10, 12)): ...``."""
    previous = _provider
    set_provider(lambda: value)
    try:
        yield
    finally:
        set_provider(previous)


__all__ = ["today", "today_iso", "now", "now_iso", "set_provider", "freeze"]
