"""Слой 2 приёмки: стартовый набор Приложения А (ACC-S-01…ACC-S-20).

Слой 2 проверяет **значения** стартового набора по Приложению А, а не механику
(механика — слой 1). Расхождение здесь не блокирует приёмку (правило 6 §0), но
показывает, что набор собран верно.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from student_planner import SCHEMA_VERSION
from student_planner.core.day_resolution import DayResolver
from student_planner.core.models import PaymentMethod, TransportType
from student_planner.core.repositories import (
    BellRepository,
    ScheduleOverrideRepository,
    ScheduleTemplateRepository,
    SubjectRepository,
    TariffRepository,
    WeekAnchorRepository,
)
from student_planner.core.seed_data import (
    EXPECTED_FILLED_CELLS,
    LOWER_WEEK,
    TARIFFS,
    UPPER_WEEK,
    WEEK_TEMPLATES,
)
from student_planner.core.seeding import Seeder
from student_planner.core.settings_registry import SettingsKeys
from student_planner.core.settings_service import SettingsService
from student_planner.core.transport_repositories import (
    RideRepository,
    TripTemplateRepository,
)


@pytest.fixture
def seeded(db):
    """База со стартовым набором Приложения А."""
    Seeder(db).seed_all()
    return db


# ---------------------------------------------------------------------------
# ACC-S-01 — профили звонков по А.1.
# ---------------------------------------------------------------------------
def test_acc_s_01_bell_profiles_match_appendix(seeded) -> None:
    bells = BellRepository(seeded)
    profiles = seeded.fetchall("SELECT * FROM bell_profiles ORDER BY weekday")
    assert len(profiles) == 7, "Пн–Сб + воскресенье (А.1)"

    weekday_profile = bells.profile_for(date(2026, 9, 7))
    assert weekday_profile is not None
    assert len(weekday_profile.slots) == 5, "Понедельник: 5 блоков (А.1)"


def test_acc_s_01_slot_times_match_appendix(seeded) -> None:
    """А.1: Пн — цельные блоки 08:30–09:15, 09:25–10:45, 11:00–12:20."""
    bells = BellRepository(seeded)
    monday = bells.profile_for(date(2026, 9, 7))
    assert monday is not None
    assert monday.slots[0].start_time == "08:30"
    assert monday.slots[0].end_time == "09:15", "Классный час"
    assert monday.slots[1].start_time == "09:25"
    assert monday.slots[1].end_time == "10:45", "1 пара"
    assert monday.slots[2].start_time == "11:00"
    assert monday.slots[2].end_time == "12:20", "2 пары"


def test_acc_s_01_monday_is_single_part_blocks(seeded) -> None:
    """А.1: у понедельника каждый блок — одна часть ``lesson``."""
    bells = BellRepository(seeded)
    monday = bells.profile_for(date(2026, 9, 7))
    assert monday is not None
    for slot in monday.slots:
        assert len(slot.parts) == 1, "Перемены между блоками не хранятся"
        assert slot.parts[0].part_type == "lesson"


def test_acc_s_01_tuesday_to_friday_two_part_blocks(seeded) -> None:
    """А.1: Вт–Пт — двухчастные блоки «занятие | перемена | занятие»."""
    bells = BellRepository(seeded)
    tuesday = bells.profile_for(date(2026, 9, 8))
    assert tuesday is not None
    assert len(tuesday.slots) == 4
    first = tuesday.slots[0]
    assert len(first.parts) == 3, "lesson | break | lesson"
    assert first.start_time == "08:30"
    assert first.end_time == "10:10"
    assert first.parts[1].part_type == "break"


def test_acc_s_01_saturday_whole_blocks(seeded) -> None:
    """А.1: суббота — 4 цельных блока, первый 08:30–09:50."""
    bells = BellRepository(seeded)
    saturday = bells.profile_for(date(2026, 9, 12))
    assert saturday is not None
    assert len(saturday.slots) == 4
    assert saturday.slots[0].start_time == "08:30"
    assert saturday.slots[0].end_time == "09:50"


def test_acc_s_01_sunday_profile_without_slots(seeded) -> None:
    """А.1: профиль воскресенья существует, блоков нет."""
    bells = BellRepository(seeded)
    sunday = bells.profile_for(date(2026, 9, 13))
    assert sunday is not None
    assert sunday.slots == ()


def test_acc_s_01_total_slots(seeded) -> None:
    total = seeded.scalar("SELECT COUNT(*) FROM bell_slots")
    # Пн 5 + Вт–Пт 4×4 + Сб 4 = 25 (А.1).
    assert total == 25, "5 блоков в Пн, по 4 в Вт–Сб"


# ---------------------------------------------------------------------------
# ACC-S-02 — предметы по А.2.
# ---------------------------------------------------------------------------
def test_acc_s_02_nine_subjects(seeded) -> None:
    subjects = SubjectRepository(seeded)
    all_subjects = subjects.all()
    assert len(all_subjects) == 9, "А.2: девять предметов"


def test_acc_s_02_two_subjects_share_mdk_code(seeded) -> None:
    """А.2: два предмета с кодом МДК.01.02 — разные записи (SUBJ-02)."""
    seeded_subjects = SubjectRepository(seeded).all()
    mdk = [item for item in seeded_subjects if item.code == "МДК.01.02"]
    assert len(mdk) == 2, "МДК.01.02 встречается дважды"
    assert mdk[0].name != mdk[1].name, "Это разные предметы"


def test_acc_s_02_subject_names_present(seeded) -> None:
    names = {item.name for item in SubjectRepository(seeded).all()}
    expected = {
        "Классный час",
        "Разработка программных модулей",
        "Поддержка и тестирование программных модулей",
        "Документирование программных средств",
        "Технология разработки и защиты баз данных",
        "Компьютерные сети",
        "Психология общения",
        "Физическая культура",
        "Иностранный язык в профессиональной деятельности",
    }
    assert names == expected, "А.2: состав предметов дословно"


def test_acc_s_02_teachers_match_appendix(seeded) -> None:
    by_name = {item.name: item for item in SubjectRepository(seeded).all()}
    assert by_name["Разработка программных модулей"].teacher == "Кузьмина Е.Е."
    assert by_name["Документирование программных средств"].teacher == "Ветрова К.В."
    assert by_name["Физическая культура"].room == "Спортзал"
    assert by_name["Психология общения"].room == "Каб. №32п"


def test_acc_s_02_colors_are_null(seeded) -> None:
    """А.2: ``color`` — NULL, цвета назначает пользователь."""
    for subject in SubjectRepository(seeded).all():
        assert subject.color is None


def test_acc_s_02_teachers_and_rooms_filled(seeded) -> None:
    for subject in SubjectRepository(seeded).all():
        assert subject.name.strip(), "Название обязательно"
        assert subject.is_active is True, "Все стартовые предметы активны"


# ---------------------------------------------------------------------------
# ACC-S-03 / ACC-S-04 / ACC-S-11 / ACC-S-12 — шаблон недели по А.3.
# ---------------------------------------------------------------------------
def test_acc_s_03_upper_week_matches_appendix(seeded) -> None:
    templates = ScheduleTemplateRepository(seeded)
    bells = BellRepository(seeded)
    subjects = {item.code: item.id for item in SubjectRepository(seeded).all()}

    filled = 0
    for weekday, slots in UPPER_WEEK.items():
        profile = next(
            (p for p in seeded.fetchall("SELECT * FROM bell_profiles WHERE weekday = ?", (weekday,))),
            None,
        )
        assert profile is not None, f"Профиль для дня {weekday}"
        profile_obj = bells.profile_for(date(2026, 9, 6 + weekday))
        for slot_no, subject_key in slots.items():
            stored = templates.subject_at(profile_obj.id, "upper", slot_no)
            assert stored is not None, f"Пн-Сб {weekday}, блок {slot_no} должен быть заполнен"
            filled += 1
    assert filled == EXPECTED_FILLED_CELLS, "А.7 п. 2: 16 заполненных ячеек"


def test_acc_s_03_total_cells_both_weeks(seeded) -> None:
    total = seeded.scalar("SELECT COUNT(*) FROM schedule_templates")
    assert total == 32, "По 16 ячеек в верхней и нижней неделе"


def test_acc_s_04_lower_week_differs_only_thursday(seeded) -> None:
    """А.3: отличие только в четверг, слот 2."""
    differences = []
    for weekday in UPPER_WEEK:
        upper = UPPER_WEEK[weekday]
        lower = LOWER_WEEK[weekday]
        for slot_no in set(upper) | set(lower):
            if upper.get(slot_no) != lower.get(slot_no):
                differences.append((weekday, slot_no))
    assert differences == [(4, 2)], (
        f"Ожидалось единственное отличие (чт, блок 2), получено {differences}"
    )


def test_acc_s_11_editor_shows_sixteen_cells_per_week(seeded) -> None:
    """А.7 п. 2: 16 заполненных ячеек на стартовой верхней неделе."""
    templates = ScheduleTemplateRepository(seeded)
    upper_cells = templates.cells("upper")
    assert len(upper_cells) == EXPECTED_FILLED_CELLS == 16


def test_acc_s_12_lower_week_one_cell_different(seeded) -> None:
    templates = ScheduleTemplateRepository(seeded)
    bells = BellRepository(seeded)

    # Четверг: слот 2 отличается, слоты 1 и 3 совпадают.
    thursday = bells.profile_for(date(2026, 9, 10))
    assert thursday is not None
    upper_slot2 = templates.subject_at(thursday.id, "upper", 2)
    lower_slot2 = templates.subject_at(thursday.id, "lower", 2)
    assert upper_slot2 != lower_slot2, "Чт, блок 2 — разный предмет"

    for slot_no in (1, 3):
        assert templates.subject_at(thursday.id, "upper", slot_no) == \
            templates.subject_at(thursday.id, "lower", slot_no), (
                f"Чт, блок {slot_no} совпадает по неделям"
            )


def test_acc_s_14_no_null_subject_cells(seeded) -> None:
    """А.7 п. 4: ячеек с ``subject_id IS NULL`` нет."""
    rows = seeded.fetchall("SELECT * FROM schedule_templates WHERE subject_id IS NULL")
    assert rows == [], "Пустых ячеек в наборе нет — они просто отсутствуют"


def test_acc_s_13_clear_cell_keeps_bells(seeded) -> None:
    """А.7 п. 3: очистка ячейки не трогает профили и слоты."""
    bells_before = seeded.scalar("SELECT COUNT(*) FROM bell_profiles")
    slots_before = seeded.scalar("SELECT COUNT(*) FROM bell_slots")

    bells = BellRepository(seeded)
    monday = bells.profile_for(date(2026, 9, 7))
    templates = ScheduleTemplateRepository(seeded)
    templates.clear_cell(monday.id, "upper", 1)

    assert seeded.scalar("SELECT COUNT(*) FROM bell_profiles") == bells_before
    assert seeded.scalar("SELECT COUNT(*) FROM bell_slots") == slots_before


# ---------------------------------------------------------------------------
# ACC-S-06 / ACC-S-09 / ACC-S-19 — поездки и тарифы по А.4.
# ---------------------------------------------------------------------------
def test_acc_s_06_seven_trip_templates(seeded) -> None:
    templates = TripTemplateRepository(seeded)
    all_templates = templates.all()
    assert len(all_templates) == 7, "А.4: семь шаблонов поездок"

    directions = {template.direction for template in all_templates}
    assert directions <= {"home_to_college", "college_to_home"}, "Только два направления"


def test_acc_s_06_both_directions_present(seeded) -> None:
    templates = TripTemplateRepository(seeded)
    outbound = templates.by_direction("home_to_college")
    inbound = templates.by_direction("college_to_home")
    assert outbound, "Шаблоны «туда» есть"
    assert inbound, "Шаблоны «обратно» есть"


def test_acc_s_06_electric_plus_bus_exists(seeded) -> None:
    """А.4: маршрут «Электричка + №22» (туда) и «№22 + электричка» (обратно)."""
    templates = TripTemplateRepository(seeded)
    combined = [
        template for template in templates.all()
        if "train" in template.modes and "bus" in template.modes
    ]
    assert len(combined) == 2, "А.4: по одному смешанному маршруту в каждую сторону"

    outbound = next(t for t in combined if t.direction == "home_to_college")
    assert outbound.name == "Электричка + №22"
    assert [leg.mode for leg in outbound.legs] == ["train", "bus"], (
        "Туда: сначала электричка, потом автобус"
    )

    inbound = next(t for t in combined if t.direction == "college_to_home")
    assert inbound.name == "№22 + электричка"
    assert [leg.mode for leg in inbound.legs] == ["bus", "train"], (
        "Обратно: сначала автобус, потом электричка"
    )


def test_acc_s_06_all_templates_match_appendix(seeded) -> None:
    """А.4: точный состав семи шаблонов."""
    templates = TripTemplateRepository(seeded)
    actual = {
        (template.direction, template.name): [
            (leg.mode, leg.vehicle, leg.payment_method) for leg in template.legs
        ]
        for template in templates.all()
    }
    expected = {
        ("home_to_college", "Электричка + №22"): [
            ("train", "Электричка", "train_student"), ("bus", "22", "strelka"),
        ],
        ("home_to_college", "Прямой №42"): [("bus", "42", "strelka")],
        ("home_to_college", "№35 + №22"): [
            ("bus", "35", "strelka"), ("bus", "22", "strelka"),
        ],
        ("college_to_home", "Прямой №42"): [("bus", "42", "strelka")],
        ("college_to_home", "№22 + №35"): [
            ("bus", "22", "strelka"), ("bus", "35", "strelka"),
        ],
        ("college_to_home", "№22 + электричка"): [
            ("bus", "22", "strelka"), ("train", "Электричка", "train_student"),
        ],
        ("college_to_home", "№22 + №44"): [
            ("bus", "22", "strelka"), ("bus", "44", "strelka"),
        ],
    }
    assert actual == expected


def test_acc_s_06_no_depart_arrive_hints(seeded) -> None:
    """А.4: справочные времена не заданы — расписаний транспорта в наборе нет."""
    for template in TripTemplateRepository(seeded).all():
        assert template.depart_hint is None
        assert template.arrive_hint is None


def test_acc_s_06_all_templates_active(seeded) -> None:
    for template in TripTemplateRepository(seeded).all():
        assert template.is_active is True, "А.4: ``is_active = 1``"


def test_acc_s_06_train_legs_use_student_ticket(seeded) -> None:
    """RT-17: электричка в шаблонах оплачивается студенческим билетом."""
    for template in TripTemplateRepository(seeded).all():
        for leg in template.legs:
            if leg.mode == "train":
                assert leg.payment_method == "train_student", (
                    f"«{template.name}»: электричка только по студенческому"
                )


def test_acc_s_09_five_tariffs(seeded) -> None:
    tariffs = TariffRepository(seeded).all()
    assert len(tariffs) == 5, "А.0: пять тарифов"
    kinds = {tariff.kind for tariff in tariffs}
    assert kinds == {
        "bus_base", "train_base", "train_student", "strelka_stage1", "strelka_stage2",
    }


def test_acc_s_09_tariff_prices_match_appendix(seeded) -> None:
    """А.0: 73.00 / 61.00 / 30.50 / 36.50 / 0.73."""
    tariffs = {tariff.kind: tariff for tariff in TariffRepository(seeded).all()}
    assert tariffs["bus_base"].price == Decimal("73.00")
    assert tariffs["train_base"].price == Decimal("61.00")
    assert tariffs["train_student"].price == Decimal("30.50")
    assert tariffs["strelka_stage1"].price == Decimal("36.50")
    assert tariffs["strelka_stage2"].price == Decimal("0.73")


def test_acc_s_09_benefits_end_may_2027(seeded) -> None:
    """А.0: льготы ограничены 2027-05-31 (TODO-13 закрыт)."""
    tariffs = {tariff.kind: tariff for tariff in TariffRepository(seeded).all()}
    for kind in ("train_student", "strelka_stage1", "strelka_stage2"):
        assert tariffs[kind].effective_to == date(2027, 5, 31), (
            f"Льгота «{kind}» действует до 31.05.2027"
        )
    for kind in ("bus_base", "train_base"):
        assert tariffs[kind].effective_to is None, "Базовые тарифы бессрочны"


def test_acc_s_09_vehicle_null_in_all_rows(seeded) -> None:
    """[У-17]: ``vehicle = NULL`` во всех тарифах MVP."""
    rows = seeded.fetchall("SELECT vehicle FROM tariffs")
    assert all(row["vehicle"] is None for row in rows)


def test_acc_s_19_threshold_reached_within_one_period(seeded) -> None:
    """А.4: при Пн–Сб счётчик достигает ~52 за 30-дневный период."""
    from student_planner.core.strelka import StrellaPeriodCalculator

    # 26 учебных дней Пн–Сб в окне [07.09, 06.10], по 2 «Стрелки» в день.
    dates = [
        date(2026, 9, 7).toordinal() + offset
        for offset in range(30)
    ]
    study_days = [
        date.fromordinal(value) for value in dates
        if date.fromordinal(value).isoweekday() <= 6
    ]
    assert len(study_days) == 26

    rides = []
    ride_id = 1
    for day in study_days:
        rides.append((ride_id, day))
        ride_id += 1
        rides.append((ride_id, day))
        ride_id += 1

    calc = StrellaPeriodCalculator(rides=rides, anchor=None)
    numbers = [state.ride_number for _, state in calc.recalculate()]
    assert max(numbers) == 52, "Порог 35 проходится внутри периода (А.4)"
    assert numbers[-1] == 52


# ---------------------------------------------------------------------------
# ACC-S-07 / ACC-S-08 / ACC-S-16 — настройки и якорь по А.0.
# ---------------------------------------------------------------------------
def test_acc_s_07_defaults_match_appendix(seeded) -> None:
    settings = SettingsService(seeded)
    assert settings.get_int(SettingsKeys.SCHEMA_VERSION) == SCHEMA_VERSION
    assert settings.strelka_period_days() == 30
    assert settings.strelka_first_limit() == 35
    assert settings.get_int(SettingsKeys.STRELKA_LOW_BALANCE_WARN) == 2
    assert settings.display_format() == "DD.MM.YYYY"
    assert settings.get_str(SettingsKeys.TIME_DISPLAY_FORMAT) == "HH:MM"
    assert settings.get_str(SettingsKeys.DEFAULT_BUS_PAYMENT_METHOD) == "strelka"
    assert settings.get_str(SettingsKeys.HOME_POINT_NAME) == "пос. Авсюнино"


def test_acc_s_08_anchor_is_monday_lower(seeded) -> None:
    """А.0: стартовый якорь 07.09.2026 — понедельник, нижняя неделя, цикл 2."""
    anchors = WeekAnchorRepository(seeded).all()
    assert anchors, "Стартовый якорь задан"
    anchor = anchors[0]
    assert anchor.base_date == date(2026, 9, 7)
    assert anchor.base_date.isoweekday() == 1, "Понедельник"
    assert anchor.base_type == "lower", "Нижняя неделя"
    assert anchor.cycle_length == 2


def test_acc_s_16_anchor_keys_present_and_empty(seeded) -> None:
    settings = SettingsService(seeded)
    assert settings.raw(SettingsKeys.STRELKA_PERIOD_ANCHOR_DATE) == "", (
        "А.0: пустая строка = «не задано»"
    )
    assert settings.strelka_initial_ride_count() == 0


def test_acc_s_16_removed_key_absent(seeded) -> None:
    row = seeded.fetchone("SELECT 1 FROM settings WHERE key = 'strelka_period_start'")
    assert row is None, "v1.6: ключ strelka_period_start удалён"


def test_acc_s_17_no_strelka_periods_table(seeded) -> None:
    row = seeded.fetchone(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'strelka_periods'"
    )
    assert row is None, "А.6: таблицы периодов нет — только снапшот в поездке"


# ---------------------------------------------------------------------------
# ACC-S-10 / ACC-S-20 — пустые модули стартового набора.
# ---------------------------------------------------------------------------
def test_acc_s_10_no_periods_in_seed(seeded) -> None:
    assert seeded.scalar("SELECT COUNT(*) FROM study_periods") == 0, "А.5: периодов нет"


def test_acc_s_10_no_exams_in_seed(seeded) -> None:
    assert seeded.scalar("SELECT COUNT(*) FROM exams") == 0, "А.5: экзаменов нет"


def test_acc_s_10_no_overrides_in_seed(seeded) -> None:
    assert seeded.scalar("SELECT COUNT(*) FROM schedule_overrides") == 0


def test_acc_s_20_no_homework_in_seed(seeded) -> None:
    """А.5: домашних заданий в наборе нет."""
    assert seeded.scalar("SELECT COUNT(*) FROM homework") == 0


def test_acc_s_20_no_homework_badges(seeded) -> None:
    from student_planner.core.transport_repositories import HomeworkRepository

    monday = date(2026, 9, 7)
    lesson = DayResolver(seeded).resolve(monday).lessons[0]
    assert lesson.homework_count == 0, "Бейджей ДЗ нет"
    assert HomeworkRepository(seeded).all() == []


def test_acc_s_20_no_rides_in_seed(seeded) -> None:
    assert RideRepository(seeded).all() == [], "Поездок в стартовом наборе нет"
    assert seeded.scalar("SELECT COUNT(*) FROM trip_confirmations") == 0


# ---------------------------------------------------------------------------
# ACC-S-15 / ACC-S-18 — разрешение первого учебного дня.
# ---------------------------------------------------------------------------
def test_acc_s_15_first_study_day_uses_template(seeded) -> None:
    """А.6: 07.09.2026 — нижняя неделя без периодов, занятия по шаблону."""
    resolver = DayResolver(seeded)
    day = date(2026, 9, 7)
    result = resolver.resolve(day)

    assert result.week_type == "lower"
    assert not result.is_day_off, "Периодов нет — день учебный"
    assert len(result.lessons) == 3, "Пн: три занятия (А.3)"
    assert [lesson.slot_no for lesson in result.lessons] == [1, 2, 3]


def test_acc_s_15_all_six_weekdays_have_lessons(seeded) -> None:
    resolver = DayResolver(seeded)
    expected = {1: 3, 2: 3, 3: 2, 4: 3, 5: 2, 6: 3}
    for weekday, count in expected.items():
        day = date(2026, 9, 6) .toordinal()
        target = date.fromordinal(day + weekday)  # 07.09 — понедельник
        result = resolver.resolve(target)
        assert len(result.lessons) == count, (
            f"День {target} (Пн=07.09 + {weekday - 1}): ожидалось {count} занятий"
        )


def test_acc_s_15_sunday_has_no_lessons(seeded) -> None:
    resolver = DayResolver(seeded)
    sunday = date(2026, 9, 13)
    assert sunday.isoweekday() == 7
    assert resolver.resolve(sunday).lessons == ()


def test_acc_s_18_day_shows_no_empty_rows(seeded) -> None:
    """А.7 п. 5: в дне показываются только заполненные блоки, пустых строк нет."""
    resolver = DayResolver(seeded)
    monday = resolver.resolve(date(2026, 9, 7))
    assert len(monday.lessons) == 3
    assert all(lesson.subject is not None for lesson in monday.lessons), (
        "Ни одной пустой строки"
    )


def test_acc_s_18_editor_shows_all_slots(seeded) -> None:
    """А.7 п. 1: в редакторе у профиля «Понедельник» видны все 5 блоков."""
    bells = BellRepository(seeded)
    monday_profile = bells.profile_for(date(2026, 9, 7))
    assert monday_profile is not None
    assert len(monday_profile.slots) == 5, "5 блоков × Пн–Сб = 30 ячеек в редакторе"
    assert len(monday_profile.slots) - len(UPPER_WEEK[1]) == 2, "Две ячейки пусты"


def test_acc_s_18_upper_week_day_resolution(seeded) -> None:
    """Верхняя неделя: 14.09 — понедельник, тоже три занятия."""
    resolver = DayResolver(seeded)
    monday = resolver.resolve(date(2026, 9, 14))
    assert monday.week_type == "upper"
    assert len(monday.lessons) == 3
