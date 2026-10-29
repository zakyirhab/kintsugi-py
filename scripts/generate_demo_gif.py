"""
Generates an ultra-crisp, high-resolution dark-mode terminal GIF
demonstrating KintsugiPy's autonomous self-healing, AST validation,
HealReport diff display, and zero-overhead hot-swapping.
"""

import os
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont

WIDTH = 920
HEIGHT = 580
BG_COLOR = (13, 17, 23)        # GitHub Dark Dim #0d1117
BORDER_COLOR = (48, 54, 61)    # #30363d
HEADER_BG = (22, 27, 34)       # #161b22
TEXT_COLOR = (201, 209, 217)   # #c9d1d9
DIM_TEXT = (139, 148, 158)     # #8b949e
GREEN_TEXT = (63, 185, 80)     # #3fb950
RED_TEXT = (248, 81, 73)       # #f85149
YELLOW_TEXT = (210, 153, 34)   # #d29922
CYAN_TEXT = (88, 166, 255)     # #58a6ff
PURPLE_TEXT = (188, 140, 255)  # #bc8cff
DIFF_BG = (17, 22, 29)

FONT_PATH = "C:\\Windows\\Fonts\\consola.ttf"
FONT_SIZE = 15
LINE_HEIGHT = 22

try:
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    bold_font = ImageFont.truetype("C:\\Windows\\Fonts\\consolab.ttf", FONT_SIZE)
except Exception:
    font = ImageFont.load_default()
    bold_font = font


def draw_window_frame(draw: ImageDraw.ImageDraw) -> None:
    # Outer terminal window with border and rounded corners
    draw.rounded_rectangle([0, 0, WIDTH - 1, HEIGHT - 1], radius=10, fill=BG_COLOR, outline=BORDER_COLOR, width=1)
    # Header bar
    draw.rounded_rectangle([0, 0, WIDTH - 1, 38], radius=10, fill=HEADER_BG)
    draw.rectangle([0, 26, WIDTH - 1, 38], fill=HEADER_BG)
    draw.line([(0, 38), (WIDTH - 1, 38)], fill=BORDER_COLOR, width=1)

    # Window controls (macOS style dots)
    draw.ellipse([16, 13, 28, 25], fill=(255, 95, 86))    # Red
    draw.ellipse([36, 13, 48, 25], fill=(255, 189, 46))   # Yellow
    draw.ellipse([56, 13, 68, 25], fill=(39, 201, 63))    # Green

    # Window Title
    title = "kintsugi-py — autonomous runtime repair demo"
    bbox = font.getbbox(title)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) // 2, 11), title, font=font, fill=DIM_TEXT)


