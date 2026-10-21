"""Схема БД — Приложение Б ТЗ v1.11, версия схемы 1 (DATA-19, ACC-M-97).

Схема **не сокращена** вместе с MVP: столбцы и таблицы будущих версий
(`group_mark`, `part_seq`, `vehicle`, `calendar_day_marks`, `exams`,
`practice_*`) присутствуют, но приложение MVP их не заполняет и по ним не
фильтрует. Это осознанное решение ТЗ: возврат функций v1.1 не должен требовать
миграции данных. Имена таблиц и полей сохранены как в Приложении Б.

Соглашения:
    время  — TEXT 'ЧЧ:ММ'
    даты   — TEXT 'ГГГГ-ММ-ДД' (сравнимы лексикографически)
    суммы  — NUMERIC (в приложении Decimal, 2 знака, ROUND_HALF_UP)
    NULL в effective_to / date_to / period_start_date — «не задано»
"""

from __future__ import annotations

import sqlite3
from typing import Final

#: Все таблицы схемы в порядке создания (зависимости внешних ключей учтены).
#: ``ACC-M-97`` требует ровно 18 таблиц и отсутствие таблиц расписаний рейсов.
TABLE_ORDER: Final[tuple[str, ...]] = (
    "settings",
    "subjects",
    "tariffs",
    "bell_profiles",
    "bell_slots",
    "bell_slot_parts",
    "week_anchors",
    "trip_templates",
    "trip_template_legs",
    "study_periods",
    "schedule_templates",
    "schedule_overrides",
    "calendar_day_marks",
    "exams",
    "trip_confirmations",
    "strelka_topups",
    "transport_rides",
    "homework",
)

