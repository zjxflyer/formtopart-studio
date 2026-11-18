"""Create the original layered-panel product mark without a model/API request."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "backend/.deps"))
from PIL import Image, ImageDraw

image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), radius=48, fill="#173f37")
# Three panels become a precise part stack. Gold lines suggest a cutting list.
draw.line([(48, 136), (128, 180), (208, 136)], fill="#c8ab77", width=9, joint="curve")
draw.line([(48, 166), (128, 210), (208, 166)], fill="#f7f5ec", width=9, joint="curve")
draw.polygon([(48, 100), (128, 54), (208, 100), (128, 146)], outline="#f7f5ec", fill="#214d43", width=9)
draw.line([(128, 146), (128, 210)], fill="#f7f5ec", width=7)
draw.line([(162, 65), (198, 65)], fill="#c8ab77", width=6)
draw.line([(178, 52), (178, 78)], fill="#c8ab77", width=6)
image.save(ROOT / "Studio.ico", format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(ROOT / "FormToPart-Mark.png")
