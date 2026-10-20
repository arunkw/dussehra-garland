"""
Genda Phool Garland — a Dussehra desktop decoration for Windows
Doneology Labs

* Transparent, frameless, always-on-top window spanning the screen above the taskbar.
* Marigold (genda) toran with green mango leaves, simulated as a Verlet rope
  (position-based dynamics), so it swings when the mouse brushes it.
* Click a flower or leaf to pluck it: flowers fall, bounce and roll on the taskbar,
  leaves and petals flutter down.
* Paper tag with editable text (double-click the tag, right-click menu, tray menu,
  --text on the command line, or edit config.json).

Run:   python dussehra_garland.py
Needs: pip install PySide6 numpy
"""

import argparse
import json
import math
import os
import random
import sys

import numpy as np
from PySide6.QtCore import QDir, QElapsedTimer, QLockFile, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QFontMetrics, QGuiApplication,
                           QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon, QWidget

APP_NAME = "DussehraGarland"
DEFAULT_TEXT = "Happy Dussehra\nfrom Doneology Labs"

# ----------------------------------------------------------------------------- config

def config_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    folder = os.path.join(base, APP_NAME)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "config.json")


def load_config():
    cfg = {"tag_text": DEFAULT_TEXT, "click_through": False}
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

# ----------------------------------------------------------------------------- sprites

FMT = QImage.Format.Format_ARGB32_Premultiplied

ORANGE = dict(deep=(150, 45, 0), outer=(205, 72, 4), mid=(238, 110, 12), inner=(255, 148, 34))
YELLOW = dict(deep=(165, 100, 0), outer=(220, 148, 0), mid=(246, 188, 14), inner=(255, 216, 68))


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _mix3(pal, t):
    if t < 0.5:
        return QColor(*_mix(pal["outer"], pal["mid"], t * 2))
    return QColor(*_mix(pal["mid"], pal["inner"], (t - 0.5) * 2))


def _new_image(w, h, dpr):
    img = QImage(max(1, math.ceil(w * dpr)), max(1, math.ceil(h * dpr)), FMT)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    return img


def _draw_petal(p, x, y, ang, pw, ph, col, rng):
    """One ruffled marigold petal; local -y points outward."""
    p.save()
    p.translate(x, y)
    p.rotate(ang)
    path = QPainterPath()
    path.moveTo(-pw * 0.35, ph * 0.4)
    path.cubicTo(-pw * 0.62, ph * 0.1, -pw * 0.62, -ph * 0.5, -pw * 0.5, -ph * 0.72)
    bumps = 3
    for b in range(bumps):
        x0 = -pw * 0.5 + pw * b / bumps
        x1 = -pw * 0.5 + pw * (b + 1) / bumps
        path.quadTo((x0 + x1) / 2, -ph * (1.05 + rng.uniform(-0.12, 0.12)),
                    x1, -ph * (0.72 + rng.uniform(-0.06, 0.06)))
    path.cubicTo(pw * 0.62, -ph * 0.5, pw * 0.62, ph * 0.1, pw * 0.35, ph * 0.4)
    path.closeSubpath()
    g = QLinearGradient(0, ph * 0.4, 0, -ph)
    g.setColorAt(0.0, col.darker(140))
    g.setColorAt(0.65, col)
    g.setColorAt(1.0, col.lighter(114))
    edge = col.darker(155)
    edge.setAlpha(170)
    p.setBrush(g)
    p.setPen(QPen(edge, 0.5))
    p.drawPath(path)
    p.restore()


def make_marigold(R, pal, seed, dpr):
    """Dense, ruffled genda ball seen from the front. Returns (pixmap, half_size)."""
    rng = random.Random(seed)
    half = R * 1.12 + 2
    img = _new_image(half * 2, half * 2, dpr)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = half
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(*pal["deep"]))
    p.drawEllipse(QPointF(c, c), R * 0.93, R * 0.93)
    rings = 9
    for k in range(rings):
        t = k / (rings - 1)
        rr = R * (0.72 - 0.66 * t)
        pw = R * (0.46 - 0.22 * t)
        ph = R * (0.34 - 0.14 * t)
        n = max(4, int(2 * math.pi * max(rr, R * 0.12) / (pw * 0.5)))
        off = rng.random() * 2 * math.pi
        for i in range(n):
            a = off + 2 * math.pi * i / n + rng.uniform(-0.15, 0.15)
            r_ = max(0.0, rr + rng.uniform(-0.05, 0.05) * R)
            tc = min(1.0, max(0.0, t + rng.uniform(-0.15, 0.15)))
            _draw_petal(p, c + math.cos(a) * r_, c + math.sin(a) * r_,
                        math.degrees(a) + 90 + rng.uniform(-30, 30),
                        pw * rng.uniform(0.85, 1.15), ph * rng.uniform(0.85, 1.15),
                        _mix3(pal, tc), rng)
    # light from top-left, shade bottom-right, only on painted pixels
    g = QRadialGradient(QPointF(c - R * 0.35, c - R * 0.42), R * 1.55)
    g.setColorAt(0.0, QColor(255, 250, 210, 70))
    g.setColorAt(0.45, QColor(255, 255, 255, 0))
    g.setColorAt(1.0, QColor(70, 15, 0, 130))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRect(QRectF(0, 0, half * 2, half * 2))
    p.end()
    return QPixmap.fromImage(img), half


