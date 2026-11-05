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
from ...core.exam_service import ExamService
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
from ...core.subject_names import SubjectNameService
from ..dialogs import (
    AddLessonDialog,
    CancelLessonDialog,
    ReplaceLessonDialog,
)
from ..grid_editor import GridEditorDialog
from ..theme import FONT_FAMILY, subject_color_index
from ..widgets import (
    Card,
    EmptyState,
    FlowLayout,
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

#: UI-14: предел длины подписи предмета в колонке дня (символов).
#: Даже при выключенных сокращениях более длинное название режется по границе
#: слова: колонка дня в недельном режиме уже 200 px. Предел взят с запасом,
#: чтобы самое длинное название стартового набора
#: («Иностранный язык в профессиональной деятельности», 49 символов) читалось
#: целиком — пользователь, выключивший сокращения, должен видеть полный текст.
SUBJECT_CAPTION_LIMIT = 50


class LessonCard(QFrame):
    """SCH-04/SCH-11: карточка занятия с временем, предметом, статусом, бейджем ДЗ.

    ``subject_caption`` — подпись предмета для показа. Страница передаёт сюда
    сокращённое название (UI-14), если оно включено в настройках, и полное —
    иначе. Полное название остаётся в подсказке и в ``lesson.subject_name``,
    поэтому поиск и диалоги правки работают с настоящим названием.
    """

    cancel_requested = Signal(int, int)   # profile_id, slot_no
    replace_requested = Signal(int, int)
    reset_requested = Signal(int)         # override_id
    homework_requested = Signal()

    def __init__(
        self,
        lesson,
        parent: QWidget | None = None,
        *,
        subject_caption: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.lesson = lesson
        # Отменённая пара — карточка приглушённых цветов (CardCancelled),
        # остальные — обычная карточка. Цвета задаёт тема, а не эта строка.
        self.setObjectName(
            "CardCancelled" if lesson.status == LessonStatus.CANCELLED else "Card"
        )
        # UI-13: номер оттенка предмета. Сам оттенок выбирает тема, поэтому
        # смена темы перекрашивает пары без пересоздания карточек.
        subject_id = lesson.subject.id if lesson.subject else None
        self.setProperty(
            "subjectColor",
            subject_color_index(subject_id, lesson.subject_name or ""),
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
        caption = subject_caption or lesson.subject_name or "—"
        self.subject_label = QLabel(caption)
        self.subject_label.setObjectName(
            "StrikeText" if lesson.status == LessonStatus.CANCELLED else "SubjectName"
        )
        self.subject_label.setWordWrap(True)
        # UI-14: сокращённая подпись не должна скрывать полное название — оно
        # видно во всплывающей подсказке.
        if caption != (lesson.subject_name or "—"):
            self.subject_label.setToolTip(lesson.subject_name or "")
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
            comment.setObjectName("WarningText")
            comment.setWordWrap(True)
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
        # UI-27: раскладка получает родителя сразу (self). Вложенная раскладка
        # без родителя НЕ назначает родителя добавляемым виджетам: кнопка
        # остаётся самостоятельным окном, и любой setVisible(True) показывает
        # её отдельным окном на один кадр — это и были «всплывающие окна» при
        # переключении дней.
        actions = QVBoxLayout()
        actions.setSpacing(4)

        # Изменение этой даты внесено и его можно снять (OVR-11). Для пары,
        # добавленной оверрайдом ``add``, «Убрать» не нужно: её удаляет
        # «Отменить» (OVR-04), иначе вышли бы две кнопки об одном и том же.
        has_change = (
            lesson.override_id is not None
            and lesson.status in (LessonStatus.CANCELLED, LessonStatus.REPLACED)
        )

        self.cancel_button = QPushButton("Отменить", self)
        self.cancel_button.setObjectName("Flat")
        self.cancel_button.clicked.connect(
            lambda: self.cancel_requested.emit(self.lesson.profile_id, self.lesson.slot_no)
        )
        self.cancel_button.setEnabled(
            lesson.status in (LessonStatus.PLANNED, LessonStatus.ADDED)
        )
        actions.addWidget(self.cancel_button)
        # На отменённой паре кнопка уже не нужна, на заменённой — бессмысленна:
        # отменять нечего, пара и так изменена.
        self.cancel_button.setVisible(not has_change)

        self.replace_button = QPushButton("Заменить", self)
        self.replace_button.setObjectName("Flat")
        self.replace_button.clicked.connect(
            lambda: self.replace_requested.emit(self.lesson.profile_id, self.lesson.slot_no)
        )
        # SCH-18/OVR-05: заменять можно и отменённую пару — это путь «убрал
        # одну, поставил другую»: cancel снимается, ставится replace.
        self.replace_button.setEnabled(True)
        actions.addWidget(self.replace_button)
        # На заменённой паре второго «Заменить» не показываем: замену снимают
        # через «Убрать изменение», иначе кнопки дублируют друг друга.
        self.replace_button.setVisible(lesson.status != LessonStatus.REPLACED)

        # OVR-11: «Убрать изменение» возвращает пару к состоянию расписания.
        self.undo_button = QPushButton("↺ Убрать изменение", self)
        self.undo_button.setObjectName("Danger")
        self.undo_button.setToolTip(
            "Снять изменение этой даты: отмена вернёт пару в расписание, "
            "замена — предмет из сетки. Сама сетка не меняется."
        )
        self.undo_button.clicked.connect(
            lambda: self.reset_requested.emit(self.lesson.override_id)
        )
        actions.addWidget(self.undo_button)
        self.undo_button.setVisible(has_change)
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
                # deleteLater() отложен: без hide()+setParent(None) старая
                # карточка остаётся видимой до возврата в цикл событий и
                # рисуется поверх новой.
                widget.hide()
                widget.setParent(None)
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
        #: UI-14: сервис сокращённых названий; создаётся при первой отрисовке.
        self._names: SubjectNameService | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self.header = SectionHeader("Расписание")
        outer.addWidget(self.header)

        self.grid_button = QPushButton("Редактировать сетку недели…")
        self.grid_button.setObjectName("Primary")
        self.grid_button.clicked.connect(self.open_grid_editor)
        self.header.add_action(self.grid_button)

        # UI-14: расписание картинкой — «скинуть в чат группы».
        self.export_button = QPushButton("Сохранить картинкой…")
        self.export_button.setObjectName("Flat")
        self.export_button.setToolTip(
            "Сохранить видимое расписание в PNG: удобно отправить в чат."
        )
        self.export_button.clicked.connect(self.export_image)
        self.header.add_action(self.export_button)

        # ------------------------------------------------- переключатель режимов
        # Раскладка с переносом, а не в одну строку: панель управления
        # содержит поле режима, стрелки, дату (минимум 240 px), «Сегодня» и
        # флажок. В одну строку это 1022 px — больше, чем
        # центральная зона при минимальном окне 1080x680 (около 452 px), и
        # QHBoxLayout сжимал элементы ниже минимума: флажок получал 73 px при
        # 172, бейдж «Нижняя неделя» — 73 при 103, и текст обрезался.
        controls = FlowLayout()
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

        self.week_badge_holder = FlowLayout()
        self.week_badge_holder.setSpacing(8)
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
    def _subject_caption(self, name: str) -> str:
        """UI-14: подпись предмета по настройкам сокращённых названий.

        Сокращения читаются один раз на перерисовку: страница создаёт сервис
        заново в ``refresh``, поэтому включение или правка сокращений в
        настройках видны сразу, без перезапуска.
        """
        if self._names is None:
            self._names = SubjectNameService(self.db)
        return self._names.smart(name, limit=SUBJECT_CAPTION_LIMIT)

    def refresh(self) -> None:
        resolver = DayResolver(self.db)
        overrides = OverrideService(self.db)
        calendar = CalendarService(self.db)
        # Настройки сокращений перечитываются на каждую перерисовку.
        self._names = SubjectNameService(self.db)

        while self.days_layout.count():
            item = self.days_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # UI-26: hide()+setParent(None) обязательны. Одного
                # deleteLater() мало: удаление отложено до возврата в цикл
                # событий, а снятый из layout виджет сохраняет родителя и
                # остаётся видимым. При переключении дней такие «призраки»
                # копились и рисовались поверх новых колонок — выглядело как
                # всплывающие и сразу закрывающиеся окна.
                widget.hide()
                widget.setParent(None)
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
                widget.hide()
                widget.setParent(None)
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
            column.header.setObjectName("TodayHeader")
            column.subheader.setText("сегодня")
        else:
            column.subheader.setText("")

        result = resolver.resolve(day)

        # EXAM-06: испытание показывается в дне первым — важнее пар, и о нём
        # легко забыть, если он виден только на отдельной странице.
        for day_exam in ExamService(self.db).day_exams(day):
            column.body.addWidget(self._exam_card(day_exam))

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
            card = LessonCard(
                lesson, subject_caption=self._subject_caption(lesson.subject_name)
            )
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

    # ------------------------------------------------------------------ экспорт
    def export_image(self) -> str | None:
        """UI-14: сохранить видимое расписание в PNG.

        Снимок делается с области дней (``days_host``), а не со всей страницы:
        в картинку не попадают кнопки правки и переключатели — получается
        расписание, которое не стыдно отправить в чат группы.

        Возвращает путь сохранённого файла или ``None``, если пользователь
        отменил выбор. Метод отдельный от обработчика кнопки, чтобы его можно
        было проверить тестом без диалога.
        """
        from PySide6.QtWidgets import QFileDialog

        days = self._visible_days()
        default_name = "raspisanie_"
        if len(days) == 1:
            default_name += days[0].strftime("%Y-%m-%d")
        else:
            default_name += f"{days[0]:%Y-%m-%d}_{days[-1]:%Y-%m-%d}"

        target, _ = QFileDialog.getSaveFileName(
            self, "Сохранить расписание", f"{default_name}.png", "Изображение (*.png)"
        )
        if not target:
            return None
        if not target.lower().endswith(".png"):
            target += ".png"
        if self.save_image_to(target):
            self._message(f"Расписание сохранено: {target}")
            return target
        self._message(f"Не удалось сохранить файл: {target}")
        return None

    def save_image_to(self, path: str) -> bool:
        """Записать картинку расписания по указанному пути (UI-14).

        Молча: сообщение показывает вызывающий. Иначе проверка сохранения в
        тесте упиралась бы в модальное окно.
        """
        try:
            pixmap = self.render_image()
            return bool(pixmap.save(path, "PNG"))
        except OSError:
            return False

    def render_image(self):
        """Собрать картинку расписания: заголовок с датой и колонки дней.

        Заголовок рисуется здесь, а не берётся со страницы: на снимке нужно
        видеть, за какой период расписание, иначе картинка в чате теряет смысл.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont, QPainter, QPixmap

        source = self.days_host
        # Скрытые элементы (пустое состояние, баннеры) не должны попадать
        # белыми полосами: grab() рисует только видимое.
        body = source.grab()
        # Полоса заголовка с запасом: 13pt DemiBold занимает ~24 px, плюс
        # отступ сверху и снизу — при 46 px нижняя часть букв обрезалась.
        header_height = 64
        margin = 12
        width = max(body.width(), 480)
        height = body.height() + header_height + margin * 2

        canvas = QPixmap(width, height)
        canvas.fill(self._export_background())

        painter = QPainter(canvas)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont(FONT_FAMILY, 13)
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(self._export_text_color())
            days = self._visible_days()
            if len(days) == 1:
                caption = f"Расписание · {format_display(days[0])}"
            else:
                caption = (
                    f"Расписание · {format_display(days[0])} — "
                    f"{format_display(days[-1])}"
                )
            painter.drawText(
                margin,
                margin,
                width - margin * 2,
                header_height - 8,
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                caption,
            )
            painter.drawPixmap(margin, margin + header_height, body)
        finally:
            painter.end()
        return canvas

    @staticmethod
    def _export_background() -> "QColor":
        from PySide6.QtGui import QColor

        from ..theme import COLORS

        return QColor(COLORS["background"])

    @staticmethod
    def _export_text_color() -> "QColor":
        from PySide6.QtGui import QColor

        from ..theme import COLORS

        return QColor(COLORS["text"])

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

    def _exam_card(self, day_exam) -> QWidget:
        """EXAM-06: карточка испытания в колонке дня."""
        from PySide6.QtWidgets import QLabel

        from ...core.exam_service import ExamRow as _ExamRow  # noqa: F401 - тип для читаемости
        from ..widgets import Badge, Card

        card = Card(self._subject_caption(day_exam.subject_name))
        card.setObjectName("CardWarning")
        caption = QLabel(
            " · ".join(
                part
                for part in (
                    day_exam.exam.kind_label,
                    day_exam.exam.time,
                    f"каб. {day_exam.exam.room}" if day_exam.exam.room else None,
                )
                if part
            )
        )
        caption.setObjectName("WarningText")
        caption.setWordWrap(True)
        card.add_widget(caption)

        badges = QWidget()
        badges_layout = QHBoxLayout(badges)
        badges_layout.setContentsMargins(0, 0, 0, 0)
        badges_layout.setSpacing(6)
        badges_layout.addWidget(Badge(day_exam.countdown, "warning"))
        badges_layout.addStretch(1)
        card.add_widget(badges)
        return card

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
