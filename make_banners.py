import math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops

BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
S = 2
W, H = 1280 * S, 640 * S

def lerp(a, b, t): return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def waves(c1, c2, seed, w=W, h=H):
    random.seed(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    n = 46
    ph = random.uniform(0, 6)
    for i in range(n):
        t = i / (n - 1)
        col = lerp(c1, c2, t)
        pts = []
        for x in range(0, w + 12, 12):
            u = x / w
            y = h * 0.62 + math.sin(u * 5.2 + ph + t * 2.4) * h * 0.13 * (0.4 + u) \
                + math.sin(u * 9.0 - t * 3.0 + ph) * h * 0.035 + (t - 0.5) * h * 0.30 * (0.3 + u)
            pts.append((x, y))
        a = int(40 + 150 * (1 - abs(t - 0.5) * 2))
        d.line(pts, fill=col + (a,), width=2 * S // 2 + 1)
    return layer

def spaced(d, xy, text, font, fill, sp):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + sp
    return x

def make(name, tag, title, lines, c1, c2, seed, big=False):
    bg = Image.new("RGB", (W, H), (6, 6, 10))
    # mesh glows
    g = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(g)
    gd.ellipse([W * 0.45, -H * 0.6, W * 1.2, H * 0.55], fill=lerp((0, 0, 0), c1, 0.55))
    gd.ellipse([-W * 0.2, H * 0.5, W * 0.5, H * 1.5], fill=lerp((0, 0, 0), c2, 0.40))
    g = g.filter(ImageFilter.GaussianBlur(160 * S))
    bg = ImageChops.add(bg, g)
    # waves + glow
    wv = waves(c1, c2, seed)
    glow = wv.filter(ImageFilter.GaussianBlur(14 * S))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow)
    bg = Image.alpha_composite(bg, wv)
    d = ImageDraw.Draw(bg)
    # frame corners
    m, L = 44 * S, 54 * S
    fc = (255, 255, 255, 120)
    for (cx, cy, sx, sy) in [(m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)]:
        d.line([(cx, cy), (cx + sx * L, cy)], fill=fc, width=2 * S)
        d.line([(cx, cy), (cx, cy + sy * L)], fill=fc, width=2 * S)
    # tag
    spaced(d, (92 * S, 92 * S), tag.upper(), ImageFont.truetype(MONO, 22 * S), (200, 210, 235, 200), 5 * S)
    d.rectangle([92 * S, 128 * S, 92 * S + 64 * S, 128 * S + 3 * S], fill=c1 + (255,))
    # title
    tf = ImageFont.truetype(BOLD, (150 if big else 104) * S)
    ty = 150 * S if big else 168 * S
    if big:
        spaced(d, (88 * S, ty), title, tf, (250, 251, 255, 255), 14 * S)
    else:
        d.text((88 * S, ty), title, font=tf, fill=(250, 251, 255, 255))
    y = (350 if big else 310) * S
    for ln in lines:
        d.text((92 * S, y), ln, font=ImageFont.truetype(REG, 34 * S), fill=(176, 184, 210, 255))
        y += 50 * S
    # footer
    spaced(d, (92 * S, H - 96 * S), "VANTA  //  AI", ImageFont.truetype(MONO, 20 * S), (130, 138, 170, 255), 4 * S)
    # vignette + grain
    vg = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vg)
    vd.ellipse([-W * 0.2, -H * 0.4, W * 1.2, H * 1.4], fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(120 * S))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    bg = Image.composite(bg, dark, vg)
    random.seed(1)
    noise = Image.effect_noise((W, H), 18).convert("L")
    bg = Image.blend(bg.convert("RGB"), ImageChops.add(bg.convert("RGB"), Image.merge("RGB", (noise,) * 3), 0), 0)
    out = bg.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    out.save(f"banners/{name}.jpg", quality=92, optimize=True)

CY, MG, VI, OR, GR = (34, 211, 238), (244, 63, 168), (139, 92, 246), (251, 146, 60), (52, 211, 153)
make("menu", "Нейро-ассистент нового поколения", "VANTA", ["Мыслит быстро. Говорит прямо.", "Бесплатно и без подписок."], CY, MG, 3, big=True)
make("modes", "Личность", "Режимы", ["Выбери, кем сегодня будет Vanta."], VI, CY, 8)
make("image", "Генерация", "Рисую", ["Опиши сцену одним сообщением.", "Чем точнее, тем эффектнее."], MG, OR, 11)
make("help", "Инструкция", "Справка", ["Пиши вопрос, получай ответ.", "Команды: /menu  /new  /mode  /image"], GR, CY, 5)
make("about", "О проекте", "Vanta", ["Личный ИИ без воды и пафоса.", "Сделан на открытых моделях."], OR, VI, 14)

# avatar
a = 1280
av = Image.new("RGB", (a, a), (6, 6, 10))
g = Image.new("RGB", (a, a), (0, 0, 0)); gd = ImageDraw.Draw(g)
gd.ellipse([a*0.1, a*0.1, a*0.9, a*0.9], fill=lerp((0,0,0), VI, 0.6))
gd.ellipse([a*0.35, a*0.35, a*1.1, a*1.1], fill=lerp((0,0,0), MG, 0.5))
g = g.filter(ImageFilter.GaussianBlur(170)); av = ImageChops.add(av, g)
w = waves(CY, MG, 21, a, a); av = Image.alpha_composite(av.convert("RGBA"), w.filter(ImageFilter.GaussianBlur(10))); av = Image.alpha_composite(av, w)
d = ImageDraw.Draw(av)
f = ImageFont.truetype(BOLD, 640)
tw = d.textlength("V", font=f)
d.text(((a - tw) / 2, a * 0.12), "V", font=f, fill=(255, 255, 255, 245))
av.convert("RGB").resize((640, 640), Image.LANCZOS).save("banners/avatar.jpg", quality=94)
