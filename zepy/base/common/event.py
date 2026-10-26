"""Event."""

from collections.abc import Callable

from pyjs import js

from zepy.base.common.lifecycle import IDisposable


@js
class Listener:
    def __init__(self, callback: Callable[[object], None]):
        self.callback = callback
        self.disposed = False


@js
class ListenerDisposer(IDisposable):
    def __init__(self, listener: Listener):
        super().__init__()
        self._listener = listener
        self._disposed = False

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._listener.disposed = True


@js
class Emitter:
    def __init__(self):
        self._listeners: list[Listener] = []
        self._disposed = False

    def event(self, callback: Callable[[object], None]) -> ListenerDisposer:
        listener = Listener(callback)
        self._listeners.append(listener)
        return ListenerDisposer(listener)

    def fire(self, value: object) -> None:
        if self._disposed:
            return
        index = 0
        while index < len(self._listeners):
            listener = self._listeners[index]
            if not listener.disposed:
                listener.callback(value)
            index = index + 1

    def dispose(self) -> None:
        self._disposed = True
        self._listeners = []
