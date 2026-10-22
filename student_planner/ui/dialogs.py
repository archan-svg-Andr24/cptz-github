"""Диалоги интерфейса: подтверждение поездок, отмена пары, ручная поездка и др.

Быстрый ввод (UI-14) — не более трёх полей до сохранения и Enter сохраняет —
реализован для отмены пары, подтверждения поездок дня, пополнения «Стрелки» и
ручной поездки (REP-14). Остальные диалоги компактные, без жёсткого лимита.
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.dates import format_display
from ..core.errors import AppError
from ..core.models import (
    Direction,
    PaymentMethod,
    TransportType,
)
from ..core.recalculation import RecalculationService
from ..core.schedule_service import HomeworkService, OverrideService
from ..core.transport_service import TransportService, WalletService
from ..core.trip_service import TripPlanService
from .theme import COLORS
from .widgets import Separator

log = logging.getLogger(__name__)


def _date_edit(value: date) -> QDateEdit:
    widget = QDateEdit()
    widget.setCalendarPopup(True)
    widget.setDisplayFormat("dd.MM.yyyy")
    widget.setDate(QDate(value.year, value.month, value.day))
    return widget


def _to_date(widget: QDateEdit) -> date:
    value = widget.date()
    return date(value.year(), value.month(), value.day())


class BaseDialog(QDialog):
    """Общая основа: тёмная тема, кнопки, показ ошибок."""

    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(parent)
        from .theme import stylesheet

        self.setStyleSheet(stylesheet())
        self.setWindowTitle(title)
        self.setModal(True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(16, 14, 16, 14)
        self.layout_.setSpacing(10)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)

    def add_widget(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)

    def add_form(self, form: QFormLayout) -> None:
        self.layout_.addLayout(form)

    def finish(self, ok_text: str = "Сохранить") -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
        self.layout_.addWidget(self.buttons)

    def error_label(self) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setVisible(False)
        label.setStyleSheet(
            f"color: {COLORS['error']}; background-color: {COLORS['error_bg']}; "
            f"border: 1px solid {COLORS['error']}; border-radius: 6px; padding: 6px;"
        )
        self.layout_.addWidget(label)
        return label

    def show_error(self, error: Exception) -> None:
        label = getattr(self, "_error_label", None)
        text = error.message if isinstance(error, AppError) else str(error)
        if label is None:
            QMessageBox.critical(self, "Ошибка", text)
            return
        label.setText(text)
        label.setVisible(True)

    def _on_accept(self) -> None:
        try:
            if self.apply():
                self.accept()
        except AppError as error:
            log.info("Диалог отклонил ввод: %s", error)
            self.show_error(error)
        except Exception as error:  # pragma: no cover - непредвиденная ошибка
            log.exception("Ошибка диалога")
            self.show_error(error)

    def apply(self) -> bool:  # pragma: no cover - переопределяется
        return True


# ===========================================================================
# UI-08 / TRIP-08 — подтверждение поездок дня
# ===========================================================================
class ConfirmTripsDialog(BaseDialog):
    """Подтверждение поездок дня: два шаблона и одна кнопка (UI-14)."""

    def __init__(self, db, day: date, parent: QWidget | None = None,
                 *, outbound_template_id: int | None = None,
                 return_template_id: int | None = None) -> None:
        super().__init__(parent, f"Поездки на {format_display(day)}")
        self.db = db
        self.day = day
        self.service = TripPlanService(db)
        self._error_label = self.error_label()

        plan = self.service.plan(
            day,
            outbound_template_id=outbound_template_id,
            return_template_id=return_template_id,
        )

        form = QFormLayout()
        form.setSpacing(8)

        self.outbound_combo = QComboBox()
        self._fill_templates(
            self.outbound_combo,
            self.service.available_templates(Direction.HOME_TO_COLLEGE),
        )
        if plan.outbound is not None:
            _select_id(self.outbound_combo, plan.outbound.id)
        form.addRow("Туда:", self.outbound_combo)

        self.return_combo = QComboBox()
        self._fill_templates(
            self.return_combo,
            self.service.available_templates(Direction.COLLEGE_TO_HOME),
        )
        if plan.return_trip is not None:
            _select_id(self.return_combo, plan.return_trip.id)
        form.addRow("Обратно:", self.return_combo)

        if not plan.has_lessons:
            hint = QLabel("Занятий нет: подтверждение необязательно")
            hint.setObjectName("Muted")
            form.addRow("", hint)

        self.add_form(form)
        self.add_widget(Separator())

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.add_widget(self.summary_label)

        self.outbound_combo.currentIndexChanged.connect(self._update_preview)
        self.return_combo.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

        self.finish("Подтвердить")
        # UI-14: Enter сохраняет.
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setAutoDefault(True)

    def _fill_templates(self, combo: QComboBox, templates) -> None:
        combo.clear()
        combo.addItem("— не выбрано —", None)
        for template in templates:
            legs = ", ".join(
                f"{TransportType.label(leg.mode)} {leg.vehicle}" for leg in template.legs
            )
            combo.addItem(f"{template.name} ({legs})", template.id)

    def _update_preview(self) -> None:
        outbound = self.outbound_combo.currentData()
        back = self.return_combo.currentData()
        plan = self.service.plan(
            self.day, outbound_template_id=outbound, return_template_id=back
        )
        legs = plan.legs_count
        lines = [f"Рейсов: {legs}"]
        if plan.is_confirmed:
            lines.append("День уже подтверждён — набор поездок будет заменён.")
        self.summary_label.setText("\n".join(lines))

    def apply(self) -> bool:
        self.service.confirm(
            self.day,
            outbound_template_id=self.outbound_combo.currentData(),
            return_template_id=self.return_combo.currentData(),
        )
        return True


class RecalculateDialog(BaseDialog):
    """REP-08: «Пересчитать счётчик «Стрелки»» с подтверждением."""

    def __init__(self, db, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Пересчёт счётчика «Стрелки»")
        self.db = db
        self._error_label = self.error_label()

        text = QLabel(
            "Пересчёт заново нумерует все поездки «Стрелки» и пересчитывает их "
            "стоимость по действующим тарифам (CALC-04).\n"
            "Снапшоты поездок, которых изменение не коснулось, не переписываются "
            "(DATA-16). Продолжить?"
        )
        text.setWordWrap(True)
        self.add_widget(text)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.add_widget(self.result_label)
        self.finish("Пересчитать")

    def apply(self) -> bool:
        result = TransportService(self.db).recalculate()
        self.result_label.setText(
            f"Проверено поездок: {result.rides_total}, изменено: {result.rides_changed}.\n"
            f"Было {result.amount_before} ₽, стало {result.amount_after} ₽."
        )
        QMessageBox.information(self, "Готово", result.summary)
        return True


# ===========================================================================
# UI-14 — отмена пары
# ===========================================================================
class CancelLessonDialog(BaseDialog):
    """Отмена пары: не более трёх полей (UI-14)."""

    def __init__(self, db, day: date, profile_id: int, slot_no: int,
                 caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Отменить пару")
        self.db = db
        self.service = OverrideService(db)
        self.day = day
        self.profile_id = profile_id
        self.slot_no = slot_no
        self._error_label = self.error_label()

        info = QLabel(f"{format_display(day)}: {caption}")
        info.setWordWrap(True)
        self.add_widget(info)

        form = QFormLayout()
        form.setSpacing(8)
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("Причина (необязательно)")
        form.addRow("Комментарий:", self.comment_edit)
        self.add_form(form)

        self.finish("Отменить пару")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)

    def apply(self) -> bool:
        self.service.cancel(
            self.day, self.profile_id, self.slot_no,
            comment=self.comment_edit.text().strip() or None,
        )
        return True


# ===========================================================================
# OVR-05 — замена пары
# ===========================================================================
class ReplaceLessonDialog(BaseDialog):
    """Замена пары: предмет, преподаватель, кабинет, время, комментарий.

    Если передан ``override_id``, диалог правит существующее изменение
    (``OVR-01``) вместо создания замены. Это путь для пары, добавленной через
    ``add``: в сетке её нет, поэтому ``replace`` на том же блоке был бы
    сиротским (ALG-10).
    """

    def __init__(self, db, day: date, profile_id: int, slot_no: int,
                 caption: str, parent: QWidget | None = None,
                 *, override_id: int | None = None) -> None:
        super().__init__(parent, "Заменить пару")
        self.db = db
        self.service = OverrideService(db)
        self.day = day
        self.profile_id = profile_id
        self.slot_no = slot_no
        self.override_id = override_id
        self._error_label = self.error_label()

        info = QLabel(f"{format_display(day)}: {caption}")
        info.setWordWrap(True)
        self.add_widget(info)

        from ..core.repositories import SubjectRepository

        self.subjects = SubjectRepository(db).all(include_inactive=False)

        form = QFormLayout()
        form.setSpacing(8)

        self.subject_combo = QComboBox()
        self.subject_combo.setEditable(True)
        for subject in self.subjects:
            self.subject_combo.addItem(subject.name, subject.id)
        form.addRow("Предмет:", self.subject_combo)

        self.teacher_edit = QLineEdit()
        form.addRow("Преподаватель:", self.teacher_edit)

        self.room_edit = QLineEdit()
        form.addRow("Кабинет:", self.room_edit)

        self.comment_edit = QLineEdit()
        form.addRow("Комментарий:", self.comment_edit)

        self.add_form(form)
        self.finish("Заменить")

        self.subject_combo.currentIndexChanged.connect(self._fill_from_subject)
        self._fill_from_subject()

    def _fill_from_subject(self) -> None:
        index = self.subject_combo.currentIndex()
        if 0 <= index < len(self.subjects):
            subject = self.subjects[index]
            if not self.teacher_edit.text().strip() and subject.teacher:
                self.teacher_edit.setText(subject.teacher)
            if not self.room_edit.text().strip() and subject.room:
                self.room_edit.setText(subject.room)

    def apply(self) -> bool:
        subject_id = self.subject_combo.currentData()
        if subject_id is None:
            raise AppError("Выберите предмет для замены (OVR-05).")
        teacher = self.teacher_edit.text().strip() or None
        room = self.room_edit.text().strip() or None
        comment = self.comment_edit.text().strip() or None
        if self.override_id is not None:
            # OVR-09: правим блок целиком, тип изменения сохраняется.
            self.service.edit(
                self.override_id,
                subject_id=subject_id,
                teacher=teacher,
                room=room,
                comment=comment,
            )
            return True
        self.service.replace(
            self.day, self.profile_id, self.slot_no,
            subject_id=subject_id,
            teacher=teacher,
            room=room,
            comment=comment,
        )
        return True


# ===========================================================================
# OVR-07 — добавление пары
# ===========================================================================
class AddLessonDialog(BaseDialog):
    """Добавление занятия в свободный слот."""

    def __init__(self, db, day: date, profile_id: int, slot_no: int,
                 caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Добавить занятие")
        self.db = db
        self.service = OverrideService(db)
        self.day = day
        self.profile_id = profile_id
        self.slot_no = slot_no
        self._error_label = self.error_label()

        info = QLabel(f"{format_display(day)}, блок {slot_no}: {caption}")
        info.setWordWrap(True)
        self.add_widget(info)

        from ..core.repositories import SubjectRepository

        self.subjects = SubjectRepository(db).all(include_inactive=False)

        form = QFormLayout()
        form.setSpacing(8)
        self.subject_combo = QComboBox()
        for subject in self.subjects:
            self.subject_combo.addItem(subject.name, subject.id)
        form.addRow("Предмет:", self.subject_combo)

        self.teacher_edit = QLineEdit()
        form.addRow("Преподаватель:", self.teacher_edit)
        self.room_edit = QLineEdit()
        form.addRow("Кабинет:", self.room_edit)
        self.add_form(form)
        self.finish("Добавить")

    def apply(self) -> bool:
        subject_id = self.subject_combo.currentData()
        if subject_id is None:
            raise AppError("Выберите предмет (OVR-07).")
        self.service.add(
            self.day, self.profile_id, self.slot_no,
            subject_id=subject_id,
            teacher=self.teacher_edit.text().strip() or None,
            room=self.room_edit.text().strip() or None,
        )
        return True


# ===========================================================================
# WAL-01 — пополнение «Стрелки»
# ===========================================================================
class TopUpDialog(BaseDialog):
    """Пополнение «Стрелки»: дата, сумма, комментарий — три поля (UI-14)."""

    def __init__(self, db, parent: QWidget | None = None,
                 initial: bool = False) -> None:
        super().__init__(parent, "Начальный остаток" if initial else "Пополнение «Стрелки»")
        self.db = db
        self.wallet = WalletService(db)
        self.initial = initial
        self._error_label = self.error_label()

        if initial:
            hint = QLabel(
                "Укажите фактический остаток на карте на дату начала учёта (WAL-09). "
                "Отказ допустим: тогда остаток не показывается."
            )
            hint.setWordWrap(True)
            self.add_widget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        self.date_edit = _date_edit(date.today())
        form.addRow("Дата:", self.date_edit)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.00, 1_000_000.00)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setSuffix(" ₽")
        form.addRow("Сумма:", self.amount_spin)

        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("необязательно")
        form.addRow("Комментарий:", self.comment_edit)
        self.add_form(form)

        self.finish("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)

    def apply(self) -> bool:
        amount = f"{self.amount_spin.value():.2f}"
        if self.initial:
            self.wallet.add_initial(amount, topup_date=_to_date(self.date_edit))
        else:
            self.wallet.add(
                _to_date(self.date_edit), amount,
                comment=self.comment_edit.text().strip() or None,
            )
        return True


# ===========================================================================
# REP-14 — ручная поездка
# ===========================================================================
class ManualRideDialog(BaseDialog):
    """Ручная поездка: дата, направление с шаблоном, оплата (REP-14, UI-14).

    UI-14 разрешает ручной поездке не более трёх полей. Поэтому направление и
    шаблон объединены в одном списке: каждый пункт описывает маршрут целиком
    («Дом → Колледж · №22 + электричка»). Это сохраняет выбор шаблона (TRIP-02)
    и укладывается в лимит.
    """

    def __init__(self, db, day: date, parent: QWidget | None = None) -> None:
        super().__init__(parent, "Ручная поездка")
        self.db = db
        self.service = TripPlanService(db)
        self._error_label = self.error_label()

        form = QFormLayout()
        form.setSpacing(8)

        self.date_edit = _date_edit(day)
        form.addRow("Дата:", self.date_edit)

        # REP-14/TRIP-02: маршрут = направление + шаблон в одном поле.
        self.route_combo = QComboBox()
        self._fill_routes()
        form.addRow("Маршрут:", self.route_combo)

        self.payment_combo = QComboBox()
        for value in PaymentMethod.ALL:
            self.payment_combo.addItem(PaymentMethod.label(value), value)
        form.addRow("Оплата:", self.payment_combo)

        self.add_form(form)

        hint = QLabel(
            "Поездка участвует в счётчике и остатке наравне с остальными и не "
            "удаляется при снятии подтверждения дня (REP-14)."
        )
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.route_combo.currentIndexChanged.connect(self._on_route_changed)

        self.finish("Добавить")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)

    def _fill_routes(self) -> None:
        """Направления, внутри — шаблоны и пункт «без шаблона» (TRIP-02)."""
        for direction in Direction.ALL:
            caption = Direction.label(direction)
            self.route_combo.addItem(f"{caption} · без шаблона", (direction, None))
            for template in self.service.available_templates(direction):
                legs = ", ".join(
                    f"{TransportType.label(leg.mode)} {leg.vehicle}"
                    for leg in template.legs
                )
                self.route_combo.addItem(
                    f"{caption} · {template.name} ({legs})", (direction, template.id)
                )

    def _on_route_changed(self) -> None:
        """Подставить способ оплаты из первого рейса шаблона."""
        template_id = self.selected_template_id
        if template_id is None:
            return
        template = self.service.templates.by_id(template_id)
        if template is None or not template.legs:
            return
        index = self.payment_combo.findData(template.legs[0].payment_method)
        if index >= 0:
            self.payment_combo.setCurrentIndex(index)

    @property
    def selected_direction(self) -> str:
        data = self.route_combo.currentData()
        return data[0] if data else Direction.HOME_TO_COLLEGE

    @property
    def selected_template_id(self) -> int | None:
        data = self.route_combo.currentData()
        return data[1] if data else None

    def _selected_leg(self) -> tuple[str, str]:
        """Тип транспорта и номер рейса: из шаблона либо по способу оплаты."""
        template_id = self.selected_template_id
        if template_id is not None:
            template = self.service.templates.by_id(template_id)
            if template is not None and template.legs:
                leg = template.legs[0]
                return leg.mode, leg.vehicle
        if self.payment_combo.currentData() == PaymentMethod.TRAIN_STUDENT:
            return TransportType.TRAIN, "Электричка"
        return TransportType.BUS, "Автобус"

    def apply(self) -> bool:
        payment = self.payment_combo.currentData()
        transport_type, vehicle = self._selected_leg()
        # RT-17: электричка оплачивается только студенческим билетом.
        if transport_type == TransportType.TRAIN:
            payment = PaymentMethod.TRAIN_STUDENT
            index = self.payment_combo.findData(payment)
            if index >= 0:
                self.payment_combo.setCurrentIndex(index)
        self.service.add_manual_ride(
            _to_date(self.date_edit),
            direction=self.selected_direction,
            transport_type=transport_type,
            vehicle=vehicle,
            payment_method=payment,
            template_id=self.selected_template_id,
        )
        return True


# ===========================================================================
# HW-07 — быстрое создание задания
# ===========================================================================
class HomeworkDialog(BaseDialog):
    """Задание: предмет, дата сдачи, описание — три поля (HW-07, UI-14)."""

    def __init__(self, db, parent: QWidget | None = None,
                 homework=None, default_date: date | None = None) -> None:
        super().__init__(parent, "Задание")
        self.db = db
        self.service = HomeworkService(db)
        self.homework = homework
        self._error_label = self.error_label()

        subjects = self.service.subject_choices()
        if not subjects:
            hint = QLabel("Сначала добавьте предмет в справочнике (HW-14).")
            hint.setWordWrap(True)
            self.add_widget(hint)

        form = QFormLayout()
        form.setSpacing(8)

        self.subject_combo = QComboBox()
        for subject in subjects:
            self.subject_combo.addItem(subject.name, subject.id)
        if homework is not None:
            _select_id(self.subject_combo, homework.subject_id)
        form.addRow("Предмет:", self.subject_combo)

        self.date_edit = _date_edit(
            homework.due_date if homework is not None else (default_date or date.today())
        )
        form.addRow("Сдать до:", self.date_edit)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setPlaceholderText("Что задано (необязательно)")
        self.description_edit.setFixedHeight(70)
        if homework is not None and homework.description:
            self.description_edit.setPlainText(homework.description)
        form.addRow("Описание:", self.description_edit)
        self.add_form(form)

        self.finish("Сохранить")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)

    def apply(self) -> bool:
        subject_id = self.subject_combo.currentData()
        if subject_id is None:
            raise AppError("Сначала добавьте предмет (HW-14).")
        description = self.description_edit.toPlainText().strip() or None
        if self.homework is None:
            self.service.create(subject_id, _to_date(self.date_edit), description)
        else:
            self.service.update(
                self.homework.id,
                subject_id=subject_id,
                due_date=_to_date(self.date_edit),
                description=description,
            )
        return True


# ===========================================================================
# SET-06 / CAL-01 — учебный период
# ===========================================================================
class PeriodDialog(BaseDialog):
    """Каникулы или праздник: вид, название, даты, комментарий (CAL-01)."""

    def __init__(self, db, parent: QWidget | None = None, period=None) -> None:
        super().__init__(parent, "Учебный период")
        from ..core.schedule_service import CalendarService

        self.service = CalendarService(db)
        self.period = period
        self._error_label = self.error_label()

        form = QFormLayout()
        form.setSpacing(8)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Каникулы", "vacation")
        self.kind_combo.addItem("Праздник", "holiday")
        if period is not None:
            index = self.kind_combo.findData(period.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        form.addRow("Вид:", self.kind_combo)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Например, осенние каникулы")
        if period is not None:
            self.title_edit.setText(period.title)
        form.addRow("Название:", self.title_edit)

        self.start_edit = _date_edit(period.date_from if period else date.today())
        form.addRow("С:", self.start_edit)

        self.end_edit = _date_edit(period.date_to if period else date.today())
        form.addRow("По:", self.end_edit)

        self.comment_edit = QLineEdit()
        if period is not None and period.comment:
            self.comment_edit.setText(period.comment)
        form.addRow("Комментарий:", self.comment_edit)
        self.add_form(form)

        hint = QLabel("В период занятий нет: отмена и замена пар не применяются (OVR-10).")
        hint.setObjectName("Small")
        hint.setWordWrap(True)
        self.add_widget(hint)

        self.finish("Сохранить")

    def apply(self) -> bool:
        title = self.title_edit.text().strip()
        if not title:
            raise AppError("Укажите название периода (CAL-01).")
        fields = dict(
            kind=self.kind_combo.currentData(),
            title=title,
            start_date=_to_date(self.start_edit),
            end_date=_to_date(self.end_edit),
            comment=self.comment_edit.text().strip() or None,
        )
        if self.period is None:
            self.service.create(**fields)
        else:
            self.service.update(self.period.period_id, **fields)
        return True


def _select_id(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


__all__ = [
    "BaseDialog",
    "ConfirmTripsDialog",
    "RecalculateDialog",
    "CancelLessonDialog",
    "ReplaceLessonDialog",
    "AddLessonDialog",
    "TopUpDialog",
    "ManualRideDialog",
    "HomeworkDialog",
    "PeriodDialog",
]
