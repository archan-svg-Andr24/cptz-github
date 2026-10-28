"""Страница «Расписание» (§24: SCH-02…SCH-19).

Три режима (текущая неделя, следующая неделя, выбранная дата), карточки занятий
со статусами, кнопки отмены/замены/добавления, сброс изменений даты, переход в
редактор сетки и предупреждение о сиротских оверрайдах.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core import clock
from ...core.dates import (
    MONTH_NAMES_NOMINATIVE,
    WEEKDAY_NAMES,
    add_days,
    format_display,
    monday_of,
    week_dates,
)
from ...core.day_resolution import DayResolver
from ...core.errors import AppError
from ...core.models import LessonStatus
from ...core.schedule_service import CalendarService, OverrideService
from ..dialogs import (
    AddLessonDialog,
    CancelLessonDialog,
    ReplaceLessonDialog,
)
from ..grid_editor import GridEditorDialog
from ..theme import COLORS
from ..widgets import (
    Card,
    EmptyState,
    SectionHeader,
    Separator,
    WarningBanner,
    status_badge,
)

log = logging.getLogger(__name__)

#: SCH-02: три режима отображения. Режимов «шаблон недели» нет ([У-22]).
MODES = (
    ("selected", "Выбранная дата"),
    ("current", "Текущая неделя"),
    ("next", "Следующая неделя"),
)


class LessonCard(QFrame):
    """SCH-04/SCH-11: карточка занятия с временем, предметом, статусом, бейджем ДЗ."""

    cancel_requested = Signal(int, int)   # profile_id, slot_no
    replace_requested = Signal(int, int)
    reset_requested = Signal(int)         # override_id
    homework_requested = Signal()

    def __init__(self, lesson, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lesson = lesson
        self.setObjectName("Card")
        if lesson.status == LessonStatus.CANCELLED:
            self.setStyleSheet(
                f"QFrame#Card {{ background-color: {COLORS['cancelled_bg']}; "
                f"border: 1px solid {COLORS['cancelled']}; border-radius: 6px; }}"
            )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(12)

        # Время и номер пары.
        time_box = QVBoxLayout()
        time_box.setSpacing(1)
        self.time_label = QLabel(lesson.time_range)
        self.time_label.setObjectName("Subtitle")
        time_box.addWidget(self.time_label)
        self.slot_label = QLabel(f"блок {lesson.slot_no}")
        self.slot_label.setObjectName("Small")
        time_box.addWidget(self.slot_label)
        holder = QWidget()
        holder.setLayout(time_box)
        holder.setFixedWidth(94)
        layout.addWidget(holder)

        # Предмет, преподаватель, кабинет.
        text_box = QVBoxLayout()
        text_box.setSpacing(1)
        self.subject_label = QLabel(lesson.subject_name or "—")
        self.subject_label.setObjectName("Subtitle")
        self.subject_label.setWordWrap(True)
        if lesson.status == LessonStatus.CANCELLED:
            self.subject_label.setStyleSheet(
                f"color: {COLORS['status_cancelled']}; text-decoration: line-through;"
            )
        text_box.addWidget(self.subject_label)

        details = " · ".join(
            part for part in (lesson.teacher, lesson.room) if part
        )
        self.details_label = QLabel(details or " ")
        self.details_label.setObjectName("Small")
        self.details_label.setWordWrap(True)
        text_box.addWidget(self.details_label)

        if lesson.comment:
            comment = QLabel(lesson.comment)
            comment.setObjectName("Small")
            comment.setWordWrap(True)
            comment.setStyleSheet(f"color: {COLORS['warning_text']};")
            text_box.addWidget(comment)

        layout.addLayout(text_box, 1)

        # Статус и бейдж ДЗ.
        badges = QVBoxLayout()
        badges.setSpacing(4)
        badges.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        badges.addWidget(status_badge(lesson.status), 0, Qt.AlignmentFlag.AlignRight)

        if lesson.homework_count:
            badge = QPushButton(
                f"Заданий: {lesson.homework_count}"
                if lesson.homework_count > 1 else "Задание"
            )
            badge.setObjectName("BadgeAccent")
            badge.setCursor(Qt.CursorShape.PointingHandCursor)
            badge.setToolTip("Открыть домашние задания")
            badge.clicked.connect(self.homework_requested)
            badges.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(badges)

        # Действия. Набор кнопок зависит от состояния пары: показываем только
        # осмысленные действия. Раньше «Заменить» и «Убрать изменение» висели
        # одновременно, и блок пары вырастал с 62 до 86 px.
        actions = QVBoxLayout()
        actions.setSpacing(4)

        # Изменение этой даты внесено и его можно снять (OVR-11). Для пары,
        # добавленной оверрайдом ``add``, «Убрать» не нужно: её удаляет
        # «Отменить» (OVR-04), иначе вышли бы две кнопки об одном и том же.
        has_change = (
            lesson.override_id is not None
            and lesson.status in (LessonStatus.CANCELLED, LessonStatus.REPLACED)
        )

        self.cancel_button = QPushButton("Отменить")
        self.cancel_button.setObjectName("Flat")
        self.cancel_button.clicked.connect(
            lambda: self.cancel_requested.emit(self.lesson.profile_id, self.lesson.slot_no)
        )
        # На отменённой паре кнопка уже не нужна, на заменённой — бессмысленна:
        # отменять нечего, пара и так изменена.
        self.cancel_button.setVisible(not has_change)
        self.cancel_button.setEnabled(
            lesson.status in (LessonStatus.PLANNED, LessonStatus.ADDED)
        )
        actions.addWidget(self.cancel_button)

        self.replace_button = QPushButton("Заменить")
        self.replace_button.setObjectName("Flat")
        self.replace_button.clicked.connect(
            lambda: self.replace_requested.emit(self.lesson.profile_id, self.lesson.slot_no)
        )
        # SCH-18/OVR-05: заменять можно и отменённую пару — это путь «убрал
        # одну, поставил другую»: cancel снимается, ставится replace.
        self.replace_button.setEnabled(True)
        # На заменённой паре второго «Заменить» не показываем: замену снимают
        # через «Убрать изменение», иначе кнопки дублируют друг друга.
        self.replace_button.setVisible(lesson.status != LessonStatus.REPLACED)
        actions.addWidget(self.replace_button)

        # OVR-11: «Убрать изменение» возвращает пару к состоянию расписания.
        self.undo_button = QPushButton("↺ Убрать изменение")
        self.undo_button.setObjectName("Danger")
        self.undo_button.setToolTip(
            "Снять изменение этой даты: отмена вернёт пару в расписание, "
            "замена — предмет из сетки. Сама сетка не меняется."
        )
        self.undo_button.setVisible(has_change)
        self.undo_button.clicked.connect(
            lambda: self.reset_requested.emit(self.lesson.override_id)
        )
        actions.addWidget(self.undo_button)
        layout.addLayout(actions)


class DayColumn(QWidget):
    """Колонка дня недели: заголовок с датой, карточки занятий."""

    empty_caption = "Занятий нет"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)

        self.header = QLabel()
        self.header.setObjectName("Subtitle")
        self.layout_.addWidget(self.header)

        self.subheader = QLabel()
        self.subheader.setObjectName("Small")
        self.layout_.addWidget(self.subheader)

        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        self.layout_.addLayout(self.body)
        self.layout_.addStretch(1)

    def clear_body(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class SchedulePage(QWidget):
    """SCH-09/SCH-10: расписание с тремя режимами и правкой одной даты."""

    changed = Signal()
    # Дату сменили внутри страницы (стрелки, «Сегодня», режим). Главное окно
    # обязано узнать об этом, иначе мини-календарь и бейдж типа недели слева
    # продолжают показывать прежнюю дату — расписание живёт своей жизнью.
    date_changed = Signal(object)  # date

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._date: date = clock.today()
        self._mode = "selected"
        self._warnings: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self.header = SectionHeader("Расписание")
        outer.addWidget(self.header)

        self.grid_button = QPushButton("Редактировать сетку недели…")
        self.grid_button.setObjectName("Primary")
        self.grid_button.clicked.connect(self.open_grid_editor)
        self.header.add_action(self.grid_button)

        # ------------------------------------------------- переключатель режимов
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.mode_combo = QComboBox()
        for key, caption in MODES:
            self.mode_combo.addItem(caption, key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo)

        self.prev_button = QPushButton("‹")
        self.prev_button.setFixedWidth(34)
        self.prev_button.clicked.connect(lambda: self.shift_date(-1))
        controls.addWidget(self.prev_button)

        self.date_label = QLabel()
        self.date_label.setObjectName("Subtitle")
        self.date_label.setMinimumWidth(240)
        controls.addWidget(self.date_label)

        self.next_button = QPushButton("›")
        self.next_button.setFixedWidth(34)
        self.next_button.clicked.connect(lambda: self.shift_date(1))
        controls.addWidget(self.next_button)

        self.today_button = QPushButton("Сегодня")
        self.today_button.clicked.connect(self.go_today)
        controls.addWidget(self.today_button)

        # SCH-11/SCH-18: отменённые пары по умолчанию скрыты — после «Отменить»
        # занятие должно исчезать из дня, а не оставаться зачёркнутым.
        self.show_cancelled = QCheckBox("Показывать отменённые")
        self.show_cancelled.setToolTip(
            "Отменённая пара остаётся в этот день, но по умолчанию не показывается: "
            "включите, чтобы увидеть, что именно отменено и почему (SCH-18)."
        )
        self.show_cancelled.toggled.connect(self._on_show_cancelled)
        controls.addWidget(self.show_cancelled)

        controls.addStretch(1)
        self.week_badge_holder = QHBoxLayout()
        controls.addLayout(self.week_badge_holder)
        outer.addLayout(controls)

        # ------------------------------------------------------- предупреждения
        self.warning = WarningBanner()
        outer.addWidget(self.warning)

        # --------------------------------------------------------- область дней
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.days_host = QWidget()
        self.days_layout = QHBoxLayout(self.days_host)
        self.days_layout.setContentsMargins(0, 0, 0, 0)
        self.days_layout.setSpacing(10)
        self.scroll.setWidget(self.days_host)
        outer.addWidget(self.scroll, 1)

        self.empty = EmptyState(
            "Занятий нет", action_text="Редактировать сетку недели"
        )
        self.empty.action_clicked.connect(self.open_grid_editor)
        # Пустое состояние занимает всё место, освободившееся от области дней:
        # с весом 0 оно прижималось к низу страницы, и подпись «Занятий нет»
        # оказывалась в середине пустого экрана, отдельно от заголовка.
        outer.addWidget(self.empty, 1)

        self.refresh()

    # ------------------------------------------------------------------ данные
    @property
    def date(self) -> date:
        return self._date

    def set_date(self, value: date) -> None:
        """Установить дату извне (главное окно). Сигнал не испускается.

        Спутник ``date_changed`` нужен для обратного направления: когда дату
        меняют внутри страницы. Здесь дата приходит уже от окна, и повторный
        сигнал вызвал бы рекурсию.
        """
        self._date = value
        self.refresh()

    def shift_date(self, days: int) -> None:
        if self._mode == "current":
            self._date = add_days(self._date, 7 * days)
        elif self._mode == "next":
            self._date = add_days(self._date, 7 * days)
        else:
            self._date = add_days(self._date, days)
        self.refresh()
        self.date_changed.emit(self._date)

    def go_today(self) -> None:
        """Кнопка «Сегодня» внутри страницы."""
        self._date = clock.today()
        self.refresh()
        self.date_changed.emit(self._date)

    def _on_mode_changed(self) -> None:
        self._mode = self.mode_combo.currentData()
        today = clock.today()
        if self._mode == "current":
            self._date = today
        elif self._mode == "next":
            self._date = add_days(today, 7)
        self.refresh()
        self.date_changed.emit(self._date)

    def _visible_days(self) -> list[date]:
        """SCH-02: текущая неделя / следующая неделя / выбранная дата."""
        if self._mode in ("current", "next"):
            return week_dates(monday_of(self._date))
        return [self._date]

    def _on_show_cancelled(self, _checked: bool) -> None:
        """SCH-18: переключатель показа отменённых пар."""
        self.refresh()

    # ------------------------------------------------------------------ отрисовка
    def refresh(self) -> None:
        resolver = DayResolver(self.db)
        overrides = OverrideService(self.db)
        calendar = CalendarService(self.db)

        while self.days_layout.count():
            item = self.days_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        days = self._visible_days()
        week_type = resolver.week_type(self._date)
        self._update_header(days, week_type)

        any_lesson = False
        for day in days:
            column, has_lessons = self._build_day(resolver, overrides, calendar, day)
            self.days_layout.addWidget(column, 1)
            any_lesson = any_lesson or has_lessons

        self.empty.setVisible(not any_lesson)
        self.scroll.setVisible(any_lesson)
        self._update_warnings(overrides)

    def _update_header(self, days: list[date], week_type: str | None) -> None:
        from ..widgets import Badge

        while self.week_badge_holder.count():
            item = self.week_badge_holder.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if week_type:
            self.week_badge_holder.addWidget(
                Badge("Верхняя неделя" if week_type == "upper" else "Нижняя неделя",
                      "accent")
            )

        if len(days) == 1:
            value = days[0]
            self.date_label.setText(
                f"{WEEKDAY_NAMES[value.isoweekday()]}, {format_display(value)}"
            )
        else:
            first, last = days[0], days[-1]
            self.date_label.setText(
                f"{first.day} {MONTH_NAMES_NOMINATIVE[first.month].lower()} — "
                f"{last.day} {MONTH_NAMES_NOMINATIVE[last.month].lower()} {last.year}"
            )

    def _build_day(self, resolver, overrides, calendar, day: date) -> tuple[QWidget, bool]:
        column = DayColumn()
        column.header.setText(
            f"{WEEKDAY_NAMES[day.isoweekday()]} {day.strftime('%d.%m')}"
        )
        if day == clock.today():
            column.header.setStyleSheet(f"color: {COLORS['accent_hover']};")
            column.subheader.setText("сегодня")
        else:
            column.subheader.setText("")

        result = resolver.resolve(day)

        # CAL-09: в период без занятий показываем название и причину.
        period = calendar.period_at(day)
        if period is not None and period.no_classes:
            card = Card(period.title)
            reason = QLabel(f"{period.kind_caption}: занятий нет")
            reason.setObjectName("Muted")
            reason.setWordWrap(True)
            card.add_widget(reason)
            column.body.addWidget(card)
            return column, False

        if not result.lessons:
            label = QLabel("Занятий нет")
            label.setObjectName("Empty")
            column.body.addWidget(label)
            return column, False

        # SCH-18: отменённые пары не занимают место в дне, пока их не попросят
        # показать. Раньше карточка оставалась зачёркнутой, и «Отменить»
        # выглядело как «ничего не произошло».
        visible = [
            lesson for lesson in result.lessons
            if self.show_cancelled.isChecked()
            or lesson.status != LessonStatus.CANCELLED
        ]
        hidden = len(result.lessons) - len(visible)
        if hidden and not self.show_cancelled.isChecked():
            note = QLabel(
                f"Отменено пар: {hidden} — включите «Показывать отменённые», "
                "чтобы увидеть (SCH-18)."
            )
            note.setObjectName("Small")
            note.setWordWrap(True)
            column.body.addWidget(note)
        if not visible:
            label = QLabel("Занятий нет")
            label.setObjectName("Empty")
            column.body.addWidget(label)
            return column, False

        for lesson in visible:
            card = LessonCard(lesson)
            card.cancel_requested.connect(
                lambda profile_id, slot_no, value=day: self.cancel_lesson(
                    value, profile_id, slot_no
                )
            )
            card.replace_requested.connect(
                lambda profile_id, slot_no, value=day: self.replace_lesson(
                    value, profile_id, slot_no
                )
            )
            card.homework_requested.connect(self._open_homework)
            card.reset_requested.connect(self.undo_override)
            column.body.addWidget(card)

        add_button = QPushButton("Добавить занятие…")
        add_button.setObjectName("Flat")
        add_button.clicked.connect(lambda _checked=False, value=day: self.add_lesson(value))
        column.body.addWidget(add_button)
        return column, True

    def _update_warnings(self, overrides) -> None:
        warnings = overrides.warnings_for_date(self._date)
        if not warnings:
            self.warning.hide()
            return

        self.warning.clear_actions()
        self.warning.set_message(
            "Изменения ссылаются на занятия, которых больше нет в сетке:\n"
            + "\n".join(warnings)
        )
        self.warning.add_action("Удалить изменение", self._delete_orphans)
        self.warning.show()

    # ------------------------------------------------------------------ действия
    def cancel_lesson(self, day: date, profile_id: int, slot_no: int) -> None:
        lesson = self._find_lesson(day, profile_id, slot_no)
        dialog = CancelLessonDialog(
            self.db, day, profile_id, slot_no,
            lesson.subject_name if lesson else f"блок {slot_no}", self,
        )
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def replace_lesson(self, day: date, profile_id: int, slot_no: int) -> None:
        lesson = self._find_lesson(day, profile_id, slot_no)
        caption = lesson.subject_name if lesson else f"блок {slot_no}"
        # OVR-01/OVR-02: пара, добавленная оверрайдом ``add``, живёт только в
        # этой дате — в сетке её нет. Замена создала бы ``replace`` на пустом
        # слоте, и ALG-10 тут же сочла бы его сиротским. Правим сам ``add``.
        override_id = None
        if lesson is not None and lesson.status == LessonStatus.ADDED:
            override_id = lesson.override_id
        dialog = ReplaceLessonDialog(
            self.db, day, profile_id, slot_no, caption, self,
            override_id=override_id,
            subject_id=lesson.subject.id if lesson and lesson.subject else None,
        )
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def add_lesson(self, day: date) -> None:
        from ...core.repositories import BellRepository

        result = DayResolver(self.db).resolve(day)
        if result.profile is None:
            self._message("Для этого дня нет профиля звонков (BELL-18).")
            return
        profile_id = result.profile.id
        slot_no = self._first_free_slot(day, profile_id)
        if slot_no is None:
            self._message("Свободных блоков нет: все заняты (OVR-08).")
            return

        # OVR-07: список всех блоков дня, чтобы выбрать любой, а не только
        # первый свободный. Отменённые блоки помечаются как свободные.
        by_slot = {lesson.slot_no: lesson for lesson in result.lessons}
        slots: list[tuple[int, str, bool]] = []
        for slot in BellRepository(self.db).profile(profile_id).slots:
            lesson = by_slot.get(slot.slot_no)
            free = lesson is None or lesson.status == LessonStatus.CANCELLED
            text = slot.display_name or slot.time_caption or ""
            slots.append((slot.slot_no, text, not free))

        dialog = AddLessonDialog(
            self.db, day, profile_id, slot_no, f"блок {slot_no}", self, slots=slots
        )
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    def undo_override(self, override_id: int) -> None:
        """OVR-11: убрать изменение этой даты — пара возвращается к сетке.

        Отмена снимается, и пара снова показывается как обычно; замена
        снимается, и возвращается предмет из шаблона недели. Сетка не
        меняется: TPL-08 правит только редактор сетки.
        """
        if override_id is None:
            return
        item = OverrideService(self.db).overrides.by_id(override_id)
        if item is None:
            self._message("Изменение уже удалено.")
            self.refresh()
            return
        kind = "отмену" if str(item.override_type) == "cancel" else "замену"
        if not self._confirm(
            f"Убрать {kind} пары в блоке {item.slot_no} на "
            f"{format_display(self._date)}? Пара вернётся к расписанию."
        ):
            return
        OverrideService(self.db).delete(override_id)
        self.changed.emit()
        self.refresh()

    def reset_day(self) -> None:
        overrides = OverrideService(self.db)
        result = overrides.reset_day(self._date, dry_run=True)
        if not result.removed:
            self._message("Изменений на эту дату нет.")
            return
        if self._confirm(
            f"Сбросить все изменения на {format_display(self._date)}? "
            f"Будет удалено записей: {result.removed}."
        ):
            overrides.reset_day(self._date)
            self.changed.emit()
            self.refresh()

    def open_grid_editor(self) -> None:
        dialog = GridEditorDialog(self.db, self._date, self)
        if dialog.exec():
            self.changed.emit()
            self.refresh()

    # ------------------------------------------------------------------ помощь
    def _find_lesson(self, day: date, profile_id: int, slot_no: int):
        result = DayResolver(self.db).resolve(day)
        for lesson in result.lessons:
            if lesson.profile_id == profile_id and lesson.slot_no == slot_no:
                return lesson
        return None

    def _first_free_slot(self, day: date, profile_id: int) -> int | None:
        """Первый свободный блок дня (OVR-07): отменённый блок тоже свободен."""
        from ...core.repositories import BellRepository

        profile = BellRepository(self.db).profile(profile_id)
        if profile is None:
            return None
        result = DayResolver(self.db).resolve(day)
        # SCH-18: отменённая пара в этот день не показывается, значит блок
        # свободен — иначе «Добавить» предлагал только блок после последней
        # пары, и вставить занятие на место отменённого было нельзя.
        occupied = {
            lesson.slot_no
            for lesson in result.lessons
            if lesson.status != LessonStatus.CANCELLED
        }
        for slot in profile.slots:
            if slot.slot_no not in occupied:
                return slot.slot_no
        return None

    def _delete_orphans(self) -> None:
        removed = OverrideService(self.db).delete_orphans()
        self._message(f"Удалено изменений: {len(removed)}.")
        self.changed.emit()
        self.refresh()

    def _open_homework(self) -> None:
        window = self.window()
        if hasattr(window, "open_page"):
            window.open_page("homework")

    def _message(self, text: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(self, "Расписание", text)

    def _confirm(self, text: str) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self, "Подтверждение", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes


__all__ = ["SchedulePage", "MODES"]
