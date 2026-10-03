"""生成 client/assets/app.ico（exe 内嵌图标 + 备用图标源）。

源图 = MV3 图标四档 PNG（spore_client/assets/icon-{16,32,48,128}.png）。
每档按"最近的够大源图"LANCZOS 缩放后单独入 ICO——Pillow 的 ICO 写入会原样
采用 append_images 中尺寸对上的那张，所以每一档都是我们自己渲的，不是它重采样。
256 档由 128 放大（源没有更大档；发版若要更锐需另出 256 源图）。

用法：python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "spore_client" / "assets"
OUT = ROOT / "assets" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
SOURCE_SIZES = (16, 32, 48, 128)


def render(size: int, sources: dict[int, Image.Image]) -> Image.Image:
    key = min((s for s in SOURCE_SIZES if s >= size), default=max(SOURCE_SIZES))
    im = sources[key]
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    return im


def main() -> int:
    sources = {s: Image.open(SRC / f"icon-{s}.png").convert("RGBA")
               for s in SOURCE_SIZES}
    imgs = {s: render(s, sources) for s in SIZES}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    imgs[256].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES],
                   append_images=[imgs[s] for s in SIZES if s != 256])
    got = sorted(Image.open(OUT).ico.sizes())
    assert got == sorted((s, s) for s in SIZES), f"档位不对：{got}"
    print(f"{OUT}  sizes={got}  {OUT.stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
