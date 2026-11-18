"""Build a correspondence map from original PDF crops before native drawing."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

from .drawing_workflow import _source_crops


COLORS = ("#6741c7", "#bd3637", "#cc530b", "#00829e", "#217650", "#9e4b92")
DIRECTIONS = {"page-up": (0, -1), "page-down": (0, 1), "page-left": (-1, 0), "page-right": (1, 0)}


def _font(size):
    font = Path("C:/Windows/Fonts/msyh.ttc")
    return ImageFont.truetype(str(font), size) if font.is_file() else ImageFont.load_default(size=size)


def _card(canvas, draw, source, caption, bounds, color, image_bytes, fonts):
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=12, fill="#f8fafc", outline=color, width=3)
    title = textwrap.wrap(source.label, width=47, max_lines=2, placeholder="…")
    draw.multiline_text((left + 14, top + 12), "\n".join(title), font=fonts[0], fill=color, spacing=1)
    draw.text((left + 14, top + 67), caption, font=fonts[1], fill="#46566b")
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((right - left - 28, bottom - top - 108), Image.Resampling.LANCZOS)
    x = left + (right - left - image.width) // 2
    y = top + 92 + (bottom - top - 108 - image.height) // 2
    canvas.paste(image, (x, y))
    draw.rectangle((x, y, x + image.width, y + image.height), outline="#cbd5e1")
    return x, y, image.width, image.height


def _mark_callout(draw, plan, area, item, color, font):
    point = item.get("callout_point")
    direction = DIRECTIONS.get(item.get("sight_direction"))
    if not point or not direction or item.get("plan_view_id") != plan.id:
        return
    x, y, width, height = area
    left, top, right, bottom = plan.region
    if not (left <= point[0] <= right and top <= point[1] <= bottom):
        return
    start_x = round(x + (point[0] - left) / (right - left) * width)
    start_y = round(y + (point[1] - top) / (bottom - top) * height)
    dx, dy = direction
    finish_x = max(x + 7, min(x + width - 7, start_x + 52 * dx))
    finish_y = max(y + 7, min(y + height - 7, start_y + 52 * dy))
    if abs(finish_x - start_x) + abs(finish_y - start_y) < 12:
        return
    draw.ellipse((start_x - 9, start_y - 9, start_x + 9, start_y + 9), outline=color, width=3)
    draw.line((start_x, start_y, finish_x, finish_y), fill=color, width=4)
    draw.polygon(((finish_x, finish_y), (finish_x - 13 * dx - 7 * dy, finish_y - 13 * dy + 7 * dx),
                  (finish_x - 13 * dx + 7 * dy, finish_y - 13 * dy - 7 * dx)), fill=color)
    caption = item.get("callout") or ""
    if caption:
        label_x = max(x + 2, min(x + width - 105, start_x + 11))
        label_y = max(y + 2, start_y - 28)
        draw.rectangle((label_x - 2, label_y, label_x + min(103, draw.textlength(caption, font=font)) + 3,
                        label_y + 23), fill="#ffffff", outline=color)
        draw.text((label_x, label_y + 1), caption, fill=color, font=font)


def render_source_group_map(documents, index, source_views, path, label):
    """Compose the app's plan/elevation grouping from the original source crops."""
    records = {item["view_id"]: item for item in source_views}
    plans = [view for view in index.views if view.kind == "plan"]
    elevations = [view for view in index.views if view.kind == "elevation"]
    crops = _source_crops(documents, index.views)
    rows = max(1, len(plans), (len(elevations) + 1) // 2)
    width, height = 1780, 164 + rows * 390
    canvas = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    fonts = (_font(20), _font(16))
    heading = textwrap.shorten(label, width=85, placeholder="…")
    draw.text((26, 20), f"{heading}  |  Source correspondence", font=_font(32), fill="#153047")
    draw.text((27, 68), "Plan callouts link the numbered elevations. Arrows use source page directions.",
              font=fonts[0], fill="#46566b")
    for index_number, plan in enumerate(plans):
        top = 106 + index_number * (rows * 390 // len(plans))
        bottom = 106 + (index_number + 1) * (rows * 390 // len(plans)) - 14
        area = _card(canvas, draw, plan, f"Controlling plan  |  PDF page {plan.page}",
                     (25, top, 658, bottom), "#315d79", crops[plan.id], fonts)
        for index_elevation, elevation in enumerate(elevations):
            _mark_callout(draw, plan, area, records.get(elevation.id, {}),
                          COLORS[index_elevation % len(COLORS)], fonts[1])
    for number, elevation in enumerate(elevations):
        item = records.get(elevation.id, {})
        callout = item.get("callout") or "Callout unresolved"
        direction = item.get("sight_direction") or "Direction unresolved"
        caption = f"{callout}  |  PDF page {elevation.page}  |  {direction}"
        column, row = number % 2, number // 2
        x, y = 676 + column * 545, 106 + row * 390
        _card(canvas, draw, elevation, caption, (x, y, x + 530, y + 376),
              COLORS[number % len(COLORS)], crops[elevation.id], fonts)
    draw.text((27, height - 41), "Original PDF crops for source mapping. Drawing generation and review follow separately.",
              font=fonts[0], fill="#46566b")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    data = buffer.getvalue()
    path.write_bytes(data)
    return sha256(data).hexdigest()
