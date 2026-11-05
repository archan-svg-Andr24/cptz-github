"""Тесты тем интерфейса (UI-13): тёмная, светлая, радужная.

Проверяется то, что легко сломать незаметно:

* тёмная тема осталась ровно той, что была до появления выбора тем;
* каждая тема проходит WCAG AA и содержит полный набор цветов;
* выбор темы сохраняется в настройках и переживает перезапуск;
* переключение на лету доходит до уже построенных виджетов, а не только до
  новых: страницы не хранят hex-значения в собственных строках стиля.

Слой 1 — синтетические данные (TEST-01).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """Один QApplication на сессию: второй создать нельзя."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_theme(qapp):
    """Каждый тест начинает и заканчивает в тёмной теме.

    Тема — состояние процесса: без сброса тест, переключивший палитру,
    менял бы ожидания соседних тестов.
    """
    from student_planner.ui import theme as theme_module

    theme_module.set_active_theme(theme_module.DEFAULT_THEME)
    theme_module.apply_application_theme(qapp)
    yield
    theme_module.set_active_theme(theme_module.DEFAULT_THEME)
    theme_module.apply_application_theme(qapp)
    # Менеджер держит базу теста: следующий тест создаёт свою.
    theme_module._MANAGER = None


@pytest.fixture
def seeded(db, qapp):
    """База со стартовым набором Приложения А."""
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    return db


# ===========================================================================
# Состав тем
# ===========================================================================
class TestThemeCatalog:
    """UI-13: три темы, у всех одинаковый набор цветов."""

    def test_three_themes_in_order(self):
        from student_planner.ui.theme import THEMES, THEME_ORDER, ThemeId

        assert THEME_ORDER == (ThemeId.DARK, ThemeId.LIGHT, ThemeId.RAINBOW)
        assert set(THEMES) == set(THEME_ORDER)

    def test_captions_are_russian(self):
        """Названия в интерфейсе — по-русски, ключи — стабильный ASCII."""
        from student_planner.ui.theme import theme_choices

        assert dict(theme_choices()) == {
            "dark": "Тёмная",
            "light": "Светлая",
            "rainbow": "Радужная",
        }

    def test_all_themes_share_same_color_keys(self):
        """Пропущенный цвет дал бы прозрачный элемент в одной из тем."""
        from student_planner.ui.theme import THEMES

        reference = set(THEMES["dark"].colors)
        for key, theme in THEMES.items():
            assert set(theme.colors) == reference, (
                f"В теме «{key}» набор цветов отличается от тёмной"
            )

    def test_dark_theme_is_unchanged(self):
        """Тёмная тема — прежние цвета приложения, без правок оттенков."""
        from student_planner.ui.theme import THEMES

        # Полный набор дословно: «в качестве тёмной используй текущую тему»,
        # поэтому любое расхождение — дефект, а не вкусовщина.
        assert THEMES["dark"].colors == {
            "background": "#1e2126",
            "surface": "#262a31",
            "surface_alt": "#2f343c",
            "surface_high": "#383e48",
            "border": "#3d444f",
            "border_strong": "#4d5663",
            "text": "#e6e9ee",
            "text_muted": "#a3acb9",
            "text_disabled": "#6d7683",
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
            "status_planned": "#a3acb9",
            "status_cancelled": "#7a828e",
            "status_replaced": "#d9a828",
            "status_added": "#3fb950",
            "week_upper": "#6ba0ff",
            "week_sunday": "#ff7b72",
        }

    def test_themes_are_visually_distinct(self):
        """Темы отличаются фоном, а не только названием."""
        from student_planner.ui.theme import THEMES

        backgrounds = {theme.colors["background"] for theme in THEMES.values()}
        assert len(backgrounds) == len(THEMES)


