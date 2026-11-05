"""Сокращённые названия предметов: стандартные наборы и автоматические сокращения.

Модуль намеренно не зависит ни от БД, ни от сервисов: им пользуются и реестр
настроек (значения по умолчанию), и сервис коротких имён, и интерфейс. Такая
развязка исключает циклический импорт «реестр → сервис → реестр».

Зачем сокращения нужны:

* колонка дня в расписании узкая, а названия вроде «Иностранный язык в
  профессиональной деятельности» занимают три-четыре строки и вытесняют пары;
* сокращённая подпись должна оставаться узнаваемой, поэтому у стандартных
  предметов сокращения заданы вручную, а не вычислены.

Предусмотрены **два набора** (как в исходной таблице предметов):

* ``medium`` — средние сокращения для обычной работы: «Разработка ПМ»,
  «Комп. сети», «Физкультура»;
* ``short`` — минимальные для плотной сетки недели, где на день приходится
  ~150 px: «РПМ», «КС», «Физ-ра».

Набор выбирается настройкой ``subject_abbreviations_style``, а отдельные
сокращения можно переопределить в ``subject_short_names`` (строки
«Название=Сокращение»). Переопределения не смешиваются со стандартными: смена
набора не стирает правки пользователя.
"""

from __future__ import annotations

import re
from typing import Final

#: Средние сокращения: читаемые, для обычного показа расписания.
STOCK_MEDIUM_NAMES: Final[dict[str, str]] = {
    "Классный час": "Кл. час",
    "Разработка программных модулей": "Разработка ПМ",
    "Поддержка и тестирование программных модулей": "Поддержка и тестир. ПМ",
    "Документирование программных средств": "Документир. ПС",
    "Технология разработки и защиты баз данных": "Технология БД",
    "Компьютерные сети": "Комп. сети",
    "Психология общения": "Псих. общения",
    "Физическая культура": "Физкультура",
    "Иностранный язык в профессиональной деятельности": "Ин. язык (проф.)",
}

#: Минимальные сокращения: для плотной сетки недели. Коды МДК в подписи не
#: повторяются — на карточке пары код не выводится, и «МДК 01.01 · РПМ» было бы
#: длиннее полного названия.
STOCK_MINIMAL_NAMES: Final[dict[str, str]] = {
    "Классный час": "Кл. Ч",
    "Разработка программных модулей": "РПМ",
    "Поддержка и тестирование программных модулей": "ПиТПМ",
    "Документирование программных средств": "Док. ПС",
    "Технология разработки и защиты баз данных": "ТРиЗБД",
    "Компьютерные сети": "КС",
    "Психология общения": "Псих. общ.",
    "Физическая культура": "Физ-ра",
    "Иностранный язык в профессиональной деятельности": "Ин. яз.",
}

#: Наборы сокращений по стилю.
STOCK_NAMES_BY_STYLE: Final[dict[str, dict[str, str]]] = {
    "medium": STOCK_MEDIUM_NAMES,
    "short": STOCK_MINIMAL_NAMES,
}

#: Средний набор — стиль по умолчанию.
DEFAULT_STYLE: Final = "medium"

#: Код предмета вида «МДК.01.02», «ОП.03», «ЕН.01» — такие слова не сокращаются.
_CODE_RE: Final = re.compile(r"^[А-ЯЁA-Z]{1,6}[.\-]?\d{1,4}([.\-]\d{1,4})*$")

#: Гласные, которые не должны оставаться в конце обрубка («Докуме.», «програ.»).
_VOWELS: Final = "аеёиоуыэюя"

#: Слово короче этого не трогаем: «сети», «час», «ПМ», «БД» и так короткие.
_KEEP_WORD: Final = 5

#: Длина обрубка длинного слова: шесть букв дают узнаваемое «Поддер.», «Докум.».
_STEM_LENGTH: Final = 6

#: Предел длины подписи, дальше — многоточие.
DEFAULT_MAX_LENGTH: Final = 26


