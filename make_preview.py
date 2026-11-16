"""Собирает картинку-превью демо (preview.jpg) из готовых файлов."""
import json
import os
import subprocess

FF = os.environ.get("FFMPEG_BINARY", "ffmpeg")
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
W = 2400
T = 2  # секунда, с которой берём кадр


def txt(text, x, y, size, font=FONT, color="white"):
    text = text.replace(":", r"\:").replace(",", r"\,").replace("'", "")
    return f"drawtext=fontfile='{font}':text='{text}':x={x}:y={y}:fontsize={size}:fontcolor={color}"


screens = json.load(open("screens_hap/screens.json", encoding="utf-8"))
k = W / 12000  # масштаб мастера
inputs = ["scene_hard.mp4", "scene_soft.mp4", "master_12000x900.mp4"] + \
    [f"screens_hap/{s['name']}.mov" for s in screens]
args = []
for f in inputs:
    args += ["-ss", str(T), "-i", f]

g = []
# 1. сцены: без обработки и с мягкими стыками
g.append("[0:v]scale=1180:-2[h]")
g.append("[1:v]scale=1180:-2[s]")
# 2. мастер с контурами экранов
boxes = ",".join(
    f"drawbox=x={int(s['x']*k)}:y={int(s['y']*k)}:w={int(s['w']*k)}:h={int(s['h']*k)}:c=white:t=3,"
    + txt(str(i + 1), int(s['x'] * k) + 8, int(s['y'] * k) + 6, 22, BOLD)
    for i, s in enumerate(screens))
g.append(f"[2:v]scale={W}:-2,{boxes}[m]")
# 3. файлы экранов в ряд, одной высоты
th = 150
for i, s in enumerate(screens):
    g.append(f"[{3+i}:v]crop={s['w']}:{s['h']}:0:0,scale=-2:{th},"
             f"pad=iw+16:ih+40:8:0:color=0x111111,"
             + txt(f"{i+1} · {s['w']}×{s['h']}", 10, th + 8, 20, FONT, "0xbbbbbb") + f"[t{i}]")
g.append("".join(f"[t{i}]" for i in range(len(screens))) +
         f"hstack=inputs={len(screens)},scale='min({W}-40,iw)':-2[row]")

H = 1290
g.append(f"color=c=0x111111:s={W}x{H}:d=1[bg]")
g.append("[bg][h]overlay=20:110[b1]")
g.append("[b1][s]overlay=1220:110[b2]")
g.append("[b2][m]overlay=0:770[b3]")
g.append("[b3][row]overlay=20:1070[b4]")
labels = ",".join([
    txt("1. Сборка широкой сцены из 3 кадров (2000 × 900)", 20, 30, 40, BOLD),
    txt("Просто встык: видны швы и скачки цвета", 20, 75, 26, FONT, "0xff8080"),
    txt("Автоматически: мягкие стыки и выравнивание цвета", 1220, 75, 26, FONT, "0x80ff9a"),
    txt("2. Мастер 12 000 × 900 и экраны: найдены по PNG-маске автоматически", 20, 685, 40, BOLD),
    txt("Собран из 6 роликов с плавными стыками. Белые рамки — экраны из маски.", 20, 730, 26, FONT, "0xbbbbbb"),
    txt("3. Готовые файлы под каждый экран: HAP · одинаковая длина до кадра · нарезка 8 экранов ≈ 2 сек", 20, 1010, 34, BOLD),
])
g.append(f"[b4]{labels}[out]")
subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *args,
                "-filter_complex", ";".join(g), "-map", "[out]", "-frames:v", "1",
                "-q:v", "3", "preview.jpg"], check=True)
print("preview.jpg")
