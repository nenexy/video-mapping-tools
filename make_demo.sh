#!/usr/bin/env bash
# Воспроизводит демо: генерирует исходники средствами ffmpeg (без чужого видео),
# собирает сцену 2000×900, мастер 12 000×900, маску на 8 экранов, режет в HAP и рисует превью.
set -euo pipefail
FF="${FFMPEG_BINARY:-ffmpeg}"; export FFMPEG_BINARY="$FF"
mkdir -p src
gen(){ "$FF" -hide_banner -loglevel error -y -f lavfi -i "$1" -t 4 -c:v libx264 -crf 18 "src/$2.mp4"; }
gen "gradients=s=1280x900:c0=0x0a1a5c:c1=0x1fa2ff:c2=0x7a00ff:speed=0.02:n=3,format=yuv420p" 01_ocean
gen "gradients=s=1280x900:c0=0xff4e00:c1=0xffd000:c2=0xb3002d:speed=0.03:n=3,format=yuv420p" 02_sunset
gen "mandelbrot=s=1280x900:rate=25:start_scale=2.5:end_scale=0.6:outer=normalized_iteration_count,format=yuv420p" 03_fractal
gen "gradients=s=1280x900:c0=0x003b2f:c1=0x00e09a:c2=0x0b4fff:speed=0.025:n=3,format=yuv420p" 04_aurora
gen "gradients=s=1280x900:c0=0x2b0040:c1=0xff2fa0:c2=0x1a0066:speed=0.02:n=3,format=yuv420p" 05_neon
gen "mandelbrot=s=1280x900:rate=25:start_x=-0.743643887:start_y=-0.131825904:start_scale=0.05:end_scale=0.001:outer=normalized_iteration_count,hue=h=140,format=yuv420p" 06_spiral

python mapping.py compose src/01_ocean.mp4 src/02_sunset.mp4 src/03_fractal.mp4 -W 2000 -H 900 --overlap 0 --no-match -t 4 -o scene_hard.mp4
python mapping.py compose src/01_ocean.mp4 src/02_sunset.mp4 src/03_fractal.mp4 -W 2000 -H 900 --overlap 300 -t 4 -o scene_soft.mp4
python mapping.py compose src/0*.mp4 -W 12000 -H 900 --overlap 500 -t 4 -o master_12000x900.mp4

B="drawbox=x=100:y=60:w=1300:h=780:c=white:t=fill"
for r in "1520 0 1600 900" "3240 120 1200 660" "4560 0 1900 900" "6580 60 1300 780" "8000 180 900 540" "9020 0 1600 900" "10740 60 1160 780"; do
  set -- $r; B="$B,drawbox=x=$1:y=$2:w=$3:h=$4:c=white:t=fill"; done
"$FF" -hide_banner -loglevel error -y -f lavfi -i "color=black:s=12000x900,format=gray,$B" -frames:v 1 mask.png

python mapping.py cut master_12000x900.mp4 --mask mask.png --codec hap -o screens_hap
python make_preview.py
