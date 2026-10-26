"""Lifecycle."""

from collections.abc import Callable

from pyjs import js

from zepy.base.common.errors import BugIndicatingError


@js
class IDisposable:
    def __init__(self):
        return

    def dispose(self) -> None:
        return


@js
class CallbackDisposable(IDisposable):
    def __init__(self, callback: Callable[[], None]):
        super().__init__()
        self._callback = callback
        self._disposed = False

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._callback()


@js
def to_disposable(callback: Callable[[], None]) -> CallbackDisposable:
    return CallbackDisposable(callback)


@js
class DisposableStore(IDisposable):
    def __init__(self):
        super().__init__()
        self._to_dispose: list[IDisposable] = []
        self._is_disposed = False

    @property
    def is_disposed(self) -> bool:
        return self._is_disposed

    def dispose(self) -> None:
        if self._is_disposed:
            return
        self._is_disposed = True
        self.clear()

    def clear(self) -> None:
        index = 0
        while index < len(self._to_dispose):
            item = self._to_dispose[index]
            item.dispose()
            index = index + 1
        self._to_dispose = []

    def add(self, disposable: IDisposable) -> IDisposable:
        if disposable is self:
            raise BugIndicatingError("Cannot register a disposable on itself!")
        if self._is_disposed:
            disposable.dispose()
            return disposable
        self._to_dispose.append(disposable)
        return disposable


@js
class Disposable(IDisposable):
    def __init__(self):
        super().__init__()
        self._store = DisposableStore()

    def dispose(self) -> None:
        self._store.dispose()

    def _register(self, disposable: IDisposable) -> IDisposable:
        if disposable is self:
            raise BugIndicatingError("Cannot register a disposable on itself!")
        return self._store.add(disposable)


@js
class MutableDisposable(IDisposable):
    def __init__(self):
        super().__init__()
        self._value: IDisposable | None = None
        self._is_disposed = False

    @property
    def value(self) -> IDisposable | None:
        if self._is_disposed:
            return None
        return self._value

    @value.setter
    def value(self, disposable: IDisposable | None) -> None:
        if self._is_disposed or disposable is self._value:
            return
        current = self._value
        if current is not None:
            current.dispose()
        self._value = disposable

    def dispose(self) -> None:
        if self._is_disposed:
            return
        self._is_disposed = True
        current = self._value
        if current is not None:
            current.dispose()
        self._value = None
