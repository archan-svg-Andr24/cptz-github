"""Темы интерфейса: тёмная, светлая и радужная (UI-13).

Цвета заданы в одном месте: палитра и таблица стилей строятся из словаря
:data:`COLORS`, поэтому «насыщенный синий акцент» и «жёлтый предупреждающий
бейдж» не расходятся между страницами.

Тема — это именованный набор цветов (:class:`Theme`). Активная тема хранится
в настройке ``ui_theme`` (реестр §30) и применяется сразу, без перезапуска:
:class:`ThemeManager` перестраивает таблицу стилей приложения, и все виджеты
перекрашиваются. Виджеты, которые рисуют цвета сами (мини-календарь, таблицы),
перерисовываются по сигналу ``theme_changed``.

Контраст проверяется тестом (``WCAG AA``: не ниже 4.5:1 для текста) для
**каждой** темы — это дешевле, чем искать плохо читаемую подпись глазами.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette


class ThemeId:
    """Идентификаторы тем (ключи настройки ``ui_theme``)."""

    DARK = "dark"
    LIGHT = "light"
    RAINBOW = "rainbow"


#: Порядок тем в интерфейсе.
THEME_ORDER: tuple[str, ...] = (ThemeId.DARK, ThemeId.LIGHT, ThemeId.RAINBOW)

#: Тема по умолчанию: приложение исторически тёмное.
DEFAULT_THEME = ThemeId.DARK

# ---------------------------------------------------------------------------
# Палитры. Набор ключей у всех тем одинаковый — стилевая таблица общая,
# поэтому новая тема не может «забыть» цвет и получить прозрачный фон.
# ---------------------------------------------------------------------------
_DARK = {
    # Фон и панели.
    "background": "#1e2126",
    "surface": "#262a31",
    "surface_alt": "#2f343c",
    "surface_high": "#383e48",
    "border": "#3d444f",
    "border_strong": "#4d5663",
    # Текст.
    "text": "#e6e9ee",
    "text_muted": "#a3acb9",
    "text_disabled": "#6d7683",
    # Акцент и состояния.
    "accent": "#2f6fed",
    "accent_hover": "#4a84f5",
    "accent_pressed": "#1f57c9",
    "accent_text": "#ffffff",
    "success": "#3fb950",
    "warning": "#d9a828",
    "warning_bg": "#3a3320",
    "warning_text": "#ffd75e",
    "error": "#e5534b",
    "error_bg": "#3d2624",
    "cancelled": "#7a828e",
    "cancelled_bg": "#2b2f36",
    # Дополнительные подписи статусов (SCH-05, SCH-11).
    "status_planned": "#a3acb9",
    "status_cancelled": "#7a828e",
    "status_replaced": "#d9a828",
    "status_added": "#3fb950",
    # Мини-календарь (UI-05): верхняя неделя выделена синим, нижняя — обычным
    # текстом, воскресенье — красным. Цвета прошли проверку WCAG AA (≥ 4.5:1)
    # и на обычном фоне, и на фоне учебного периода.
    "week_upper": "#6ba0ff",
    "week_sunday": "#ff7b72",
}

_LIGHT = {
    # Фон и панели: почти белая бумага, панели светлее фона.
    "background": "#eef2f7",
    "surface": "#ffffff",
    "surface_alt": "#f5f8fc",
    "surface_high": "#e5ecf5",
    "border": "#d5dde7",
    "border_strong": "#b6c2d1",
    # Текст: тёплый графит вместо чистого чёрного — меньше «звона».
    "text": "#161f2a",
    "text_muted": "#4f5d6d",
    "text_disabled": "#8b97a6",
    # Акцент и состояния.
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_pressed": "#1e40af",
    "accent_text": "#ffffff",
    "success": "#0f7a37",
    "warning": "#a0660a",
    "warning_bg": "#fdf3dd",
    "warning_text": "#6f4500",
    "error": "#b3261e",
    "error_bg": "#fdeceb",
    "cancelled": "#5c6773",
    "cancelled_bg": "#eceff3",
    "status_planned": "#4f5d6d",
    "status_cancelled": "#5c6773",
    "status_replaced": "#a0660a",
    "status_added": "#0f7a37",
    "week_upper": "#1a4fb4",
    "week_sunday": "#c02626",
}

_RAINBOW = {
    # Фон и панели: глубокий фиолетовый, панели светлее фона.
    "background": "#17102b",
    "surface": "#221641",
    "surface_alt": "#2c1c53",
    "surface_high": "#3a2569",
    "border": "#4a2f85",
    "border_strong": "#6b45b8",
    # Текст.
    "text": "#f7f1ff",
    "text_muted": "#cbb5f2",
    "text_disabled": "#9079c0",
    # Акцент и состояния: яркая маджента вместо синего.
    "accent": "#9333ea",
    "accent_hover": "#c084fc",
    "accent_pressed": "#7e22ce",
    "accent_text": "#ffffff",
    "success": "#4ade80",
    "warning": "#f59e0b",
    "warning_bg": "#3a2a0e",
    "warning_text": "#ffd58a",
    "error": "#ff8fa3",
    "error_bg": "#3d1226",
    "cancelled": "#a08cc6",
    "cancelled_bg": "#2a1b48",
    "status_planned": "#cbb5f2",
    "status_cancelled": "#b8a3df",
    "status_replaced": "#f59e0b",
    "status_added": "#4ade80",
    "week_upper": "#22d3ee",
    "week_sunday": "#fb7185",
}
@dataclass(frozen=True)
class Theme:
    """Именованный набор цветов интерфейса."""

    key: str
    caption: str
    description: str
    dark: bool
    colors: dict[str, str]
    #: Красит ли тема пары расписания по предметам.
    subject_colors: bool = False

    def color(self, name: str) -> str:
        return self.colors[name]


#: Палитра для различения предметов (UI-13, радужная тема).
#:
#: Двенадцать оттенков, равномерно разнесённых по кругу тонов. Насыщенность и
#: светлота подобраны так, что **каждый** цвет читается как текст на всех фонах
#: расписания (карточка, отменённая карточка, выделенная строка) — минимум
#: 4.5:1 по WCAG AA. Соседние оттенки отличаются на 55 пунктов по сумме
#: каналов RGB, поэтому «Алгебра» и «Физика» не выглядят одинаково.
SUBJECT_COLORS: tuple[str, ...] = (
    "#f99494",  # 0°   — коралл
    "#f9c794",  # 30°  — янтарь
    "#f9f994",  # 60°  — лимон
    "#c7f994",  # 90°  — лайм
    "#94f994",  # 120° — зелень
    "#94f9c7",  # 150° — мята
    "#94f9f9",  # 180° — бирюза
    "#94c7f9",  # 210° — небо
    "#9494f9",  # 240° — индиго
    "#c794f9",  # 270° — сирень
    "#f994f9",  # 300° — маджента
    "#f994c7",  # 330° — фуксия
)


def subject_color_index(subject_id: int | None, name: str = "") -> int:
    """Номер цвета предмета: стабильный и не зависящий от порядка занятий.

    Считается по идентификатору предмета, поэтому один и тот же предмет
    окрашен одинаково во всех днях и после перезапуска. Предмет без
    идентификатора (пустая пара) различается по названию, чтобы две пустые
    пары тоже не сливались.
    """
    if subject_id:
        return subject_id % len(SUBJECT_COLORS)
    return sum(ord(char) for char in name) % len(SUBJECT_COLORS)


def subject_color(subject_id: int | None, name: str = "") -> str:
    """Цвет предмета из :data:`SUBJECT_COLORS`."""
    return SUBJECT_COLORS[subject_color_index(subject_id, name)]



#: Все темы приложения. Порядок словаря — порядок переключателя (THEME_ORDER).
THEMES: dict[str, Theme] = {
    ThemeId.DARK: Theme(
        ThemeId.DARK,
        "Тёмная",
        "Спокойный тёмно-серый фон и насыщенный синий акцент — тема по умолчанию.",
        True,
        _DARK,
    ),
    ThemeId.LIGHT: Theme(
        ThemeId.LIGHT,
        "Светлая",
        "Белая бумага и графитовый текст: читать днём при ярком свете.",
        False,
        _LIGHT,
    ),
    ThemeId.RAINBOW: Theme(
        ThemeId.RAINBOW,
        "Радужная",
        "Фиолетовая основа, градиентные акценты и свой цвет у каждого предмета.",
        True,
        _RAINBOW,
        subject_colors=True,
    ),
}


#: Активная палитра. Это **изменяемый** словарь: при смене темы он
#: обновляется на месте, поэтому модули, сделавшие ``from .theme import
#: COLORS``, автоматически видят новые цвета в момент построения стиля.
COLORS: dict[str, str] = dict(THEMES[DEFAULT_THEME].colors)

#: Активная тема (ключ).
_active_key: str = DEFAULT_THEME

#: Семейство шрифта: системное без засечек, читаемое в кириллице.
FONT_FAMILY = "Segoe UI"

FONT_SIZES = {
    "small": 9,
    "base": 10,
    "medium": 11,
    "large": 13,
    "title": 16,
    "huge": 20,
}

RADIUS = 6
SPACING = 8


# ---------------------------------------------------------------------------
# Доступ к активной теме
# ---------------------------------------------------------------------------
def active_theme_key() -> str:
    """Ключ действующей темы."""
    return _active_key


def active_theme() -> Theme:
    """Действующая тема."""
    return THEMES[_active_key]


def get_theme(key: str | None) -> Theme:
    """Тема по ключу; неизвестный ключ — тема по умолчанию (устойчиво к данным)."""
    return THEMES.get(key or "", THEMES[DEFAULT_THEME])


def theme_choices() -> tuple[tuple[str, str], ...]:
    """Пары «ключ — название» в порядке интерфейса (для переключателя)."""
    return tuple((key, THEMES[key].caption) for key in THEME_ORDER)


def set_active_theme(key: str) -> Theme:
    """Сделать тему активной: обновить палитру на месте и запомнить ключ."""
    global _active_key
    theme = get_theme(key)
    _active_key = theme.key
    # На месте: ссылки ``COLORS`` в других модулях остаются валидными.
    COLORS.clear()
    COLORS.update(theme.colors)
    return theme


# ---------------------------------------------------------------------------
# Таблица стилей
# ---------------------------------------------------------------------------
def _subject_rules() -> str:
    """Правила раскраски пар по предмету для радужной темы (UI-13).

    Цвет живёт в стилевой таблице, а не в ``setStyleSheet`` карточки: только
    так он меняется вместе с темой. Карточка помечает себя свойством
    ``subjectColor`` (номер оттенка), а какой это оттенок — решает тема.

    Красится название предмета и полоса слева. Фон карточки не трогаем:
    заливка тоном предмета давала контраст 1.2–1.6 к соседним карточкам и
    «радуга» превращалась в грязное пятно, а цветной текст читается.
    """
    rules = []
    for index, color in enumerate(SUBJECT_COLORS):
        rules.append(
            f'QFrame[subjectColor="{index}"] {{'
            f" border-left: 4px solid {color}; }}\n"
            f'QFrame[subjectColor="{index}"] QLabel#SubjectName {{'
            f" color: {color}; }}"
        )
    return "\n".join(rules) + "\n"


_BASE_QSS = """
QWidget {
    background-color: %(background)s;
    color: %(text)s;
    font-family: "%(font_family)s";
    font-size: %(base_size)dpt;
}

