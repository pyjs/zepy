"""Rectangle renderer."""

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
    GPUDevice,
    GPUFragmentState,
    GPUPrimitiveState,
    GPURenderPassEncoder,
    GPURenderPipeline,
    GPURenderPipelineDescriptor,
    GPUShaderModuleDescriptor,
    GPUVertexAttribute,
    GPUVertexBufferLayout,
    GPUVertexState,
)

from zepy.base.common.lifecycle import Disposable
from zepy.editor.browser.gpu.gpu import (
    FLOATS_PER_SHAPE,
    RECTANGLE_RENDERER_WGSL,
)
from zepy.editor.browser.gpu.gpu_disposable import create_buffer
from zepy.editor.browser.gpu.gpu_utils import quad_vertices


@js
class RectangleRenderer(Disposable):
    def __init__(
        self,
        device: GPUDevice,
        canvas: HTMLCanvasElement,
        context: GPUCanvasContext,
        pipeline: GPURenderPipeline,
        vertex_buffer: GPUBuffer,
        shape_buffer: GPUBuffer,
        layout_buffer: GPUBuffer,
        scroll_buffer: GPUBuffer,
        bind_group: GPUBindGroup,
        max_shapes: int,
    ):
        super().__init__()
        self._device = device
        self._canvas = canvas
        self._context = context
        self._pipeline = pipeline
        self._vertex_buffer = vertex_buffer
        self._shape_buffer = shape_buffer
        self._layout_buffer = layout_buffer
        self._scroll_buffer = scroll_buffer
        self._bind_group = bind_group
        self._max_shapes = max_shapes
        self._shapes = Float32Array(max_shapes * FLOATS_PER_SHAPE)
        self._shape_count = 0

    @staticmethod
    async def create(
        device: GPUDevice,
        canvas: HTMLCanvasElement,
        context: GPUCanvasContext,
        format: str,
    ) -> RectangleRenderer:
        max_shapes = 1024
        shader = device.createShaderModule(
            GPUShaderModuleDescriptor(RECTANGLE_RENDERER_WGSL, label="zepy-rect")
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
                label="zepy-rect-verts",
            ),
            verts,
        )
        shape_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                max_shapes * FLOATS_PER_SHAPE * 4,
                GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
                label="zepy-rect-shapes",
            ),
        )
        layout_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                32,
                GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
                label="zepy-rect-layout",
            ),
        )
        scroll_buffer = create_buffer(
            device,
            GPUBufferDescriptor(
                16,
                GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
                label="zepy-rect-scroll",
            ),
        )
        bind_group = device.createBindGroup(
            GPUBindGroupDescriptor(
                pipeline.getBindGroupLayout(0),
                [
                    GPUBindGroupEntry(0, GPUBufferBinding(shape_buffer)),
                    GPUBindGroupEntry(1, GPUBufferBinding(layout_buffer)),
                    GPUBindGroupEntry(2, GPUBufferBinding(scroll_buffer)),
                ],
            )
        )
        renderer = RectangleRenderer(
            device,
            canvas,
            context,
            pipeline,
            vertex_buffer,
            shape_buffer,
            layout_buffer,
            scroll_buffer,
            bind_group,
            max_shapes,
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
        scroll = Float32Array(4)
        scroll[0] = scroll_x
        scroll[1] = scroll_y
        self._device.queue.writeBuffer(self._scroll_buffer, 0, scroll)

    def clear(self) -> None:
        self._shape_count = 0

    def register(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        red: float,
        green: float,
        blue: float,
        alpha: float,
    ) -> None:
        if self._shape_count >= self._max_shapes:
            return
        base = self._shape_count * FLOATS_PER_SHAPE
        self._shapes[base] = x
        self._shapes[base + 1] = y
        self._shapes[base + 2] = width
        self._shapes[base + 3] = height
        self._shapes[base + 4] = red
        self._shapes[base + 5] = green
        self._shapes[base + 6] = blue
        self._shapes[base + 7] = alpha
        self._shape_count = self._shape_count + 1

    def draw(self, pass_encoder: GPURenderPassEncoder) -> None:
        if self._shape_count <= 0:
            return
        self._device.queue.writeBuffer(self._shape_buffer, 0, self._shapes)
        pass_encoder.setPipeline(self._pipeline)
        pass_encoder.setVertexBuffer(0, self._vertex_buffer)
        pass_encoder.setBindGroup(0, self._bind_group)
        pass_encoder.draw(6, self._shape_count)
