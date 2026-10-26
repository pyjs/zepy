"""Texture atlas shelf allocator."""

from pyjs import js
from pyjs.web.html import (
    CanvasRenderingContext2DSettings,
    OffscreenCanvas,
    OffscreenCanvasRenderingContext2D,
    draw_image_source,
    get_offscreen_2d_context,
)

from zepy.base.common.errors import BugIndicatingError
from zepy.editor.browser.gpu.raster.glyph_rasterizer import RasterizedGlyph


@js
class TextureAtlasPageGlyph:
    def __init__(
        self,
        page_index: int,
        glyph_index: int,
        x: int,
        y: int,
        w: int,
        h: int,
        origin_offset_x: int,
        origin_offset_y: int,
        font_bounding_box_ascent: float,
        font_bounding_box_descent: float,
    ):
        self.page_index = page_index
        self.glyph_index = glyph_index
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.origin_offset_x = origin_offset_x
        self.origin_offset_y = origin_offset_y
        self.font_bounding_box_ascent = font_bounding_box_ascent
        self.font_bounding_box_descent = font_bounding_box_descent


@js
class TextureAtlasShelf:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.h = 0


@js
class TextureAtlasShelfAllocator:
    def __init__(self, canvas: OffscreenCanvas, texture_index: int):
        self._canvas = canvas
        self._texture_index = texture_index
        context = get_offscreen_2d_context(
            canvas,
            CanvasRenderingContext2DSettings(alpha=True, willReadFrequently=True),
        )
        if context is None:
            raise BugIndicatingError("OffscreenCanvas 2d context is unavailable")
        self._ctx: OffscreenCanvasRenderingContext2D = context
        self._current_row = TextureAtlasShelf()
        self._next_index = 1

    def allocate(self, rasterized: RasterizedGlyph) -> TextureAtlasPageGlyph | None:
        glyph_width = rasterized.bounding_box.right - rasterized.bounding_box.left + 1
        glyph_height = rasterized.bounding_box.bottom - rasterized.bounding_box.top + 1
        if glyph_width <= 0 or glyph_height <= 0:
            return TextureAtlasPageGlyph(
                self._texture_index,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0.0,
                0.0,
            )
        if glyph_width > self._canvas.width or glyph_height > self._canvas.height:
            raise BugIndicatingError("Glyph is too large for the atlas page")
        if glyph_width > self._canvas.width - self._current_row.x:
            self._current_row.x = 0
            self._current_row.y = self._current_row.y + self._current_row.h
            self._current_row.h = 1
        if self._current_row.y + glyph_height > self._canvas.height:
            return None
        draw_image_source(
            self._ctx,
            rasterized.source,
            float(rasterized.bounding_box.left),
            float(rasterized.bounding_box.top),
            float(glyph_width),
            float(glyph_height),
            float(self._current_row.x),
            float(self._current_row.y),
            float(glyph_width),
            float(glyph_height),
        )
        glyph = TextureAtlasPageGlyph(
            self._texture_index,
            self._next_index,
            self._current_row.x,
            self._current_row.y,
            glyph_width,
            glyph_height,
            rasterized.origin_offset.x,
            rasterized.origin_offset.y,
            rasterized.font_bounding_box_ascent,
            rasterized.font_bounding_box_descent,
        )
        self._next_index = self._next_index + 1
        self._current_row.x = self._current_row.x + glyph_width
        self._current_row.h = max(self._current_row.h, glyph_height)
        return glyph
