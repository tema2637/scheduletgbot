"""CSV/XLSX-импорт сетки расписания колледжа."""
import csv
import re
import json
from pathlib import Path
from collections import defaultdict


CSV_FILE   = "Расписание-2.csv"

JSON_FILE  = "schedule.json"

GROUPS_ROW = 4

GROUPS_COL = 2

DAYS = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА"]

# Служебные мероприятия не меняют номера обычных пар.
SPECIAL_EVENTS: dict[int, list[tuple[str, str, str]]] = {
    1: [
        ("Поднятие Государственного флага Российской Федерации", "08:15", "08:25"),
        ("Разговоры о важном", "08:30", "09:15"),
    ],
    4: [("Организационный / классный час", "12:10", "12:55")],
}

TIME_SLOTS: dict[int, dict[int, tuple[str, str]]] = {
    1: {  # ПОНЕДЕЛЬНИК
        1: ("09:25", "10:55"),
        2: ("11:05", "12:35"),
        3: ("13:05", "14:35"),
        4: ("14:45", "16:15"),
        5: ("16:25", "17:55"),
        6: ("18:05", "19:35"),
    },
    2: {  # ВТОРНИК
        1: ("08:30", "10:00"),
        2: ("10:10", "11:40"),
        3: ("12:10", "13:40"),
        4: ("13:50", "15:20"),
        5: ("15:30", "17:00"),
        6: ("17:10", "18:40"),
        7: ("18:50", "20:20"),
    },
    3: {  # СРЕДА (совпадает с вторником/пятницей)
        1: ("08:30", "10:00"),
        2: ("10:10", "11:40"),
        3: ("12:10", "13:40"),
        4: ("13:50", "15:20"),
        5: ("15:30", "17:00"),
        6: ("17:10", "18:40"),
        7: ("18:50", "20:20"),
    },
    4: {  # ЧЕТВЕРГ (орг.час после 2-й пары, 3-я пара сдвинута)
        1: ("08:30", "10:00"),
        2: ("10:10", "11:40"),
        3: ("13:00", "14:30"),
        4: ("14:40", "16:10"),
        5: ("16:20", "17:50"),
        6: ("18:00", "19:30"),
    },
    5: {  # ПЯТНИЦА (совпадает с вторником/средой)
        1: ("08:30", "10:00"),
        2: ("10:10", "11:40"),
        3: ("12:10", "13:40"),
        4: ("13:50", "15:20"),
        5: ("15:30", "17:00"),
        6: ("17:10", "18:40"),
        7: ("18:50", "20:20"),
    },
}

RE_TEACHER_FULL = re.compile(
    r'[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.\s?[А-ЯЁ]?\.?'
)

RE_SURNAME_WORD = re.compile(r'\b([А-ЯЁ][а-яё]{3,})\b')

RE_WEEKS_PAREN = re.compile(r'\((\d[\d,.\-\s]*)\)')

RE_ROOM = re.compile(r'(?<![.\d])(\d{3}[а-яё]?)(?!\.\d)(?!\d)')

_TEACHER_STOPWORDS = {
    "Рус", "Ин", "МДК", "ОБП", "ЗР", "ТВ", "МС", "ОП", "ФГ",
    "ДМ", "СД", "ТДВ", "ИТ", "ПД", "СС", "БЖ", "КС", "ОФГ",
    "СКС", "ОПБД", "ПОПД", "КГ", "АиЦУ",
    "Физ", "Прак", "Осн",
}

def build_teacher_master(rows: list[list[str]]) -> tuple[set[str], set[str]]:
    """Возвращает (полные_ФИО, фамилии)."""
    all_text = " ".join(cell for row in rows for cell in row)

    full_names: set[str] = set()
    for m in RE_TEACHER_FULL.finditer(all_text):
        full_names.add(m.group(0).strip())

    surnames: set[str] = set()
    for name in full_names:
        sn = name.split()[0].rstrip(".,")
        if len(sn) >= 4 and sn not in _TEACHER_STOPWORDS:
            surnames.add(sn)

    return full_names, surnames

