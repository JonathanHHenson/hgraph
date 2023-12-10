from typing import Mapping, Any

from frozendict import frozendict

from hg._impl._builder._switch_builder import PythonSwitchNodeBuilder
from hg._types import SCALAR
from hg._wiring._wiring import BaseWiringNodeClass, WiringNodeClass, create_input_output_builders
from hg._wiring._wiring_node_signature import WiringNodeSignature
from hg._wiring._wiring_utils import wire_nested_graph, extract_stub_node_indices


__all__ = ("SwitchWiringNodeClass",)


class SwitchWiringNodeClass(BaseWiringNodeClass):
    """The outer switch node"""

    def __init__(self, signature: WiringNodeSignature,
                 nested_graphs: Mapping[SCALAR, WiringNodeClass],
                 resolved_signature_inner: WiringNodeSignature,
                 reload_on_ticked: bool):
        super().__init__(signature, None)
        self._nested_graphs = nested_graphs
        self._resolved_signature_inner = resolved_signature_inner
        self._reload_on_ticked = reload_on_ticked

    def create_node_builder_instance(self, node_ndx: int, node_signature: "NodeSignature",
                                     scalars: Mapping[str, Any]) -> "NodeBuilder":
        # create nested graphs
        nested_graphs = {k: wire_nested_graph(v, self._resolved_signature_inner, scalars, node_signature) for k, v in
                         self._nested_graphs.items()}
        nested_graph_input_ids = {}
        nested_graph_output_ids = {}
        for k, v in nested_graphs.items():
            nested_graph_input_ids[k], nested_graph_output_ids[k] = extract_stub_node_indices(v, node_signature)

        input_builder, output_builder = create_input_output_builders(self._resolved_signature_inner)

        return PythonSwitchNodeBuilder(node_ndx, node_signature, scalars, input_builder, output_builder,
                                       frozendict(nested_graphs), frozendict(nested_graph_input_ids),
                                       frozendict(nested_graph_output_ids), self._reload_on_ticked)
