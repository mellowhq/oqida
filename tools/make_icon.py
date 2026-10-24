"""assets/oqida.ico を生成する（OQIDAのロゴ：リング＋しっぽ、緑のグロー）。"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)
S = 1024
ACC = (53, 242, 160)
BG = (9, 11, 10)


def draw_mark(img, width_scale=1.0):
    """リング(O)の中に下向き矢印(ダウンロード)。UIのSVGロゴと同じ形。"""
    d = ImageDraw.Draw(img)
    u = S / 24.0
    w = int(2.3 * u * width_scale)
    cx = cy = 12 * u
    r = 8.6 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ACC + (255,), width=w)
    d.line([(12 * u, 6.6 * u), (12 * u, 15.4 * u)], fill=ACC + (255,), width=w)
    d.line([(8.4 * u, 11.9 * u), (12 * u, 15.5 * u), (15.6 * u, 11.9 * u)], fill=ACC + (255,), width=w, joint="curve")
    for x, y in [(12 * u, 6.6 * u), (8.4 * u, 11.9 * u), (15.6 * u, 11.9 * u), (12 * u, 15.5 * u)]:
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ACC + (255,))


base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(base).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=BG + (255,),
                                       outline=(34, 41, 37, 255), width=8)
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw_mark(glow, 1.0)
halo = glow.filter(ImageFilter.GaussianBlur(S * 0.045))
halo2 = glow.filter(ImageFilter.GaussianBlur(S * 0.016))
for layer in (halo, halo2):
    a = layer.split()[3].point(lambda v: min(255, int(v * 0.9)))
    layer.putalpha(a)
base = Image.alpha_composite(base, halo)
base = Image.alpha_composite(base, halo2)
mark = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw_mark(mark, 1.0)
base = Image.alpha_composite(base, mark)

base.save(OUT / "oqida.png")
base.save(OUT / "oqida.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written")