def preprocess(text: str) -> str:
    # "412Обществоз" → "412 Обществоз"  (цифра + заглавная)
    text = re.sub(r"(\d)([А-ЯЁ])", r"\1 \2", text)
    # "Е.А.228" → "Е.А. 228"
    # Используем (?<!\w) чтобы НЕ разбивать МДК.02 (К - часть слова)
    text = re.sub(r"(?<!\w)([А-ЯЁ]\.)(\d)", r"\1 \2", text)
    # "(1-5)Слово" → "(1-5) Слово"
    text = re.sub(r"\)([А-ЯЁа-яё])", r") \1", text)
    # "Фамилия303" → "Фамилия 303"  (строчная + 3 цифры)
    text = re.sub(r"([а-яё])(\d{3})", r"\1 \2", text)
    return " ".join(text.split())

def find_teachers(
    text: str,
    full_names: set[str],
    surnames: set[str],
) -> list[tuple[int, int, str]]:
    """
    Возвращает [(start, end, teacher_str), …], отсортированный по позиции.
    Перекрытия не допускаются (первое совпадение «занимает» символы).
    """
    used = bytearray(len(text))  # 0 = свободно, 1 = занято
    found: list[tuple[int, int, str]] = []

    # 1. Полные ФИО (приоритет — берём как можно раньше)
    for m in RE_TEACHER_FULL.finditer(text):
        s, e = m.start(), m.end()
        if any(used[s:e]):
            continue
        used[s:e] = b"\x01" * (e - s)
        found.append((s, e, m.group(0).strip()))

    # 2. Одиночные фамилии из мастер-списка
    for m in RE_SURNAME_WORD.finditer(text):
        sn = m.group(1)
        if sn not in surnames:
            continue
        s, e = m.start(), m.end()
        if any(used[s:e]):
            continue
        # Не берём фамилию, если сразу за ней стоят инициалы
        # (значит RE_TEACHER_FULL её не поймал только из-за нестандартного
        # разделителя — обрабатываем как ФИО)
        after = text[e : e + 6]
        if re.match(r"\s+[А-ЯЁ]\.", after):
            continue
        used[s:e] = b"\x01" * (e - s)
        found.append((s, e, sn))

    found.sort(key=lambda x: x[0])
    return found

def extract_from_segment(seg: str) -> tuple[str, list[int], str]:
    """
    Из куска текста перед преподавателем извлекаем:
      (subject, weeks, room)

    Правило недели: ПОСЛЕДНЯЯ скобка «только цифры» = недели.
    Скобки с буквами (1и2, п/гр …) = часть названия предмета.
    Первое трёхзначное число = аудитория.
    """
    # Найдём все «цифровые» скобки
    digit_parens = list(RE_WEEKS_PAREN.finditer(seg))

    weeks: list[int] = []
    weeks_span: tuple[int, int] | None = None

    if digit_parens:
        last = digit_parens[-1]
        weeks = parse_weeks(last.group(1))
        weeks_span = (last.start(), last.end())

    # Маска: удаляем недели и аудиторию, чтобы получить предмет
    mask = list(seg)

    if weeks_span:
        for i in range(*weeks_span):
            mask[i] = "\0"

    # Аудитория — первое подходящее 3-значное число
    room = ""
    for m in RE_ROOM.finditer(seg):
        # Пропускаем позиции, уже съеденные неделями
        if all(mask[i] == "\0" for i in range(m.start(), m.end())):
            continue
        room = m.group(1)
        for i in range(m.start(), m.end()):
            mask[i] = "\0"
        break

    # Собираем предмет из оставшегося текста
    raw = "".join(c for c in mask if c != "\0")
    subject = raw.strip(" ;/,-").strip()
    subject = " ".join(subject.split())

    return subject, weeks, room

def is_subgroup_segment(seg: str) -> bool:
    """
    True, если сегмент не содержит полноценного занятия (нет недель, нет предмета),
    то есть является продолжением предыдущей подгруппы.
    """
    clean = seg.strip(" /;.,")
    if not clean:
        return True
    # Только аудитория (3 цифры + буква) + возможные слэши/пробелы
    return bool(re.fullmatch(r"\d{3}[а-яё]?", clean))

