from typing import Tuple

from hgraph import compute_node, TIME_SERIES_TYPE, graph, TS, TSL, SIZE, Size, SCALAR
from hgraph.test import eval_node


def test_overloads():
    @compute_node
    def add(lhs: TIME_SERIES_TYPE, rhs: TIME_SERIES_TYPE) -> TIME_SERIES_TYPE:
        return lhs.value + rhs.value

    @graph
    def t_add(lhs: TIME_SERIES_TYPE, rhs: TIME_SERIES_TYPE) -> TIME_SERIES_TYPE:
        return add(lhs, rhs)

    @compute_node(overloads=add)
    def add_ints(lhs:  TS[int], rhs: TS[int]) -> TS[int]:
        return lhs.value + rhs.value + 1

    @compute_node(overloads=add)
    def add_strs(lhs:  TS[str], rhs: TS[str]) -> TS[str]:
        return lhs.value + rhs.value + "~"

    @graph(overloads=add)
    def add_tsls(lhs: TSL[TIME_SERIES_TYPE, SIZE], rhs: TSL[TIME_SERIES_TYPE, SIZE]) -> TSL[TIME_SERIES_TYPE, SIZE]:
        return TSL.from_ts(*[a + b for a, b in zip(lhs, rhs)])

    assert eval_node(t_add[TIME_SERIES_TYPE: TS[int]], lhs=[1, 2, 3], rhs=[1, 5, 7]) == [3, 8, 11]
    assert eval_node(t_add[TIME_SERIES_TYPE: TS[float]], lhs=[1., 2., 3.], rhs=[1., 5., 7.]) == [2., 7., 10.]
    assert eval_node(t_add[TIME_SERIES_TYPE: TS[str]], lhs=["1.", "2.", "3."], rhs=["1.", "5.", "7."]) == ['1.1.~', "2.5.~", "3.7.~"]
    assert eval_node(t_add[TIME_SERIES_TYPE: TSL[TS[int], Size[2]]], lhs=[(1, 1)], rhs=[(2, 2)]) == [{0: 3, 1: 3}]


def test_scalar_overloads():
    @compute_node
    def add(lhs: TS[SCALAR], rhs: SCALAR) -> TS[SCALAR]:
        return lhs.value + rhs

    @graph
    def t_add(lhs: TIME_SERIES_TYPE, rhs: SCALAR) -> TIME_SERIES_TYPE:
        return add(lhs, rhs)

    @compute_node(overloads=add)
    def add_ints(lhs: TS[int], rhs: int) -> TS[int]:
        return lhs.value + rhs + 1

    @compute_node(overloads=add)
    def add_ints(lhs: TS[int], rhs: SCALAR) -> TS[int]:
        return lhs.value + rhs + 2

    @compute_node(overloads=add)
    def add_strs(lhs: TS[str], rhs: str) -> TS[str]:
        return lhs.value + rhs + "~"

    @compute_node(overloads=add)
    def add_tsls(lhs: TSL[TIME_SERIES_TYPE, SIZE], rhs: Tuple[SCALAR, ...]) -> TSL[TIME_SERIES_TYPE, SIZE]:
        return tuple(a.value + b for a, b in zip(lhs.values(), rhs))

    assert eval_node(t_add[TIME_SERIES_TYPE: TS[int]], lhs=[1, 2, 3], rhs=1) == [3, 4, 5]
    assert eval_node(t_add[TIME_SERIES_TYPE: TS[float], SCALAR: float], lhs=[1., 2., 3.], rhs=1.) == [2., 3., 4.]
    assert eval_node(t_add[TIME_SERIES_TYPE: TS[str]], lhs=["1.", "2.", "3."], rhs=".") == ['1..~', "2..~", "3..~"]
    assert eval_node(t_add[TIME_SERIES_TYPE: TSL[TS[int], Size[2]]], lhs=[(1, 1)], rhs=(2, 2)) == [{0: 3, 1: 3}]