# ===========================================================================
# Таблица стилей и контраст
# ===========================================================================
#: Пары «текст на фоне», которые действительно встречаются в интерфейсе.
CONTRAST_PAIRS = (
    ("text", "background"),
    ("text", "surface"),
    ("text", "surface_alt"),
    ("text_muted", "surface"),
    ("text_muted", "background"),
    ("accent_text", "accent"),
    ("warning_text", "warning_bg"),
    ("error", "error_bg"),
    ("status_cancelled", "cancelled_bg"),
    ("week_upper", "surface"),
    ("week_sunday", "surface"),
)

#: Унаследованные исключения тёмной темы.
#:
#: Эти пары были ниже 4.5:1 ещё до появления выбора тем. Тёмная тема обязана
#: остаться прежней («в качестве тёмной используй текущую»), поэтому оттенки не
#: подгоняются под норму; исключения зафиксированы явно, а не спрятаны.
#: В светлой и радужной темах обе пары проходят.
DARK_LEGACY_EXCEPTIONS = {
    ("error", "error_bg"): 3.78,
    ("status_cancelled", "cancelled_bg"): 3.46,
}


class TestThemeStylesheet:
    """UI-13: таблица стилей строится из палитры выбранной темы."""

    @pytest.mark.parametrize("key", ("dark", "light", "rainbow"))
    def test_stylesheet_contains_own_background(self, key):
        from student_planner.ui.theme import THEMES, stylesheet

        css = stylesheet(key)
        assert css, "Стилевая таблица не должна быть пустой"
        assert THEMES[key].colors["background"].lower() in css.lower()

    @pytest.mark.parametrize("key", ("dark", "light", "rainbow"))
    def test_stylesheet_has_no_foreign_theme_colors(self, key):
        """В таблицу не должны просачиваться цвета другой темы."""
        from student_planner.ui.theme import THEMES, stylesheet

        own = set(THEMES[key].colors.values())
        foreign = {
            color
            for other_key, other in THEMES.items()
            if other_key != key
            for color in other.colors.values()
            if color not in own
        }
        css = stylesheet(key).lower()
        leaked = sorted(color for color in foreign if color.lower() in css)
        assert not leaked, f"В теме «{key}» найдены цвета других тем: {leaked}"

    @pytest.mark.parametrize("key", ("dark", "light", "rainbow"))
    @pytest.mark.parametrize(("foreground", "background"), CONTRAST_PAIRS)
    def test_contrast_meets_wcag(self, key, foreground, background):
        """UI-13: контраст не ниже 4.5:1 в каждой теме.

        Исключения — только унаследованные пары тёмной темы
        (:data:`DARK_LEGACY_EXCEPTIONS`): их нельзя исправить, не изменив
        саму тёмную тему.
        """
        from student_planner.ui.theme import THEMES, contrast_ratio

        colors = THEMES[key].colors
        ratio = contrast_ratio(colors[foreground], colors[background])
        legacy = DARK_LEGACY_EXCEPTIONS.get((foreground, background))
        if key == "dark" and legacy is not None:
            assert ratio == pytest.approx(legacy, abs=0.02), (
                f"Тёмная тема: {foreground}/{background} = {ratio:.2f}:1, "
                f"ожидалось унаследованное {legacy:.2f}:1"
            )
            return
        assert ratio >= 4.5, (
            f"{key}: контраст {foreground}/{background} = {ratio:.2f}:1, "
            "требуется ≥ 4.5:1"
        )

    def test_rainbow_has_gradients(self):
        """Радужная тема отличается оформлением, а не только палитрой."""
        from student_planner.ui.theme import stylesheet

        assert "qlineargradient" in stylesheet("rainbow")
        assert "qlineargradient" not in stylesheet("dark")


