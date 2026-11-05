"""Сервис сокращённых названий предметов (UI-14, SET-02).

Единственная точка, через которую интерфейс спрашивает короткую подпись
предмета. Решение «показывать сокращение или полное название» принимается
здесь, а не разбросано по страницам: иначе переключатель в настройках
действовал бы только на части экранов.

У предмета **два независимых варианта** сокращения:

* средний (``medium``) — «Разработка ПМ», «Комп. сети»;
* минимальный (``short``) — «РПМ», «КС», «Физ-ра» для плотной сетки недели.

Оба задаются отдельно и хранятся в одной таблице ``subject_short_names``
строками «Название=среднее|минимальное»; пустая сторона означает «не
переопределено», прочерк ``-`` — «показывать полное название». Какой вариант
действует сейчас, решает настройка ``subject_abbreviations_style``.

Порядок поиска подписи для действующего варианта:

1. своё сокращение из таблицы;
2. стандартное сокращение того же варианта из ``STOCK_*_NAMES``;
3. автоматическое сокращение (:func:`abbreviate` или ``abbreviate_minimal``).

Сервис читает настройки один раз на создание объекта: страницы перерисовки
создают его заново, поэтому изменения из настроек видны сразу после
сохранения.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .database import Database
from .settings_registry import SettingsKeys
from .settings_service import SettingsService
from .subject_abbreviations import (
    DEFAULT_STYLE,
    NO_SHORTENING,
    abbreviate,
    abbreviate_minimal,
    parse_short_names,
    serialize_short_names,
    stock_names,
)

#: Порядок вариантов: (ключ стиля, подпись для интерфейса).
STYLE_CAPTIONS: tuple[tuple[str, str], ...] = (
    ("medium", "Среднее"),
    ("short", "Минимальное"),
)


def variant_index(style: str) -> int:
    """Индекс варианта в кортеже значений: ``medium`` → 0, ``short`` → 1."""
    return 1 if (style or DEFAULT_STYLE) == "short" else 0


def auto_variant(name: str, style: str | None) -> str:
    """Автоматическое сокращение названия в указанном варианте."""
    if (style or DEFAULT_STYLE) == "short":
        return abbreviate_minimal(name)
    return abbreviate(name)


@dataclass
class ShortNameTable:
    """Снимок настроек сокращений: включённость, вариант и переопределения.

    ``overrides`` хранит для каждого названия пару значений
    ``(среднее, минимальное)``; ``None`` — вариант не переопределён.
    """

    enabled: bool = True
    style: str = DEFAULT_STYLE
    overrides: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)

    # ------------------------------------------------------------------ чтение
    def value(self, name: str, style: str | None = None) -> str:
        """Сокращение в указанном (по умолчанию действующем) варианте.

        Пустая строка означает «показывать полное название»: так выражен
        осознанный отказ от сокращения (прочерк в таблице).
        """
        key = (name or "").strip()
        if not key:
            return ""
        style = style or self.style
        index = variant_index(style)
        if key in self.overrides:
            override = self.overrides[key][index]
            if override is not None:
                return override
        stock = stock_names(style)
        if key in stock:
            return stock[key]
        return auto_variant(key, style)

    def resolve(self, name: str) -> str:
        """Сокращение в действующем варианте (совместимость с :meth:`value`)."""
        return self.value(name)

    def medium(self, name: str) -> str:
        """Средний вариант подписи независимо от действующего."""
        return self.value(name, "medium")

    def minimal(self, name: str) -> str:
        """Минимальный вариант подписи независимо от действующего."""
        return self.value(name, "short")

    def variants(self, name: str) -> tuple[str, str]:
        """Пара «среднее, минимальное» — для редактора и диалога предмета."""
        return (self.medium(name), self.minimal(name))

    def is_custom(self, name: str, style: str | None = None) -> bool:
        """Задано ли сокращение пользователем (а не набором или автоматикой)."""
        key = (name or "").strip()
        if key not in self.overrides:
            return False
        return self.overrides[key][variant_index(style or self.style)] is not None

    def effective(self, style: str | None = None) -> dict[str, str]:
        """Все действующие сокращения варианта: набор плюс переопределения."""
        style = style or self.style
        result = dict(stock_names(style))
        index = variant_index(style)
        for name, values in self.overrides.items():
            override = values[index]
            if override is not None:
                result[name] = override
        return result


class SubjectNameService:
    """Короткие подписи предметов с учётом настроек (SET-02)."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings = SettingsService(db)
        self._table: ShortNameTable | None = None

    # ------------------------------------------------------------------ таблица
    @property
    def table(self) -> ShortNameTable:
        """Настройки сокращений (читаются один раз на объект)."""
        if self._table is None:
            style = self.settings.raw(SettingsKeys.SUBJECT_ABBREVIATIONS_STYLE)
            self._table = ShortNameTable(
                enabled=self.settings.raw(SettingsKeys.SUBJECT_ABBREVIATIONS_ENABLED)
                in ("", "1"),
                style=style or DEFAULT_STYLE,
                overrides=parse_short_names(
                    self.settings.raw(SettingsKeys.SUBJECT_SHORT_NAMES)
                ),
            )
        return self._table

    @property
    def enabled(self) -> bool:
        """Включён ли показ сокращений (по умолчанию — включён)."""
        return self.table.enabled

    @property
    def style(self) -> str:
        """Действующий вариант сокращений: ``medium`` или ``short``."""
        return self.table.style

    # ------------------------------------------------------------------ чтение
    def short(self, name: str, style: str | None = None) -> str:
        """Короткая подпись без учёта переключателя показа.

        ``style`` позволяет спросить конкретный вариант: он нужен редактору, где
        обе колонки показываются одновременно.
        """
        return self.table.value(name, style)

    def medium(self, name: str) -> str:
        """Средний вариант сокращения."""
        return self.table.medium(name)

    def minimal(self, name: str) -> str:
        """Минимальный вариант сокращения."""
        return self.table.minimal(name)

    def variants(self, name: str) -> tuple[str, str]:
        """Пара «среднее, минимальное» для диалога предмета."""
        return self.table.variants(name)

    def display(self, name: str) -> str:
        """Подпись для интерфейса: сокращение при включённом режиме, иначе полное.

        Пустое название остаётся пустым: страницы подставляют прочерк сами.
        """
        text = (name or "").strip()
        if not text:
            return ""
        if not self.enabled:
            return text
        return self.table.resolve(text) or text

    def smart(self, name: str, *, limit: int = 0) -> str:
        """Подпись для узких мест (колонка дня, правая панель).

        В отличие от :meth:`display` дополнительно укорачивает результат до
        ``limit`` символов по границе слова, даже когда сокращения выключены: в
        колонке дня длинное полное название ломает вёрстку сильнее, чем польза
        от него.
        """
        text = self.display(name)
        if not text or not limit or len(text) <= limit:
            return text
        words = text.split()
        while words and len(" ".join(words)) > limit - 1:
            words.pop()
        return (" ".join(words) or text[: limit - 1]).rstrip(" .,") + "…"

    # ------------------------------------------------------------------ запись
    def save_overrides(
        self, overrides: dict[str, tuple[str | None, str | None]]
    ) -> None:
        """Сохранить переопределения обоих вариантов.

        ``None`` снимает переопределение, ``""`` — «показывать полное название».
        Пары, у которых оба варианта не заданы, в настройку не попадают.
        """
        cleaned: dict[str, tuple[str | None, str | None]] = {}
        for name, values in overrides.items():
            key = (name or "").strip()
            if not key:
                continue
            medium, minimal = values
            medium = (medium or "").strip() if medium else medium
            minimal = (minimal or "").strip() if minimal else minimal
            medium = "" if medium == "" else medium
            minimal = "" if minimal == "" else minimal
            if medium is None and minimal is None:
                continue
            cleaned[key] = (medium, minimal)
        self.settings.set(
            SettingsKeys.SUBJECT_SHORT_NAMES, serialize_short_names(cleaned)
        )
        self._table = None

    def set_variant(self, name: str, style: str, value: str | None) -> None:
        """Задать один вариант сокращения, не трогая второй.

        ``value=None`` — снять переопределение, ``""`` — «показывать полное
        название» (в таблице это прочерк ``-``).
        """
        key = (name or "").strip()
        if not key:
            return
        overrides = dict(self.table.overrides)
        current = list(overrides.get(key, (None, None)))
        current[variant_index(style)] = value
        overrides[key] = (current[0], current[1])
        self.save_overrides(overrides)

    def set_variants(self, name: str, medium: str | None, minimal: str | None) -> None:
        """Задать сразу оба варианта (диалог предмета)."""
        key = (name or "").strip()
        if not key:
            return
        overrides = dict(self.table.overrides)
        overrides[key] = (medium, minimal)
        self.save_overrides(overrides)

    def set_enabled(self, enabled: bool) -> None:
        """Включить или выключить показ сокращённых названий."""
        self.settings.set(
            SettingsKeys.SUBJECT_ABBREVIATIONS_ENABLED, "1" if enabled else "0"
        )
        self._table = None

    def set_style(self, style: str) -> None:
        """Выбрать действующий вариант (``medium`` или ``short``)."""
        self.settings.set(SettingsKeys.SUBJECT_ABBREVIATIONS_STYLE, style)
        self._table = None

    def reset_to_stock(self) -> None:
        """Убрать все переопределения: остаются стандартные наборы."""
        self.settings.set(SettingsKeys.SUBJECT_SHORT_NAMES, "")
        self._table = None

    def suggested(self, name: str, style: str | None = None) -> str:
        """Сокращение, которое приложение предложит предмету (для редактора)."""
        return self.short(name, style)

    def rename(self, old: str, new: str) -> None:
        """Перенести сокращения на новое название предмета при переименовании.

        Без этого правка названия в справочнике «теряла» сокращения: они были
        привязаны к прежнему имени и оставались сиротами.
        """
        old_key, new_key = (old or "").strip(), (new or "").strip()
        if not old_key or not new_key or old_key == new_key:
            return
        overrides = dict(self.table.overrides)
        if old_key not in overrides:
            return
        overrides[new_key] = overrides.pop(old_key)
        self.save_overrides(overrides)


def subject_name_service(db: Database) -> SubjectNameService:
    return SubjectNameService(db)


__all__ = [
    "SubjectNameService",
    "ShortNameTable",
    "STYLE_CAPTIONS",
    "variant_index",
    "auto_variant",
    "subject_name_service",
]