# Lines to show across frames
# Each item is a list of segments: [(text, color, is_bold), ...]
FRAMES_DATA = [
    # Frame 1: Command prompt
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
    ],
    # Frame 2: Record 1
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
    ],
    # Frame 3: Record 2
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
    ],
    # Frame 4: Record 3 breaks!
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("FAIL ", RED_TEXT, True), ("Record 3/5: {'item': 'HDPE 100g', 'cost': 'Rp 12.000'} -> KeyError: 'price'", RED_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("WARN ", YELLOW_TEXT, True), ("[Kintsugi] ⚡ Intercepted KeyError in 'parse_price'. Initiating repair...", YELLOW_TEXT, False)],
    ],
    # Frame 5: LLM surgical repair
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("FAIL ", RED_TEXT, True), ("Record 3/5: {'item': 'HDPE 100g', 'cost': 'Rp 12.000'} -> KeyError: 'price'", RED_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("WARN ", YELLOW_TEXT, True), ("[Kintsugi] ⚡ Intercepted KeyError in 'parse_price'. Initiating repair...", YELLOW_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("LLM  ", PURPLE_TEXT, True), ("Calling Universal Provider (Claude 3.5 Sonnet / Qwen 2.5 Coder)...", PURPLE_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("SAFE ", GREEN_TEXT, True), ("🛡️ AST Guardrail: 0 security violations. Module sandbox approved.", GREEN_TEXT, False)],
    ],
    # Frame 6: Hot-swapped & Diff shown
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("FAIL ", RED_TEXT, True), ("Record 3/5: {'item': 'HDPE 100g', 'cost': 'Rp 12.000'} -> KeyError: 'price'", RED_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("WARN ", YELLOW_TEXT, True), ("[Kintsugi] ⚡ Intercepted KeyError in 'parse_price'. Initiating repair...", YELLOW_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("LLM  ", PURPLE_TEXT, True), ("Calling Universal Provider (Claude 3.5 Sonnet / Qwen 2.5 Coder)...", PURPLE_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("SAFE ", GREEN_TEXT, True), ("🛡️ AST Guardrail: 0 security violations. Module sandbox approved.", GREEN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("✨ Hot-swapped active function in-memory (attempt 1)", CYAN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("DIFF ", YELLOW_TEXT, True), ("Unified Patch (HealReport):", DIM_TEXT, False)],
        [("   --- a/parse_price.py", DIM_TEXT, False)],
        [("   +++ b/parse_price.py", DIM_TEXT, False)],
        [("   -def parse_price(data: dict) -> int:", RED_TEXT, False)],
        [("   -    return data['price']", RED_TEXT, False)],
        [("   +def parse_price(data: dict) -> int:", GREEN_TEXT, False)],
        [("   +    val = data.get('price') or data.get('cost', 0)", GREEN_TEXT, False)],
        [("   +    if isinstance(val, str): val = int(re.sub(r'[^0-9]', '', val))", GREEN_TEXT, False)],
        [("   +    return int(val)", GREEN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Retried Record 3/5 with healed function -> 12000 (0.2ms)", TEXT_COLOR, False)],
    ],
    # Frame 7: Record 4 with 0ms LLM overhead
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("FAIL ", RED_TEXT, True), ("Record 3/5: {'item': 'HDPE 100g', 'cost': 'Rp 12.000'} -> KeyError: 'price'", RED_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("WARN ", YELLOW_TEXT, True), ("[Kintsugi] ⚡ Intercepted KeyError in 'parse_price'. Initiating repair...", YELLOW_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("✨ Hot-swapped active function in-memory (attempt 1)", CYAN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("DIFF ", YELLOW_TEXT, True), ("Unified Patch (HealReport):", DIM_TEXT, False)],
        [("   -    return data['price']", RED_TEXT, False)],
        [("   +    val = data.get('price') or data.get('cost', 0)", GREEN_TEXT, False)],
        [("   +    if isinstance(val, str): val = int(re.sub(r'[^0-9]', '', val))", GREEN_TEXT, False)],
        [("   +    return int(val)", GREEN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Retried Record 3/5 with healed function -> 12000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:05] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 4/5: {'item': 'Kardus 20x20', 'cost': 'Rp 8.500'} -> 8500 (0ms LLM overhead)", TEXT_COLOR, False)],
    ],
    # Frame 8: Record 5 & Done!
    [
        [("$ python stream_scraper.py", TEXT_COLOR, True)],
        [("[09:41:00] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("Starting resilient stream ingestion pipeline...", TEXT_COLOR, False)],
        [("[09:41:01] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 1/5: {'item': 'Botol Kaca', 'price': 5000} -> 5000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:02] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 2/5: {'item': 'Tutup Ulir', 'price': 1500} -> 1500 (0.1ms)", TEXT_COLOR, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("FAIL ", RED_TEXT, True), ("Record 3/5: {'item': 'HDPE 100g', 'cost': 'Rp 12.000'} -> KeyError: 'price'", RED_TEXT, False)],
        [("[09:41:03] ", DIM_TEXT, False), ("WARN ", YELLOW_TEXT, True), ("[Kintsugi] ⚡ Intercepted KeyError in 'parse_price'. Initiating repair...", YELLOW_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("INFO ", CYAN_TEXT, True), ("✨ Hot-swapped active function in-memory (attempt 1)", CYAN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("DIFF ", YELLOW_TEXT, True), ("Unified Patch (HealReport):", DIM_TEXT, False)],
        [("   -    return data['price']", RED_TEXT, False)],
        [("   +    val = data.get('price') or data.get('cost', 0)", GREEN_TEXT, False)],
        [("   +    if isinstance(val, str): val = int(re.sub(r'[^0-9]', '', val))", GREEN_TEXT, False)],
        [("   +    return int(val)", GREEN_TEXT, False)],
        [("[09:41:04] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Retried Record 3/5 with healed function -> 12000 (0.2ms)", TEXT_COLOR, False)],
        [("[09:41:05] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 4/5: {'item': 'Kardus 20x20', 'cost': 'Rp 8.500'} -> 8500 (0ms LLM overhead)", TEXT_COLOR, False)],
        [("[09:41:06] ", DIM_TEXT, False), ("OK   ", GREEN_TEXT, True), ("Record 5/5: {'item': 'Lakban 100m', 'cost': 'Rp 15.000'} -> 15000 (0ms LLM overhead)", TEXT_COLOR, False)],
        [("[09:41:06] ", DIM_TEXT, False), ("DONE ", GREEN_TEXT, True), ("🎉 Pipeline finished: 5/5 parsed with ZERO downtime & 0 restarts!", GREEN_TEXT, True)],
    ],
]

# Durations for each frame in milliseconds
FRAME_DURATIONS = [
    1200,  # 1: start
    1000,  # 2: rec 1
    1000,  # 3: rec 2
    1600,  # 4: error caught
    1600,  # 5: calling LLM & AST guardrail
    2500,  # 6: hot-swap & diff display
    1500,  # 7: rec 4 with 0ms
    4000,  # 8: finish state (freeze for 4 seconds)
]


def render_frame(lines_data) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (10, 10, 10))
    draw = ImageDraw.Draw(img)
    draw_window_frame(draw)

    start_x = 24
    start_y = 52

    for line_idx, line in enumerate(lines_data):
        curr_x = start_x
        curr_y = start_y + (line_idx * LINE_HEIGHT)
        for text, color, is_bold in line:
            f = bold_font if is_bold else font
            draw.text((curr_x, curr_y), text, font=f, fill=color)
            bbox = f.getbbox(text)
            w = bbox[2] - bbox[0]
            curr_x += w

    return img


def main():
    images = []
    temp_dir = Path("dist_frames")
    temp_dir.mkdir(exist_ok=True)

    for idx, (frame_data, dur) in enumerate(zip(FRAMES_DATA, FRAME_DURATIONS)):
        frame_img = render_frame(frame_data)
        images.append((frame_img, dur))

    # Save as animated GIF
    output_gif = Path("assets/demo.gif")
    first_frame = images[0][0]
    durations = [item[1] for item in images]
    other_frames = [item[0] for item in images[1:]]

    first_frame.save(
        output_gif,
        save_all=True,
        append_images=other_frames,
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Generated {output_gif} successfully ({os.path.getsize(output_gif) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