/* Контейнеры-«прокладки». Пустой QWidget внутри карточки не имеет своего
   оформления и получает цвет из правила выше — фон окна. На тёмной теме это
   малозаметно, а на фиолетовой (радужной) посреди карточки оставалась
   длинная тёмная полоса. Такой контейнер обязан быть прозрачным: он не
   рисует ничего своего, а показывает фон родителя.

   Селектор именно `.QWidget` (точный класс, без наследников): `QWidget`
   закрасил бы и карточки, и панели, а `QLabel`, `QPushButton` и прочие
   наследники сохраняют свои правила. */
.QWidget {
    background: transparent;
}

QMainWindow, QDialog {
    background-color: %(background)s;
}

/* ---------------------------------------------------------- панели */
QFrame#NavPanel, QFrame#WidgetsPanel {
    background-color: %(surface)s;
    border: none;
}
QFrame#NavPanel {
    border-right: 1px solid %(border)s;
}
QFrame#WidgetsPanel {
    border-left: 1px solid %(border)s;
}
QFrame#Card, QFrame#CardAccent, QFrame#CardCancelled, QFrame#CardWarning,
QFrame#WarningCard {
    background-color: %(surface_alt)s;
    border: 1px solid %(border)s;
    border-radius: %(radius)dpx;
}
QFrame#CardAccent {
    border: 1px solid %(accent)s;
}
QFrame#CardCancelled {
    background-color: %(cancelled_bg)s;
    border: 1px solid %(cancelled)s;
}
QFrame#CardWarning, QFrame#WarningCard {
    background-color: %(warning_bg)s;
    border: 1px solid %(warning)s;
}
QFrame#Separator {
    background-color: %(border)s;
    max-height: 1px;
    border: none;
}

