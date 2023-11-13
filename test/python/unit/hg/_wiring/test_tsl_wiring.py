from hg import TS, graph, TSL, Size, SCALAR, compute_node
from hg.nodes import flatten_tsl_values
from hg.test import eval_node


@compute_node
def my_tsl_maker(ts1: TS[int], ts2: TS[int]) -> TSL[TS[int], Size[2]]:
    out = {}
    if ts1.modified:
        out[0] =ts1.delta_value
    if ts2.modified:
        out[1] = ts2.delta_value
    return out


def test_fixed_tsl_non_peered():
    @graph
    def my_tsl(ts1: TS[int], ts2: TS[int]) -> TS[tuple[int, ...]]:
        tsl = TSL[TS[float], Size[2]].from_ts(ts1, ts2)
        return flatten_tsl_values[SCALAR: int](tsl)

    assert eval_node(my_tsl, ts1=[1, 2], ts2=[3, 4]) == [(1,3), (2, 4)]


def test_fixed_tsl_peered():
    @graph
    def my_tsl(ts1: TS[int], ts2: TS[int]) -> TS[int]:
        tsl = my_tsl_maker(ts1, ts2)
        return tsl[0]

    assert eval_node(my_tsl, ts1=[1, 2], ts2=[3, 4]) == [1, 2]