def parse_cell(
    raw_text: str,
    group_name: str,
    day_num: int,       # 1-based
    lesson_num: int,    # 1-based (номер пары)
    full_names: set[str],
    surnames: set[str],
) -> list[dict]:
    if not raw_text.strip():
        return []

    text = preprocess(raw_text)
    teachers = find_teachers(text, full_names, surnames)

    if not teachers:
        # Нет преподавателей — пробуем вытащить хоть что-то
        subj, weeks, room = extract_from_segment(text)
        if weeks and subj:
            return [_make(subj, "", room, weeks, group_name, day_num, lesson_num)]
        return []

    lessons: list[dict] = []
    # Базовый предмет/недели для наследования подгруппами
    base_subject = ""
    base_weeks: list[int] = []
    prev_end = 0

    for t_start, t_end, t_name in teachers:
        seg = text[prev_end:t_start]
        prev_end = t_end

        if is_subgroup_segment(seg) and base_subject and base_weeks:
            # ── Подгруппа ───────────────────────────────────────────
            room = ""
            m = RE_ROOM.search(seg.strip(" /;.,"))
            if m:
                room = m.group(1)
            lessons.append(_make(base_subject, t_name, room, base_weeks,
                                 group_name, day_num, lesson_num))
        else:
            # ── Обычное занятие ─────────────────────────────────────
            subj, weeks, room = extract_from_segment(seg)

            if not weeks:
                # Нет недель — запоминаем предмет как возможную базу и пропускаем
                if subj:
                    base_subject = subj
                continue

            if not subj:
                subj = base_subject   # берём предмет от предыдущего сегмента

            lessons.append(_make(subj, t_name, room, weeks,
                                 group_name, day_num, lesson_num))
            base_subject = subj
            base_weeks = weeks

    return lessons

def _make(subject, teacher, room, weeks, group, day, lesson):
    day_slots = TIME_SLOTS.get(day, {})
    slot_time = day_slots.get(lesson, ("", ""))
    return {
        "LessonTitle":  subject,
        "TeacherName":  teacher,
        "Cabinet":      room,
        "Weeks":        weeks,
        "Group":        {"Name": group},
        "TimeSlot": {
            "NumberSlot": lesson,
            "DayOfWeek":  day,
            "StartTime":  slot_time[0],
            "EndTime":    slot_time[1],
        },
    }

def collect_cells(
    rows: list[list[str]],
    num_groups: int,
) -> dict[tuple[int, int, int], str]:
    """
    Объединяет строки расписания в ячейки (day, lesson, group_idx) → текст.
    Несколько строк одного слота склеиваются пробелом.
    """
    cells: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    cur_day, cur_lesson = None, None

    for row in rows[GROUPS_ROW + 1:]:
        if not row:
            continue

        day_str = row[0].strip().upper()
        if day_str in DAYS:
            cur_day = DAYS.index(day_str)

        if len(row) > 1 and row[1].strip().isdigit():
            cur_lesson = int(row[1].strip())

        if cur_day is None or cur_lesson is None:
            continue

        for gi in range(num_groups):
            ci = gi + GROUPS_COL
            if ci >= len(row):
                continue
            cell = row[ci].strip()
            if cell:
                cells[(cur_day, cur_lesson, gi)].append(cell)

    return {k: " ".join(" ".join(v).split()) for k, v in cells.items()}

RE_WEEKS_PAREN=re.compile(r'\(\s*(\d[\d,;.\-\s–—−]*)\)')
def parse_weeks(text):
    text=text.replace('–','-').replace('—','-').replace('−','-')
    text=re.sub(r'\s*-\s*','-',text.strip())
    if not text or re.search(r'[^\d,;.\s-]',text): raise ValueError('Непонятные недели: '+repr(text))
    values=set()
    for part in re.split(r'[,;.\s]+',text):
        if not part: continue
        if re.fullmatch(r'\d+-\d+',part): a,b=map(int,part.split('-'))
        elif part.isdigit(): a=b=int(part)
        else: raise ValueError('Непонятный диапазон недель: '+part)
        if not 1<=a<=b<=60: raise ValueError('Недели должны быть в пределах 1..60, по возрастанию.')
        values.update(range(a,b+1))
    if not values: raise ValueError('Нет номеров недель.')
    return sorted(values)