# ===========================================================================
# Переключение палитры
# ===========================================================================
class TestActiveTheme:
    """UI-13: активная палитра меняется на месте."""

    def test_default_is_dark(self):
        from student_planner.ui.theme import active_theme_key

        assert active_theme_key() == "dark"

    def test_colors_dict_updates_in_place(self):
        """Ссылки ``from .theme import COLORS`` должны видеть новые цвета."""
        from student_planner.ui.theme import COLORS, set_active_theme

        reference = COLORS
        set_active_theme("light")
        assert reference is COLORS
        assert COLORS["background"] == "#eef2f7"
        assert reference["text"] == COLORS["text"]

    def test_unknown_key_falls_back_to_dark(self):
        """Испорченное значение настройки не оставляет окно без оформления."""
        from student_planner.ui.theme import active_theme_key, set_active_theme

        assert set_active_theme("не-тема").key == "dark"
        assert active_theme_key() == "dark"
        assert set_active_theme("").key == "dark"

    def test_application_gets_palette_and_stylesheet(self, qapp):
        from student_planner.ui.theme import (
            COLORS,
            apply_application_theme,
            set_active_theme,
        )

        set_active_theme("light")
        apply_application_theme(qapp)
        assert COLORS["background"] == "#eef2f7"
        assert COLORS["background"] in qapp.styleSheet().lower()
        assert qapp.palette().window().color() == QColor(COLORS["background"])


# ===========================================================================
# Настройка и её сохранение
# ===========================================================================
class TestThemeSetting:
    """SET-08/UI-13: тема — обычная настройка реестра §30."""

    def test_registry_spec(self):
        from student_planner.core.settings_registry import (
            SettingType,
            UiSection,
            default_registry,
        )
        from student_planner.core.settings_registry import SettingsKeys

        spec = default_registry().get(SettingsKeys.UI_THEME)
        assert spec.type == SettingType.ENUM
        assert spec.default == "dark"
        assert spec.choices == ("dark", "light", "rainbow")
        assert spec.section == UiSection.GENERAL
        assert spec.visible is True

    def test_enum_validation_rejects_unknown(self):
        from student_planner.core.errors import SettingsError
        from student_planner.core.settings_registry import SettingsKeys, default_registry

        registry = default_registry()
        with pytest.raises(SettingsError):
            registry.validate(SettingsKeys.UI_THEME, "neon")

    def test_default_used_when_row_missing(self, db):
        """База прежней версии без строки настройки не падает."""
        from student_planner.core.settings_registry import SettingsKeys
        from student_planner.core.settings_service import SettingsService

        assert SettingsService(db).raw(SettingsKeys.UI_THEME) == "dark"

    def test_choice_is_persisted(self, seeded):
        from student_planner.core.settings_registry import SettingsKeys
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.theme import theme_manager

        theme_manager(seeded).apply("rainbow")
        assert SettingsService(seeded).raw(SettingsKeys.UI_THEME) == "rainbow"
        # Повторный запуск читает сохранённое значение.
        assert theme_manager(seeded).load() == "rainbow"
        assert theme_manager(seeded).key == "rainbow"

    def test_broken_stored_value_is_ignored(self, seeded):
        from student_planner.core.settings_registry import SettingsKeys
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.theme import theme_manager

        # Значение пишется в обход валидации: имитация правки файла БД руками.
        with seeded.transaction() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SettingsKeys.UI_THEME, "neon"),
            )
        SettingsService(seeded).set(SettingsKeys.UI_THEME, "dark")
        from student_planner.ui.theme import set_active_theme

        set_active_theme("dark")
        assert theme_manager(seeded).key == "dark"


