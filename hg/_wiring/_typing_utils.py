from typing import TypeVar

__all__ = ("clone_typevar",)


def clone_typevar(tp: TypeVar, name: str) -> TypeVar:
    """Creates a copy of a typevar and sets the name to the copies name"""
    if tp.__constraints__:
        rv = TypeVar(name, *tp.__constraints__, covariant=tp.__covariant__, contravariant=tp.__contravariant__)
    else:
        rv = TypeVar(name, bound=tp.__bound__, covariant=tp.__covariant__,
                 contravariant=tp.__contravariant__)
    return rv
