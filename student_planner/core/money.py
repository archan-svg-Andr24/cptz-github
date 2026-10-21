"""Деньги: ``Decimal``, 2 знака, ``ROUND_HALF_UP`` (GEN-09, DATA-13).

SUM в SQLite теряет тип, поэтому все денежные величины хранятся в ``NUMERIC``
текстом с двумя знаками (``to_db``) и читаются обратно через ``str`` →
``Decimal`` (``from_db``). Арифметика выполняется только в Python:

    paid = money(base - discount)

Функции модуля намеренно не принимают ``float`` без явного преобразования
через ``str``: ``Decimal(0.1)`` дал бы двоичный шум.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

Number = Union[Decimal, int, str, float]

#: Точность денежных величин — две цифры после запятой.
CENT = Decimal("0.01")

ZERO = Decimal("0.00")


def money(value: Number = "0") -> Decimal:
    """Привести значение к деньгам: 2 знака, ``ROUND_HALF_UP``.

    >>> money("30.505")
    Decimal('30.51')
    """
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, bool):  # bool — это int, но деньгами не бывает
        raise InvalidOperation(f"Недопустимое денежное значение: {value!r}")
    elif isinstance(value, float):
        dec = Decimal(str(value))
    elif isinstance(value, int):
        dec = Decimal(value)
    else:
        text = str(value).strip().replace(",", ".").replace("\u00a0", "").replace(" ", "")
        dec = Decimal(text)
    return dec.quantize(CENT, rounding=ROUND_HALF_UP)


def to_db(value: Number) -> str:
    """Строка для записи в ``NUMERIC``: всегда два знака (``'61.00'``)."""
    return str(money(value))


def from_db(value: object) -> Decimal:
    """Прочитать денежное значение из SQLite (int/float/str) без потери знаков.

    SQLite может вернуть ``61`` (int) или ``30.5`` (float); ``str`` от обоих
    даёт точное десятичное представление для двухзнаковых сумм.
    """
    if isinstance(value, Decimal):
        return money(value)
    if value is None:
        return ZERO
    return money(str(value))


def is_negative(value: Number) -> bool:
    return money(value) < ZERO


__all__ = ["CENT", "ZERO", "Number", "money", "to_db", "from_db", "is_negative"]
