#!/usr/bin/env python3
"""Export deliverables: 24-bit WAV + 320 kbps MP3 with ID3 tags and generated cover art.

Usage: export.py MANIFEST.json
MANIFEST: {"out_dir": "deliverables", "album": "...", "tracks": [
   {"src": "work/renders/x.wav", "name": "01 - ...", "title": "...", "artist": "...", "subtitle": "...", "comment": "..."}]}
"""
import json
import os
import subprocess
import sys

from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TIT2, TPE1, TPE2, TRCK, TYER
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def font(size, bold=True):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def cover(path, title, subtitle, accent=(255, 140, 40)):
    W = 1400
    img = Image.new("RGB", (W, W), (12, 8, 10))
    px = img.load()
    for y in range(W):                          # campfire glow from the bottom
        for x in range(0, W, 2):
            dx, dy = (x - W / 2) / W, (y - W * 1.05) / W
            d = (dx * dx * 1.6 + dy * dy) ** 0.5
            g = max(0.0, 1.0 - d * 1.35)
            c = (int(12 + accent[0] * g ** 1.6), int(8 + accent[1] * g ** 2.2), int(10 + accent[2] * g ** 3))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    img = img.filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(img)
    d.text((90, 110), "JUICE WRLD", font=font(120), fill=(245, 240, 232))
    d.text((94, 250), title, font=font(78), fill=(255, 196, 120))
    y = 360
    for line in subtitle.split("\n"):
        d.text((96, y), line, font=font(44, bold=False), fill=(235, 225, 215))
        y += 60
    d.text((96, W - 120), "fan edit · personal use · not for distribution", font=font(30, bold=False), fill=(200, 190, 180))
    img.save(path, quality=92)


def main():
    m = json.load(open(sys.argv[1]))
    out = m["out_dir"]
    os.makedirs(out, exist_ok=True)
    os.makedirs(os.path.join(out, "_covers"), exist_ok=True)
    n = len(m["tracks"])
    for i, t in enumerate(m["tracks"], 1):
        base = os.path.join(out, t["name"])
        art = os.path.join(out, "_covers", f"{i:02d}.jpg")
        cover(art, t.get("cover_title", "Campfire"), t.get("subtitle", ""), tuple(t.get("accent", (255, 140, 40))))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", t["src"], "-c:a", "pcm_s24le", base + ".wav"], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", t["src"], "-c:a", "libmp3lame", "-b:a", "320k",
                        "-id3v2_version", "3", base + ".mp3"], check=True)
        tags = ID3()
        tags.add(TIT2(encoding=3, text=t["title"]))
        tags.add(TPE1(encoding=3, text=t.get("artist", "Juice WRLD")))
        tags.add(TPE2(encoding=3, text="Juice WRLD"))
        tags.add(TALB(encoding=3, text=m["album"]))
        tags.add(TRCK(encoding=3, text=f"{i}/{n}"))
        tags.add(TYER(encoding=3, text="2018"))
        tags.add(TCON(encoding=3, text="Hip-Hop"))
        tags.add(COMM(encoding=3, lang="eng", desc="", text=t.get("comment", "")))
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=open(art, "rb").read()))
        tags.save(base + ".mp3", v2_version=3)
        print("exported", base + ".mp3", base + ".wav")


if __name__ == "__main__":
    main()