_DDL: Final[tuple[str, ...]] = (
    # --- Б.1. Настройки -----------------------------------------------------
    """
    CREATE TABLE settings (
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
    """,
    # --- Б.2. Предметы ------------------------------------------------------
    """
    CREATE TABLE subjects (
      id        INTEGER PRIMARY KEY,
      code      TEXT,
      name      TEXT NOT NULL,
      teacher   TEXT,
      room      TEXT,
      color     TEXT,
      is_active INTEGER NOT NULL DEFAULT 1,
      UNIQUE (code, name)
    )
    """,
    # --- Б.3. Тарифы --------------------------------------------------------
    """
    CREATE TABLE tariffs (
      id             INTEGER PRIMARY KEY,
      kind           TEXT NOT NULL CHECK (kind IN
                       ('train_base','train_student','bus_base',
                        'strelka_stage1','strelka_stage2')),
      price          NUMERIC NOT NULL CHECK (price >= 0),
      effective_from TEXT NOT NULL,
      effective_to   TEXT,
      vehicle        TEXT,
      is_active      INTEGER NOT NULL DEFAULT 1,
      comment        TEXT,
      CHECK (effective_to IS NULL OR effective_from <= effective_to)
    )
    """,
    # --- Б.4. Профили звонков ----------------------------------------------
    """
    CREATE TABLE bell_profiles (
      id             INTEGER PRIMARY KEY,
      weekday        INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
      variant        TEXT NOT NULL CHECK (variant IN ('default','friday_class_hour','custom')),
      name           TEXT NOT NULL,
      effective_from TEXT,
      effective_to   TEXT,
      is_active      INTEGER NOT NULL DEFAULT 1,
      UNIQUE (weekday, variant, effective_from)
    )
    """,
    # --- Б.5. Блоки профиля -------------------------------------------------
    """
    CREATE TABLE bell_slots (
      id           INTEGER PRIMARY KEY,
      profile_id   INTEGER NOT NULL REFERENCES bell_profiles(id) ON DELETE CASCADE,
      slot_no      INTEGER NOT NULL,
      pair_no      INTEGER,
      block_type   TEXT NOT NULL CHECK (block_type IN ('class_hour','pair','custom')),
      display_name TEXT,
      sort_order   INTEGER,
      UNIQUE (profile_id, slot_no)
    )
    """,
    # --- Б.6. Части блоков --------------------------------------------------
    """
    CREATE TABLE bell_slot_parts (
      id         INTEGER PRIMARY KEY,
      slot_id    INTEGER NOT NULL REFERENCES bell_slots(id) ON DELETE CASCADE,
      seq        INTEGER NOT NULL,
      part_type  TEXT NOT NULL CHECK (part_type IN ('lesson','break')),
      start_time TEXT NOT NULL,
      end_time   TEXT NOT NULL,
      UNIQUE (slot_id, seq)
    )
    """,
    # --- Б.11. Якоря типа недели -------------------------------------------
    """
    CREATE TABLE week_anchors (
      id             INTEGER PRIMARY KEY,
      effective_from TEXT NOT NULL UNIQUE,
      base_date      TEXT NOT NULL,
      base_type      TEXT NOT NULL CHECK (base_type IN ('upper','lower')),
      cycle_length   INTEGER NOT NULL DEFAULT 2 CHECK (cycle_length >= 2),
      comment        TEXT
    )
    """,
    # --- Б.13. Шаблоны поездок ---------------------------------------------
    """
    CREATE TABLE trip_templates (
      id                     INTEGER PRIMARY KEY,
      direction              TEXT NOT NULL CHECK (direction IN ('home_to_college','college_to_home')),
      name                   TEXT NOT NULL,
      is_active              INTEGER NOT NULL DEFAULT 1,
      default_payment_method TEXT CHECK (default_payment_method IN ('strelka','debit_card')),
      depart_hint            TEXT,
      arrive_hint            TEXT,
      note                   TEXT,
      sort_order             INTEGER
    )
    """,
    # --- Б.14. Рейсы шаблона -----------------------------------------------
    """
    CREATE TABLE trip_template_legs (
      id             INTEGER PRIMARY KEY,
      template_id    INTEGER NOT NULL REFERENCES trip_templates(id) ON DELETE CASCADE,
      seq            INTEGER NOT NULL,
      mode           TEXT NOT NULL CHECK (mode IN ('train','bus')),
      vehicle        TEXT NOT NULL,
      is_paid        INTEGER NOT NULL DEFAULT 1,
      payment_method TEXT NOT NULL CHECK (payment_method IN ('strelka','debit_card','train_student')),
      UNIQUE (template_id, seq)
    )
    """,
    # --- Б.9. Учебные периоды ----------------------------------------------
    """
    CREATE TABLE study_periods (
      id                   INTEGER PRIMARY KEY,
      kind                 TEXT NOT NULL CHECK (kind IN
                             ('vacation','holiday','practice_educational',
                              'practice_industrial','exam_session')),
      title                TEXT NOT NULL,
      date_from            TEXT NOT NULL,
      date_to              TEXT NOT NULL,
      no_classes           INTEGER NOT NULL DEFAULT 1,
      place                TEXT,
      outbound_template_id INTEGER REFERENCES trip_templates(id) ON DELETE SET NULL,
      return_template_id   INTEGER REFERENCES trip_templates(id) ON DELETE SET NULL,
      is_active            INTEGER NOT NULL DEFAULT 1,
      comment              TEXT,
      CHECK (date_from <= date_to)
    )
    """,
    # --- Б.7. Шаблоны расписания -------------------------------------------
    """
    CREATE TABLE schedule_templates (
      id         INTEGER PRIMARY KEY,
      profile_id INTEGER NOT NULL REFERENCES bell_profiles(id),
      week_type  TEXT NOT NULL CHECK (week_type IN ('upper','lower')),
      slot_no    INTEGER NOT NULL,
      group_mark INTEGER CHECK (group_mark IN (1, 2)),
      subject_id INTEGER REFERENCES subjects(id),
      UNIQUE (profile_id, week_type, slot_no, group_mark)
    )
    """,
    # --- Б.8. Разовые изменения расписания ---------------------------------
    """
    CREATE TABLE schedule_overrides (
      id              INTEGER PRIMARY KEY,
      date            TEXT NOT NULL,
      profile_id      INTEGER NOT NULL REFERENCES bell_profiles(id),
      slot_no         INTEGER NOT NULL,
      group_mark      INTEGER CHECK (group_mark IN (1, 2)),
      part_seq        INTEGER,
      override_type   TEXT NOT NULL CHECK (override_type IN ('cancel','replace','add','move')),
      subject_id      INTEGER REFERENCES subjects(id),
      teacher         TEXT,
      room            TEXT,
      custom_start    TEXT,
      custom_end      TEXT,
      target_slot_no  INTEGER,
      keep_original   INTEGER NOT NULL DEFAULT 0,
      comment         TEXT,
      created_at      TEXT NOT NULL
    )
    """,
    # --- Б.10. Пометки дня (заготовка v1.1) ---------------------------------
    """
    CREATE TABLE calendar_day_marks (
      id      INTEGER PRIMARY KEY,
      date    TEXT NOT NULL,
      kind    TEXT NOT NULL CHECK (kind IN ('no_class','force_class','friday_variant')),
      value   TEXT,
      comment TEXT,
      UNIQUE (date, kind)
    )
    """,
    # --- Б.12. Экзамены (заготовка v1.1) ------------------------------------
    """
    CREATE TABLE exams (
      id         INTEGER PRIMARY KEY,
      subject_id INTEGER NOT NULL REFERENCES subjects(id),
      period_id  INTEGER REFERENCES study_periods(id) ON DELETE SET NULL,
      kind       TEXT NOT NULL CHECK (kind IN ('exam','credit','credit_diff')),
      date       TEXT NOT NULL,
      time       TEXT,
      room       TEXT,
      teacher    TEXT,
      status     TEXT NOT NULL DEFAULT 'planned'
                   CHECK (status IN ('planned','passed','postponed')),
      comment    TEXT,
      created_at TEXT NOT NULL
    )
    """,
    # --- Б.15. Подтверждения дней ------------------------------------------
    """
    CREATE TABLE trip_confirmations (
      id                   INTEGER PRIMARY KEY,
      study_date           TEXT NOT NULL UNIQUE,
      outbound_template_id INTEGER REFERENCES trip_templates(id) ON DELETE SET NULL,
      return_template_id   INTEGER REFERENCES trip_templates(id) ON DELETE SET NULL,
      include_outbound     INTEGER NOT NULL DEFAULT 1,
      include_return       INTEGER NOT NULL DEFAULT 1,
      week_type_snapshot   TEXT,
      confirmed_at         TEXT NOT NULL,
      comment              TEXT
    )
    """,
    # --- Б.16. Пополнения «Стрелки» ----------------------------------------
    """
    CREATE TABLE strelka_topups (
      id         INTEGER PRIMARY KEY,
      topup_date TEXT NOT NULL,
      amount     NUMERIC NOT NULL CHECK (amount >= 0),
      fee        NUMERIC NOT NULL DEFAULT 0 CHECK (fee >= 0),
      method     TEXT,
      comment    TEXT,
      created_at TEXT NOT NULL
    )
    """,
    # --- Б.17. Поездки ------------------------------------------------------
    """
    CREATE TABLE transport_rides (
      id                    INTEGER PRIMARY KEY,
      confirmation_id       INTEGER REFERENCES trip_confirmations(id) ON DELETE SET NULL,
      study_date            TEXT NOT NULL,
      ride_date             TEXT NOT NULL,
      direction             TEXT NOT NULL,
      template_id           INTEGER REFERENCES trip_templates(id) ON DELETE SET NULL,
      template_leg_id       INTEGER REFERENCES trip_template_legs(id) ON DELETE SET NULL,
      period_id             INTEGER REFERENCES study_periods(id) ON DELETE SET NULL,
      transport_type        TEXT NOT NULL CHECK (transport_type IN ('train','bus')),
      vehicle               TEXT NOT NULL,
      base_price            NUMERIC NOT NULL,
      paid_price            NUMERIC NOT NULL,
      discount_amount       NUMERIC NOT NULL,
      payment_method        TEXT NOT NULL CHECK (payment_method IN ('strelka','debit_card','train_student')),
      tariff_id             INTEGER REFERENCES tariffs(id) ON DELETE SET NULL,
      period_start_date     TEXT,
      ride_number_in_period INTEGER,
      week_type_snapshot    TEXT,
      is_manual             INTEGER NOT NULL DEFAULT 0,
      price_locked          INTEGER NOT NULL DEFAULT 0,
      comment               TEXT,
      created_at            TEXT NOT NULL
    )
    """,
    # --- Б.18. Домашние задания --------------------------------------------
    """
    CREATE TABLE homework (
      id           INTEGER PRIMARY KEY,
      subject_id   INTEGER NOT NULL REFERENCES subjects(id),
      group_mark   INTEGER CHECK (group_mark IN (1, 2)),
      due_date     TEXT NOT NULL,
      description  TEXT,
      status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done')),
      created_at   TEXT NOT NULL,
      completed_at TEXT
    )
    """,
)

