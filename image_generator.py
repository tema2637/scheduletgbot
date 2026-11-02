import io
from datetime import date, timedelta
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from data_manager import data_manager

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
REGULAR_FONT_PATH = ASSETS_DIR / "font_regular.ttf"
BOLD_FONT_PATH = ASSETS_DIR / "font_bold.ttf"

def get_font(size: int, bold: bool = False):
    font_path = BOLD_FONT_PATH if bold else REGULAR_FONT_PATH
    if font_path.exists():
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)

def render_week_image(target_name: str, monday: date, is_teacher: bool = False) -> bytes:
    BG_COLOR = (24, 25, 30)
    CARD_BG = (34, 36, 44)
    HEADER_ACCENT = (100, 160, 255)
    TEXT_MAIN = (240, 243, 246)
    TEXT_MUTED = (155, 163, 178)
    BORDER_COLOR = (48, 52, 64)
    TAG_TEXT = (140, 190, 255)

    WIDTH = 1080
    PAD = 40

    f_title = get_font(36, bold=True)
    f_subtitle = get_font(22, bold=False)
    f_day_head = get_font(26, bold=True)
    f_time = get_font(22, bold=False)
    f_lesson = get_font(22, bold=True)
    f_sub = get_font(20, bold=False)
    f_footer = get_font(18, bold=False)

    DAYS_RU = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА']
    friday = monday + timedelta(days=4)
    week_num = data_manager.get_academic_week(monday)

    day_blocks = []
    total_height = PAD + 90 + 20

    for i in range(5):
        d = monday + timedelta(days=i)
        if is_teacher:
            lessons = data_manager.get_teacher_schedule_for_day(target_name, d) or []
        else:
            lessons = data_manager.get_schedule_for_day(target_name, d) or []

        slots = {}
        for r in lessons:
            slots.setdefault(r['TimeSlot']['NumberSlot'], []).append(r)

        block_h = 50
        if not slots:
            block_h += 35
        else:
            for _, items in sorted(slots.items()):
                block_h += 36 * len(items) + 10
        block_h += 15

        day_blocks.append((d, DAYS_RU[i], slots, block_h))
        total_height += block_h + 16

    total_height += 50 + PAD

    im = Image.new('RGB', (WIDTH, total_height), color=BG_COLOR)
    draw = ImageDraw.Draw(im)

    y = PAD
    role_prefix = "Преподаватель" if is_teacher else "Группа"
    draw.text((PAD, y), f"{role_prefix}: {target_name}", fill=TEXT_MAIN, font=f_title)
    y += 46
    date_str = f"{monday.strftime('%d.%m.%Y')} — {friday.strftime('%d.%m.%Y')}"
    week_str = f" • Неделя: {week_num}" if week_num > 0 else ""
    draw.text((PAD, y), f"{date_str}{week_str}", fill=TEXT_MUTED, font=f_subtitle)
    y += 46

    card_w = WIDTH - 2 * PAD
    for d, day_name, slots, block_h in day_blocks:
        card_x = PAD
        card_y = y
        draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + block_h), radius=14, fill=CARD_BG, outline=BORDER_COLOR, width=1)

        cy = card_y + 14
        draw.text((card_x + 18, cy), f"{day_name} ({d.strftime('%d.%m')})", fill=HEADER_ACCENT, font=f_day_head)
        cy += 38

        if not slots:
            draw.text((card_x + 18, cy), "Занятий нет", fill=TEXT_MUTED, font=f_sub)
        else:
            for num, items in sorted(slots.items()):
                st = items[0]['TimeSlot']['StartTime']
                et = items[0]['TimeSlot']['EndTime']
                for r in items:
                    title = r['LessonTitle']
                    extra = f"[{r['Group']['Name']}]" if is_teacher else (r.get('TeacherName') or '')
                    cab = f"ауд. {r['Cabinet']}" if r.get('Cabinet') else ""

                    time_label = f"{num}. {st}–{et}"
                    draw.text((card_x + 18, cy), time_label, fill=TEXT_MUTED, font=f_time)
                    draw.text((card_x + 220, cy), title, fill=TEXT_MAIN, font=f_lesson)

                    extra_text = f"{extra}  {cab}".strip()
                    if extra_text:
                        draw.text((card_x + 650, cy), extra_text, fill=TAG_TEXT, font=f_sub)

                    cy += 36
                cy += 6

        y += block_h + 16

    draw.text((PAD, y + 10), "Расписание колледжа • @Ollamamonitorbbot", fill=TEXT_MUTED, font=f_footer)

    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