def make_leaf(L, Wd, seed, dpr):
    """Mango leaf pointing +x, base at the returned pivot."""
    rng = random.Random(seed)
    pad = 2
    img = _new_image(L + pad * 2, Wd + pad * 2, dpr)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(pad, (Wd + pad * 2) / 2)
    path = QPainterPath()
    path.moveTo(0, 0)
    path.cubicTo(L * 0.25, -Wd * 0.62, L * 0.68, -Wd * 0.52, L, 0)
    path.cubicTo(L * 0.68, Wd * 0.52, L * 0.25, Wd * 0.62, 0, 0)
    shade = rng.uniform(-12, 12)
    dark = QColor(int(26 + shade / 2), int(92 + shade), 34)
    light = QColor(int(76 + shade / 2), int(152 + shade), 58)
    g = QLinearGradient(0, -Wd / 2, 0, Wd / 2)
    g.setColorAt(0.0, dark)
    g.setColorAt(0.45, light)
    g.setColorAt(1.0, dark.darker(115))
    p.setBrush(g)
    p.setPen(QPen(QColor(18, 64, 24), 0.7))
    p.drawPath(path)
    rib = QColor(190, 225, 150, 170)
    p.setPen(QPen(rib, 0.8))
    p.drawLine(QPointF(0, 0), QPointF(L * 0.93, 0))
    p.setPen(QPen(QColor(190, 225, 150, 90), 0.5))
    for i in range(1, 7):
        x = L * i / 7.5
        p.drawLine(QPointF(x, 0), QPointF(x + L * 0.08, -Wd * 0.3))
        p.drawLine(QPointF(x, 0), QPointF(x + L * 0.08, Wd * 0.3))
    p.end()
    return QPixmap.fromImage(img), QPointF(pad, (Wd + pad * 2) / 2)


def make_petal_sprite(size, pal, seed, dpr):
    rng = random.Random(seed)
    half = size
    img = _new_image(half * 2, half * 2, dpr)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_petal(p, half, half + size * 0.25, 0, size * 1.1, size * 0.9,
                _mix3(pal, rng.uniform(0.2, 0.9)), rng)
    p.end()
    return QPixmap.fromImage(img), half


def make_tag(text, s, dpr):
    """Paper tag; returns (pixmap, hole point inside pixmap, width, height)."""
    TW, TH, hole_y, ch, pad = 172 * s, 106 * s, 15 * s, 22 * s, 5 * s
    img = _new_image(TW + pad * 2, TH + pad * 2, dpr)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
    p.translate(pad, pad)
    shape = QPainterPath()
    shape.moveTo(ch, 0)
    shape.lineTo(TW - ch, 0)
    shape.lineTo(TW, ch)
    shape.lineTo(TW, TH)
    shape.lineTo(0, TH)
    shape.lineTo(0, ch)
    shape.closeSubpath()
    # soft shadow
    p.save()
    p.translate(2.5 * s, 3.5 * s)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(40, 20, 0, 55))
    p.drawPath(shape)
    p.restore()
    g = QLinearGradient(0, 0, TW, TH)
    g.setColorAt(0.0, QColor(253, 246, 226))
    g.setColorAt(1.0, QColor(240, 224, 190))
    p.setBrush(g)
    p.setPen(QPen(QColor(170, 135, 90), 1.0 * s))
    p.drawPath(shape)
    # paper fibres
    rng = random.Random(7)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(int(140 * s)):
        p.setBrush(QColor(150, 110, 60, rng.randint(10, 28)))
        p.drawEllipse(QPointF(rng.uniform(4, TW - 4), rng.uniform(ch / 2 + 4, TH - 4)),
                      rng.uniform(0.4, 1.1) * s, rng.uniform(0.4, 1.1) * s)
    # dashed inner border
    inset = 7 * s
    border = QPainterPath()
    border.moveTo(ch + inset * 0.4, inset)
    border.lineTo(TW - ch - inset * 0.4, inset)
    border.lineTo(TW - inset, ch + inset * 0.4)
    border.lineTo(TW - inset, TH - inset)
    border.lineTo(inset, TH - inset)
    border.lineTo(inset, ch + inset * 0.4)
    border.closeSubpath()
    pen = QPen(QColor(140, 30, 25, 150), 1.0 * s)
    pen.setStyle(Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(border)
    # eyelet + punched hole (hole made truly transparent)
    hc = QPointF(TW / 2, hole_y)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(196, 150, 60))
    p.drawEllipse(hc, 6.2 * s, 6.2 * s)
    p.setBrush(QColor(240, 205, 120))
    p.drawEllipse(hc, 4.8 * s, 4.8 * s)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    p.drawEllipse(hc, 3.2 * s, 3.2 * s)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    # text: first line bold "title", remaining lines regular; auto-fit
    lines = [ln.strip() for ln in (text or "").split("\n") if ln.strip()] or [" "]
    box = QRectF(14 * s, hole_y + 11 * s, TW - 28 * s, TH - hole_y - 21 * s)
    flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.TextFlag.TextWordWrap)
    families = ["Georgia", "Nirmala UI", "Segoe UI", "serif"]
    chosen = None
    for size10 in range(190, 70, -5):
        fonts, rects, total = [], [], 0.0
        for i, ln in enumerate(lines):
            f = QFont()
            f.setFamilies(families)
            f.setPointSizeF(size10 / 10 * s * (1.0 if i == 0 else 0.78))
            f.setBold(i == 0)
            f.setItalic(i == 0)
            fm = QFontMetrics(f)
            r = fm.boundingRect(QRect(0, 0, int(box.width()), 100000), flags, ln)
            fonts.append(f)
            rects.append(r)
            total += r.height()
        total += (len(lines) - 1) * 2 * s
        if total <= box.height() and max(r.width() for r in rects) <= box.width() + 1:
            chosen = (fonts, rects, total)
            break
    if chosen is None:
        chosen = (fonts, rects, total)
    fonts, rects, total = chosen
    y = box.top() + max(0.0, (box.height() - total) / 2)
    for i, ln in enumerate(lines):
        p.setFont(fonts[i])
        p.setPen(QColor(128, 18, 18) if i == 0 else QColor(92, 40, 20))
        r = QRectF(box.left(), y, box.width(), rects[i].height())
        p.drawText(r, flags, ln)
        y += rects[i].height() + 2 * s
    p.end()
    return QPixmap.fromImage(img), QPointF(pad + TW / 2, pad + hole_y), TW, TH, hole_y