_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX ix_tpl_profile   ON schedule_templates(profile_id, week_type)",
    "CREATE INDEX ix_tpl_subject   ON schedule_templates(subject_id)",
    "CREATE INDEX ix_ovr_date      ON schedule_overrides(date, profile_id)",
    "CREATE INDEX ix_periods_range ON study_periods(date_from, date_to)",
    "CREATE INDEX ix_marks_date    ON calendar_day_marks(date)",
    "CREATE INDEX ix_rides_date    ON transport_rides(ride_date)",
    "CREATE INDEX ix_rides_conf    ON transport_rides(confirmation_id)",
    "CREATE INDEX ix_rides_strelka ON transport_rides(payment_method, ride_date)",
    "CREATE INDEX ix_rides_pstart  ON transport_rides(period_start_date)",
    "CREATE INDEX ix_topups_date   ON strelka_topups(topup_date)",
    "CREATE INDEX ix_exams_date    ON exams(date)",
    "CREATE INDEX ix_bells_day     ON bell_profiles(weekday, variant, effective_from)",
    "CREATE INDEX ix_slots_profile ON bell_slots(profile_id, slot_no)",
    "CREATE INDEX ix_parts_slot    ON bell_slot_parts(slot_id, seq)",
    "CREATE INDEX ix_tariffs_kind  ON tariffs(kind, effective_from, effective_to)",
    "CREATE INDEX ix_anchors_from  ON week_anchors(effective_from)",
)


def create_schema(conn: sqlite3.Connection) -> None:
    """Создать схему (18 таблиц + индексы). Вызывается только при инициализации."""
    for statement in _DDL:
        conn.execute(statement)
    for statement in _INDEXES:
        conn.execute(statement)


def table_names(conn: sqlite3.Connection) -> list[str]:
    """Имена пользовательских таблиц БД (для проверок ACC-M-97/DATA-19)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


__all__ = ["TABLE_ORDER", "create_schema", "table_names", "has_table"]
