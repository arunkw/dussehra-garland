"""
Generates the binary assets from code, so the repository holds only source:
  web/icons/*.png      app icons (home screen, favicon)
  desktop/garland.ico  Windows icon
  web/og-image.png     1200x630 link-preview image (needs Playwright + Chromium)

Usage:
  python tools/make_assets.py            # everything
  python tools/make_assets.py --ico-only # just the Windows icon (used by the .exe build)
"""
import argparse
import asyncio
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "desktop"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
import dussehra_garland as dg  # noqa: E402


def icon(size, maskable, path, background=True):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    if background:
        g = QLinearGradient(0, 0, 0, size)
        g.setColorAt(0, QColor(42, 22, 58))
        g.setColorAt(1, QColor(110, 40, 34))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        if maskable:
            p.drawRect(0, 0, size, size)
        else:
            p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    r = size * (0.30 if maskable else 0.36 if background else 0.44)
    pix, half = dg.make_marigold(r, dg.ORANGE, 4242, 1.0)
    p.drawPixmap(QPointF(size / 2 - half, size / 2 - half), pix)
    p.end()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)
    print("wrote", os.path.relpath(path, ROOT))


def make_ico():
    from PIL import Image
    tmp = os.path.join(ROOT, "desktop", "_icon256.png")
    icon(256, False, tmp, background=False)
    out = os.path.join(ROOT, "desktop", "garland.ico")
    Image.open(tmp).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    os.remove(tmp)
    print("wrote", os.path.relpath(out, ROOT))


def make_icons():
    base = os.path.join(ROOT, "web", "icons")
    icon(192, False, os.path.join(base, "icon-192.png"))
    icon(512, False, os.path.join(base, "icon-512.png"))
    icon(512, True, os.path.join(base, "maskable-512.png"))
    icon(180, True, os.path.join(base, "apple-touch-icon.png"))
    icon(64, False, os.path.join(base, "favicon.png"))


async def make_og():
    from playwright.async_api import async_playwright
    page_url = "file://" + os.path.join(ROOT, "web", "index.html").replace("\\", "/")
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=os.environ.get("CHROME") or None)
        pg = await (await b.new_context(viewport={"width": 1200, "height": 630})).new_page()
        await pg.goto(page_url)
        await pg.add_style_tag(content="""#hint,#bar,#credit{display:none!important}
          #og{position:fixed;z-index:5;left:0;right:0;top:300px;text-align:center;font-family:Georgia,serif}
          #og h1{font-size:68px;margin:0;font-style:italic;color:#ffc35a;font-weight:400}
          #og p{font:600 28px 'Mukta','Segoe UI',system-ui,sans-serif;margin:14px 0 0;color:rgba(246,231,207,.82)}""")
        await pg.evaluate("""()=>{const d=document.createElement('div');d.id='og';
          d.innerHTML='<h1>Happy Dussehra</h1><p>Brush the garland. Pluck a genda phool. Watch it fall.</p>';
          document.body.appendChild(d)}""")
        await pg.wait_for_timeout(1200)
        await pg.evaluate("""()=>{const g=window.__garland;[7,19,33].forEach(k=>{let c=0;
          for(let i=0;i<g.N;i++){if(g.kind[i]<=1){if(c++===k){g.tapAt(g.px[i],g.py[i]);break;}}}})}""")
        await pg.wait_for_timeout(1500)
        out = os.path.join(ROOT, "web", "og-image.png")
        await pg.screenshot(path=out)
        await b.close()
    print("wrote", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ico-only", action="store_true")
    a = ap.parse_args()
    make_ico()
    if not a.ico_only:
        make_icons()
        asyncio.run(make_og())
