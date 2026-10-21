"""Тёмная тема интерфейса (UI-01).

Цвета заданы в одном месте: палитра и таблица стилей строятся из словаря
:data:`COLORS`, поэтому «насыщенный синий акцент» и «жёлтый предупреждающий
бейдж» не расходятся между страницами.

Контраст проверяется тестом (``WCAG AA``: не ниже 4.5:1 для текста) — это
дешевле, чем искать плохо читаемую подпись глазами.
"""

from __future__ import annotations

#: UI-01: тёмно-серый фон, панели светлее/темнее, насыщенный синий акцент.
COLORS = {
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
}

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


def stylesheet() -> str:
    """Таблица стилей приложения в тёмной теме (UI-01)."""
    c = COLORS
    return f"""
    QWidget {{
        background-color: {c['background']};
        color: {c['text']};
        font-family: "{FONT_FAMILY}";
        font-size: {FONT_SIZES['base']}pt;
    }}

    QMainWindow, QDialog {{
        background-color: {c['background']};
    }}

    /* ---------------------------------------------------------- панели */
    QFrame#NavPanel, QFrame#WidgetsPanel {{
        background-color: {c['surface']};
        border: none;
    }}
    QFrame#NavPanel {{
        border-right: 1px solid {c['border']};
    }}
    QFrame#WidgetsPanel {{
        border-left: 1px solid {c['border']};
    }}
    QFrame#Card {{
        background-color: {c['surface_alt']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS}px;
    }}
    QFrame#CardAccent {{
        background-color: {c['surface_alt']};
        border: 1px solid {c['accent']};
        border-radius: {RADIUS}px;
    }}
    QFrame#Separator {{
        background-color: {c['border']};
        max-height: 1px;
        border: none;
    }}

    /* ---------------------------------------------------------- подписи */
    QLabel {{
        background: transparent;
    }}
    QLabel#Title {{
        font-size: {FONT_SIZES['title']}pt;
        font-weight: 600;
    }}
    QLabel#Subtitle {{
        font-size: {FONT_SIZES['medium']}pt;
        font-weight: 600;
    }}
    QLabel#Muted {{
        color: {c['text_muted']};
    }}
    QLabel#Small {{
        font-size: {FONT_SIZES['small']}pt;
        color: {c['text_muted']};
    }}
    QLabel#ProfileName {{
        font-size: {FONT_SIZES['medium']}pt;
        font-weight: 600;
    }}
    QLabel#Clock {{
        font-size: {FONT_SIZES['huge']}pt;
        font-weight: 300;
    }}
    QLabel#Metric {{
        font-size: {FONT_SIZES['large']}pt;
        font-weight: 600;
    }}
    QLabel#Empty {{
        color: {c['text_muted']};
        font-size: {FONT_SIZES['medium']}pt;
    }}

    /* ---------------------------------------------------------- бейджи */
    QLabel#Badge {{
        background-color: {c['surface_high']};
        color: {c['text']};
        border-radius: {RADIUS}px;
        padding: 2px 8px;
        font-size: {FONT_SIZES['small']}pt;
    }}
    QLabel#BadgeAccent {{
        background-color: {c['accent']};
        color: {c['accent_text']};
        border-radius: {RADIUS}px;
        padding: 2px 8px;
        font-size: {FONT_SIZES['small']}pt;
        font-weight: 600;
    }}
    QLabel#BadgeWarning {{
        background-color: {c['warning_bg']};
        color: {c['warning_text']};
        border: 1px solid {c['warning']};
        border-radius: {RADIUS}px;
        padding: 2px 8px;
        font-size: {FONT_SIZES['small']}pt;
    }}
    QLabel#BadgeSuccess {{
        background-color: {c['surface_high']};
        color: {c['success']};
        border: 1px solid {c['success']};
        border-radius: {RADIUS}px;
        padding: 2px 8px;
        font-size: {FONT_SIZES['small']}pt;
    }}
    QLabel#BadgeError {{
        background-color: {c['error_bg']};
        color: {c['error']};
        border: 1px solid {c['error']};
        border-radius: {RADIUS}px;
        padding: 2px 8px;
        font-size: {FONT_SIZES['small']}pt;
    }}

    /* ---------------------------------------------------------- кнопки */
    QPushButton {{
        background-color: {c['surface_high']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        border-radius: {RADIUS}px;
        padding: 6px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background-color: {c['border']};
    }}
    QPushButton:pressed {{
        background-color: {c['surface']};
    }}
    QPushButton:disabled {{
        color: {c['text_disabled']};
        border-color: {c['border']};
        background-color: {c['surface']};
    }}
    QPushButton#Primary {{
        background-color: {c['accent']};
        color: {c['accent_text']};
        border: 1px solid {c['accent']};
        font-weight: 600;
    }}
    QPushButton#Primary:hover {{
        background-color: {c['accent_hover']};
        border-color: {c['accent_hover']};
    }}
    QPushButton#Primary:pressed {{
        background-color: {c['accent_pressed']};
    }}
    QPushButton#Primary:disabled {{
        background-color: {c['surface_high']};
        color: {c['text_disabled']};
        border-color: {c['border']};
    }}
    QPushButton#Danger {{
        color: {c['error']};
        border-color: {c['error']};
    }}
    QPushButton#Danger:hover {{
        background-color: {c['error_bg']};
    }}
    QPushButton#Flat {{
        background: transparent;
        border: none;
        padding: 4px 6px;
        color: {c['text_muted']};
    }}
    QPushButton#Flat:hover {{
        color: {c['text']};
        background-color: {c['surface_high']};
        border-radius: {RADIUS}px;
    }}

    /* ------------------------------------------------------ навигация */
    QPushButton#NavItem {{
        background: transparent;
        border: none;
        border-radius: {RADIUS}px;
        padding: 9px 12px;
        text-align: left;
        color: {c['text_muted']};
    }}
    QPushButton#NavItem:hover {{
        background-color: {c['surface_alt']};
        color: {c['text']};
    }}
    QPushButton#NavItem:checked {{
        background-color: {c['accent']};
        color: {c['accent_text']};
        font-weight: 600;
    }}

    /* -------------------------------------------------------- поля ввода */
    QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
        background-color: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        border-radius: {RADIUS}px;
        padding: 5px 8px;
        selection-background-color: {c['accent']};
        selection-color: {c['accent_text']};
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus,
    QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {c['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {c['text_disabled']};
        background-color: {c['surface_alt']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['surface_alt']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        selection-background-color: {c['accent']};
        selection-color: {c['accent_text']};
        outline: none;
    }}
    QCheckBox, QRadioButton {{
        background: transparent;
        spacing: 7px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {c['border_strong']};
        background-color: {c['surface']};
    }}
    QCheckBox::indicator {{ border-radius: 3px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {c['accent']};
        border-color: {c['accent']};
    }}

    /* ---------------------------------------------------------- таблицы */
    QTableWidget, QTreeWidget, QListWidget, QTableView, QTreeView {{
        background-color: {c['surface']};
        alternate-background-color: {c['surface_alt']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS}px;
        gridline-color: {c['border']};
        selection-background-color: {c['accent']};
        selection-color: {c['accent_text']};
        outline: none;
    }}
    QTableWidget::item, QTreeWidget::item, QListWidget::item {{
        padding: 4px 6px;
    }}
    QHeaderView::section {{
        background-color: {c['surface_alt']};
        color: {c['text_muted']};
        border: none;
        border-bottom: 1px solid {c['border_strong']};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background-color: {c['surface_alt']};
        border: none;
    }}

    /* ------------------------------------------------------ прокрутка */
    QScrollBar:vertical {{
        background: transparent;
        width: 11px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-height: 26px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c['text_disabled']};
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 11px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-width: 26px;
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        height: 0;
        width: 0;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
    }}

    /* ---------------------------------------------------------- вкладки */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: {RADIUS}px;
        background-color: {c['surface']};
    }}
    QTabBar::tab {{
        background-color: {c['surface_alt']};
        color: {c['text_muted']};
        border: 1px solid {c['border']};
        border-bottom: none;
        border-top-left-radius: {RADIUS}px;
        border-top-right-radius: {RADIUS}px;
        padding: 6px 14px;
        margin-right: 2px;
    }}
    QTabBar::tab:selected {{
        background-color: {c['surface']};
        color: {c['text']};
        border-bottom: 2px solid {c['accent']};
    }}
    QTabBar::tab:hover {{
        color: {c['text']};
    }}

    /* ------------------------------------------------------ прочее */
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: {RADIUS}px;
        margin-top: 10px;
        padding-top: 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: {c['text_muted']};
    }}
    QMenu {{
        background-color: {c['surface_alt']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        border-radius: {RADIUS}px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 14px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {c['accent']};
        color: {c['accent_text']};
    }}
    QToolTip {{
        background-color: {c['surface_high']};
        color: {c['text']};
        border: 1px solid {c['border_strong']};
        border-radius: 4px;
        padding: 4px 6px;
    }}
    QStatusBar {{
        background-color: {c['surface']};
        color: {c['text_muted']};
        border-top: 1px solid {c['border']};
    }}
    QSplitter::handle {{
        background-color: {c['border']};
        width: 1px;
    }}
    QProgressBar {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        text-align: center;
        color: {c['text']};
    }}
    QProgressBar::chunk {{
        background-color: {c['accent']};
        border-radius: 3px;
    }}
    """


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


__all__ = ["COLORS", "FONT_FAMILY", "FONT_SIZES", "RADIUS", "SPACING",
           "stylesheet", "contrast_ratio", "relative_luminance"]
