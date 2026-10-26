"""Gpu."""

from typing import Final

from pyjs import JS

BINDING_GLYPH_INFO: Final[JS] = 0
BINDING_CELLS: Final[JS] = 1
BINDING_TEXTURE_SAMPLER: Final[JS] = 2
BINDING_TEXTURE: Final[JS] = 3
BINDING_LAYOUT_INFO: Final[JS] = 4
BINDING_ATLAS_DIMS: Final[JS] = 5
BINDING_SCROLL_OFFSET: Final[JS] = 6

RECT_BINDING_SHAPES: Final[JS] = 0
RECT_BINDING_LAYOUT_INFO: Final[JS] = 1
RECT_BINDING_SCROLL_OFFSET: Final[JS] = 2

MAXIMUM_GLYPH_COUNT: Final[JS] = 256
MAXIMUM_PAGE_COUNT: Final[JS] = 1
FLOATS_PER_CELL: Final[JS] = 6
FLOATS_PER_GLYPH: Final[JS] = 6
FLOATS_PER_SHAPE: Final[JS] = 8

RECTANGLE_RENDERER_WGSL: Final[JS] = """
struct Vertex {
    @location(0) position: vec2f,
};
struct LayoutInfo {
    canvasDims: vec2f,
    viewportOffset: vec2f,
    viewportDims: vec2f,
    _pad: vec2f,
};
struct ScrollOffset {
    offset: vec2f,
    _pad: vec2f,
};
struct Shape {
    position: vec2f,
    size: vec2f,
    color: vec4f,
};
struct VSOutput {
    @builtin(position) position: vec4f,
    @location(0) color: vec4f,
};
@group(0) @binding(1) var<uniform> layoutInfo: LayoutInfo;
@group(0) @binding(0) var<storage, read> shapes: array<Shape>;
@group(0) @binding(2) var<uniform> scrollOffset: ScrollOffset;
@vertex fn vs(vert: Vertex, @builtin(instance_index) instanceIndex: u32) -> VSOutput {
    let shape = shapes[instanceIndex];
    var vsOut: VSOutput;
    vsOut.position = vec4f(
        vec2f(-1.0, 1.0) +
        vec2f(2.0, -2.0) / layoutInfo.canvasDims *
        (layoutInfo.viewportOffset - scrollOffset.offset + shape.position + vert.position * shape.size),
        0.0,
        1.0
    );
    vsOut.color = shape.color;
    return vsOut;
}
@fragment fn fs(vsOut: VSOutput) -> @location(0) vec4f {
    return vsOut.color;
}
"""

FULL_FILE_RENDER_STRATEGY_WGSL: Final[JS] = """
struct GlyphInfo {
    position: vec2f,
    size: vec2f,
    origin: vec2f,
};
struct Vertex {
    @location(0) position: vec2f,
};
struct Cell {
    position: vec2f,
    unused1: vec2f,
    glyphIndex: f32,
    textureIndex: f32,
};
struct LayoutInfo {
    canvasDims: vec2f,
    viewportOffset: vec2f,
    viewportDims: vec2f,
    _pad: vec2f,
};
struct ScrollOffset {
    offset: vec2f,
    _pad: vec2f,
};
struct AtlasDims {
    size: vec2f,
    _pad: vec2f,
};
struct VSOutput {
    @builtin(position) position: vec4f,
    @location(0) texcoord: vec2f,
};
@group(0) @binding(4) var<uniform> layoutInfo: LayoutInfo;
@group(0) @binding(5) var<uniform> atlasDims: AtlasDims;
@group(0) @binding(6) var<uniform> scrollOffset: ScrollOffset;
@group(0) @binding(0) var<storage, read> glyphInfo: array<array<GlyphInfo, 256>, 1>;
@group(0) @binding(1) var<storage, read> cells: array<Cell>;
@vertex fn vs(vert: Vertex, @builtin(instance_index) instanceIndex: u32) -> VSOutput {
    let cell = cells[instanceIndex];
    var glyph = glyphInfo[u32(cell.textureIndex)][u32(cell.glyphIndex)];
    var vsOut: VSOutput;
    vsOut.position = vec4f(
        vec2f(-1.0, 1.0) +
        ((vert.position * vec2f(2.0, -2.0)) / layoutInfo.canvasDims) * glyph.size +
        ((cell.position * vec2f(2.0, -2.0)) / layoutInfo.canvasDims) +
        ((glyph.origin * vec2f(2.0, -2.0)) / layoutInfo.canvasDims) +
        (((layoutInfo.viewportOffset - scrollOffset.offset * vec2f(1.0, -1.0)) * 2.0) / layoutInfo.canvasDims),
        0.0,
        1.0
    );
    vsOut.texcoord = (glyph.position / atlasDims.size) + (vert.position * (glyph.size / atlasDims.size));
    return vsOut;
}
@group(0) @binding(2) var ourSampler: sampler;
@group(0) @binding(3) var ourTexture: texture_2d<f32>;
@fragment fn fs(vsOut: VSOutput) -> @location(0) vec4f {
    return textureSample(ourTexture, ourSampler, vsOut.texcoord);
}
"""