/* ---------------------------------------------------------- подписи */
QLabel {
    background: transparent;
}
QLabel#Title {
    font-size: %(title_size)dpt;
    font-weight: 600;
}
QLabel#Subtitle, QLabel#SubtitleWarning {
    font-size: %(medium_size)dpt;
    font-weight: 600;
}
QLabel#SubtitleWarning {
    color: %(warning_text)s;
}
/* Название предмета в карточке пары. Цвет задаёт тема: в радужной — свой у
   каждого предмета, в остальных — обычный текст. */
QLabel#SubjectName {
    font-size: %(medium_size)dpt;
    font-weight: 600;
    color: %(text)s;
}
QLabel#MutedSubtitle {
    font-size: %(medium_size)dpt;
    font-weight: 600;
    color: %(text_muted)s;
}
QLabel#Muted {
    color: %(text_muted)s;
}
QLabel#Small {
    font-size: %(small_size)dpt;
    color: %(text_muted)s;
}
QLabel#SmallWarning {
    font-size: %(small_size)dpt;
    color: %(warning_text)s;
    font-weight: 600;
}
QLabel#ProfileName {
    font-size: %(medium_size)dpt;
    font-weight: 600;
}
QLabel#Clock {
    font-size: %(huge_size)dpt;
    font-weight: 300;
}
QLabel#Metric {
    font-size: %(large_size)dpt;
    font-weight: 600;
}
QLabel#Empty {
    color: %(text_muted)s;
    font-size: %(medium_size)dpt;
}
/* Подписи-сообщения и предупреждения: цвет живёт в стиле темы, а не в
   setStyleSheet отдельных виджетов — иначе при смене темы он оставался
   прежним. Кегль сохранён мелким: раньше эти подписи были «Small». */
