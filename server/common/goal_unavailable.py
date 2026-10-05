"""Substituts des symboles de `goal` quand le service n'est pas installé."""


class _Unavailable:
    def __init__(self, name: str) -> None:
        self._name = name

    def _fail(self):
        raise RuntimeError(f"goal indisponible : {self._name}")

    def __call__(self, *args, **kwargs):
        self._fail()

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        self._fail()

    # permet les annotations de type `X | None` évaluées à l'import
    def __or__(self, other):
        return self

    __ror__ = __or__


def unavailable(*names: str):
    return tuple(_Unavailable(n) for n in names)
