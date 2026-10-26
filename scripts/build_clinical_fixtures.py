"""Generate public scan examples solely from explicitly fictional source text."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TEXT = """SJD-SYNTHETIC
Fictional laboratory report for software testing
subject_code: SYN-DEMO-001
visit_code: SYN-VISIT-001
date: 2025-01-15
IgG: 12.0 g/L
C3: 1.0 g/L
C4: 0.2 g/L

Synthetic example only. Not a patient record.
"""


def build():
    output = ROOT / 'clinical/fixtures'
    canvas = Image.new('RGB', (1100, 800), 'white')
    draw = ImageDraw.Draw(canvas)
    draw.multiline_text((50, 45), TEXT, fill='black', font=ImageFont.load_default(size=28), spacing=14)
    canvas.save(output / 'scan.png')
    canvas.save(output / 'scan.pdf', resolution=120)
    return output


if __name__ == '__main__':
    build()
    print('Synthetic scan examples generated from the checked-in fictional text.')
