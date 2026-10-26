"""Gpu disposable."""

from pyjs import js
from pyjs.javascript import Float32Array
from pyjs.web.webgpu import (
    GPUBuffer,
    GPUBufferDescriptor,
    GPUDevice,
    GPUTexture,
    GPUTextureDescriptor,
    navigator,
)

from zepy.base.common.errors import BugIndicatingError


@js
async def request_device() -> GPUDevice:
    if navigator.gpu is None:
        raise BugIndicatingError("This browser does not support WebGPU")
    adapter = await navigator.gpu.requestAdapter()
    if adapter is None:
        raise BugIndicatingError("This browser supports WebGPU but it appears to be disabled")
    return await adapter.requestDevice()


@js
def create_buffer(
    device: GPUDevice,
    descriptor: GPUBufferDescriptor,
    initial: Float32Array | None = None,
) -> GPUBuffer:
    buffer = device.createBuffer(descriptor)
    if initial is not None:
        device.queue.writeBuffer(buffer, 0, initial)
    return buffer


@js
def create_texture(device: GPUDevice, descriptor: GPUTextureDescriptor) -> GPUTexture:
    return device.createTexture(descriptor)
