"""Слой 1: сокращённые названия предметов (UI-14, SET-02, SUBJ-04).

Проверяется механика, а не конкретные подписи колледжа: стандартные наборы
используются как значения по умолчанию, но сами правила сокращения проверяются
на синтетических названиях (TEST-01, FIRST-09).

Покрытие:

* ``abbreviate`` — детерминированное сокращение и предел длины;
* два набора (``medium``/``short``) и их независимость от переопределений;
* сервис — включение, отключение, правка, сброс к стандартному набору;
* интерфейс — колонка «Сокращение», переключатель, подписи на страницах.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен")

from PySide6.QtWidgets import QApplication  # noqa: E402

from student_planner.core.settings_registry import (  # noqa: E402
    SettingsKeys,
    UiSection,
    default_registry,
)
from student_planner.core.settings_service import SettingsService  # noqa: E402
from student_planner.core.subject_abbreviations import (  # noqa: E402
    DEFAULT_MAX_LENGTH,
    STOCK_MEDIUM_NAMES,
    STOCK_MINIMAL_NAMES,
    abbreviate,
    parse_short_names,
    serialize_short_names,
    stock_names,
)
from student_planner.core.subject_names import SubjectNameService  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def seeded(db, qapp):
    from student_planner.core.seeding import Seeder

    Seeder(db).seed_all()
    return db


# ===========================================================================
# Автоматическое сокращение
# ===========================================================================
class TestAbbreviate:
    """Правила автоматического сокращения названий."""

    def test_short_name_is_untouched(self) -> None:
        """Короткое название сокращать не нужно: «История» остаётся собой."""
        assert abbreviate("История") == "История"

    def test_empty_name_stays_empty(self) -> None:
        assert abbreviate("   ") == ""

    def test_long_words_are_trimmed(self) -> None:
        result = abbreviate("Документирование программных средств")
        assert result != "Документирование программных средств"
        assert result.endswith("средств"), f"последнее слово должно читаться: {result}"
        assert "Докум." in result

    def test_code_is_preserved(self) -> None:
        """Код предмета — часть идентичности, его не уродуем."""
        result = abbreviate("МДК.01.02 Поддержка и тестирование программных модулей")
        assert result.startswith("МДК.01.02"), result

    def test_hyphenated_word_is_shortened_in_parts(self) -> None:
        assert abbreviate("Веб-разработка") == "Веб-разраб."

    def test_result_fits_limit(self) -> None:
        result = abbreviate("Иностранный язык в профессиональной деятельности")
        assert len(result) <= DEFAULT_MAX_LENGTH, f"подпись длиннее предела: {result}"
        assert result.endswith("…"), "обрезанная подпись помечается многоточием"

    def test_custom_limit(self) -> None:
        result = abbreviate("Психология общения", max_length=10)
        assert len(result) <= 10

    def test_idempotent_on_short_result(self) -> None:
        """Повторное сокращение короткой подписи её не портит."""
        once = abbreviate("Компьютерные сети")
        assert abbreviate(once) == once

    def test_minimal_set_is_shorter_than_medium(self) -> None:
        for name, medium in STOCK_MEDIUM_NAMES.items():
            minimal = STOCK_MINIMAL_NAMES[name]
            assert len(minimal) <= len(medium), (
                f"«{name}»: минимальное сокращение длиннее среднего"
            )


# ===========================================================================
# Наборы и таблица переопределений
# ===========================================================================
class TestShortNamesStorage:
    """Хранимый вид таблицы «Название=Сокращение» и выбор набора."""

    def test_parse_and_serialize_round_trip(self) -> None:
        mapping = {"Алгебра": ("Алг.", "Алг."), "Физика": ("Физ.", None)}
        text = serialize_short_names(mapping)
        assert parse_short_names(text) == mapping

    def test_variants_are_independent(self) -> None:
        """Среднее и минимальное значения хранятся отдельно и не смешиваются."""
        parsed = parse_short_names("Алгебра=Алг.|Алг-мин")
        assert parsed == {"Алгебра": ("Алг.", "Алг-мин")}

    def test_empty_side_means_default(self) -> None:
        """Пустая сторона — «вариант не переопределён»."""
        assert parse_short_names("Алгебра=|Мин") == {"Алгебра": (None, "Мин")}

    def test_dash_means_no_shortening(self) -> None:
        """Прочерк — осознанный отказ от сокращения в этом варианте."""
        assert parse_short_names("Алгебра=-|-") == {"Алгебра": ("", "")}

    def test_legacy_single_value_sets_both(self) -> None:
        """Строка прежнего вида «Название=Сокращение» задаёт оба варианта."""
        assert parse_short_names("Алгебра=Алг.") == {"Алгебра": ("Алг.", "Алг.")}

    def test_comments_and_broken_lines_are_ignored(self) -> None:
        text = "# комментарий\n\nАлгебра=Алг.|Алг\nстрока без равно"
        assert parse_short_names(text) == {"Алгебра": ("Алг.", "Алг")}

    def test_stock_style_lookup(self) -> None:
        assert stock_names("short") is STOCK_MINIMAL_NAMES
        assert stock_names("medium") is STOCK_MEDIUM_NAMES
        assert stock_names(None) is STOCK_MEDIUM_NAMES
        assert stock_names("неизвестный") is STOCK_MEDIUM_NAMES

    def test_stock_sets_cover_seed_subjects(self, seeded) -> None:
        """Стартовые наборы покрывают все предметы Прил. А в обоих стилях."""
        from student_planner.core.repositories import SubjectRepository

        for style in ("medium", "short"):
            names = SubjectNameService(seeded)
            names.set_style(style)
            service = SubjectNameService(seeded)
            for subject in SubjectRepository(seeded).all():
                caption = service.display(subject.name)
                assert caption, f"нет подписи для «{subject.name}»"
                assert len(caption) < len(subject.name), (
                    f"«{subject.name}» не сокращено ({caption})"
                )


# ===========================================================================
# Сервис сокращений и настройки
# ===========================================================================
class TestSubjectNameService:
    """SET-02: сокращения — обычная настройка реестра §30."""

    def test_registry_has_abbreviation_keys(self) -> None:
        registry = default_registry()
        for key in (
            SettingsKeys.SUBJECT_ABBREVIATIONS_ENABLED,
            SettingsKeys.SUBJECT_ABBREVIATIONS_STYLE,
            SettingsKeys.SUBJECT_SHORT_NAMES,
        ):
            spec = registry.get(key)
            assert spec.visible is True
            assert spec.section == UiSection.SUBJECTS
        enabled = registry.get(SettingsKeys.SUBJECT_ABBREVIATIONS_ENABLED)
        assert enabled.default == "1", "по умолчанию сокращения включены"
        style = registry.get(SettingsKeys.SUBJECT_ABBREVIATIONS_STYLE)
        assert style.default == "medium"
        assert style.choices == ("medium", "short")

    def test_enabled_by_default(self, seeded) -> None:
        assert SubjectNameService(seeded).enabled is True

    def test_default_style_is_medium(self, seeded) -> None:
        service = SubjectNameService(seeded)
        assert service.style == "medium"
        assert (
            service.display("Физическая культура")
            == STOCK_MEDIUM_NAMES["Физическая культура"]
        )

    def test_style_switch_changes_caption(self, seeded) -> None:
        SubjectNameService(seeded).set_style("short")
        service = SubjectNameService(seeded)
        assert service.style == "short"
        assert (
            service.display("Физическая культура")
            == STOCK_MINIMAL_NAMES["Физическая культура"]
        )

    def test_disabled_shows_full_name(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_enabled(False)
        again = SubjectNameService(seeded)
        assert again.enabled is False
        assert again.display("Физическая культура") == "Физическая культура"

    def test_custom_short_name_is_used(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_variant("Физическая культура", "medium", "Физра")
        assert SubjectNameService(seeded).display("Физическая культура") == "Физра"

    def test_variants_stored_independently(self, seeded) -> None:
        """Среднее и минимальное правятся по отдельности (UI-14)."""
        names = SubjectNameService(seeded)
        names.set_variant("Физическая культура", "medium", "Физра")
        names.set_variant("Физическая культура", "short", "Ф")
        service = SubjectNameService(seeded)
        assert service.medium("Физическая культура") == "Физра"
        assert service.minimal("Физическая культура") == "Ф"

    def test_setting_one_variant_keeps_other(self, seeded) -> None:
        """Правка минимального варианта не затирает среднее."""
        names = SubjectNameService(seeded)
        names.set_variant("Физическая культура", "medium", "Физра")
        names.set_variant("Физическая культура", "short", "Ф")
        names.set_variant("Физическая культура", "short", "Физ")
        assert SubjectNameService(seeded).medium("Физическая культура") == "Физра"

    def test_override_survives_style_change(self, seeded) -> None:
        """Переопределение одного варианта не мешает другому."""
        names = SubjectNameService(seeded)
        names.set_variant("Физическая культура", "medium", "Физра")
        names.set_style("short")
        service = SubjectNameService(seeded)
        assert service.display("Физическая культура") == STOCK_MINIMAL_NAMES[
            "Физическая культура"
        ]

    def test_empty_override_disables_single_subject(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_variant("Компьютерные сети", "medium", "")
        assert (
            SubjectNameService(seeded).display("Компьютерные сети")
            == "Компьютерные сети"
        )
        # Минимальный вариант остался из набора.
        assert (
            SubjectNameService(seeded).minimal("Компьютерные сети")
            == STOCK_MINIMAL_NAMES["Компьютерные сети"]
        )

    def test_unknown_subject_is_abbreviated(self, seeded) -> None:
        """Предмет вне таблицы сокращается автоматически, а не пропадает."""
        names = SubjectNameService(seeded)
        caption = names.display("Электротехника и электроника")
        assert caption and caption != "Электротехника и электроника"

    def test_reset_removes_overrides(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_variants("Физическая культура", "Ф", "Ф")
        names.reset_to_stock()
        again = SubjectNameService(seeded)
        assert again.table.overrides == {}
        assert (
            again.display("Физическая культура")
            == STOCK_MEDIUM_NAMES["Физическая культура"]
        )

    def test_effective_merges_stock_and_overrides(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_variants("Физическая культура", "Физра", "Ф")
        again = SubjectNameService(seeded)
        medium = again.table.effective("medium")
        minimal = again.table.effective("short")
        assert medium["Физическая культура"] == "Физра"
        assert minimal["Физическая культура"] == "Ф"
        assert medium["Классный час"] == STOCK_MEDIUM_NAMES["Классный час"]

    def test_rename_moves_overrides(self, seeded) -> None:
        """Переименование предмета переносит сокращения на новое название."""
        names = SubjectNameService(seeded)
        names.set_variants("Физическая культура", "Физра", "Ф")
        names.rename("Физическая культура", "Физкультура и спорт")
        again = SubjectNameService(seeded)
        assert again.medium("Физкультура и спорт") == "Физра"
        assert again.minimal("Физкультура и спорт") == "Ф"

    def test_smart_limits_long_caption(self, seeded) -> None:
        """В узких местах подпись режется даже при выключенных сокращениях."""
        names = SubjectNameService(seeded)
        names.set_enabled(False)
        again = SubjectNameService(seeded)
        caption = again.smart(
            "Иностранный язык в профессиональной деятельности", limit=14
        )
        assert len(caption) <= 14, caption
        assert caption.endswith("…")

    def test_smart_keeps_short_caption(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_enabled(False)
        again = SubjectNameService(seeded)
        assert again.smart("История", limit=14) == "История"

    def test_settings_persisted_in_db(self, seeded) -> None:
        names = SubjectNameService(seeded)
        names.set_enabled(False)
        names.set_style("short")
        settings = SettingsService(seeded)
        assert settings.raw(SettingsKeys.SUBJECT_ABBREVIATIONS_ENABLED) == "0"
        assert settings.raw(SettingsKeys.SUBJECT_ABBREVIATIONS_STYLE) == "short"


# ===========================================================================
# Интерфейс
# ===========================================================================
class TestAbbreviationsUi:
    """UI-14: переключатель и правка сокращений в «Настройки → Предметы»."""

    def test_subjects_tab_has_short_column(self, seeded) -> None:
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            headers = [
                tab.table.horizontalHeaderItem(index).text()
                for index in range(tab.table.columnCount())
            ]
            assert "Среднее сокращение" in headers, headers
            assert "Минимальное сокращение" in headers, headers
            assert tab.table.rowCount() > 0
            # В каждой строке оба варианта заполнены — они независимы.
            for row in range(tab.table.rowCount()):
                assert tab.table.item(row, tab.MEDIUM_COLUMN).text(), row
                assert tab.table.item(row, tab.MINIMAL_COLUMN).text(), row
        finally:
            page.close()

    def test_toggle_switch_saves_setting(self, seeded) -> None:
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            assert tab.short_enabled_check.isChecked() is True
            tab.short_enabled_check.setChecked(False)
            assert SubjectNameService(seeded).enabled is False, (
                "UI-14: переключатель должен сохраняться в настройках"
            )
            for column in tab.SHORT_COLUMNS:
                assert tab.table.isColumnHidden(column), (
                    "UI-14: при выключении обе колонки сокращений скрываются"
                )
            assert tab.short_style_combo.isEnabled() is False
            tab.short_enabled_check.setChecked(True)
            assert SubjectNameService(seeded).enabled is True
            assert tab.short_style_combo.isEnabled() is True
        finally:
            page.close()

    def test_style_switch_saves_setting(self, seeded) -> None:
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            index = tab.short_style_combo.findData("short")
            tab.short_style_combo.setCurrentIndex(index)
            assert SubjectNameService(seeded).style == "short", (
                "UI-14: действующий вариант должен сохраняться"
            )
            captions = {
                tab.table.item(row, tab.MINIMAL_COLUMN).text()
                for row in range(tab.table.rowCount())
            }
            assert STOCK_MINIMAL_NAMES["Компьютерные сети"] in captions, captions
        finally:
            page.close()

    def test_editing_medium_cell_keeps_minimal(self, seeded) -> None:
        """UI-14: правка среднего варианта не меняет минимальный."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            name = tab.table.item(0, 0).text()
            minimal_before = tab.table.item(0, tab.MINIMAL_COLUMN).text()
            tab.table.item(0, tab.MEDIUM_COLUMN).setText("Сред.")
            service = SubjectNameService(seeded)
            assert service.medium(name) == "Сред.", (
                "UI-14: правка среднего варианта должна сохраняться"
            )
            assert service.minimal(name) == minimal_before, (
                "UI-14: минимальный вариант не должен меняться"
            )
        finally:
            page.close()

    def test_editing_minimal_cell_keeps_medium(self, seeded) -> None:
        """UI-14: правка минимального варианта не меняет средний."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            name = tab.table.item(0, 0).text()
            medium_before = tab.table.item(0, tab.MEDIUM_COLUMN).text()
            tab.table.item(0, tab.MINIMAL_COLUMN).setText("Мин.")
            service = SubjectNameService(seeded)
            assert service.minimal(name) == "Мин.", (
                "UI-14: правка минимального варианта должна сохраняться"
            )
            assert service.medium(name) == medium_before, (
                "UI-14: средний вариант не должен меняться"
            )
        finally:
            page.close()

    def test_clearing_cell_returns_to_stock(self, seeded) -> None:
        """Пустая ячейка — «вариант из набора», а не «полное название»."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            name = tab.table.item(0, 0).text()
            tab.table.item(0, tab.MEDIUM_COLUMN).setText("Своё")
            tab.table.item(0, tab.MEDIUM_COLUMN).setText("")
            assert SubjectNameService(seeded).medium(name) == STOCK_MEDIUM_NAMES.get(
                name, SubjectNameService(seeded).medium(name)
            )
        finally:
            page.close()

    def test_dash_cell_shows_full_name(self, seeded) -> None:
        """Прочерк — осознанный отказ от сокращения этого предмета."""
        from student_planner.ui.pages.settings import SettingsPage

        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            name = tab.table.item(0, 0).text()
            tab.table.item(0, tab.MEDIUM_COLUMN).setText("-")
            assert SubjectNameService(seeded).display(name) == name
        finally:
            page.close()

    def test_fill_button_writes_both_variants(self, seeded, monkeypatch) -> None:
        from PySide6.QtWidgets import QMessageBox

        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SettingsPage

        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
        )
        page = SettingsPage(seeded)
        try:
            tab = page.subjects_tab
            tab.fill_short_names()
            service = SubjectNameService(seeded)
            for subject in SubjectRepository(seeded).all():
                medium, minimal = service.table.overrides.get(
                    subject.name, (None, None)
                )
                assert medium, subject.name
                assert minimal, subject.name
        finally:
            page.close()

    def test_subject_dialog_has_two_short_fields(self, seeded) -> None:
        """UI-14: в диалоге предмета оба варианта задаются отдельно."""
        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SubjectDialog

        subject = SubjectRepository(seeded).all()[0]
        dialog = SubjectDialog(seeded, subject=subject)
        try:
            service = SubjectNameService(seeded)
            medium, minimal = service.variants(subject.name)
            assert dialog.medium_edit.text() == SubjectDialog._short_edit_text(medium)
            assert dialog.minimal_edit.text() == SubjectDialog._short_edit_text(minimal)
        finally:
            dialog.close()

    def test_subject_dialog_saves_both_variants(self, seeded) -> None:
        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SubjectDialog

        subject = SubjectRepository(seeded).all()[0]
        dialog = SubjectDialog(seeded, subject=subject)
        try:
            dialog.medium_edit.setText("Сред-диалог")
            dialog.minimal_edit.setText("МИН")
            assert dialog.apply()
            service = SubjectNameService(seeded)
            assert service.medium(subject.name) == "Сред-диалог"
            assert service.minimal(subject.name) == "МИН"
        finally:
            dialog.close()

    def test_new_subject_gets_suggested_variants(self, seeded) -> None:
        """При вводе названия диалог предлагает оба варианта сразу.

        Для однословного названия варианты совпадают — аббревиатура из одной
        буквы бесполезна. Поэтому проверка идёт на многословном названии.
        """
        from student_planner.ui.pages.settings import SubjectDialog

        dialog = SubjectDialog(seeded)
        try:
            name = "Электротехника и электроника"
            dialog.name_edit.setText(name)
            dialog._on_name_edited(name)
            assert dialog.medium_edit.text()
            assert dialog.minimal_edit.text()
            assert dialog.medium_edit.text() != dialog.minimal_edit.text()
            assert len(dialog.minimal_edit.text()) <= len(dialog.medium_edit.text())
        finally:
            dialog.close()

    def test_single_word_subject_keeps_same_variants(self, seeded) -> None:
        """Однословное название не сокращается до одной буквы."""
        from student_planner.ui.pages.settings import SubjectDialog

        dialog = SubjectDialog(seeded)
        try:
            dialog.name_edit.setText("Электротехника")
            dialog._on_name_edited("Электротехника")
            assert len(dialog.minimal_edit.text()) > 1
        finally:
            dialog.close()

    def test_rename_moves_short_names(self, seeded) -> None:
        """Переименование предмета не теряет заданные сокращения."""
        from student_planner.core.repositories import SubjectRepository
        from student_planner.ui.pages.settings import SubjectDialog

        subject = SubjectRepository(seeded).all()[0]
        dialog = SubjectDialog(seeded, subject=subject)
        try:
            dialog.medium_edit.setText("Было-сред")
            dialog.minimal_edit.setText("Было-мин")
            assert dialog.apply()
            dialog2 = SubjectDialog(seeded, subject=subject)
            try:
                dialog2.name_edit.setText("Переименованный")
                assert dialog2.apply()
            finally:
                dialog2.close()
            service = SubjectNameService(seeded)
            assert service.medium("Переименованный") == "Было-сред"
            assert service.minimal("Переименованный") == "Было-мин"
        finally:
            dialog.close()

    def test_schedule_uses_short_caption(self, seeded) -> None:
        """UI-14: карточка пары показывает сокращённое название."""
        from datetime import date

        from student_planner.ui.pages.schedule import (
            SUBJECT_CAPTION_LIMIT,
            LessonCard,
            SchedulePage,
        )

        page = SchedulePage(seeded)
        try:
            page.set_date(date(2026, 9, 7))
            page.refresh()
            cards = page.days_host.findChildren(LessonCard)
            assert cards, "на дату должны быть пары"
            names = SubjectNameService(seeded)
            for card in cards:
                expected = names.smart(
                    card.lesson.subject_name, limit=SUBJECT_CAPTION_LIMIT
                )
                assert card.subject_label.text() == expected, (
                    f"UI-14: ожидалось «{expected}», "
                    f"получено «{card.subject_label.text()}»"
                )
        finally:
            page.close()

    def test_schedule_follows_style_switch(self, seeded) -> None:
        """Смена набора видна на карточках без перезапуска."""
        from datetime import date

        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        page = SchedulePage(seeded)
        try:
            page.set_date(date(2026, 9, 7))
            page.refresh()
            before = {
                card.subject_label.text()
                for card in page.days_host.findChildren(LessonCard)
            }
            SubjectNameService(seeded).set_style("short")
            page.refresh()
            after = {
                card.subject_label.text()
                for card in page.days_host.findChildren(LessonCard)
            }
            assert before != after, "UI-14: набор сокращений не применился"
            assert STOCK_MINIMAL_NAMES["Разработка программных модулей"] in after
        finally:
            page.close()

    def test_schedule_uses_full_names_when_disabled(self, seeded) -> None:
        """Выключенные сокращения возвращают полные названия на карточках."""
        from datetime import date

        from student_planner.ui.pages.schedule import LessonCard, SchedulePage

        SubjectNameService(seeded).set_enabled(False)
        page = SchedulePage(seeded)
        try:
            page.set_date(date(2026, 9, 7))
            page.refresh()
            cards = page.days_host.findChildren(LessonCard)
            assert cards
            # «Классный час» — первая пара понедельника стартового набора.
            captions = {card.subject_label.text() for card in cards}
            assert "Классный час" in captions, captions
        finally:
            page.close()

    def test_homework_rows_use_short_caption(self, seeded) -> None:
        """UI-14: список заданий тоже показывает сокращённое название."""
        from datetime import date

        from PySide6.QtWidgets import QLabel

        from student_planner.core.transport_repositories import HomeworkRepository
        from student_planner.ui.pages.homework import HomeworkPage, HomeworkRowWidget

        subject_id = int(seeded.scalar("SELECT id FROM subjects ORDER BY name LIMIT 1"))
        subject_name = str(
            seeded.scalar("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        )
        HomeworkRepository(seeded).create(
            subject_id=subject_id,
            due_date=date(2026, 10, 25),
            description="Проверка сокращений",
        )
        page = HomeworkPage(seeded)
        try:
            page.refresh()
            rows = page.findChildren(HomeworkRowWidget)
            assert rows, "должна появиться строка задания"
            captions = {label.text() for label in rows[0].findChildren(QLabel)}
            expected = SubjectNameService(seeded).display(subject_name)
            assert expected in captions, (
                f"UI-14: ожидалась подпись «{expected}», есть {captions}"
            )
        finally:
            page.close()

    def test_widgets_panel_uses_short_caption(self, seeded) -> None:
        """UI-14: правая панель показывает сокращённые названия."""
        from datetime import date

        from PySide6.QtWidgets import QLabel

        from student_planner.core.transport_repositories import HomeworkRepository
        from student_planner.ui.widgets_panel import HomeworkWidget

        subject_id = int(seeded.scalar("SELECT id FROM subjects ORDER BY name LIMIT 1"))
        subject_name = str(
            seeded.scalar("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        )
        HomeworkRepository(seeded).create(
            subject_id=subject_id,
            due_date=date(2026, 10, 25),
            description="Панель",
        )
        widget = HomeworkWidget(seeded)
        try:
            widget.refresh()
            captions = {label.text() for label in widget.findChildren(QLabel)}
            expected = SubjectNameService(seeded).smart(
                subject_name, limit=HomeworkWidget.SUBJECT_CAPTION_LIMIT
            )
            assert expected in captions, (
                f"UI-14: ожидалась подпись «{expected}», есть {captions}"
            )
        finally:
            widget.close()

    def test_exam_page_uses_short_caption(self, seeded) -> None:
        """UI-14: страница испытаний показывает сокращённое название."""
        from datetime import date

        from student_planner.core.exam_repository import ExamRepository
        from student_planner.ui.pages.exams import ExamRowWidget, ExamsPage

        subject_id = int(seeded.scalar("SELECT id FROM subjects ORDER BY name LIMIT 1"))
        subject_name = str(
            seeded.scalar("SELECT name FROM subjects WHERE id = ?", (subject_id,))
        )
        ExamRepository(seeded).create(
            subject_id=subject_id, when=date(2026, 12, 20),
        )
        page = ExamsPage(seeded)
        try:
            page.refresh()
            rows = page.findChildren(ExamRowWidget)
            assert rows, "должна появиться строка испытания"
            # Испытание по этому предмету должно быть найдено среди строк:
            # берём строку, а не первую, потому что стартовый набор может
            # содержать другие записи.
            row = next(
                item for item in rows
                if item.row.exam.subject_id == subject_id
            )
            expected = SubjectNameService(seeded).display(subject_name)
            assert row.subject_label.text() == expected, (
                f"UI-14: ожидалось «{expected}», "
                f"получено «{row.subject_label.text()}»"
            )
        finally:
            page.close()
