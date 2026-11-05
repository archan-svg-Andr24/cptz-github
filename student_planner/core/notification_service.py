"""Системные уведомления (NOTIF-01…NOTIF-05).

Программа сама напоминает о том, что легко пропустить: начало пары, дедлайн
задания, близкий экзамен и низкий остаток «Стрелки». Проверка выполняется по
таймеру, поэтому модуль ничего не знает про интерфейс — он только отвечает на
вопрос «что нужно показать прямо сейчас».

Ключевое правило: **одно и то же событие не показывается дважды**. Для этого
сервис помнит идентификаторы уже показанных напоминаний в памяти процесса:
запись в БД не нужна, потому что после перезапуска напоминание снова уместно.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import clock
from .database import Database
from .dates import time_to_minutes
from .day_resolution import DayResolver
from .exam_service import ExamService
from .schedule_service import HomeworkService
from .settings_registry import SettingsKeys
from .settings_service import SettingsService
from .transport_service import TransportService


@dataclass(frozen=True)
class Notification:
    """Одно напоминание: заголовок, текст и ключ «не повторять»."""

    key: str
    title: str
    message: str
    #: Чем важнее, тем первым показывается (0 — самое важное).
    priority: int = 5


class NotificationService:
    """NOTIF-01…NOTIF-05: отбор напоминаний на текущий момент."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.settings = SettingsService(db)
        #: Ключи уже показанных напоминаний (в пределах запуска).
        self._shown: set[str] = set()

    # ------------------------------------------------------------------ настройки
    @property
    def enabled(self) -> bool:
        return self.settings.raw(SettingsKeys.NOTIFY_ENABLED) != "0"

    @property
    def exam_days(self) -> int:
        return self.settings.get_int(SettingsKeys.NOTIFY_EXAM_DAYS)

    @property
    def homework_days(self) -> int:
        return self.settings.get_int(SettingsKeys.NOTIFY_HOMEWORK_DAYS)

    @property
    def lesson_minutes(self) -> int:
        return self.settings.get_int(SettingsKeys.NOTIFY_LESSON_MINUTES)

    @property
    def low_balance_enabled(self) -> bool:
        return self.settings.raw(SettingsKeys.NOTIFY_LOW_BALANCE) != "0"

    # -------------------------------------------------------------------- отбор
    def all_pending(self, *, now: datetime | None = None) -> list[Notification]:
        """Все напоминания, которые уместны сейчас и ещё не показаны.

        Возвращает список, отсортированный по важности. Пустой список —
        обычная ситуация, а не ошибка.
        """
        if not self.enabled:
            return []
        moment = now or clock.now()
        today = moment.date()
        result: list[Notification] = []
        result.extend(self._exam_items(today))
        result.extend(self._homework_items(today))
        result.extend(self._lesson_items(moment))
        result.extend(self._balance_items(today))
        result = [item for item in result if item.key not in self._shown]
        return sorted(result, key=lambda item: (item.priority, item.key))

    def next_notification(self, *, now: datetime | None = None) -> Notification | None:
        """Самое важное непоказанное напоминание или ``None``."""
        items = self.all_pending(now=now)
        return items[0] if items else None

    def mark_shown(self, notification: Notification) -> None:
        """Запомнить, что напоминание уже показано в этом запуске."""
        self._shown.add(notification.key)

    def reset_shown(self) -> None:
        """Забыть показанные (например, после смены настроек)."""
        self._shown.clear()

    # ------------------------------------------------------------------ события
    def _exam_items(self, today: date) -> list[Notification]:
        """NOTIF-02: экзамен за N дней."""
        days = self.exam_days
        if days <= 0:
            return []
        items = []
        for row in ExamService(self.db).upcoming_within(days, today=today):
            key = f"exam:{row.exam.id}:{row.days_left}"
            if row.days_left == 0:
                when = "сегодня"
            elif row.days_left == 1:
                when = "завтра"
            else:
                when = f"через {row.days_left} дн."
            items.append(
                Notification(
                    key=key,
                    title="Скоро экзамен",
                    message=f"{row.subject_name} — {row.exam.kind_short.lower()} {when}"
                    + (f" в {row.exam.time}" if row.exam.time else ""),
                    priority=0 if row.days_left <= 1 else 2,
                )
            )
        return items

    def _homework_items(self, today: date) -> list[Notification]:
        """NOTIF-03: ближайший дедлайн задания."""
        days = self.homework_days
        if days <= 0:
            return []
        limit = today + timedelta(days=days)
        items = []
        for row in HomeworkService(self.db).rows(status="active", today=today):
            due = row.homework.due_date
            if due < today or due > limit:
                continue
            key = f"homework:{row.homework.id}:{due.isoformat()}"
            if due == today:
                when = "сегодня"
            elif due == today + timedelta(days=1):
                when = "завтра"
            else:
                when = f"через {(due - today).days} дн."
            text = row.short_description or "без описания"
            items.append(
                Notification(
                    key=key,
                    title="Дедлайн задания",
                    message=f"{row.subject_name}: {text} — сдать {when}",
                    priority=1 if due <= today else 3,
                )
            )
        return items

    def _lesson_items(self, moment: datetime) -> list[Notification]:
        """NOTIF-04: начало пары через N минут."""
        minutes = self.lesson_minutes
        if minutes <= 0:
            return []
        today = moment.date()
        now_minutes = moment.hour * 60 + moment.minute
        try:
            result = DayResolver(self.db).resolve(today)
        except Exception:  # pragma: no cover - защита таймера
            return []
        items = []
        for lesson in result.lessons:
            if lesson.is_cancelled or not lesson.start_time:
                continue
            try:
                start = time_to_minutes(lesson.start_time)
            except Exception:  # pragma: no cover - некорректное время в данных
                continue
            delta = start - now_minutes
            if not 0 <= delta <= minutes:
                continue
            key = f"lesson:{today.isoformat()}:{lesson.profile_id}:{lesson.slot_no}"
            items.append(
                Notification(
                    key=key,
                    title="Скоро пара",
                    message=(
                        f"{lesson.subject_name} начнётся в {lesson.start_time} "
                        f"(через {delta} мин.), каб. {lesson.room}"
                        if lesson.room
                        else f"{lesson.subject_name} начнётся в {lesson.start_time} "
                        f"(через {delta} мин.)"
                    ),
                    priority=0,
                )
            )
        return items

    def _balance_items(self, today: date) -> list[Notification]:
        """NOTIF-05: низкий остаток поездок «Стрелки».

        Порог ``strelka_low_balance_warn`` задан **в поездках**: он переводится
        в деньги как «цена следующей поездки × порог», и сравнивается с
        остатком кошелька (``StrellaState.low_balance``). Раньше здесь
        вызывался несуществующий ``TransportService.strelka_balance()`` —
        исключение молча съедалось, и этот вид напоминаний не работал никогда.
        """
        if not self.low_balance_enabled:
            return []
        try:
            state = TransportService(self.db).strella_state(today=today)
        except Exception:  # pragma: no cover - защита таймера
            return []
        if not state.low_balance:
            return []
        threshold = self.settings.get_int(SettingsKeys.STRELKA_LOW_BALANCE_WARN)
        balance = state.balance if state.balance is not None else 0
        return [
            Notification(
                key=f"balance:{today.isoformat()}:{balance}",
                title="Мало поездок «Стрелки»",
                message=(
                    f"Остаток на карте {balance} ₽ — меньше {threshold} поездок "
                    f"по текущему тарифу. Пора пополнить счёт."
                ),
                priority=4,
            )
        ]


def format_lesson_reminder(lesson) -> str:
    """Подпись «пара через N минут» — вынесено для повторного использования."""
    if not lesson.start_time:
        return ""
    return f"{lesson.subject_name} в {lesson.start_time}"


__all__ = ["Notification", "NotificationService", "format_lesson_reminder"]