QLabel#WarningText {
    color: %(warning_text)s;
    font-size: %(small_size)dpt;
}
QLabel#WarningBanner {
    color: %(warning_text)s;
    background-color: %(warning_bg)s;
    border: 1px solid %(warning)s;
    border-radius: %(radius)dpx;
    padding: 6px;
}
QLabel#ErrorText {
    color: %(error)s;
    font-size: %(small_size)dpt;
}
QLabel#ErrorBanner {
    color: %(error)s;
    background-color: %(error_bg)s;
    border: 1px solid %(error)s;
    border-radius: %(radius)dpx;
    padding: 6px;
}
QLabel#SuccessText {
    color: %(success)s;
    font-size: %(small_size)dpt;
}
QLabel#AccentText {
    color: %(accent_hover)s;
    font-size: %(small_size)dpt;
}
QLabel#TodayHeader {
    color: %(accent_hover)s;
    font-weight: 600;
}
QLabel#StrikeText {
    color: %(status_cancelled)s;
    text-decoration: line-through;
}
/* MetricRow.set_kind: цвет значения задаётся свойством, а не строкой стиля. */
QLabel[kind="warning"] { color: %(warning_text)s; }
QLabel[kind="success"] { color: %(success)s; }
QLabel[kind="error"] { color: %(error)s; }
QLabel[kind="muted"] { color: %(text_muted)s; }

