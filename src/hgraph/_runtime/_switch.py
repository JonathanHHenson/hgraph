from pathlib import Path
from typing import Callable, Optional, cast, Mapping, TYPE_CHECKING

from frozendict import frozendict

from hgraph._wiring._source_code_details import SourceCodeDetails
from hgraph._types._time_series_meta_data import HgTimeSeriesTypeMetaData
from hgraph._types._type_meta_data import HgTypeMetaData
from hgraph._wiring._wiring_utils import stub_wiring_port, as_reference
from hgraph._wiring._wiring_node_signature import WiringNodeSignature, WiringNodeType
from hgraph._wiring._wiring import WiringNodeClass, extract_kwargs, WiringPort
from hgraph._types._ts_meta_data import HgTSTypeMetaData
from hgraph._wiring._wiring import WiringContext
from hgraph._types._scalar_types import SCALAR, STATE
from hgraph._types._time_series_types import TIME_SERIES_TYPE
from hgraph._types._ts_type import TS
from hgraph._wiring._wiring_errors import CustomMessageWiringError

if TYPE_CHECKING:
    from hgraph._builder._graph_builder import GraphBuilder

__all__ = ("switch_",)


def switch_(switches: dict[SCALAR, Callable[[...], Optional[TIME_SERIES_TYPE]]], key: TS[SCALAR], *args,
            reload_on_ticked: bool = False, **kwargs) -> Optional[TIME_SERIES_TYPE]:
    """
    The ability to select and instantiate a graph based on the value of the key time-series input.
    By default, when the key changes, a new instance of graph is created and run.
    The graph will be evaluated when it is initially created and then as the values are ticked as per normal.
    If the code depends on inputs to have ticked, they will only be evaluated when the inputs next tick (unless
    they have ticked when the graph is wired in).

    The selector is part of the graph shaping operators. This allows for different shapes that operate on the same
    inputs nad return the same output. An example of using this is when you have different order types, and then you
    dynamically choose which graph to evaluate based on the order type.

    This node has the overhead of instantiating and tearing down the sub-graphs as the key changes. The use of switch
    should consider this overhead, the positive side is that once the graph is instantiated the performance is the same
    as if it were wired in directly. This is great when the key changes infrequently.

    The mapped graphs / nodes can have a first argument which is of the same type as the key. In this case the key
    will be mapped into this argument. If the first argument is not of the same type as the key, or the kwargs match
    the argument name of the first argument, the key will be not be mapped into the argument.

    Example:
        key: TS[str] = ...
        ts1: TS[int] = ...
        ts2: TS[int] = ...
        out = switch({'add': add_, "sub": sub_}, key, ts1, ts2)

    Which will perform the computation based on the key's value.
    """
    # Create a nifty simplified signature for the switch node.
    with WiringContext(
            current_signature=STATE(current_signature=f"switch_({{{', '.join(f'{k}: ...' for k in switches)}}}, ...)")):
        from hgraph._wiring._wiring import WiringPort

        # Perform basic validations fo the inputs
        if switches is None or len(switches) == 0:
            raise CustomMessageWiringError("No components supplied to switch")
        if key is None:
            raise CustomMessageWiringError("No key supplied to switch")
        if not isinstance(key, WiringPort) or not isinstance(cast(WiringPort, key).output_type, HgTSTypeMetaData):
            raise CustomMessageWiringError("The key must be a time-series value of form TS[SCALAR]")

        # Assume that the switch items are correctly typed to start with, then we can take the first signature and
        # use it to create a signature for the outer switch node.
        a_signature = cast(WiringNodeClass, next(iter(switches.values()))).signature

        input_has_key_arg = a_signature.args[0] == 'key' and \
                            a_signature.input_types['key'] == cast(WiringPort, key).output_type

        # We add the key to the inputs if the internal component has a key argument.
        kwargs_ = extract_kwargs(a_signature, *args,
                                 _args_offset=1 if input_has_key_arg else 0, key=key,
                                 **(kwargs | dict(key=key) if input_has_key_arg else {}))

        # Now create a resolved signature for the inner graph, then for the outer switch node.
        resolved_signature_inner = _validate_signature(switches, **kwargs_)

        input_types = {k: as_reference(v) if k != 'key' and isinstance(v, HgTimeSeriesTypeMetaData) else v for k, v in
                       resolved_signature_inner.input_types.items()}
        time_series_args = resolved_signature_inner.time_series_args
        if not input_has_key_arg:
            input_types['key'] = cast(WiringPort, key).output_type
            time_series_args = time_series_args | {'key', }

        output_type = as_reference(
            resolved_signature_inner.output_type) if resolved_signature_inner.output_type else None

        resolved_signature_outer = WiringNodeSignature(
            node_type=resolved_signature_inner.node_type,
            name="switch",
            # All actual inputs are encoded in the input_types, so we just need to add the keys if present.
            args=resolved_signature_inner.args if input_has_key_arg else ('key',) + resolved_signature_inner.args,
            defaults=frozendict(),  # Defaults would have already been applied.
            input_types=frozendict(input_types),
            output_type=output_type,
            src_location=SourceCodeDetails(Path(__file__), 25),
            active_inputs=frozenset({'key', }),
            valid_inputs=frozenset({'key', }),
            # We have constructed the map so that the key are is always present.
            unresolved_args=frozenset(),
            time_series_args=time_series_args,
            uses_scheduler=False,
            label=f"switch_({{{', '.join(f'{k}: ...' for k in switches)}}}, ...)",
        )
        # Create the outer wiring node, and call it with the inputs
        from hgraph._wiring._switch_wiring_node import SwitchWiringNodeClass
        # noinspection PyTypeChecker
        return SwitchWiringNodeClass(
            resolved_signature_outer, switches, resolved_signature_inner, reload_on_ticked
        )(**(kwargs_ | ({} if input_has_key_arg else dict(key=key))))


def _validate_signature(switches: dict[SCALAR, Callable[[...], Optional[TIME_SERIES_TYPE]]],
                        **kwargs) -> WiringNodeSignature:
    check_signature: WiringNodeSignature = None
    for k, v in switches.items():
        if check_signature is None:
            check_signature = cast(WiringNodeClass, v).resolve_signature(**kwargs)
        else:
            this_signature = cast(WiringNodeClass, v).resolve_signature(**kwargs)
            if this_signature.args != check_signature.args or \
                    any(not check_signature.input_types[arg].matches(this_signature.input_types[arg]) for arg in
                        check_signature.args) or \
                    not this_signature.output_type.matches(check_signature.output_type):
                # If the signatures do not match, then we cannot wire the switch.
                # We ensure the arguments and their types match, as well as the output type.
                raise CustomMessageWiringError(
                    f"The signature of the switch nodes do not match: "
                    f"{check_signature.signature} != {k}: {this_signature.signature}")
    return check_signature
