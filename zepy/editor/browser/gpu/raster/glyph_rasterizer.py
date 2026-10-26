"""Greyscale glyph rasterization."""

from pyjs import js
from pyjs.web.html import (
    CanvasRenderingContext2DSettings,
    OffscreenCanvas,
    OffscreenCanvasRenderingContext2D,
    get_offscreen_2d_context,
)

from zepy.base.common.errors import BugIndicatingError
from zepy.base.common.lifecycle import Disposable


@js
class BoundingBox:
    def __init__(self, left: int, top: int, right: int, bottom: int):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


@js
class OriginOffset:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y


@js
class RasterizedGlyph:
    def __init__(
        self,
        source: OffscreenCanvas,
        bounding_box: BoundingBox,
        origin_offset: OriginOffset,
        font_bounding_box_ascent: float,
        font_bounding_box_descent: float,
    ):
        self.source = source
        self.bounding_box = bounding_box
        self.origin_offset = origin_offset
        self.font_bounding_box_ascent = font_bounding_box_ascent
        self.font_bounding_box_descent = font_bounding_box_descent


@js
class GlyphRasterizer(Disposable):
    def __init__(self, font_size: float, font_family: str, device_pixel_ratio: float):
        super().__init__()
        self.font_size = font_size
        self.font_family = font_family
        self.device_pixel_ratio = device_pixel_ratio
        device_pixel_font_size = int(font_size * device_pixel_ratio)
        device_pixel_font_size = max(device_pixel_font_size, 1)
        self._device_pixel_font_size = device_pixel_font_size
        dim = device_pixel_font_size * 3
        self._canvas = OffscreenCanvas(dim, dim)
        context = get_offscreen_2d_context(
            self._canvas,
            CanvasRenderingContext2DSettings(alpha=True, willReadFrequently=True),
        )
        if context is None:
            raise BugIndicatingError("OffscreenCanvas 2d context is unavailable")
        self._ctx: OffscreenCanvasRenderingContext2D = context
        self._ctx.textBaseline = "top"
        self._ctx.font = str(device_pixel_font_size) + "px " + font_family
        metrics = self._ctx.measureText("A")
        space_width = self._ctx.measureText(" ").width
        em_width = self._ctx.measureText("M").width
        quote_width = self._ctx.measureText('"').width
        self.space_width = max(space_width, em_width, quote_width)
        self.font_bounding_box_ascent = metrics.fontBoundingBoxAscent
        self.font_bounding_box_descent = metrics.fontBoundingBoxDescent
        if self.font_bounding_box_ascent + self.font_bounding_box_descent <= 0.0:
            self.font_bounding_box_ascent = float(device_pixel_font_size)
            self.font_bounding_box_descent = 0.0

    def rasterize_glyph(self, chars: str, color: str) -> RasterizedGlyph:
        if chars == "":
            return RasterizedGlyph(
                self._canvas,
                BoundingBox(0, 0, -1, -1),
                OriginOffset(0, 0),
                0.0,
                0.0,
            )
        dim = self._device_pixel_font_size * 3
        if self._canvas.width != dim:
            self._canvas.width = dim
            self._canvas.height = dim
            self._ctx.font = str(self._device_pixel_font_size) + "px " + self.font_family
            self._ctx.textBaseline = "top"
        self._ctx.clearRect(0, 0, dim, dim)
        self._ctx.fillStyle = color
        origin_x = self._device_pixel_font_size
        origin_y = self._device_pixel_font_size
        self._ctx.fillText(chars, float(origin_x), float(origin_y))
        metrics = self._ctx.measureText(chars)
        glyph_width = int(metrics.width) + 2
        if glyph_width < 2:
            glyph_width = self._device_pixel_font_size
        glyph_height = self._device_pixel_font_size + 2
        left = origin_x - 1
        top = origin_y - 1
        right = left + glyph_width - 1
        bottom = top + glyph_height - 1
        if right >= dim:
            right = dim - 1
        if bottom >= dim:
            bottom = dim - 1
        box = BoundingBox(left, top, right, bottom)
        return RasterizedGlyph(
            self._canvas,
            box,
            OriginOffset(box.left - origin_x, box.top - origin_y),
            self.font_bounding_box_ascent,
            self.font_bounding_box_descent,
        )