def read_input(path,sheet=None):
    from io import BytesIO,StringIO
    import zipfile
    path=Path(path)
    if path.stat().st_size>20*1024*1024: raise ValueError('Файл превышает 20 МБ.')
    raw=path.read_bytes()
    if raw.startswith(b'PK\x03\x04'):
        with zipfile.ZipFile(BytesIO(raw)) as z:
            if 'xl/workbook.xml' not in z.namelist(): raise ValueError('Это ZIP, но не XLSX.')
            if sum(e.file_size for e in z.infolist())>100*1024*1024 or len(z.infolist())>5000: raise ValueError('Слишком большой XLSX.')
        import openpyxl
        wb=openpyxl.load_workbook(BytesIO(raw),read_only=True,data_only=True,keep_links=False)
        try:
            if sheet and sheet not in wb.sheetnames: raise ValueError('Лист не найден.')
            ws=wb[sheet] if sheet else wb.worksheets[0]
            if ws.max_row>20000 or ws.max_column>500: raise ValueError('Слишком большой лист.')
            return [[str(v).strip() if v is not None else '' for v in row] for row in ws.iter_rows(values_only=True)],'XLSX / '+ws.title
        finally: wb.close()
    if raw.startswith(b'\xd0\xcf\x11\xe0'): raise ValueError('Сохраните старый XLS как XLSX.')
    encodings=['utf-16'] if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else ['utf-8-sig','cp1251']
    text=None
    for encoding in encodings:
        try: text=raw.decode(encoding); break
        except UnicodeDecodeError: pass
    if text is None: raise ValueError('Не распознана кодировка CSV.')
    try: delimiter=csv.Sniffer().sniff(text[:32768],delimiters=';,\t').delimiter
    except csv.Error: delimiter=max(';\t,',key=lambda d:text[:32768].count(d))
    rows=list(csv.reader(StringIO(text),delimiter=delimiter))
    if len(rows)>20000 or any(len(r)>500 for r in rows): raise ValueError('Слишком большая CSV-таблица.')
    return rows,'CSV / '+encoding

def parse_file(path,sheet=None):
    from storage import validate
    rows,fmt=read_input(path,sheet)
    if len(rows)<=GROUPS_ROW: raise ValueError('Нет строки заголовков групп.')
    groups=[' '.join(v.split()) for v in rows[GROUPS_ROW][GROUPS_COL:]]
    if not any(groups): raise ValueError('Не найдены группы в строке 5.')
    if len(set(g for g in groups if g))!=len([g for g in groups if g]): raise ValueError('Повторяются названия групп.')
    full,surnames=build_teacher_master(rows)
    cells=collect_cells(rows,len(groups))
    result=[]; errors=[]; seen=set()
    for (day,slot,gi),text in sorted(cells.items()):
        if not groups[gi]: continue
        tag=f'{groups[gi]} / день {day+1} / пара {slot}'
        try:
            records=parse_cell(text,groups[gi],day+1,slot,full,surnames)
            if not records: raise ValueError('Не разобрана непустая ячейка: '+text[:200])
            records=validate(records)
            for r in records:
                key=json.dumps(r,ensure_ascii=False,sort_keys=True)
                if key not in seen: seen.add(key); result.append(r)
        except (ValueError,TypeError,KeyError,IndexError) as exc:
            errors.append(tag+': '+str(exc))
    if not result: errors.append('Не получено ни одного корректного занятия.')
    return result,{'format':fmt,'source_name':Path(path).name,'source_cells':len(cells),'records':len(result),'errors':errors}

def main(argv=None):
    import argparse
    import sys
    import config
    from storage import atomic_json,publish
    p=argparse.ArgumentParser(description='Импорт сетки CSV/XLSX -> единый JSON; при ошибках старые данные не заменяются.')
    p.add_argument('input',type=Path); p.add_argument('--sheet')
    p.add_argument('--output',type=Path,default=config.SCHEDULE_PATH)
    p.add_argument('--report',type=Path); p.add_argument('--check',action='store_true')
    p.add_argument('--allow-partial',action='store_true',help='Явно разрешить неполный импорт после просмотра отчёта')
    args=p.parse_args(argv)
    try:
        target=args.output.resolve(); report=(args.report or target.parent/'last_import_report.json').resolve()
        if target==args.input.resolve() or report in {target,args.input.resolve()}: raise ValueError('Источник, результат и отчёт должны быть разными файлами.')
        records,info=parse_file(args.input,args.sheet)
        atomic_json(report,info)
        print(f'{info["format"]}: {len(records)} записей; ошибок: {len(info["errors"])}. Отчёт: {report}')
        for error in info['errors'][:10]: print('! '+error)
        if not records or (info['errors'] and not args.allow_partial):
            print('Расписание НЕ изменено. Исправьте источник; частичный импорт только через --allow-partial.'); return 2
        if args.check: print('Проверка завершена; расписание не изменено.'); return 0
        publish(target,records); print('Опубликовано: '+str(target))
        if info['errors']: print('ВНИМАНИЕ: опубликовано НЕПОЛНОЕ расписание по --allow-partial.')
        return 0
    except Exception as exc:
        print('Импорт остановлен: '+str(exc)+'. Текущее расписание сохранено.',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
