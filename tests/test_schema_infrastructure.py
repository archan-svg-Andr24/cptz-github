"""Слой 1: инфраструктура БД, схема и версия (ACC-M-68…73, 97, 99…101).

Проверки этапа 1 §1.12: «Схема БД (Прил. Б), инициализация».
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from student_planner import SCHEMA_VERSION
from student_planner.core.database import (
    Database,
    create_database,
    is_initialized,
    open_database,
)
from student_planner.core.errors import SchemaVersionError
from student_planner.core.schema import TABLE_ORDER, table_names
from student_planner.core.seeding import Seeder
from student_planner.core.settings_registry import SettingsKeys
from student_planner.core.settings_service import SettingsService


# ---------------------------------------------------------------------------
# ACC-M-97 — в схеме 18 таблиц, нет таблиц расписаний рейсов/остановок.
# ---------------------------------------------------------------------------
def test_acc_m_97_schema_has_18_tables_and_no_timetables(db: Database) -> None:
    names = table_names(db.connection)
    assert len(names) == 18, f"Ожидалось 18 таблиц, получено {len(names)}: {names}"
    assert set(names) == set(TABLE_ORDER)

    # RT-05 / [У-3]: приложение не хранит расписаний транспорта.
    forbidden = ("timetable", "timetables", "schedule_stops", "stops", "routes_schedule")
    for name in names:
        assert name not in forbidden, f"Таблица расписания рейсов недопустима: {name}"
        assert "timetable" not in name.lower()

    # Таблицы-заготовки v1.1 присутствуют, чтобы возврат не требовал миграции.
    assert "calendar_day_marks" in names
    assert "exams" in names

    # Резервные столбцы сохранены в рабочей схеме (Прил. Б).
    ride_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(transport_rides)")}
    assert {"period_start_date", "ride_number_in_period", "price_locked"} <= ride_columns
    tariff_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(tariffs)")}
    assert "vehicle" in tariff_columns
    template_columns = {row["name"] for row in db.fetchall("PRAGMA table_info(schedule_templates)")}
    assert "group_mark" in template_columns


# ---------------------------------------------------------------------------
# ACC-M-99 — файл создаётся в каталоге, каталог создаётся, journal_mode = delete.
# ---------------------------------------------------------------------------
def test_acc_m_99_creates_directory_and_uses_delete_journal(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "student_planner.db"
    assert not target.parent.exists()

    database = create_database(target)
    try:
        assert target.exists(), "Файл БД должен быть создан"
        assert target.parent.is_dir(), "Каталог БД должен быть создан автоматически (DATA-03)"
        assert database.journal_mode() == "delete", "DATA-04 требует journal_mode = DELETE"
        assert database.foreign_keys_enabled(), "DATA-15 требует включённых внешних ключей"
        assert is_initialized(target)
    finally:
        database.close()


def test_acc_m_99_file_is_portable_copy(tmp_path: Path) -> None:
    """GEN-16: файл переносится копированием и открывается без конвертации."""
    source = tmp_path / "student_planner.db"
    db = create_database(source)
    Seeder(db).seed_all()
    db.close()

    copy_path = tmp_path / "moved" / "student_planner.db"
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    copy_path.write_bytes(source.read_bytes())

    moved = open_database(copy_path)
    try:
        count = moved.scalar("SELECT COUNT(*) FROM subjects")
        assert count and count > 0
    finally:
        moved.close()


# ---------------------------------------------------------------------------
# ACC-M-71 / ACC-M-72 — несовпадение версии схемы: отказ старта, файл не изменён.
# ---------------------------------------------------------------------------
def _make_db_with_version(tmp_path: Path, version: str) -> Path:
    path = tmp_path / "versioned.db"
    db = create_database(path)
    Seeder(db).seed_all()
    db.execute(
        "UPDATE settings SET value = ? WHERE key = ?", (version, SettingsKeys.SCHEMA_VERSION)
    )
    db.commit()
    db.close()
    return path


def test_acc_m_71_schema_version_above_known_refuses_start(tmp_path: Path) -> None:
    newer = str(SCHEMA_VERSION + 1)
    path = _make_db_with_version(tmp_path, newer)
    before = path.read_bytes()

    with pytest.raises(SchemaVersionError) as excinfo:
        open_database(path)
    assert newer in str(excinfo.value)
    assert "не изменяло" in str(excinfo.value)
    assert path.read_bytes() == before, "Файл БД не должен изменяться при отказе (DATA-19)"


def test_acc_m_72_schema_version_below_known_refuses_start(tmp_path: Path) -> None:
    path = _make_db_with_version(tmp_path, "0")
    before = path.read_bytes()
    with pytest.raises(SchemaVersionError):
        open_database(path)
    assert path.read_bytes() == before


def test_acc_m_72_missing_schema_key_refuses_start(tmp_path: Path) -> None:
    """Отсутствующий ключ версии трактуется как несовпадение (DATA-19, ACC-M-72).

    По ТЗ «ниже известного» включает и отсутствующий ключ: приложение не имеет
    права молча дописать версию в чужой файл, потому что не знает, совместима
    ли его схема.
    """
    path = tmp_path / "nokey.db"
    db = create_database(path)
    Seeder(db).seed_all()
    db.execute("DELETE FROM settings WHERE key = ?", (SettingsKeys.SCHEMA_VERSION,))
    db.commit()
    db.close()

    before = path.read_bytes()
    with pytest.raises(SchemaVersionError) as excinfo:
        open_database(path)
    assert "отсутствует ключ" in str(excinfo.value)
    assert "не изменяло" in str(excinfo.value)
    assert path.read_bytes() == before, "Файл не изменяется при отказе (DATA-19)"

    # Тот же отказ и на пути создания: файл существует и не пуст.
    with pytest.raises(SchemaVersionError):
        create_database(path)
    assert path.read_bytes() == before


def test_schema_version_written_as_official_value(db: Database) -> None:
    service = SettingsService(db)
    assert service.get_int(SettingsKeys.SCHEMA_VERSION) == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# ACC-M-68 / ACC-M-69 — идемпотентность набора и точечное восстановление.
# ---------------------------------------------------------------------------
def test_acc_m_68_seeding_is_idempotent(db: Database) -> None:
    seeder = Seeder(db)
    first = seeder.seed_all()
    assert first.total > 0

    def snapshot() -> dict[str, int]:
        return {
            table: int(db.scalar(f"SELECT COUNT(*) FROM {table}") or 0)
            for table in (
                "settings", "subjects", "tariffs", "bell_profiles", "bell_slots",
                "bell_slot_parts", "week_anchors", "schedule_templates",
                "trip_templates", "trip_template_legs",
            )
        }

    before = snapshot()
    second = seeder.seed_all()
    assert second.total == 0, "Повторная загрузка не должна добавлять записи (FIRST-04)"
    assert snapshot() == before, "Повторный запуск не дублирует стартовый набор"


def test_acc_m_69_restore_adds_only_missing(db: Database, subjects) -> None:
    """FIRST-05: восстанавливаются только отсутствующие, изменённые не трогаются.

    «Изменённая запись» — та, что осталась на месте, но с другими полями
    (например, преподавателем): её восстановление не перезаписывает. Если же
    запись набора исчезла (удалена или переименована, то есть записи с таким
    именем и кодом больше нет), она считается отсутствующей и доливается — это и
    есть буквальный смысл FIRST-05.
    """
    seeder = Seeder(db)
    seeder.seed_all()

    # Изменяем поля существующей записи, не меняя её идентичности (имя и код).
    target = next(item for item in subjects.all() if item.name == "Психология общения")
    subjects.update(target.id, teacher="Другой преподаватель", room="Каб. №99")

    # Удаляем запись набора целиком, тариф и одну ячейку шаблона.
    # Удаление предмета через репозиторий запрещено (HW-09/SUBJ-04: он используется
    # в шаблоне), поэтому исчезновение записи имитируется прямым удалением строк,
    # которые на неё ссылаются, — так проверяется именно поведение восстановления.
    removed = next(item for item in subjects.all() if item.name == "Физическая культура")
    removed_slots = int(
        db.scalar("SELECT COUNT(*) FROM schedule_templates WHERE subject_id = ?", (removed.id,)) or 0
    )
    assert removed_slots == 2, "Физкультура стоит в двух ячейках стартового набора (А.3)"
    db.execute("DELETE FROM schedule_templates WHERE subject_id = ?", (removed.id,))
    db.execute("DELETE FROM subjects WHERE id = ?", (removed.id,))
    db.execute("DELETE FROM tariffs WHERE kind = 'strelka_stage2'")
    deleted_cell = db.fetchone("SELECT * FROM schedule_templates ORDER BY id LIMIT 1")
    db.execute("DELETE FROM schedule_templates WHERE id = ?", (deleted_cell["id"],))
    db.commit()

    summary = seeder.seed_missing()
    assert summary.subjects_added == 1, "Удалённый предмет должен вернуться"
    assert summary.tariffs_added == 1, "Удалённый тариф должен вернуться"
    # Вернулись ячейки, ссылавшиеся на удалённый предмет, и удалённая вручную.
    assert summary.cells_added == removed_slots + 1, (
        "Ячейки шаблона, ссылавшиеся на удалённый предмет, возвращаются вместе с ним"
    )

    changed = subjects.by_id(target.id)
    assert changed is not None
    assert changed.teacher == "Другой преподаватель", (
        "Изменённая пользователем запись не должна перезаписываться (FIRST-05)"
    )
    assert changed.room == "Каб. №99"
    assert len(subjects.all()) == 9, "Дубли предметов недопустимы"

    # Повторное восстановление ничего не добавляет — операция идемпотентна.
    again = seeder.seed_missing()
    assert again.total == 0


# ---------------------------------------------------------------------------
# ACC-M-100 — атомарность: ошибка в середине записи откатывает всё.
# ---------------------------------------------------------------------------
def test_acc_m_100_transaction_rolls_back_entirely(db: Database, subjects, bells) -> None:
    subject = subjects.create("Алгебра", code="ALG")
    profile = bells.create_profile(1, "Понедельник")
    before = int(db.scalar("SELECT COUNT(*) FROM schedule_templates") or 0)

    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, "
                "effective_from) VALUES (?, 'lower', 1, NULL, ?, '0001-01-01')",
                (profile.id, subject.id),
            )
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, "
                "effective_from) VALUES (?, 'lower', 2, NULL, ?, '0001-01-01')",
                (profile.id, subject.id),
            )
            raise RuntimeError("принудительная ошибка в середине записи")

    after = int(db.scalar("SELECT COUNT(*) FROM schedule_templates") or 0)
    assert after == before, "Частичных строк не остаётся (DATA-08, ACC-M-100)"


def test_nested_transaction_is_atomic(db: Database, subjects, bells) -> None:
    """Вложенность не ломает атомарность каскада (CALC-04 работает внутри транзакции)."""
    subject = subjects.create("Алгебра", code="ALG")
    profile = bells.create_profile(1, "Понедельник")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, effective_from) "
            "VALUES (?, 'lower', 1, NULL, ?, '0001-01-01')",
            (profile.id, subject.id),
        )
        with db.transaction() as inner:
            inner.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, "
                "effective_from) VALUES (?, 'lower', 2, NULL, ?, '0001-01-01')",
                (profile.id, subject.id),
            )
        # Внутренняя транзакция не коммитит сама по себе.
    assert int(db.scalar("SELECT COUNT(*) FROM schedule_templates") or 0) == 2


def test_nested_transaction_rollback_on_error(db: Database, subjects, bells) -> None:
    """Откат вложенного блока снимает только его изменения; внешние — откатываются целиком."""
    subject = subjects.create("Алгебра", code="ALG")
    profile = bells.create_profile(1, "Понедельник")
    with pytest.raises(ValueError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, "
                "effective_from) VALUES (?, 'lower', 1, NULL, ?, '0001-01-01')",
                (profile.id, subject.id),
            )
            with db.transaction() as inner:
                inner.execute(
                    "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, "
                    "subject_id, effective_from) VALUES (?, 'lower', 2, NULL, ?, '0001-01-01')",
                    (profile.id, subject.id),
                )
                raise ValueError("ошибка внутри вложенной транзакции")
    assert int(db.scalar("SELECT COUNT(*) FROM schedule_templates") or 0) == 0


def test_inner_rollback_keeps_outer_committed(db: Database, subjects, bells) -> None:
    """SAVEPOINT: неудача внутреннего блока не отменяет уже сделанное внешним.

    Это требование CALC-04: пересчёт идёт внутри транзакции сервиса, и его
    внутренние операции не должны разваливать внешнюю атомарность при успехе.
    """
    subject = subjects.create("Алгебра", code="ALG")
    profile = bells.create_profile(1, "Понедельник")
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, effective_from) "
            "VALUES (?, 'lower', 1, NULL, ?, '0001-01-01')",
            (profile.id, subject.id),
        )
        try:
            with db.transaction() as inner:
                inner.execute(
                    "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, "
                    "subject_id, effective_from) VALUES (?, 'lower', 2, NULL, ?, '0001-01-01')",
                    (profile.id, subject.id),
                )
                raise ValueError("внутренняя операция не удалась")
        except ValueError:
            pass
    rows = db.fetchall("SELECT slot_no FROM schedule_templates ORDER BY slot_no")
    assert [row["slot_no"] for row in rows] == [1]


# ---------------------------------------------------------------------------
# ACC-M-101 — объём хранилища: 5000 поездок ≤ 2 МБ, рост линейный.
# ---------------------------------------------------------------------------
def _bulk_insert_rides(db: Database, count: int, start: date = date(2026, 9, 1)) -> None:
    """Массовая вставка поездок для эталонной фикстуры NFR-03/NFR-10."""
    rows = []
    from datetime import timedelta

    for index in range(count):
        ride_date = start + timedelta(days=index // 2)
        rows.append(
            (
                ride_date.isoformat(), ride_date.isoformat(), "home_to_college",
                "bus", "22", "50.00", "25.00", "25.00", "strelka",
                f"2026-09-01 08:00:{index % 60:02d}",
            )
        )
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO transport_rides(study_date, ride_date, direction, transport_type, "
            "vehicle, base_price, paid_price, discount_amount, payment_method, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def test_acc_m_101_storage_size_linear(db: Database, tmp_path: Path) -> None:
    """NFR-12: размер файла линеен числу поездок, эталон 5000 ≤ 2 МБ.

    500 поездок — это 10 % от эталона. Файл содержит ещё и схему с индексами
    (~200 КБ), поэтому проверяется не «≤ 20 % эталона» целиком, а линейность
    приращения: прирост на 500 поездках не превышает ~2× прироста на 250, а
    прирост на 5000 — не более чем десятикратный прирост на 500 с запасом.
    """

    def measured(count: int) -> int:
        with db.transaction() as conn:
            conn.execute("DELETE FROM transport_rides")
        _bulk_insert_rides(db, count)
        db.commit()
        db.execute("VACUUM")
        return db.path.stat().st_size

    baseline = measured(0)
    size_500 = measured(500)
    size_5000 = measured(5000)

    assert int(db.scalar("SELECT COUNT(*) FROM transport_rides") or 0) == 5000
    assert size_5000 <= 2 * 1024 * 1024, (
        f"Файл на 5000 поездок занимает {size_5000} байт, ожидалось ≤ 2 МБ (NFR-12)"
    )

    growth_500 = size_500 - baseline
    growth_5000 = size_5000 - baseline
    assert growth_5000 > growth_500, "Рост должен наблюдаться"
    # Линейность: 10× поездок даёт не более ~12× прироста (допуск на страницы).
    ratio = growth_5000 / max(growth_500, 1)
    assert ratio <= 12, (
        f"Прирост на 5000 поездок в {ratio:.1f} раза больше прироста на 500 — "
        f"рост нелинеен (NFR-12)"
    )


def test_foreign_keys_prevent_dangling_references(db: Database) -> None:
    """DATA-15: ссылочная целостность обеспечивается внешними ключами."""
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO schedule_templates(profile_id, week_type, slot_no, group_mark, subject_id, effective_from) "
                "VALUES (999, 'lower', 1, NULL, NULL, '0001-01-01')"
            )


def test_checks_reject_invalid_enum_values(db: Database, subjects) -> None:
    """CHECK-ограничения схемы: статусы и типы вне домена не принимаются."""
    subject = subjects.create("Алгебра")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO homework(subject_id, group_mark, due_date, description, status, created_at) "
                "VALUES (?, NULL, '2026-09-10', 'x', 'overdue', '2026-09-01 00:00:00')",
                (subject.id,),
            )