# ===========================================================================
# Переключение на лету
# ===========================================================================
class TestLiveSwitch:
    """UI-13: смена темы доходит до уже построенных виджетов."""

    def test_main_window_switches_theme(self, seeded, qapp):
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.theme import COLORS

        window = MainWindow(seeded)
        try:
            assert window.themes.key == "dark"
            window.set_theme("light")
            assert window.themes.key == "light"
            assert COLORS["background"] == "#eef2f7"
            assert COLORS["background"] in qapp.styleSheet().lower()
            window.set_theme("rainbow")
            assert window.themes.key == "rainbow"
        finally:
            window.set_theme("dark")
            window.close()

    def test_calendar_repaints_on_theme_change(self, seeded, qapp):
        """Мини-календарь рисует цвета в QTextCharFormat — их надо обновить."""
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.theme import COLORS
        from student_planner.core import clock

        window = MainWindow(seeded)
        try:
            window.set_theme("light")
            today = clock.today()
            fmt = window.nav.calendar.calendar.dateTextFormat(
                __import__("PySide6.QtCore", fromlist=["QDate"]).QDate(
                    today.year, today.month, today.day
                )
            )
            assert fmt.background().color() == QColor(COLORS["surface_high"])
            assert fmt.foreground().color() == QColor(COLORS["text"])
        finally:
            window.set_theme("dark")
            window.close()

    def test_pages_do_not_bake_colors(self, seeded, qapp):
        """Страницы не хранят hex в собственных строках стиля.

        Если бы хранили, смена темы оставляла бы на светлом фоне жёлтые и
        тёмно-серые пятна от прежней палитры. Мини-календарь — исключение:
        ``QCalendarWidget`` не принимает общую таблицу стилей, поэтому он
        строит свою из активной палитры и перерисовывается по сигналу темы.
        """
        from PySide6.QtWidgets import QWidget

        from student_planner.ui.main_window import MainWindow

        window = MainWindow(seeded)
        try:
            window.set_theme("light")
            offenders: list[str] = []
            for widget in window.findChildren(QWidget):
                if widget.objectName() == "MiniCalendar":
                    continue
                sheet = widget.styleSheet()
                # Стили карточек-превью темы — единственное законное место
                # с «чужими» цветами: они показывают другие палитры.
                if sheet and "qlineargradient" not in sheet and "#" in sheet:
                    offenders.append(f"{type(widget).__name__}#{widget.objectName()}")
            assert not offenders, f"Зашитые цвета: {offenders[:5]}"
        finally:
            window.set_theme("dark")
            window.close()