def _stem(word: str) -> str:
    """Обрубок длинного слова: не длиннее ``_STEM_LENGTH`` и без гласной на конце."""
    stem = word[:_STEM_LENGTH]
    while stem and stem[-1].lower() in _VOWELS:
        stem = stem[:-1]
    # Слово из одних гласных не должно исчезнуть целиком.
    return stem or word[:_STEM_LENGTH]


def _shorten_word(token: str, *, keep_whole: bool) -> str:
    """Сократить одно слово (или часть слова через дефис)."""
    if keep_whole or len(token) <= _KEEP_WORD:
        return token
    return _stem(token) + "."


def abbreviate(name: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Сократить название предмета, если стандартного сокращения нет.

    Правило простое и предсказуемое: короткие слова и коды предметов
    («МДК.01.02») остаются как есть, длинные обрубаются до шести букв, последнее
    слово сохраняется целиком, если оно не длиннее десяти букв. Так «Поддержка и
    тестирование программных модулей» превращается в «Поддер. и тестир.
    программ. модулей», а «Компьютерные сети» — в «Компьют. сети».

    Результат ограничивается ``max_length``, чтобы подпись не вылезала за
    колонку дня. Обрезка идёт по границе слова: «Иностр. язык…» читается, а
    «профес. де…» — как опечатка. Функция идемпотентна: сокращённое повторно не
    портится — «Комп. сети» короче предела и вернётся без изменений.
    """
    text = " ".join((name or "").split())
    if not text:
        return ""
    if len(text) <= 12:
        return text

    words = text.split()
    parts: list[str] = []
    for index, word in enumerate(words):
        token = word.strip(",;:()")
        if not token:
            continue
        if _CODE_RE.match(token) or sum(char.isdigit() for char in token) > 1:
            # Код предмета — часть идентичности, его не уродуем.
            parts.append(token)
            continue
        is_last = index == len(words) - 1
        keep_whole = is_last and len(token) <= 10
        if "-" in token:
            # «Веб-разработка» сокращается по частям: «Веб-разраб.».
            parts.append(
                "-".join(
                    _shorten_word(part, keep_whole=keep_whole)
                    for part in token.split("-")
                    if part
                )
            )
            continue
        parts.append(_shorten_word(token, keep_whole=keep_whole))

    result = " ".join(parts)
    if max_length and len(result) > max_length:
        # Обрезаем по границе слова, а не посреди слова: «профес. де…» читается
        # как опечатка, а «Иностр. язык…» — как сокращение.
        while parts and len(" ".join(parts)) > max_length - 1:
            parts.pop()
        result = (" ".join(parts) or text[: max_length - 1]).rstrip(" .,") + "…"
    return result


#: Разделитель вариантов в строке таблицы: «Название=среднее|минимальное».
VARIANT_SEPARATOR: Final = "|"

#: Маркер «показывать полное название»: пустая ячейка означает «не задано»,
#: а прочерк — осознанный отказ от сокращения именно в этом варианте.
NO_SHORTENING: Final = "-"


def parse_short_names(text: str) -> dict[str, tuple[str | None, str | None]]:
    """Разобрать таблицу «Название=среднее|минимальное» (строка на предмет).

    Значение каждой стороны:

    * пусто — вариант не переопределён, берётся из стандартного набора;
    * ``-`` — сокращение для этого предмета отключено, показывать полное имя;
    * текст — своё сокращение.

    Строка без разделителя ``|`` (вид прежних версий «Название=Сокращение»)
    задаёт сразу оба варианта: правка пользователя не должна пропадать.

    Пустые строки и строки, начинающиеся с ``#``, пропускаются — их удобно
    использовать как комментарии при ручной правке значения настройки. Строка
    без ``=`` игнорируется: испорченное значение не должно ронять расписание.
    """
    result: dict[str, tuple[str | None, str | None]] = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        name = name.strip()
        if not name:
            continue
        if VARIANT_SEPARATOR not in raw:
            legacy = _variant_value(raw.strip())
            result[name] = (legacy, legacy)
            continue
        medium, _, minimal = raw.partition(VARIANT_SEPARATOR)
        result[name] = (
            _variant_value(medium.strip()),
            _variant_value(minimal.strip()),
        )
    return result


def _variant_value(raw: str) -> str | None:
    """Значение одной стороны: ``None`` — не задано, ``""`` — не сокращать."""
    if not raw:
        return None
    return "" if raw == NO_SHORTENING else raw


def _variant_text(value: str | None) -> str:
    """Обратное преобразование значения стороны в текст строки."""
    if value is None:
        return ""
    return NO_SHORTENING if value == "" else value


def serialize_short_names(
    mapping: dict[str, tuple[str | None, str | None]]
) -> str:
    """Собрать таблицу обратно в текст «Название=среднее|минимальное»."""
    lines: list[str] = []
    for name, values in mapping.items():
        if not (name or "").strip():
            continue
        medium, minimal = values
        if medium is None and minimal is None:
            continue
        lines.append(
            f"{name}={_variant_text(medium)}{VARIANT_SEPARATOR}"
            f"{_variant_text(minimal)}"
        )
    return "\n".join(lines)


def stock_names(style: str | None) -> dict[str, str]:
    """Стандартные сокращения выбранного набора (неизвестный стиль — средний)."""
    return STOCK_NAMES_BY_STYLE.get(style or DEFAULT_STYLE, STOCK_MEDIUM_NAMES)


#: Слова, которые в минимальном сокращении опускаются: они не несут смысла
#: («Поддержка и тестирование программных модулей» → «ПиТПМ»).
_STOP_WORDS: Final = frozenset(
    {"и", "в", "на", "по", "с", "для", "о", "об", "от", "до", "из", "к", "у", "за"}
)

#: Длина аббревиатуры минимального набора, дальше — многоточие.
MINIMAL_MAX_LENGTH: Final = 14


def abbreviate_minimal(name: str, *, max_length: int = MINIMAL_MAX_LENGTH) -> str:
    """Сократить название до аббревиатуры — для плотной сетки недели.

    Правило: код предмета сохраняется, смысловые слова заменяются первыми
    буквами, служебные («и», «в», «на») опускаются. Так «Поддержка и
    тестирование программных модулей» даёт «ПТПМ», а «МДК.11.01 Технология
    разработки и защиты баз данных» — «МДК.11.01 ТРЗБД».

    Однобуквенный результат («История» → «И») бесполезен, поэтому для названий
    из одного слова используется обычное сокращение.
    """
    text = " ".join((name or "").split())
    if not text:
        return ""
    words = text.split()
    if len(words) == 1 and not _CODE_RE.match(words[0]):
        return abbreviate(words[0], max_length=max_length)

    parts: list[str] = []
    acronym: list[str] = []
    for word in words:
        token = word.strip(",;:()")
        if not token:
            continue
        if _CODE_RE.match(token) or sum(char.isdigit() for char in token) > 1:
            # Код выносим отдельно и всегда оставляем целиком.
            parts.append(token)
            continue
        if token.lower() in _STOP_WORDS:
            continue
        acronym.append(token[0].upper())

    if acronym:
        parts.append("".join(acronym))

    result = " ".join(parts) or text
    if len(result) > max_length:
        result = result[: max_length - 1].rstrip(" .") + "…"
    return result


def suggested(name: str, style: str | None = None) -> str:
    """Предложить сокращение в выбранном стиле (автоматически, без настроек)."""
    if (style or DEFAULT_STYLE) == "short":
        return abbreviate_minimal(name)
    return abbreviate(name)


#: Значение настройки ``subject_short_names`` по умолчанию.
#: Пусто: стандартные сокращения берутся из кода, а в настройках хранятся только
#: переопределения пользователя. Так смена набора не требует перезаписи базы.
DEFAULT_SHORT_NAMES_TEXT: Final = ""


__all__ = [
    "STOCK_MEDIUM_NAMES",
    "STOCK_MINIMAL_NAMES",
    "STOCK_NAMES_BY_STYLE",
    "DEFAULT_STYLE",
    "DEFAULT_MAX_LENGTH",
    "MINIMAL_MAX_LENGTH",
    "DEFAULT_SHORT_NAMES_TEXT",
    "abbreviate",
    "abbreviate_minimal",
    "parse_short_names",
    "serialize_short_names",
    "stock_names",
    "suggested",
]