def _scaled(pix, f):
    img = pix.toImage()
    out = img.scaled(round(img.width() * f), round(img.height() * f),
                     Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out.setDevicePixelRatio(pix.devicePixelRatio())
    return QPixmap.fromImage(out)


class RotSprite:
    """Lazily pre-rotated copies of a sprite, drawn by plain blits around a pivot point."""

    def __init__(self, pix, pivot, steps):
        self.img = pix.toImage()
        self.dpr = pix.devicePixelRatio()
        self.pivot = QPointF(pivot.x() * self.dpr, pivot.y() * self.dpr)
        self.steps = steps
        self.step = 360.0 / steps
        self.cache = {}

    def get(self, deg):
        k = int(round(deg / self.step)) % self.steps
        hit = self.cache.get(k)
        if hit is None:
            t = QTransform().rotate(k * self.step)
            tm = QImage.trueMatrix(t, self.img.width(), self.img.height())
            rimg = self.img.transformed(t, Qt.TransformationMode.SmoothTransformation)
            rimg.setDevicePixelRatio(self.dpr)
            pv = tm.map(self.pivot)
            hit = (QPixmap.fromImage(rimg), pv.x() / self.dpr, pv.y() / self.dpr)
            self.cache[k] = hit
        return hit

    def draw(self, p, x, y, deg):
        pix, ox, oy = self.get(deg)
        p.drawPixmap(QPointF(x - ox, y - oy), pix)


# ----------------------------------------------------------------------------- physics

FLOWER_O, FLOWER_Y, LEAF, TASSEL, BARE, ANCHOR, THREAD, TAG_HOLE, TAG_BOTTOM = range(9)


class Body:
    """A plucked flower (bouncy, rolls) or leaf/petal (flutters)."""
    __slots__ = ("kind", "x", "y", "vx", "vy", "ang", "angv", "r", "sprite", "landed",
                 "age", "life", "phase", "freq", "squash", "grounded", "leaf_dir")

    def __init__(self, kind, x, y, vx, vy, r, sprite):
        self.kind, self.x, self.y, self.vx, self.vy, self.r, self.sprite = kind, x, y, vx, vy, r, sprite
        self.ang = random.uniform(0, 360)
        self.angv = random.uniform(-200, 200)
        self.landed = False
        self.grounded = False
        self.age = 0.0
        self.life = 0.0
        self.phase = random.uniform(0, 2 * math.pi)
        self.freq = random.uniform(2.2, 3.6)
        self.squash = 0.0
        self.leaf_dir = random.choice((0.0, 180.0))


class Garland:
    def __init__(self, width, height, s):
        self.W, self.H, self.s = width, height, s
        self.R = 14.0 * s
        self.g = 1500.0 * s
        self.hand_r = 9.0 * s
        self._build()

    # -- construction
    def _add(self, x, y, kind, w=1.0):
        self.pos.append([x, y])
        self.kind.append(kind)
        self.w.append(w)
        self.rot.append(random.uniform(0, 360))
        self.sprite.append(random.randrange(5))
        return len(self.pos) - 1

    def _build(self):
        s, R = self.s, self.R
        self.pos, self.kind, self.w, self.rot, self.sprite = [], [], [], [], []
        self.eq, self.mins, self.chains = [], [], []
        spacing = R * 1.32
        y0 = 12 * s
        fr = [0.035, 0.355, 0.645, 0.965]
        pins = [self._add(f * self.W, y0, ANCHOR, 0.0) for f in fr]
        self.pins = pins
        main_pattern = [FLOWER_O, FLOWER_O, FLOWER_O, LEAF, FLOWER_Y, FLOWER_Y, FLOWER_Y, LEAF]
        self.swag_mids = []
        for k in range(3):
            a, b = pins[k], pins[k + 1]
            ax, bx = self.pos[a][0], self.pos[b][0]
            span = bx - ax
            n = max(4, round(span * 1.075 / spacing))
            rest = span * 1.075 / n
            chain = [a]
            for i in range(1, n):
                kind = main_pattern[(i - 1) % len(main_pattern)]
                # start as a taut straight line: it drops and swings into place on launch
                chain.append(self._add(ax + span * i / n, y0, kind))
            chain.append(b)
            for i in range(len(chain) - 1):
                self.eq.append((chain[i], chain[i + 1], rest))
            for i in range(len(chain) - 2):
                self.mins.append((chain[i], chain[i + 2], rest * 1.55))
            self.chains.append(chain)
            self.swag_mids.append(chain[len(chain) // 2])
        # long strands from each pin, short ones from outer swag middles
        strand_pattern = [FLOWER_Y, FLOWER_O, FLOWER_Y, LEAF, FLOWER_O, FLOWER_Y, FLOWER_O, FLOWER_Y]
        lengths = {pins[0]: 6, pins[1]: 8, pins[2]: 8, pins[3]: 6,
                   self.swag_mids[0]: 4, self.swag_mids[2]: 4}
        for root, n in lengths.items():
            self._strand(root, n, spacing, strand_pattern)
        # paper tag from the middle swag
        self._tag(self.swag_mids[1])
        self.N = len(self.pos)
        self.P = np.array(self.pos, dtype=np.float64)
        self.Pp = self.P.copy()
        self.Wt = np.array(self.w, dtype=np.float64)
        self.K = np.array(self.kind, dtype=np.int32)
        self.orig_kind = self.K.copy()
        self.spin = np.zeros(self.N)
        self.spin_v = np.zeros(self.N)
        self._refresh_radii()
        self.groups = self._color(self.eq)
        self.min_groups = self._color(self.mins)
        # resting reference tangent per node, so leaves keep their hang direction
        self.theta0 = np.zeros(self.N)
        self.settle(4.0)
        self.theta0 = self._tangents()

    def _strand(self, root, n, spacing, pattern):
        x, y = self.pos[root]
        tilt = math.radians(random.uniform(-35, 35))
        chain, prev = [root], root
        for i in range(n):
            kind = TASSEL if i == n - 1 else pattern[i % len(pattern)]
            d = spacing * (i + 1)
            idx = self._add(x + math.sin(tilt) * d, y + math.cos(tilt) * d, kind)
            self.eq.append((prev, idx, spacing))
            chain.append(idx)
            prev = idx
        for i in range(len(chain) - 2):
            self.mins.append((chain[i], chain[i + 2], spacing * 1.55))
        self.chains.append(chain)

    def _tag(self, root):
        s = self.s
        x, y = self.pos[root]
        seg = 13 * s
        chain, prev = [root], root
        for i in range(3):
            idx = self._add(x + 8 * s * (i + 1), y + seg * (i + 1), THREAD, 1.6)
            self.eq.append((prev, idx, seg))
            chain.append(idx)
            prev = idx
        hole = self._add(x + 32 * s, y + seg * 4, TAG_HOLE, 1.0)
        self.eq.append((prev, hole, seg))
        chain.append(hole)
        self.tag_len = (106 - 15) * s
        bottom = self._add(x + 32 * s + self.tag_len * 0.5, y + seg * 4 + self.tag_len * 0.85, TAG_BOTTOM, 0.45)
        self.eq.append((hole, bottom, self.tag_len))
        self.tag_hole, self.tag_bottom = hole, bottom
        self.chains.append(chain)

    @staticmethod
    def _color(cons):
        groups = []  # list of (used_set, list)
        for c in cons:
            for used, lst in groups:
                if c[0] not in used and c[1] not in used:
                    used.update((c[0], c[1]))
                    lst.append(c)
                    break
            else:
                groups.append(({c[0], c[1]}, [c]))
        out = []
        for _, lst in groups:
            a = np.array(lst, dtype=np.float64)
            out.append([a[:, 0].astype(np.int64), a[:, 1].astype(np.int64), a[:, 2]])
        return out

    def _refresh_radii(self):
        R, s = self.R, self.s
        table = {FLOWER_O: R * 0.95, FLOWER_Y: R * 0.95, LEAF: R * 0.85, TASSEL: R * 0.9,
                 BARE: 3 * s, ANCHOR: 0.0, THREAD: 0.0, TAG_HOLE: 0.0, TAG_BOTTOM: 0.0}  # tag: see _tag_brush
        self.nr = np.array([table[int(k)] for k in self.K])
        self.movable = self.Wt > 0

    # -- simulation
    def settle(self, seconds):
        for _ in range(int(seconds * 120)):
            self.step(1 / 120, None, None, damping=0.96)
        self.Pp[:] = self.P

    def step(self, h, hand_a, hand_b, hand_v=None, damping=0.995):
        P, Pp = self.P, self.Pp
        v = (P - Pp) * damping
        Pp[:] = P
        v[self.tag_bottom] *= 0.986          # paper catches air: extra drag on the tag
        v[self.tag_hole] *= 0.996
        P += v
        P[self.movable, 1] += self.g * h * h
        touched = None
        if hand_a is not None:
            touched = self._hand(hand_a, hand_b, hand_v, h)
        for it in range(14):
            for I, J, L in self.groups:
                self._solve(I, J, L, False)
            if it % 4 == 3:
                for I, J, L in self.min_groups:
                    self._solve(I, J, L, True)
        # spin: damped spring back to rest
        self.spin_v += (-self.spin * 30.0) * h
        self.spin_v *= math.exp(-2.5 * h)
        self.spin += self.spin_v * h
        return touched

    def _solve(self, I, J, L, one_sided):
        P, Wt = self.P, self.Wt
        d = P[J] - P[I]
        dist = np.sqrt((d * d).sum(axis=1)) + 1e-9
        wi, wj = Wt[I], Wt[J]
        ws = wi + wj
        diff = (dist - L) / (dist * np.where(ws > 0, ws, 1.0))
        if one_sided:
            diff = np.minimum(diff, 0.0)
        corr = d * diff[:, None]
        P[I] += corr * wi[:, None]
        P[J] -= corr * wj[:, None]

    def _hand(self, a, b, hv, h):
        """Fingertip capsule from a to b pushes beads and drags them with friction."""
        P = self.P
        ab = b - a
        ab2 = float(ab @ ab)
        if ab2 > 1e-9:
            t = np.clip(((P - a) @ ab) / ab2, 0.0, 1.0)
            closest = a + t[:, None] * ab
        else:
            closest = np.broadcast_to(a, P.shape)
        d = P - closest
        dist = np.sqrt((d * d).sum(axis=1)) + 1e-9
        reach = self.nr + self.hand_r
        hit = (dist < reach) & self.movable & (self.nr > 0)
        if not hit.any():
            return None
        n = d[hit] / dist[hit][:, None]
        depth = np.minimum(reach[hit] - dist[hit], 2.0 * self.s)
        push = n * depth[:, None]
        if hv is not None:
            # Coulomb-like friction: pull the bead's velocity toward the finger's velocity
            # (bounded, so a bead can never move faster than the hand that brushes it)
            vb = (P[hit] - self.Pp[hit]) / h
            push = push + (hv - vb) * 0.08 * h
            # tangential velocity of the finger relative to each bead -> spin (torque from friction)
            vt = n[:, 0] * hv[1] - n[:, 1] * hv[0]
            self.spin_v[hit] += np.clip(vt / self.R * 0.02, -2.5, 2.5)
        P[hit] += push
        return hit

    def tag_frame(self):
        h = self.P[self.tag_hole]
        b = self.P[self.tag_bottom]
        u = b - h
        L = math.hypot(u[0], u[1]) or 1.0
        u = u / L
        return h, u, np.array([-u[1], u[0]])

    def tag_contains(self, pt, TW, TH, hole_y):
        h, u, n = self.tag_frame()
        d = pt - h
        along, across = float(d @ u), float(d @ n)
        return -hole_y <= along <= TH - hole_y and abs(across) <= TW / 2

    def tangents(self):
        return self._tangents()

    def _tangents(self):
        th = np.zeros(self.N)
        for chain in self.chains:
            idx = np.array(chain)
            pts = self.P[idx]
            fwd = np.vstack([pts[1:] - pts[:-1], pts[-1:] - pts[-2:-1]])
            bwd = np.vstack([pts[1:2] - pts[0:1], pts[1:] - pts[:-1]])
            t = fwd + bwd
            ang = np.arctan2(t[:, 1], t[:, 0])
            # roots (pins / swag nodes) keep their own chain's tangent
            th[idx[1:]] = ang[1:]
            if self.K[idx[0]] == ANCHOR and th[idx[0]] == 0:
                th[idx[0]] = ang[0]
        return th

    def bbox(self):
        mn = self.P.min(axis=0)
        mx = self.P.max(axis=0)
        return mn, mx

    def kinetic(self):
        v = self.P - self.Pp
        return float(np.sqrt((v * v).sum(axis=1)).max())

# ----------------------------------------------------------------------------- window

class GarlandWindow(QWidget):
    FIXED_H = 1 / 120

    def __init__(self, cfg):
        super().__init__(None)
        self.cfg = cfg
        flags = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                 Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus |
                 Qt.WindowType.NoDropShadowWindowHint)
        if cfg.get("click_through"):
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowTitle("Dussehra Garland")

        self.cursor_override = None  # for automated tests
        self.bodies = []
        self.screen_ref = QGuiApplication.primaryScreen()
        self._setup_geometry()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.clock = QElapsedTimer()
        self.clock.start()
        self.acc = 0.0
        self.time = 0.0
        self.idle_time = 0.0
        self.active = True
        self.timer.start(16)
        self.screen_ref.availableGeometryChanged.connect(lambda _r: self._setup_geometry())

    # -- setup
    def _setup_geometry(self):
        geo = self.screen_ref.availableGeometry()
        self.setGeometry(geo)
        self.W, self.H = geo.width(), geo.height()
        self.s = max(0.8, min(1.5, self.W / 1920 * 1.1))
        self.floor = float(self.H)
        dpr = self.screen_ref.devicePixelRatio()
        self.dpr = dpr
        R = 14.0 * self.s
        self.spr_o = [make_marigold(R * random.uniform(0.94, 1.06), ORANGE, 100 + i, dpr) for i in range(5)]
        self.spr_y = [make_marigold(R * random.uniform(0.94, 1.06), YELLOW, 200 + i, dpr) for i in range(5)]
        self.spr_big = make_marigold(R * 1.25, ORANGE, 999, dpr)
        self.spr_leaf = [make_leaf(R * 2.5, R * 0.85, 300 + i, dpr) for i in range(5)]
        self.spr_petal = ([make_petal_sprite(R * 0.42, ORANGE, 400 + i, dpr) for i in range(4)] +
                          [make_petal_sprite(R * 0.42, YELLOW, 500 + i, dpr) for i in range(4)])
        # pre-rotated caches: blitting is ~5x faster than rotating with smoothing every frame
        self.rs_o = [RotSprite(pix, QPointF(hf, hf), 36) for pix, hf in self.spr_o]
        self.rs_y = [RotSprite(pix, QPointF(hf, hf), 36) for pix, hf in self.spr_y]
        self.rs_tassel = [RotSprite(_scaled(pix, 0.85), QPointF(hf * 0.85, hf * 0.85), 36)
                          for pix, hf in self.spr_o]
        self.rs_leaf_bead = [RotSprite(pix, QPointF(pv.x() + R * 0.15, pv.y()), 72) for pix, pv in self.spr_leaf]
        self.rs_leaf_pin = [RotSprite(pix, pv, 72) for pix, pv in self.spr_leaf]
        self.rs_leaf_fall = [RotSprite(pix, QPointF(pix.width() / pix.devicePixelRatio() / 2, pv.y()), 72)
                             for pix, pv in self.spr_leaf]
        self.rs_petal = [RotSprite(pix, QPointF(hf, hf), 24) for pix, hf in self.spr_petal]
        self.garland = Garland(self.W, self.H, self.s)
        self._build_tag()
        self.hand_prev = None
        self.hand_v = np.zeros(2)
        self.last_dirty = QRect(0, 0, self.W, self.H)
        self.update()

    def _build_tag(self):
        (self.tag_pix, self.tag_hole_px, self.tag_w, self.tag_h,
         self.tag_hole_y) = make_tag(self.cfg.get("tag_text", DEFAULT_TEXT), self.s, self.dpr)

    def set_tag_text(self, text):
        self.cfg["tag_text"] = text if text.strip() else DEFAULT_TEXT
        save_config(self.cfg)
        self._build_tag()
        # a little flutter when the text changes
        self.garland.P[self.garland.tag_bottom, 0] += 3 * self.s
        self.wake()

    # -- cursor
    def _cursor(self):
        if self.cursor_override is not None:
            return np.array(self.cursor_override, dtype=np.float64)
        p = self.mapFromGlobal(QCursor.pos())
        return np.array([p.x(), p.y()], dtype=np.float64)

    def wake(self):
        self.idle_time = 0.0
        if not self.active:
            self.active = True
            self.clock.restart()
            self.acc = 0.0
            self.timer.start(16)

    # -- main loop
    def tick(self):
        dt = min(self.clock.restart() / 1000.0, 0.05)
        if self.cursor_override is not None:
            dt = 1 / 60
        cur = self._cursor()
        prev = self.hand_prev if self.hand_prev is not None else cur
        moved = float(np.hypot(*(cur - prev)))
        if moved > 260 * self.s:
            # cursor teleported (another monitor, remote desktop, test hook): no sweep, no fling
            prev = cur
            self.hand_v[:] = 0.0
        else:
            self.hand_v = 0.5 * self.hand_v + 0.5 * (cur - prev) / max(dt, 1e-3)
            sp = float(np.hypot(*self.hand_v))
            vmax = 2500 * self.s
            if sp > vmax:
                self.hand_v *= vmax / sp
        g = self.garland
        mn, mx = g.bbox()
        margin = 40 * self.s + self.tag_w
        near_garland = (mn[0] - margin <= cur[0] <= mx[0] + margin and
                        mn[1] - margin <= cur[1] <= mx[1] + margin)
        near_floor = cur[1] > self.floor - 60 * self.s and any(b.kind == "flower" for b in self.bodies)

        if not self.active:
            if moved > 0.5 and (near_garland or near_floor):
                self.wake()
            self.hand_prev = cur
            return

        inside = 0 <= cur[0] <= self.W and 0 <= cur[1] <= self.H
        self.acc += dt
        steps = 0
        while self.acc >= self.FIXED_H and steps < 8:
            f0 = steps / max(1, round(dt / self.FIXED_H))
            f1 = min(1.0, (steps + 1) / max(1, round(dt / self.FIXED_H)))
            a = prev + (cur - prev) * f0
            b = prev + (cur - prev) * f1
            if inside and near_garland:
                g.step(self.FIXED_H, a, b, self.hand_v)
                self._tag_brush(b)
            else:
                g.step(self.FIXED_H, None, None)
            self._step_bodies(self.FIXED_H, b if inside else None)
            self.time += self.FIXED_H
            self.acc -= self.FIXED_H
            steps += 1
        if steps == 8:
            self.acc = 0.0
        self.hand_prev = cur

        # rest detection -> idle mode keeps CPU near zero
        moving_bodies = any(not (b.landed or (b.grounded and abs(b.vx) < 1 and abs(b.vy) < 1))
                            or (b.life > 0) for b in self.bodies)
        if g.kinetic() < 0.02 * self.s and not moving_bodies and moved < 0.5:
            self.idle_time += dt
        else:
            self.idle_time = 0.0
        self._repaint_dirty()
        if self.idle_time > 1.2:
            self.active = False
            self.timer.start(100)

    def _tag_brush(self, hand):
        g = self.garland
        if g.tag_contains(hand, self.tag_w, self.tag_h, self.tag_hole_y):
            # paper is light: its sideways velocity is nudged toward the hand's, never beyond it
            _h, _u, n = g.tag_frame()
            i = g.tag_bottom
            vb = (g.P[i] - g.Pp[i]) / self.FIXED_H
            rel = float((self.hand_v - vb) @ n)
            g.P[i] += n * rel * 0.06 * self.FIXED_H

    # -- falling bodies
    def _spawn_petals(self, x, y, vx, vy, n):
        for _ in range(n):
            b = Body("petal", x + random.uniform(-6, 6) * self.s, y + random.uniform(-6, 6) * self.s,
                     vx * 0.5 + random.uniform(-90, 90) * self.s, vy * 0.5 + random.uniform(-160, 20) * self.s,
                     4 * self.s, random.randrange(len(self.spr_petal)))
            self.bodies.append(b)

    def _step_bodies(self, h, hand):
        s, floor, W = self.s, self.floor, self.W
        gacc = self.garland.g
        flowers = []
        for b in self.bodies:
            b.age += h
            if b.kind == "flower":
                flowers.append(b)
                b.vy += gacc * h
                b.vx *= 1 - 0.15 * h
                b.x += b.vx * h
                b.y += b.vy * h
                b.squash *= math.exp(-10 * h)
                if b.y + b.r >= floor:
                    b.y = floor - b.r
                    if b.vy > 70 * s:
                        impact = b.vy
                        b.vy = -b.vy * 0.42            # soft, petal-packed ball: low restitution
                        b.vx *= 0.86
                        b.squash = min(0.28, impact / (2600 * s))
                        if impact > 500 * s and random.random() < 0.6:
                            self._spawn_petals(b.x, floor - 2 * s, b.vx, -abs(impact) * 0.2, random.randint(1, 2))
                        b.grounded = False
                    else:
                        b.vy = 0.0
                        b.grounded = True
                    if b.grounded:
                        b.vx *= max(0.0, 1 - 2.4 * h)  # rolling resistance
                        if abs(b.vx) < 2 * s:
                            b.vx = 0.0
                    b.angv = math.degrees(b.vx / b.r)   # roll without slipping
                else:
                    b.grounded = False
                b.ang += b.angv * h
                if b.x < b.r:
                    b.x, b.vx = b.r, abs(b.vx) * 0.5
                elif b.x > W - b.r:
                    b.x, b.vx = W - b.r, -abs(b.vx) * 0.5
                if hand is not None:
                    dx, dy = b.x - hand[0], b.y - hand[1]
                    d = math.hypot(dx, dy)
                    if 1e-6 < d < b.r + 9 * s:
                        nx, ny = dx / d, dy / d
                        b.x += nx * (b.r + 9 * s - d)
                        rel = self.hand_v[0] * nx + self.hand_v[1] * ny
                        if rel > 0:
                            b.vx += nx * rel * 0.6
                            b.vy += min(0.0, ny * rel * 0.6)
                        b.grounded = False
            else:
                # leaves and petals: heavy air drag + side-to-side flutter
                if not b.landed:
                    k = 7.5 if b.kind == "leaf" else 9.0
                    sway = math.sin(self.time * b.freq + b.phase)
                    b.vy += gacc * h
                    b.vx += sway * 420 * s * h
                    b.vx -= b.vx * k * 0.6 * h
                    b.vy -= b.vy * k * h
                    b.x += b.vx * h
                    b.y += b.vy * h
                    b.ang = (b.leaf_dir if b.kind == "leaf" else b.ang + b.angv * h * 0.5) + sway * 40
                    if b.y >= floor - b.r:
                        b.y = floor - b.r
                        b.landed = True
                        b.ang = b.leaf_dir + random.uniform(-8, 8) if b.kind == "leaf" else b.ang
                        b.life = 0.0
                    b.x = min(max(b.x, 0), W)
                else:
                    b.life += h
        # flower-flower collisions (sweep and prune along x)
        if len(flowers) > 1:
            flowers.sort(key=lambda f: f.x)
            n = len(flowers)
            for i in range(n):
                a = flowers[i]
                for j in range(i + 1, n):
                    c = flowers[j]
                    if c.x - a.x > a.r + c.r:
                        break
                    dx, dy = c.x - a.x, c.y - a.y
                    d = math.hypot(dx, dy)
                    rr = a.r + c.r
                    if 1e-6 < d < rr:
                        nx, ny = dx / d, dy / d
                        ov = (rr - d) * 0.5
                        a.x -= nx * ov
                        a.y -= ny * ov
                        c.x += nx * ov
                        c.y += ny * ov
                        rv = (c.vx - a.vx) * nx + (c.vy - a.vy) * ny
                        if rv < 0:
                            imp = -(1 + 0.3) * rv * 0.5
                            a.vx -= imp * nx
                            a.vy -= imp * ny
                            c.vx += imp * nx
                            c.vy += imp * ny
                        a.y = min(a.y, floor - a.r)
                        c.y = min(c.y, floor - c.r)
        # retire old leaves/petals, cap total flowers
        keep = []
        for b in self.bodies:
            if b.kind == "petal" and b.landed and b.life > 14:
                continue
            if b.kind == "leaf" and b.landed and b.life > 45:
                continue
            keep.append(b)
        fl = [b for b in keep if b.kind == "flower"]
        if len(fl) > 160:
            drop = set(id(b) for b in fl[:len(fl) - 160])
            keep = [b for b in keep if id(b) not in drop]
        self.bodies = keep

    # -- interaction
    def mousePressEvent(self, ev):
        pt = np.array([ev.position().x(), ev.position().y()])
        if ev.button() == Qt.MouseButton.RightButton:
            self.app_menu().exec(ev.globalPosition().toPoint())
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        self.click_at(pt)

    def mouseDoubleClickEvent(self, ev):
        pt = np.array([ev.position().x(), ev.position().y()])
        if self.garland.tag_contains(pt, self.tag_w, self.tag_h, self.tag_hole_y):
            self.edit_text()
        else:
            self.click_at(pt)

    def click_at(self, pt):
        self.wake()
        g = self.garland
        # fallen flowers: toss them back up
        for b in reversed(self.bodies):
            if b.kind == "flower" and math.hypot(b.x - pt[0], b.y - pt[1]) < b.r + 3:
                b.vy = -random.uniform(520, 780) * self.s
                b.vx += random.uniform(-160, 160) * self.s
                b.grounded = False
                return
        # beads on the string
        d = np.hypot(g.P[:, 0] - pt[0], g.P[:, 1] - pt[1])
        pluckable = np.isin(g.K, (FLOWER_O, FLOWER_Y, LEAF, TASSEL))
        cand = np.where(pluckable & (d < g.nr + 4 * self.s))[0]
        if len(cand):
            i = int(cand[np.argmin(d[cand])])
            self.pluck(i)
            return
        if g.tag_contains(pt, self.tag_w, self.tag_h, self.tag_hole_y):
            g.P[g.tag_bottom, 0] += random.choice((-1, 1)) * 3 * self.s
            return

    def pluck(self, i):
        g, s = self.garland, self.s
        k = int(g.K[i])
        x, y = g.P[i]
        vx, vy = (g.P[i] - g.Pp[i]) / self.FIXED_H
        if k in (FLOWER_O, FLOWER_Y):
            spr = ("o" if k == FLOWER_O else "y", int(g.sprite[i]))
            b = Body("flower", x, y, vx + random.uniform(-50, 50) * s, vy + random.uniform(-80, 0) * s,
                     g.R * 0.92, spr)
            b.ang = float(g.rot[i])
            self.bodies.append(b)
            self._spawn_petals(x, y, vx, vy, random.randint(3, 5))
        else:
            for _ in range(3 if k == TASSEL else 2):
                lf = Body("leaf", x, y, vx + random.uniform(-60, 60) * s, vy + random.uniform(-60, 0) * s,
                          3 * s, random.randrange(len(self.spr_leaf)))
                self.bodies.append(lf)
        g.K[i] = BARE
        g.Wt[i] = 1.4
        g._refresh_radii()
        # the string recoils a little once the weight is gone
        g.Pp[i, 1] += 2.5 * s

    def restring(self):
        g = self.garland
        g.K[:] = g.orig_kind
        g.Wt[:] = np.where(g.K == ANCHOR, 0.0, np.where(g.K == THREAD, 1.6,
                           np.where(g.K == TAG_BOTTOM, 0.45, 1.0)))
        g._refresh_radii()
        self.bodies = [b for b in self.bodies if b.kind != "flower"]
        self.wake()

    def clear_fallen(self):
        self.bodies = []
        self.wake()
        self.update()

    def edit_text(self):
        dlg = QInputDialog()
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.setWindowTitle("Garland tag text")
        dlg.setLabelText("Text on the paper tag (first line is the bold heading):")
        dlg.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput, True)
        dlg.setTextValue(self.cfg.get("tag_text", DEFAULT_TEXT))
        dlg.resize(440, 230)
        dlg.activateWindow()
        if dlg.exec():
            self.set_tag_text(dlg.textValue().strip())

    def set_click_through(self, on):
        self.cfg["click_through"] = bool(on)
        save_config(self.cfg)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, bool(on))
        self.show()
        self.wake()

    def app_menu(self):
        """One persistent menu shared by right-click and the tray icon."""
        if getattr(self, "_menu", None) is None:
            m = QMenu()
            m.addAction("Change tag text…", self.edit_text)
            m.addAction("Re-string garland", self.restring)
            m.addAction("Clear fallen flowers", self.clear_fallen)
            m.addSeparator()
            self._act_ct = QAction("Hover only (clicks pass through)", m, checkable=True)
            self._act_ct.toggled.connect(self.set_click_through)
            m.addAction(self._act_ct)
            self._act_auto = QAction("Start with Windows", m, checkable=True)
            self._act_auto.setEnabled(sys.platform == "win32")
            self._act_auto.toggled.connect(set_autostart)
            m.addAction(self._act_auto)
            self._act_vis = m.addAction("Hide garland", self.toggle_visible)
            m.addSeparator()
            m.addAction("Quit", QApplication.instance().quit)
            m.aboutToShow.connect(self._sync_menu)
            self._menu = m
        self._sync_menu()
        return self._menu

    def _sync_menu(self):
        for act, val in ((self._act_ct, bool(self.cfg.get("click_through"))),
                         (self._act_auto, autostart_enabled())):
            act.blockSignals(True)
            act.setChecked(val)
            act.blockSignals(False)
        self._act_vis.setText("Hide garland" if self.isVisible() else "Show garland")

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.wake()

    # -- painting
    def _dirty_rect(self):
        g = self.garland
        mn, mx = g.bbox()
        pad = self.R_pad()
        x0, y0 = mn[0] - pad, mn[1] - pad
        x1, y1 = mx[0] + pad + self.tag_w, mx[1] + pad + self.tag_w
        for b in self.bodies:
            r = 30 * self.s
            x0, y0 = min(x0, b.x - r), min(y0, b.y - r)
            x1, y1 = max(x1, b.x + r), max(y1, b.y + r)
        return QRect(int(x0), int(y0), int(x1 - x0) + 1, int(y1 - y0) + 1)

    def R_pad(self):
        return self.garland.R * 3.2

    def _repaint_dirty(self):
        r = self._dirty_rect()
        self.update(r.united(self.last_dirty))
        self.last_dirty = r

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect() if _ev is None else _ev.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.draw_scene(p)
        p.end()

    def draw_scene(self, p):
        g, s = self.garland, self.s
        P, K = g.P, g.K
        th = g.tangents()
        # mauli thread (red-yellow cotton) through everything
        thread = QColor(176, 24, 32)
        for chain in g.chains:
            path = QPainterPath()
            path.moveTo(float(P[chain[0], 0]), float(P[chain[0], 1]))
            for i in chain[1:]:
                path.lineTo(float(P[i, 0]), float(P[i, 1]))
            p.setPen(QPen(thread, 1.6 * s))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(QPen(QColor(230, 175, 40, 160), 0.6 * s, Qt.PenStyle.DashLine))
            p.drawPath(path)
        vel = (P - g.Pp) / self.FIXED_H
        bead_leaf, pin_leaf = self.rs_leaf_bead, self.rs_leaf_pin
        # leaves (behind flowers)
        for i in range(g.N):
            k = K[i]
            if k == LEAF or k == TASSEL:
                rel = math.degrees(th[i] - g.theta0[i])
                lag = max(-25.0, min(25.0, -vel[i, 0] * 0.04))
                if k == LEAF and abs(math.cos(g.theta0[i])) < 0.5:   # hanging strand: leaves flare sideways
                    base = math.degrees(th[i])
                    dirs = (base - 62 + lag, base + 62 + lag)
                elif k == LEAF:                                      # swag: leaves hang below the string
                    dirs = (90 - 30 + rel + lag, 90 + 30 + rel + lag)
                else:
                    base = math.degrees(th[i])
                    dirs = (base - 28 + lag, base + lag, base + 28 + lag)
                x, y = float(P[i, 0]), float(P[i, 1])
                for j, a in enumerate(dirs):
                    bead_leaf[(i + j) % len(bead_leaf)].draw(p, x, y, a)
        # pin decorations: leaf fan + big flower + brass nail
        for i in g.pins:
            x, y = float(P[i, 0]), float(P[i, 1])
            for j, a in enumerate((140, 90, 40, 200, -20)):
                pin_leaf[j % len(pin_leaf)].draw(p, x, y, a)
        # flowers
        for i in range(g.N):
            k = K[i]
            if k == FLOWER_O or k == FLOWER_Y:
                rot = g.rot[i] + math.degrees(th[i] - g.theta0[i]) * 0.6 + math.degrees(g.spin[i])
                (self.rs_o if k == FLOWER_O else self.rs_y)[g.sprite[i]].draw(
                    p, float(P[i, 0]), float(P[i, 1]), rot)
            elif k == TASSEL:
                self.rs_tassel[g.sprite[i]].draw(p, float(P[i, 0]), float(P[i, 1]),
                                                  g.rot[i] + math.degrees(g.spin[i]))
            elif k == BARE:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(120, 70, 20))
                p.drawEllipse(QPointF(float(P[i, 0]), float(P[i, 1])), 1.6 * s, 1.6 * s)
        for i in g.pins:
            x, y = float(P[i, 0]), float(P[i, 1])
            pix, half = self.spr_big
            p.drawPixmap(QPointF(x - half, y - half), pix)
            p.setPen(QPen(QColor(110, 70, 10), 1))
            p.setBrush(QColor(214, 170, 70))
            p.drawEllipse(QPointF(x, y), 3.2 * s, 3.2 * s)
        # tag (one large sprite: rotate it smoothly on the fly)
        h, u, _n = g.tag_frame()
        ang = math.degrees(math.atan2(u[1], u[0])) - 90
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(float(h[0]), float(h[1]))
        p.rotate(ang)
        p.drawPixmap(QPointF(-self.tag_hole_px.x(), -self.tag_hole_px.y()), self.tag_pix)
        p.restore()
        # falling / fallen bodies
        for b in self.bodies:
            alpha = 1.0
            if b.kind == "petal" and b.landed:
                alpha = max(0.0, min(1.0, (14 - b.life) / 2.0))
            elif b.kind == "leaf" and b.landed:
                alpha = max(0.0, min(1.0, (45 - b.life) / 3.0))
            if alpha <= 0:
                continue
            p.setOpacity(alpha)
            if b.kind == "flower":
                col, idx = b.sprite
                if b.squash > 0.01:   # brief squash on a hard landing
                    pix, half = (self.spr_o if col == "o" else self.spr_y)[idx]
                    p.save()
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                    p.translate(b.x, b.y + b.r * b.squash)
                    p.scale(1 + b.squash * 0.6, 1 - b.squash)
                    p.rotate(b.ang)
                    p.drawPixmap(QPointF(-half, -half), pix)
                    p.restore()
                else:
                    (self.rs_o if col == "o" else self.rs_y)[idx].draw(p, b.x, b.y, b.ang)
            elif b.kind == "leaf":
                self.rs_leaf_fall[b.sprite].draw(p, b.x, b.y, b.ang)
            else:
                self.rs_petal[b.sprite].draw(p, b.x, b.y, b.ang)
        p.setOpacity(1.0)

def make_tray(app, win, icon):
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Dussehra Garland — Doneology Labs")
    tray.setContextMenu(win.app_menu())
    tray.activated.connect(lambda reason: win.toggle_visible()
                           if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    tray.show()
    return tray


# ----------------------------------------------------------------------------- autostart (Windows)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command():
    if getattr(sys, "frozen", False):           # PyInstaller .exe
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    if sys.platform != "win32":
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                winreg.DeleteValue(k, APP_NAME)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description="Genda phool garland desktop decoration")
    ap.add_argument("--text", help='Tag text; use "\\n" for a new line')
    args = ap.parse_args()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # single instance: a second launch just exits
    lock = QLockFile(os.path.join(QDir.tempPath(), APP_NAME + ".lock"))
    if not lock.tryLock(100):
        return
    cfg = load_config()
    if args.text:
        cfg["tag_text"] = args.text.replace("\\n", "\n")
        save_config(cfg)
    win = GarlandWindow(cfg)
    icon = QIcon(make_marigold(28, ORANGE, 4242, 2.0)[0])
    app.setWindowIcon(icon)
    win.show()
    win.tray = make_tray(app, win, icon) if QSystemTrayIcon.isSystemTrayAvailable() else None
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