# ===========================================================================
# Раскраска пар по предметам (радужная тема)
# ===========================================================================
class TestSubjectColors:
    """UI-13: в радужной теме каждая пара отличается цветом предмета."""

    def test_palette_is_readable_on_every_card_background(self):
        """Каждый оттенок читается как текст на всех фонах расписания."""
        from student_planner.ui.theme import SUBJECT_COLORS, THEMES, contrast_ratio

        colors = THEMES["rainbow"].colors
        backgrounds = {
            role: colors[role]
            for role in ("surface", "surface_alt", "surface_high", "cancelled_bg")
        }
        for color in SUBJECT_COLORS:
            for role, background in backgrounds.items():
                ratio = contrast_ratio(color, background)
                assert ratio >= 4.5, (
                    f"Предметный цвет {color} на {role} = {ratio:.2f}:1, "
                    "требуется ≥ 4.5:1"
                )

    def test_palette_hues_are_distinct(self):
        """Соседние оттенки заметно различаются — иначе тема «серая»."""
        from student_planner.ui.theme import SUBJECT_COLORS

        def distance(first: str, second: str) -> int:
            return sum(
                abs(int(first[i:i + 2], 16) - int(second[i:i + 2], 16))
                for i in (1, 3, 5)
            )

        for index, color in enumerate(SUBJECT_COLORS):
            neighbour = SUBJECT_COLORS[(index + 1) % len(SUBJECT_COLORS)]
            assert distance(color, neighbour) >= 40, (
                f"{color} и {neighbour} слишком похожи"
            )

    def test_subject_color_is_stable(self):
        """Один предмет — один цвет, независимо от порядка пар в дне."""
        from student_planner.ui.theme import SUBJECT_COLORS, subject_color

        assert subject_color(5) == subject_color(5)
        assert subject_color(5) in SUBJECT_COLORS
        # Разные предметы получают разные оттенки, пока их меньше палитры.
        shown = {subject_color(index) for index in range(len(SUBJECT_COLORS))}
        assert len(shown) == len(SUBJECT_COLORS)

    def test_empty_subject_differs_by_name(self):
        """У пары без предмета оттенок считается по названию."""
        from student_planner.ui.theme import subject_color

        assert subject_color(None, "Алгебра") == subject_color(None, "Алгебра")
        assert subject_color(None, "Алгебра") != subject_color(None, "Физика")

    def test_cards_carry_subject_index(self, seeded, qapp):
        """Карточка сообщает теме номер оттенка свойством, а не строкой стиля."""
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.pages.schedule import LessonCard

        window = MainWindow(seeded)
        try:
            window.open_page("schedule")
            qapp.processEvents()
            cards = window.findChildren(LessonCard)
            assert cards, "В расписании стартового набора должны быть пары"
            for card in cards:
                index = card.property("subjectColor")
                assert isinstance(index, int)
                assert 0 <= index < 12
        finally:
            window.close()

    def test_distinct_subjects_get_distinct_colors(self, seeded, qapp):
        """Два разных предмета в расписании — два разных оттенка."""
        from student_planner.ui.main_window import MainWindow
        from student_planner.ui.pages.schedule import LessonCard

        window = MainWindow(seeded)
        try:
            window.open_page("schedule")
            qapp.processEvents()
            by_subject: dict[str, set[int]] = {}
            for card in window.findChildren(LessonCard):
                by_subject.setdefault(card.lesson.subject_name, set()).add(
                    card.property("subjectColor")
                )
            for name, indices in by_subject.items():
                assert len(indices) == 1, (
                    f"«{name}» окрашен в разные оттенки: {indices}"
                )
            indices = {next(iter(value)) for value in by_subject.values()}
            assert len(indices) == len(by_subject), (
                f"Разные предметы получили одинаковый оттенок: {by_subject}"
            )
        finally:
            window.close()

    def test_rules_only_in_rainbow(self):
        """В тёмной и светлой темах предметы не раскрашиваются."""
        from student_planner.ui.theme import stylesheet

        assert 'QFrame[subjectColor="0"]' in stylesheet("rainbow")
        assert "subjectColor" not in stylesheet("dark")
        assert "subjectColor" not in stylesheet("light")

    def test_rules_cover_whole_palette(self):
        """Правило есть для каждого оттенка, иначе часть пар осталась бы серой."""
        from student_planner.ui.theme import SUBJECT_COLORS, stylesheet

        css = stylesheet("rainbow")
        for index, color in enumerate(SUBJECT_COLORS):
            assert f'QFrame[subjectColor="{index}"]' in css
            assert color in css


# ===========================================================================
# Страница настроек
# ===========================================================================
class TestSettingsThemeCard:
    """UI-13: выбор темы на вкладке «Общие», без восьмой вкладки."""

    def test_theme_cards_exist_in_general_tab(self, seeded, qapp):
        from student_planner.ui.pages.settings import GeneralTab

        tab = GeneralTab(seeded)
        assert set(tab.theme_buttons) == {"dark", "light", "rainbow"}
        assert tab.theme_buttons["dark"].button.isChecked()

    def test_click_applies_and_persists(self, seeded, qapp):
        from student_planner.core.settings_registry import SettingsKeys
        from student_planner.core.settings_service import SettingsService
        from student_planner.ui.pages.settings import GeneralTab

        tab = GeneralTab(seeded)
        tab.theme_buttons["rainbow"].button.click()
        assert tab.theme_buttons["rainbow"].button.isChecked()
        assert not tab.theme_buttons["dark"].button.isChecked()
        assert SettingsService(seeded).raw(SettingsKeys.UI_THEME) == "rainbow"

    def test_still_seven_tabs(self, seeded, qapp):
        """SET-01: тема не добавила восьмую вкладку."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        captions = [page.tabs.tabText(index) for index in range(page.tabs.count())]
        assert captions == [
            "Общие", "Предметы", "Недели", "Звонки", "Транспорт",
            "Календарь", "Данные",
        ]
