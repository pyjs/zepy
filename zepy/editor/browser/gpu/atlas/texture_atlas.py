"""Texture atlas."""

from pyjs import js
from pyjs.web.html import OffscreenCanvas

from zepy.base.common.lifecycle import Disposable
from zepy.editor.browser.gpu.atlas.texture_atlas_shelf_allocator import (
    TextureAtlasPageGlyph,
    TextureAtlasShelfAllocator,
)
from zepy.editor.browser.gpu.gpu import MAXIMUM_GLYPH_COUNT
from zepy.editor.browser.gpu.raster.glyph_rasterizer import GlyphRasterizer


@js
class TextureAtlas(Disposable):
    def __init__(self, page_size: int):
        super().__init__()
        self.page_size = page_size
        self._canvas = OffscreenCanvas(page_size, page_size)
        self._allocator = TextureAtlasShelfAllocator(self._canvas, 0)
        self._glyphs: dict[str, TextureAtlasPageGlyph] = {}
        self._allocated: list[TextureAtlasPageGlyph] = []
        self.version = 0
        self.used_right = 0
        self.used_bottom = 0

    def source(self) -> OffscreenCanvas:
        return self._canvas

    def get_glyph(
        self, rasterizer: GlyphRasterizer, chars: str, color: str
    ) -> TextureAtlasPageGlyph | None:
        key = chars + ":" + color
        existing = self._glyphs.get(key)
        if existing is not None:
            return existing
        if len(self._glyphs) + 1 >= MAXIMUM_GLYPH_COUNT:
            return None
        rasterized = rasterizer.rasterize_glyph(chars, color)
        glyph = self._allocator.allocate(rasterized)
        if glyph is None:
            return None
        self._glyphs[key] = glyph
        self._allocated.append(glyph)
        right = glyph.x + glyph.w - 1
        bottom = glyph.y + glyph.h - 1
        self.used_right = max(self.used_right, right)
        self.used_bottom = max(self.used_bottom, bottom)
        self.version = self.version + 1
        return glyph

    def allocated_glyphs(self) -> list[TextureAtlasPageGlyph]:
        return self._allocated
