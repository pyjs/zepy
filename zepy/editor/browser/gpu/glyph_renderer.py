"""Glyph renderer."""

from pyjs import js
from pyjs.javascript import Float32Array
from pyjs.web.html import HTMLCanvasElement
from pyjs.web.webgpu import (
    GPUBindGroup,
    GPUBindGroupDescriptor,
    GPUBindGroupEntry,
    GPUBlendComponent,
    GPUBlendState,
    GPUBuffer,
    GPUBufferBinding,
    GPUBufferDescriptor,
    GPUBufferUsage,
    GPUCanvasContext,
    GPUColorTargetState,
    GPUCopyExternalImageDestInfo,
    GPUCopyExternalImageSourceInfo,
    GPUDevice,
    GPUExtent3D,
    GPUFragmentState,
    GPUPrimitiveState,
    GPURenderPassEncoder,
    GPURenderPipeline,
    GPURenderPipelineDescriptor,
    GPUShaderModuleDescriptor,
    GPUTexture,
    GPUTextureDescriptor,
    GPUTextureUsage,
    GPUVertexAttribute,
    GPUVertexBufferLayout,
    GPUVertexState,
)

from zepy.base.common.lifecycle import Disposable
from zepy.editor.browser.gpu.atlas.texture_atlas import TextureAtlas
from zepy.editor.browser.gpu.gpu import (
    FLOATS_PER_CELL,
    FLOATS_PER_GLYPH,
    FULL_FILE_RENDER_STRATEGY_WGSL,
    MAXIMUM_GLYPH_COUNT,
)
from zepy.editor.browser.gpu.gpu_disposable import create_buffer, create_texture
from zepy.editor.browser.gpu.gpu_utils import device_pixel_ratio, quad_vertices
from zepy.editor.browser.gpu.raster.glyph_rasterizer import GlyphRasterizer
from zepy.editor.common.folds import hidden_flags
from zepy.editor.common.model.piece_tree_text_buffer.piece_tree_base import PieceTreeBase
from zepy.editor.common.tokenize import tokenize_line
from zepy.editor.common.wrap import wrapped_row_count