/* ---------------------------------------------------------- бейджи */
QLabel#Badge {
    background-color: %(surface_high)s;
    color: %(text)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
}
QLabel#BadgeAccent {
    background-color: %(accent)s;
    color: %(accent_text)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
    font-weight: 600;
}
QLabel#BadgeWarning {
    background-color: %(warning_bg)s;
    color: %(warning_text)s;
    border: 1px solid %(warning)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
}
QLabel#BadgeSuccess {
    background-color: %(surface_high)s;
    color: %(success)s;
    border: 1px solid %(success)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
}
QLabel#BadgeError {
    background-color: %(error_bg)s;
    color: %(error)s;
    border: 1px solid %(error)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
}
QLabel#BadgeCancelled {
    background-color: %(cancelled_bg)s;
    color: %(status_cancelled)s;
    border: 1px solid %(cancelled)s;
    border-radius: %(radius)dpx;
    padding: 2px 8px;
    font-size: %(small_size)dpt;
}

/* ---------------------------------------------------------- кнопки */
QPushButton {
    background-color: %(surface_high)s;
    color: %(text)s;
    border: 1px solid %(border_strong)s;
    border-radius: %(radius)dpx;
    padding: 6px 14px;
    min-height: 18px;
}
QPushButton:hover {
    background-color: %(border)s;
}
QPushButton:pressed {
    background-color: %(surface)s;
}
QPushButton:disabled {
    color: %(text_disabled)s;
    border-color: %(border)s;
    background-color: %(surface)s;
}
QPushButton#Primary {
    background-color: %(accent)s;
    color: %(accent_text)s;
    border: 1px solid %(accent)s;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background-color: %(accent_hover)s;
    border-color: %(accent_hover)s;
}
QPushButton#Primary:pressed {
    background-color: %(accent_pressed)s;
}
QPushButton#Primary:disabled {
    background-color: %(surface_high)s;
    color: %(text_disabled)s;
    border-color: %(border)s;
}
QPushButton#Danger {
    color: %(error)s;
    border-color: %(error)s;
}
QPushButton#Danger:hover {
    background-color: %(error_bg)s;
}
QPushButton#Flat {
    background: transparent;
    border: none;
    padding: 4px 6px;
    color: %(text_muted)s;
}
QPushButton#Flat:hover {
    color: %(text)s;
    background-color: %(surface_high)s;
    border-radius: %(radius)dpx;
}

/* ------------------------------------------------------ навигация */
QPushButton#NavItem {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: %(radius)dpx;
    padding: 9px 10px;
    /* Пункты меню — основные действия раздела, а не подписи: кегль
       равен medium, а не базовому 10pt, иначе названия выглядели мельче
       текста на самих страницах. */
    font-size: %(medium_size)dpt;
    text-align: left;
    color: %(text_muted)s;
}
QPushButton#NavItem:hover {
    background-color: %(surface_alt)s;
    color: %(text)s;
}
QPushButton#NavItem:checked {
    background-color: %(accent)s;
    color: %(accent_text)s;
    font-weight: 600;
}

/* -------------------------------------------------------- поля ввода */
QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QPlainTextEdit,
QTextEdit, QDoubleSpinBox {
    background-color: %(surface)s;
    color: %(text)s;
    border: 1px solid %(border_strong)s;
    border-radius: %(radius)dpx;
    padding: 5px 8px;
    selection-background-color: %(accent)s;
    selection-color: %(accent_text)s;
}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDoubleSpinBox:focus {
    border-color: %(accent)s;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateEdit:disabled {
    color: %(text_disabled)s;
    background-color: %(surface_alt)s;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: %(surface_alt)s;
    color: %(text)s;
    border: 1px solid %(border_strong)s;
    selection-background-color: %(accent)s;
    selection-color: %(accent_text)s;
    outline: none;
}
QCheckBox, QRadioButton {
    background: transparent;
    spacing: 7px;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid %(border_strong)s;
    background-color: %(surface)s;
}
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: %(accent)s;
    border-color: %(accent)s;
}

