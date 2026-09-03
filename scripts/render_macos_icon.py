#!/usr/bin/env python3
"""Render the source SVG into Apple's required iconset using QtSvg."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main(source: str, destination: str) -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(source)
    if not renderer.isValid():
        raise SystemExit(f"Invalid icon SVG: {source}")
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            image = QImage(pixels, pixels, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter, QRectF(0, 0, pixels, pixels))
            painter.end()
            suffix = "@2x" if scale == 2 else ""
            output = target / f"icon_{size}x{size}{suffix}.png"
            if not image.save(str(output)):
                raise SystemExit(f"Could not write {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