@js
class GlyphRenderer(Disposable):
    def __init__(
        self,
        device: GPUDevice,
        canvas: HTMLCanvasElement,
        pipeline: GPURenderPipeline,
        vertex_buffer: GPUBuffer,
        glyph_buffer: GPUBuffer,
        cell_buffer: GPUBuffer,
        layout_buffer: GPUBuffer,
        atlas_dims_buffer: GPUBuffer,
        scroll_buffer: GPUBuffer,
        atlas_texture: GPUTexture,
        bind_group: GPUBindGroup,
        rasterizer: GlyphRasterizer,
        atlas: TextureAtlas,
        max_cells: int,
        glyph_color: str,
    ):
        super().__init__()
        self._device = device
        self._canvas = canvas
        self._pipeline = pipeline
        self._vertex_buffer = vertex_buffer
        self._glyph_buffer = glyph_buffer
        self._cell_buffer = cell_buffer
        self._layout_buffer = layout_buffer
        self._atlas_dims_buffer = atlas_dims_buffer
        self._scroll_buffer = scroll_buffer
        self._atlas_texture = atlas_texture
        self._bind_group = bind_group
        self.rasterizer = rasterizer
        self.atlas = atlas
        self._max_cells = max_cells
        self._glyph_color = glyph_color
        self._cells = Float32Array(max_cells * FLOATS_PER_CELL)
        self._glyphs = Float32Array(MAXIMUM_GLYPH_COUNT * FLOATS_PER_GLYPH)
        self._cell_count = 0
        self._uploaded_atlas_version = -1

    @staticmethod
    async def create(
        device: GPUDevice,
        canvas: HTMLCanvasElement,
        context: GPUCanvasContext,
        format: str,
        font_size: float,
        font_family: str,
        glyph_color: str,
    ) -> GlyphRenderer:
        max_cells = 80 * 200
        ratio = device_pixel_ratio()
        page_size = 512
        if ratio >= 1.5:
            page_size = 1024
        shader = device.createShaderModule(
            GPUShaderModuleDescriptor(FULL_FILE_RENDER_STRATEGY_WGSL, label="zepy-glyphs")
        )
        blend = GPUBlendState(
            GPUBlendComponent(dstFactor="one-minus-src-alpha", srcFactor="src-alpha"),
            GPUBlendComponent(dstFactor="one-minus-src-alpha", srcFactor="src-alpha"),
        )
        pipeline = await device.createRenderPipelineAsync(
            GPURenderPipelineDescriptor(
                GPUVertexState(
                    shader,
                    "vs",
                    [
                        GPUVertexBufferLayout(
                            8,
                            [GPUVertexAttribute("float32x2", 0, 0)],
                        )
                    ],
                ),
                GPUFragmentState(
                    shader,
                    "fs",
                    [GPUColorTargetState(format, blend=blend)],
                ),
                GPUPrimitiveState(cull_mode="none"),
            )
        )
        verts = quad_vertices()
        vertex_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                verts.byteLength,
                GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
                label="zepy-glyph-verts",
            ),
            verts,
        )
        glyph_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                MAXIMUM_GLYPH_COUNT * FLOATS_PER_GLYPH * 4,
                GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
                label="zepy-glyph-info",
            ),
        )
        cell_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                max_cells * FLOATS_PER_CELL * 4,
                GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
                label="zepy-cells",
            ),
        )
        layout_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                32,
                GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
                label="zepy-glyph-layout",
            ),
        )
        atlas_dims_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                16,
                GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
                label="zepy-atlas-dims",
            ),
        )
        scroll_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                16,
                GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
                label="zepy-glyph-scroll",
            ),
        )
        atlas_texture = create_texture(
            device,
            GPUTextureDescriptor(
                GPUExtent3D(page_size, page_size),
                "rgba8unorm",
                GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
                label="zepy-atlas",
            ),
        )
        sampler = device.createSampler(magFilter="nearest", minFilter="nearest")
        bind_group = device.createBindGroup(
            GPUBindGroupDescriptor(
                pipeline.getBindGroupLayout(0),
                [
                    GPUBindGroupEntry(0, GPUBufferBinding(glyph_buffer)),
                    GPUBindGroupEntry(1, GPUBufferBinding(cell_buffer)),
                    GPUBindGroupEntry(2, sampler),
                    GPUBindGroupEntry(3, atlas_texture.createView()),
                    GPUBindGroupEntry(4, GPUBufferBinding(layout_buffer)),
                    GPUBindGroupEntry(5, GPUBufferBinding(atlas_dims_buffer)),
                    GPUBindGroupEntry(6, GPUBufferBinding(scroll_buffer)),
                ],
            )
        )
        rasterizer = GlyphRasterizer(font_size, font_family, ratio)
        atlas = TextureAtlas(page_size)
        renderer = GlyphRenderer(
            device,
            canvas,
            pipeline,
            vertex_buffer,
            glyph_buffer,
            cell_buffer,
            layout_buffer,
            atlas_dims_buffer,
            scroll_buffer,
            atlas_texture,
            bind_group,
            rasterizer,
            atlas,
            max_cells,
            glyph_color,
        )
        renderer.write_layout()
        return renderer

    def write_layout(self, scroll_x: float = 0.0, scroll_y: float = 0.0) -> None:
        values = Float32Array(8)
        values[0] = float(self._canvas.width)
        values[1] = float(self._canvas.height)
        values[2] = 0.0
        values[3] = 0.0
        values[4] = float(self._canvas.width)
        values[5] = float(self._canvas.height)
        self._device.queue.writeBuffer(self._layout_buffer, 0, values)
        dims = Float32Array(4)
        dims[0] = float(self.atlas.page_size)
        dims[1] = float(self.atlas.page_size)
        self._device.queue.writeBuffer(self._atlas_dims_buffer, 0, dims)
        scroll = Float32Array(4)
        scroll[0] = scroll_x
        scroll[1] = scroll_y
        self._device.queue.writeBuffer(self._scroll_buffer, 0, scroll)

    def line_height(self) -> float:
        height = (
            self.rasterizer.font_bounding_box_ascent + self.rasterizer.font_bounding_box_descent
        )
        if height <= 0.0:
            return self.rasterizer.font_size * 1.4
        return height

    def cell_width(self) -> float:
        width = self.rasterizer.space_width
        if width <= 0.0:
            return self.rasterizer.font_size * 0.6
        return width

    def gutter_width(self) -> float:
        return self.cell_width() * 6.0

    def _emit_cell(self, cell_index: int, x: float, y: float, chars: str, color: str) -> int:
        if cell_index >= self._max_cells:
            return cell_index
        glyph = self.atlas.get_glyph(self.rasterizer, chars, color)
        base = cell_index * FLOATS_PER_CELL
        self._cells[base] = x
        self._cells[base + 1] = y
        self._cells[base + 2] = 0.0
        self._cells[base + 3] = 0.0
        if glyph is None:
            self._cells[base + 4] = 0.0
            self._cells[base + 5] = 0.0
        else:
            self._cells[base + 4] = float(glyph.glyph_index)
            self._cells[base + 5] = float(glyph.page_index)
        return cell_index + 1

    def update(
        self,
        buffer: PieceTreeBase,
        scroll_y: float,
        view_height: float,
        line_number_color: str,
        language: str,
        scroll_x: float = 0.0,
        fold_starts: list[int] | None = None,
        fold_ends: list[int] | None = None,
        wrap_columns: int = 0,
    ) -> None:
        line_height = self.line_height()
        cell_width = self.cell_width()
        gutter = self.gutter_width()
        line_count = buffer.get_line_count()
        starts: list[int] = []
        ends: list[int] = []
        if fold_starts is not None:
            starts = fold_starts
        if fold_ends is not None:
            ends = fold_ends
        flags = hidden_flags(line_count, starts, ends)
        first_view = int(scroll_y / line_height)
        first_view = max(first_view, 0)
        visible = int(view_height / line_height) + 3
        canvas_width = float(self._canvas.width)
        used_scroll_x = scroll_x
        if wrap_columns > 0:
            used_scroll_x = 0.0
        state = 0
        cell_index = 0
        drawn = 0
        visual_row = 0
        line_number = 1
        while line_number <= line_count and drawn <= visible:
            hidden = False
            if line_number - 1 < len(flags) and flags[line_number - 1] == 1:
                hidden = True
            line = buffer.get_line_content(line_number)
            tokens = tokenize_line(line, language, state)
            state = tokens.end_state
            if hidden:
                line_number = line_number + 1
                continue
            rows = 1
            if wrap_columns > 0:
                rows = wrapped_row_count(len(line), wrap_columns)
            if visual_row + rows <= first_view:
                visual_row = visual_row + rows
                line_number = line_number + 1
                continue
            wrap_row = 0
            while wrap_row < rows:
                if visual_row + wrap_row < first_view:
                    wrap_row = wrap_row + 1
                    continue
                y = float(visual_row + wrap_row) * line_height
                if wrap_row == 0:
                    label = str(line_number)
                    label_x = gutter - cell_width * float(len(label)) - 8.0
                    digit = 0
                    while digit < len(label):
                        cell_index = self._emit_cell(
                            cell_index, label_x, y, label[digit], line_number_color
                        )
                        label_x = label_x + cell_width
                        digit = digit + 1
                if wrap_columns < 1:
                    column = 0
                    x = gutter - used_scroll_x
                    while column < len(line):
                        chars = line[column]
                        advance = cell_width
                        if chars == "\t":
                            advance = cell_width * 4.0
                        if x + advance > gutter - 1.0 and x < canvas_width + cell_width:
                            cell_index = self._emit_cell(
                                cell_index, x, y, chars, tokens.color_at(column)
                            )
                        x = x + advance
                        column = column + 1
                else:
                    start = wrap_row * wrap_columns
                    column = start
                    x = gutter
                    limit = start + wrap_columns
                    while column < len(line) and column < limit:
                        chars = line[column]
                        advance = cell_width
                        if chars == "\t":
                            advance = cell_width * 4.0
                        if x + advance > gutter - 1.0 and x < canvas_width + cell_width:
                            cell_index = self._emit_cell(
                                cell_index, x, y, chars, tokens.color_at(column)
                            )
                        x = x + advance
                        column = column + 1
                drawn = drawn + 1
                wrap_row = wrap_row + 1
                if drawn > visible:
                    break
            visual_row = visual_row + rows
            line_number = line_number + 1
        self._cell_count = cell_index
        self._device.queue.writeBuffer(self._cell_buffer, 0, self._cells)
        self._upload_atlas()

    def _upload_atlas(self) -> None:
        if self._uploaded_atlas_version == self.atlas.version:
            return
        self._uploaded_atlas_version = self.atlas.version
        allocated = self.atlas.allocated_glyphs()
        index = 0
        while index < len(allocated):
            glyph = allocated[index]
            base = glyph.glyph_index * FLOATS_PER_GLYPH
            self._glyphs[base] = float(glyph.x)
            self._glyphs[base + 1] = float(glyph.y)
            self._glyphs[base + 2] = float(glyph.w)
            self._glyphs[base + 3] = float(glyph.h)
            self._glyphs[base + 4] = float(glyph.origin_offset_x)
            self._glyphs[base + 5] = float(glyph.origin_offset_y)
            index = index + 1
        self._device.queue.writeBuffer(self._glyph_buffer, 0, self._glyphs)
        self._device.queue.copyExternalImageToTexture(
            GPUCopyExternalImageSourceInfo(self.atlas.source()),
            GPUCopyExternalImageDestInfo(self._atlas_texture),
            width=self.atlas.page_size,
            height=self.atlas.page_size,
        )

    def draw(self, pass_encoder: GPURenderPassEncoder) -> None:
        if self._cell_count <= 0:
            return
        pass_encoder.setPipeline(self._pipeline)
        pass_encoder.setVertexBuffer(0, self._vertex_buffer)
        pass_encoder.setBindGroup(0, self._bind_group)
        pass_encoder.draw(6, self._cell_count)
