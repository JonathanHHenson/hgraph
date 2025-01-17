from pathlib import Path

from frozendict import frozendict

from hgraph._types._ref_meta_data import HgREFTypeMetaData
from hgraph._wiring._wiring import PythonWiringNodeClass
from hgraph._types._time_series_meta_data import HgTimeSeriesTypeMetaData
from hgraph._wiring._wiring import SourceCodeDetails, WiringGraphContext
from hgraph._wiring._wiring import WiringNodeInstance, WiringPort
from hgraph._wiring._wiring_node_signature import WiringNodeSignature, WiringNodeType


def create_input_stub(key: str, tp: HgTimeSeriesTypeMetaData) -> WiringPort:
    """
    Creates a stub input for a wiring node input.
    """
    # We use the class approach for now since it is easier to deal with the edges that could be created
    # if the component wrapped is a graph. This would have multiple dependencies and having the stubs in once
    # place at the start of the graph is better. Using references makes this reasonably light weights with
    # minimal overhead.
    is_key = key in ('key', 'ndx')
    ref_tp = tp if type(tp) is HgREFTypeMetaData or is_key else HgREFTypeMetaData(tp)
    signature = WiringNodeSignature(
        node_type=WiringNodeType.COMPUTE_NODE,
        name=f"stub:{key}",
        args=("ts",),
        defaults=frozendict(),
        input_types=frozendict({'ts': ref_tp}),
        output_type=ref_tp,
        src_location=SourceCodeDetails(Path(__file__), 13),
        active_inputs=frozenset(),
        valid_inputs=frozenset(),
        unresolved_args=frozenset(),
        time_series_args=frozenset({'ts',}),
        uses_scheduler=False,
        label=key
    )
    node = PythonWiringNodeClass(signature, KeyStubEvalFn() if is_key else _stub)
    node_instance = WiringNodeInstance(node, signature, frozendict(), 1)
    return WiringPort(node_instance, ())


def create_output_stub(output: WiringPort):
    """
    Creates a stub output for a wiring node output.
    """
    # This ensures symetry.
    tp = output.output_type
    ref_tp = tp if type(tp) is HgREFTypeMetaData else HgREFTypeMetaData(tp)
    signature = WiringNodeSignature(
        node_type=WiringNodeType.COMPUTE_NODE,
        name=f"stub:__out__",
        args=('ts',),
        defaults=frozendict(),
        input_types=frozendict({'ts': ref_tp}),
        output_type=ref_tp,
        src_location=SourceCodeDetails(Path(__file__), 42),
        active_inputs=frozenset(),
        valid_inputs=frozenset(),
        unresolved_args=frozenset(),
        time_series_args=frozenset({'ts',}),
        uses_scheduler=False,
        label="graph:out"
    )
    node = PythonWiringNodeClass(signature, _stub)
    node_instance = WiringNodeInstance(node, signature, frozendict({"ts": output}), output.rank + 1)
    WiringGraphContext.instance().add_sink_node(node_instance)  # We cheat a bit since this is not actually a sink_node.


# Provide a light-weight function to use standard python compute node implementation choice.

from hgraph._types._ref_type import REF
from hgraph._types._time_series_types import TIME_SERIES_TYPE


def _stub(ts: REF[TIME_SERIES_TYPE]) -> REF[TIME_SERIES_TYPE]:
    """
    This is the basic implementation of a stub.
    Tge stub will either be connected in the graph as an input or an output ranked on the outer-side of the graph.
    """
    return ts.value if ts.valid else None


class KeyStubEvalFn:
    """
    A callable object we can attach the key to, then during start it will inject the key into the output.
    """
    def __init__(self):
        self.key = None

    def __call__(self, ts: REF[TIME_SERIES_TYPE]) -> REF[TIME_SERIES_TYPE]:
        """
        This is the stub start function that is used to create a stub node that is used to create a graph.
        """
        return self.key