/* ---------------------------------------------------------- таблицы */
QTableWidget, QTreeWidget, QListWidget, QTableView, QTreeView {
    background-color: %(surface)s;
    alternate-background-color: %(surface_alt)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: %(radius)dpx;
    gridline-color: %(border)s;
    selection-background-color: %(accent)s;
    selection-color: %(accent_text)s;
    outline: none;
}
QTableWidget::item, QTreeWidget::item, QListWidget::item {
    padding: 4px 6px;
}
QHeaderView::section {
    background-color: %(surface_alt)s;
    color: %(text_muted)s;
    border: none;
    border-bottom: 1px solid %(border_strong)s;
    padding: 6px 8px;
    font-weight: 600;
}
QTableCornerButton::section {
    background-color: %(surface_alt)s;
    border: none;
}

/* ------------------------------------------------------ прокрутка */
QScrollBar:vertical {
    background: transparent;
    width: 11px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: %(border_strong)s;
    border-radius: 5px;
    min-height: 26px;
}
QScrollBar::handle:vertical:hover {
    background: %(text_disabled)s;
}
QScrollBar:horizontal {
    background: transparent;
    height: 11px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: %(border_strong)s;
    border-radius: 5px;
    min-width: 26px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

/* ---------------------------------------------------------- вкладки */
QTabWidget::pane {
    border: 1px solid %(border)s;
    border-radius: %(radius)dpx;
    background-color: %(surface)s;
}
QTabBar::tab {
    background-color: %(surface_alt)s;
    color: %(text_muted)s;
    border: 1px solid %(border)s;
    border-bottom: none;
    border-top-left-radius: %(radius)dpx;
    border-top-right-radius: %(radius)dpx;
    padding: 6px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: %(surface)s;
    color: %(text)s;
    border-bottom: 2px solid %(accent)s;
}
QTabBar::tab:hover {
    color: %(text)s;
}

/* ------------------------------------------------------ прочее */
QGroupBox {
    border: 1px solid %(border)s;
    border-radius: %(radius)dpx;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: %(text_muted)s;
}
QMenu {
    background-color: %(surface_alt)s;
    color: %(text)s;
    border: 1px solid %(border_strong)s;
    border-radius: %(radius)dpx;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px 6px 14px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: %(accent)s;
    color: %(accent_text)s;
}
QToolTip {
    background-color: %(surface_high)s;
    color: %(text)s;
    border: 1px solid %(border_strong)s;
    border-radius: 4px;
    padding: 4px 6px;
}
QStatusBar {
    background-color: %(surface)s;
    color: %(text_muted)s;
    border-top: 1px solid %(border)s;
}
QSplitter::handle {
    background-color: %(border)s;
    width: 1px;
}
QProgressBar {
    background-color: %(surface)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    text-align: center;
    color: %(text)s;
}
QProgressBar::chunk {
    background-color: %(accent)s;
    border-radius: 3px;
}
"""

#: Радужная тема: градиентные акценты и свой цвет у каждого раздела меню.
#: Градиенты подобраны так, чтобы белый текст на них проходил WCAG AA —
#: светлые «радужные» полосы с белым текстом читались бы плохо.
_RAINBOW_QSS = """
QPushButton#Primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a21caf, stop:0.34 #be123c, stop:0.67 #0f766e, stop:1 #4338ca);
    border: 1px solid %(accent_pressed)s;
}
QPushButton#Primary:hover {
    background: qlineargradient(x1:1, y1:0, x2:0, y2:1,
        stop:0 #a21caf, stop:0.34 #be123c, stop:0.67 #0f766e, stop:1 #4338ca);
}
QPushButton#Primary:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7e22ce, stop:0.5 #9f1239, stop:1 #3730a3);
}
QLabel#BadgeAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a21caf, stop:0.5 #be123c, stop:1 #4338ca);
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a21caf, stop:0.25 #be123c, stop:0.5 #ca8a04,
        stop:0.75 #0f766e, stop:1 #4338ca);
}
QTabBar::tab:selected {
    border-bottom: 2px solid %(accent)s;
}
QStatusBar {
    border-top: 1px solid %(accent)s;
}
/* Каждый раздел меню — своего цвета: «радуга» видна уже в навигации.
   Оттенки тёмные, поэтому белая подпись выбранного пункта читается. */
