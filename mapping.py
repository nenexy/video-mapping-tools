"""Инструменты для видеомэппинга на ffmpeg.

  compose  — собрать широкую сцену из нескольких роликов с мягкими стыками
  cut      — нарезать мастер-видео на файлы под каждый экран
             (по PNG-маске или по JSON-карте экранов)

Примеры:
  python mapping.py compose a.mp4 b.mp4 c.mp4 -W 2000 -H 900 --overlap 220 -o scene.mp4
  python mapping.py cut master.mp4 --mask mask.png --codec hap -o screens/
  python mapping.py cut master.mp4 --map screens.json --codec prores -o screens/
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

FFMPEG = os.environ.get("FFMPEG_BINARY", "ffmpeg")

CODECS = {
    "h264": ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p"],
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
    "hap": ["-c:v", "hap", "-format", "hap"],
    "png": ["-c:v", "png"],
}
EXT = {"h264": ".mp4", "prores": ".mov", "hap": ".mov", "png": "_%05d.png"}


def ff(*args: str) -> None:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args]
    subprocess.run(cmd, check=True)


def even(v: int) -> int:
    return v - v % 2


# ---------------------------------------------------------------- compose

def compose(inputs: list[str], out: str, width: int, height: int,
            overlap: int, duration: float | None, codec: str,
            match: bool = True) -> None:
    """Раскладывает ролики слева направо с перекрытием `overlap` px.

    Каждый следующий кусок плавно проявляется поверх предыдущего по
    горизонтальному градиенту, поэтому шва не видно. Яркость и цвет кусков
    выравниваются по общему среднему (normalize), чтобы стыки не «прыгали».
    """
    n = len(inputs)
    seg = even((width + overlap * (n - 1)) // n)
    step = seg - overlap
    args: list[str] = []
    for src in inputs:
        args += ["-i", src]
    # маска-градиент для левого края куска: 0 → 255 на ширине overlap
    ramp = (f"nullsrc=s={seg}x{height}:d=1,format=gray,"
            f"geq=lum='if(lt(X\\,{overlap})\\,255*X/{overlap}\\,255)'")
    parts = [f"color=c=black:s={width}x{height}[base]"]
    if overlap and n > 1:
        parts.append(f"{ramp},loop=-1:1,split={n - 1}" +
                     "".join(f"[m{i}]" for i in range(1, n)))
    for i in range(n):
        chain = (f"[{i}:v]scale={seg}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={seg}:{height},setsar=1,fps=25,"
                 + ("normalize=smoothing=25:independence=0.3," if match else "")
                 + "format=yuva444p")
        if i == 0 or overlap == 0:
            parts.append(f"{chain}[v{i}]")
        else:
            parts.append(f"{chain}[c{i}];[c{i}][m{i}]alphamerge[v{i}]")
    prev = "base"
    for i in range(n):
        x = i * step
        tag = f"o{i}"
        parts.append(f"[{prev}][v{i}]overlay=x={x}:y=0:shortest=1[{tag}]")
        prev = tag
    graph = ";".join(parts)
    dur = ["-t", str(duration)] if duration else []
    ff(*args, "-filter_complex", graph, "-map", f"[{prev}]", *dur,
       *CODECS[codec], "-an", out)


# ---------------------------------------------------------------- screens

def screens_from_mask(mask: str) -> list[dict]:
    """Находит прямоугольные экраны на PNG-маске (белое — экран, чёрное — фон)."""
    probe = subprocess.run([FFMPEG, "-hide_banner", "-i", mask], capture_output=True, text=True)
    import re
    m = re.search(r", (\d+)x(\d+)", probe.stderr)
    if not m:
        sys.exit(f"не удалось прочитать размер маски {mask}")
    w, h = int(m.group(1)), int(m.group(2))
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", mask,
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    img = np.frombuffer(raw, np.uint8)[: w * h].reshape(h, w) > 127
    found: list[dict] = []

    def runs(flags: np.ndarray) -> list[tuple[int, int]]:
        d = np.diff(np.concatenate([[0], flags.astype(np.int8), [0]]))
        return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))

    for x0, x1 in runs(img.any(axis=0)):
        for y0, y1 in runs(img[:, x0:x1].any(axis=1)):
            found.append({"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)})
    for i, s in enumerate(found, 1):
        s["name"] = f"screen_{i:02d}"
    return found


def cut(master: str, screens: list[dict], outdir: str, codec: str,
        duration: float | None) -> list[str]:
    """Режет мастер на файлы по экранам одним проходом ffmpeg.

    Все файлы получаются одинаковой длины до кадра, поэтому на медиасервере
    они идут синхронно. У экрана можно задать `out_w`/`out_h` (родное
    разрешение экрана) и `rotate` (90/180/270).
    """
    Path(outdir).mkdir(parents=True, exist_ok=True)
    n = len(screens)
    parts = [f"[0:v]split={n}" + "".join(f"[s{i}]" for i in range(n))]
    outs: list[str] = []
    maps: list[str] = []
    for i, s in enumerate(screens):
        f = f"[s{i}]crop={s['w']}:{s['h']}:{s['x']}:{s['y']}"
        if s.get("out_w") and s.get("out_h"):
            f += f",scale={s['out_w']}:{s['out_h']}:flags=lanczos"
        rot = {90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}.get(s.get("rotate", 0))
        if rot:
            f += "," + rot
        if codec in ("h264", "hap"):
            f += ",pad=ceil(iw/4)*4:ceil(ih/4)*4"
        parts.append(f + f"[r{i}]")
        path = str(Path(outdir) / (s["name"] + EXT[codec]))
        outs.append(path)
        maps += ["-map", f"[r{i}]", *CODECS[codec], "-an",
                 *(["-t", str(duration)] if duration else []), path]
    ff("-i", master, "-filter_complex", ";".join(parts), *maps)
    with open(Path(outdir) / "screens.json", "w", encoding="utf-8") as fh:
        json.dump(screens, fh, ensure_ascii=False, indent=2)
    return outs


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compose")
    c.add_argument("inputs", nargs="+")
    c.add_argument("-o", "--output", required=True)
    c.add_argument("-W", "--width", type=int, required=True)
    c.add_argument("-H", "--height", type=int, required=True)
    c.add_argument("--overlap", type=int, default=200)
    c.add_argument("-t", "--duration", type=float)
    c.add_argument("--codec", choices=CODECS, default="h264")
    c.add_argument("--no-match", action="store_true", help="не выравнивать цвет кусков")
    k = sub.add_parser("cut")
    k.add_argument("master")
    g = k.add_mutually_exclusive_group(required=True)
    g.add_argument("--mask")
    g.add_argument("--map")
    k.add_argument("-o", "--outdir", required=True)
    k.add_argument("-t", "--duration", type=float)
    k.add_argument("--codec", choices=CODECS, default="h264")
    a = p.parse_args()
    if a.cmd == "compose":
        compose(a.inputs, a.output, a.width, a.height, a.overlap, a.duration, a.codec,
                not a.no_match)
        print(a.output)
    else:
        screens = screens_from_mask(a.mask) if a.mask else json.load(open(a.map, encoding="utf-8"))
        for s in screens:
            print(f"{s['name']}: {s['w']}x{s['h']} @ {s['x']},{s['y']}")
        for path in cut(a.master, screens, a.outdir, a.codec, a.duration):
            print(path)


if __name__ == "__main__":
    main()
