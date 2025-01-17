from hgraph import TSS, SCALAR, SIZE, TSL, compute_node, TSS_OUT, PythonSetDelta

__all__ = ("union_",)


def union_(*args: TSS[SCALAR]) -> TSS[SCALAR]:
    """
    Union of all the inputs
    :param args:
    :return:
    """
    return _union_tsl(TSL.from_ts(*args))


@compute_node(valid=tuple())
def _union_tsl(tsl: TSL[TSS[SCALAR], SIZE], output: TSS_OUT[SCALAR] = None) -> TSS[SCALAR]:
    tss: TSS[SCALAR, SIZE]
    to_add: set[SCALAR] = set()
    to_remove: set[SCALAR] = set()
    for tss in tsl.modified_values():
        to_add |= tss.added()
        to_remove |= tss.removed()
    if (disputed:=to_add.intersection(to_remove)):
        # These items are marked for addition and removal, so at least some set is hoping to add these items.
        # Thus, overall these are an add, unless they are already added.
        new_items = disputed.intersection(output.value)
        to_remove -= new_items
    to_remove &= output.value  # Only remove items that are already in the output.
    if to_remove:
        # Now we need to make sure there are no items that may be duplicated in other inputs.
        for tss in tsl.valid_values():
            to_remove -= to_remove.intersection(tss.value)  # Remove items that exist in an input
            if not to_remove:
                break
    return PythonSetDelta(to_add, to_remove)
