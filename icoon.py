"""Tekent het podcast-icoon (icoon.png, 1400x1400) voor de prekenfeed."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W = 1400
NAVY = (24, 36, 64)
NAVY_LICHT = (44, 62, 102)
GOUD = (214, 168, 82)
CREME = (246, 238, 222)

FONTS = "/usr/share/fonts/truetype/dejavu/"


def font(naam, grootte):
    try:
        return ImageFont.truetype(FONTS + naam, grootte)
    except OSError:
        return ImageFont.load_default()


# Achtergrond: zachte radiale gloed van midden naar donkerblauw
img = Image.new("RGB", (W, W), NAVY)
gloed = Image.new("L", (W, W), 0)
ImageDraw.Draw(gloed).ellipse((150, 50, 1250, 1150), fill=255)
gloed = gloed.filter(ImageFilter.GaussianBlur(220))
img = Image.composite(Image.new("RGB", (W, W), NAVY_LICHT), img, gloed)
d = ImageDraw.Draw(img)

# Dunne gouden rand
d.rounded_rectangle((60, 60, W - 60, W - 60), radius=90, outline=GOUD, width=10)

# Opengeslagen Bijbel
cx, top, breed, hoog = W // 2, 340, 300, 330
for kant in (-1, 1):
    buiten = cx + kant * breed
    blad = [(cx, top + 40), (buiten, top), (buiten, top + hoog), (cx, top + hoog + 40)]
    d.polygon(blad, fill=CREME)
    # bladzijde-lijntjes
    for i in range(6):
        y = top + 70 + i * 40
        x1, x2 = cx + kant * 50, buiten - kant * 45
        d.line([(x1, y + 22), (x2, y - 2)], fill=(200, 188, 165), width=8)
    # kaft-rand
    d.line([(cx, top + hoog + 40), (buiten, top + hoog)], fill=GOUD, width=14)
d.line([(cx, top + 40), (cx, top + hoog + 40)], fill=(190, 175, 150), width=8)
# leeslint
d.polygon([(cx + 18, top + hoog + 30), (cx + 48, top + hoog + 22),
           (cx + 48, top + hoog + 140), (cx + 33, top + hoog + 115), (cx + 18, top + hoog + 140)],
          fill=(160, 40, 50))

# Titel
titel = "Preken"
f = font("DejaVuSerif-Bold.ttf", 250)
tw = d.textlength(titel, font=f)
d.text(((W - tw) / 2, 840), titel, font=f, fill=CREME)

# Gouden scheidingslijn
d.line([(W / 2 - 230, 1170), (W / 2 + 230, 1170)], fill=GOUD, width=6)

img.save(Path(__file__).resolve().parent / "icoon.png", optimize=True)
print("icoon.png gemaakt")