QPushButton#NavItem[page="schedule"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #be185d, stop:1 #7e22ce);
}
QPushButton#NavItem[page="trips"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0f766e, stop:1 #0e7490);
}
QPushButton#NavItem[page="expenses"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #92400e, stop:1 #b45309);
}
QPushButton#NavItem[page="homework"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #4338ca, stop:1 #3730a3);
}
QPushButton#NavItem[page="settings"]:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #7e22ce, stop:1 #a21caf);
}
QPushButton#NavItem:hover {
    border-left: 3px solid %(accent_hover)s;
}
QHeaderView::section {
    border-bottom: 1px solid %(accent)s;
}
"""


def stylesheet(theme: "Theme | str | None" = None) -> str:
    """Таблица стилей приложения для темы (по умолчанию — активной).

    Все цвета подставляются из палитры выбранной темы, поэтому таблица стилей
    не может «отстать» от :data:`COLORS`.
    """
    selected = active_theme() if theme is None else get_theme(
        theme if isinstance(theme, str) else theme.key
    )
    colors = dict(selected.colors)
    values = {
        **colors,
        "font_family": FONT_FAMILY,
        "base_size": FONT_SIZES["base"],
        "small_size": FONT_SIZES["small"],
        "medium_size": FONT_SIZES["medium"],
        "large_size": FONT_SIZES["large"],
        "title_size": FONT_SIZES["title"],
        "huge_size": FONT_SIZES["huge"],
        "radius": RADIUS,
    }
    css = _BASE_QSS % values
    if selected.key == ThemeId.RAINBOW:
        css += _RAINBOW_QSS % values
        css += _subject_rules()
    return css


# ---------------------------------------------------------------------------
# Палитра Qt: колёса прокрутки, меню, календарь и системные диалоги рисуются
# не по QSS, а по QPalette — без неё светлая тема оставалась тёмной местами.
# ---------------------------------------------------------------------------
def build_palette(theme: "Theme | str | None" = None) -> QPalette:
    """Палитра Qt для темы: родные элементы не выбиваются из оформления."""
    selected = active_theme() if theme is None else get_theme(
        theme if isinstance(theme, str) else theme.key
    )
    c = selected.colors
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    palette.setColor(role.Window, QColor(c["background"]))
    palette.setColor(role.WindowText, QColor(c["text"]))
    palette.setColor(role.Base, QColor(c["surface"]))
    palette.setColor(role.AlternateBase, QColor(c["surface_alt"]))
    palette.setColor(role.Text, QColor(c["text"]))
    palette.setColor(role.Button, QColor(c["surface_high"]))
    palette.setColor(role.ButtonText, QColor(c["text"]))
    palette.setColor(role.BrightText, QColor(c["accent_text"]))
    palette.setColor(role.Highlight, QColor(c["accent"]))
    palette.setColor(role.HighlightedText, QColor(c["accent_text"]))
    palette.setColor(role.ToolTipBase, QColor(c["surface_high"]))
    palette.setColor(role.ToolTipText, QColor(c["text"]))
    palette.setColor(role.PlaceholderText, QColor(c["text_disabled"]))
    palette.setColor(role.Link, QColor(c["accent_hover"]))
    palette.setColor(role.Mid, QColor(c["border"]))
    palette.setColor(role.Midlight, QColor(c["surface_alt"]))
    palette.setColor(role.Dark, QColor(c["border_strong"]))
    palette.setColor(role.Light, QColor(c["surface_alt"]))
    palette.setColor(role.Shadow, QColor(c["border_strong"]))

    # Отключённые элементы: тот же тон, но приглушённый.
    for disabled_role, color in (
        (role.WindowText, c["text_disabled"]),
        (role.Text, c["text_disabled"]),
        (role.ButtonText, c["text_disabled"]),
        (role.HighlightedText, c["text_disabled"]),
    ):
        palette.setColor(group.Disabled, disabled_role, QColor(color))
    return palette


def apply_application_theme(app=None) -> None:
    """Применить **активную** тему ко всему приложению: палитра + стили.

    Таблица стилей ставится на ``QApplication``, а не на главное окно: тогда
    её автоматически получают диалоги, меню и всплывающие подсказки, а при
    смене темы Qt сама перекрашивает все виджеты.

    Отдельного аргумента с темой нет намеренно: применяется действующая
    палитра, поэтому ``COLORS`` и стиль приложения не могут разойтись.
    Сначала :func:`set_active_theme`, затем эта функция.
    """
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    if app is None:  # pragma: no cover - тема без QApplication не применяется
        return
    selected = active_theme()
    app.setPalette(build_palette(selected))
    app.setStyleSheet(stylesheet(selected))


# ---------------------------------------------------------------------------
# Контроллер темы: хранит выбор в настройках и оповещает интерфейс
# ---------------------------------------------------------------------------
class ThemeManager(QObject):
    """Смена темы: применить к приложению, сохранить выбор, оповестить окно."""

    theme_changed = Signal(str)

    def __init__(self, db=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db = db

    # ------------------------------------------------------------ состояние
    @property
    def key(self) -> str:
        """Ключ действующей темы."""
        return active_theme_key()

    @property
    def theme(self) -> Theme:
        return active_theme()

    # -------------------------------------------------------------- действия
    def load(self, app=None) -> str:
        """Прочитать сохранённую тему и применить её (без записи в БД).

        Неизвестное или пустое значение (например, база предыдущей версии)
        трактуется как тема по умолчанию — интерфейс не должен остаться без
        оформления.
        """
        key = DEFAULT_THEME
        if self._db is not None:
            from ..core.settings_service import SettingsService
            from ..core.settings_registry import SettingsKeys

            try:
                stored = SettingsService(self._db).raw(SettingsKeys.UI_THEME)
            except Exception:  # pragma: no cover - защита интерфейса
                stored = ""
            if stored in THEMES:
                key = stored
        return self.apply(key, persist=False, app=app)

    def apply(self, key: str, *, persist: bool = True, app=None) -> str:
        """Применить тему; ``persist`` записывает выбор в настройки."""
        theme = set_active_theme(key)
        apply_application_theme(app)
        if persist and self._db is not None:
            from ..core.settings_service import SettingsService
            from ..core.settings_registry import SettingsKeys

            try:
                SettingsService(self._db).set(SettingsKeys.UI_THEME, theme.key)
            except Exception:  # pragma: no cover - защита интерфейса
                pass
        self.theme_changed.emit(theme.key)
        return theme.key

    def cycle(self) -> str:
        """Следующая тема по кругу — для быстрого переключения."""
        index = THEME_ORDER.index(active_theme_key())
        return self.apply(THEME_ORDER[(index + 1) % len(THEME_ORDER)])


_MANAGER: ThemeManager | None = None


def theme_manager(db=None) -> ThemeManager:
    """Единственный контроллер темы на процесс.

    Страница «Настройки» и главное окно должны говорить об одной теме; два
    независимых ``ThemeManager`` дали бы два несвязанных сигнала. База
    обновляется при каждом вызове с аргументом: в тестах каждое окно работает
    со своей базой, а в приложении она одна.
    """
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = ThemeManager(db)
    elif db is not None:
        _MANAGER._db = db  # noqa: SLF001 - намеренно один менеджер
    return _MANAGER


# ---------------------------------------------------------------------------
# Контраст (WCAG 2.x)
# ---------------------------------------------------------------------------
def relative_luminance(hex_color: str) -> float:
    """Относительная яркость цвета по WCAG 2.x."""
    value = hex_color.lstrip("#")
    channels = [int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    adjusted = [
        channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Коэффициент контраста двух цветов (WCAG AA требует ≥ 4.5 для текста)."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def theme_palettes() -> Iterable[Theme]:
    """Все темы в порядке интерфейса (для проверок контраста)."""
    return (THEMES[key] for key in THEME_ORDER)


__all__ = [
    "COLORS",
    "DEFAULT_THEME",
    "FONT_FAMILY",
    "FONT_SIZES",
    "RADIUS",
    "SPACING",
    "SUBJECT_COLORS",
    "THEMES",
    "THEME_ORDER",
    "Theme",
    "ThemeId",
    "ThemeManager",
    "active_theme",
    "active_theme_key",
    "apply_application_theme",
    "build_palette",
    "contrast_ratio",
    "get_theme",
    "relative_luminance",
    "set_active_theme",
    "stylesheet",
    "subject_color",
    "subject_color_index",
    "theme_choices",
    "theme_manager",
    "theme_palettes",
]
