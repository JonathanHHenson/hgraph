import functools
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Mapping, TYPE_CHECKING, Callable, Any, Iterator

from sortedcontainers import SortedList

from hgraph._runtime._evaluation_clock import EngineEvaluationClock
from hgraph._runtime._constants import MIN_DT, MAX_DT, MIN_ST
from hgraph._runtime._graph import Graph
from hgraph._runtime._lifecycle import start_guard, stop_guard
from hgraph._runtime._node import NodeSignature, Node, NodeScheduler

if TYPE_CHECKING:
    from hgraph._types._ts_type import TimeSeriesInput, TimeSeriesOutput
    from hgraph._types._tsb_type import TimeSeriesBundleInput

__all__ = ("NodeImpl",)


class NodeImpl(Node):
    """
    Provide a basic implementation of the Node as a reference implementation.
    """

    def __init__(self,
                 node_ndx: int,
                 owning_graph_id:
                 tuple[int, ...],
                 signature: NodeSignature,
                 scalars: Mapping[str, Any],
                 eval_fn: Callable = None,
                 start_fn: Callable = None,
                 stop_fn: Callable = None
                 ):
        super().__init__()
        self._node_ndx: int = node_ndx
        self._owning_graph_id: tuple[int, ...] = owning_graph_id
        self._signature: NodeSignature = signature
        self._scalars: Mapping[str, Any] = scalars
        self._graph: Graph = None
        self.eval_fn: Callable = eval_fn
        self.start_fn: Callable = start_fn
        self.stop_fn: Callable = stop_fn
        self._input: Optional["TimeSeriesBundleInput"] = None
        self._output: Optional["TimeSeriesOutput"] = None
        self._scheduler: Optional["NodeSchedulerImpl"] = None
        self._kwargs: dict[str, Any] = None

    @property
    def node_ndx(self) -> int:
        return self._node_ndx

    @property
    def owning_graph_id(self) -> tuple[int, ...]:
        return self._owning_graph_id

    @property
    def signature(self) -> NodeSignature:
        return self._signature

    @property
    def scalars(self) -> Mapping[str, Any]:
        return self._scalars

    @functools.cached_property
    def node_id(self) -> tuple[int, ...]:
        """ Computed once and then cached """
        return self.owning_graph_id + tuple([self.node_ndx])

    @property
    def graph(self) -> "Graph":
        return self._graph

    @graph.setter
    def graph(self, value: "Graph"):
        self._graph = value

    @property
    def input(self) -> Optional["TimeSeriesBundleInput"]:
        return self._input

    @input.setter
    def input(self, value: "TimeSeriesBundleInput"):
        self._input = value

    @property
    def output(self) -> Optional["TimeSeriesOutput"]:
        return self._output

    @output.setter
    def output(self, value: "TimeSeriesOutput"):
        self._output = value

    @property
    def inputs(self) -> Optional[Mapping[str, "TimeSeriesInput"]]:
        # noinspection PyTypeChecker
        return {k: self.input[k] for k in self.signature.time_series_inputs}

    @property
    def scheduler(self) -> "NodeScheduler":
        if self._scheduler is None:
            self._scheduler = NodeSchedulerImpl(self)
        return self._scheduler

    def initialise(self):
        pass

    def _initialise_kwargs(self):
        from hgraph._types._scalar_type_meta_data import Injector
        extras = {}
        for k, s in self.scalars.items():
            if isinstance(s, Injector):
                extras[k] = s(self)
        try:
            self._kwargs = {k: v for k, v in {**(self.input or {}), **self.scalars, **extras}.items() if
                            k in self.signature.args}
        except:
            print("Except")
            raise

    def _initialise_inputs(self):
        if self.input:
            for k, ts in self.input.items():
                ts: TimeSeriesInput
                if self.signature.active_inputs is None or k in self.signature.active_inputs:
                    ts.make_active()

    def eval(self):
        scheduled = False if self._scheduler is None else self._scheduler.is_scheduled_now
        if self.input:
            # Perform validity check of inputs
            args = self.signature.valid_inputs if self.signature.valid_inputs is not None else self.signature.time_series_inputs.keys()
            if not all(self.input[k].valid for k in args):
                return  # We should look into caching the result of this check.
                # This check could perhaps be set on a separate call?
            if self._scheduler is not None:
                # It is possible we have scheduled and then remove the schedule,
                # so we need to check that something has caused this to be scheduled.
                if not scheduled and not any(self.input[k].valid for k in args):
                    return
        out = self.eval_fn(**self._kwargs)
        if out is not None:
            self.output.apply_result(out)
        if scheduled:
            self._scheduler.advance()

    @start_guard
    def start(self):
        self._initialise_kwargs()
        self._initialise_inputs()
        if self.start_fn is not None:
            from inspect import signature
            self.start_fn(**{k: self._kwargs[k] for k in (signature(self.start_fn).parameters.keys())})
        if self._scheduler is not None:
            if self._scheduler.pop_tag("start", None) is not None:
                self.notify()
                if not self.signature.uses_scheduler:
                    self._scheduler = None
            else:
                self._scheduler.advance()

    @stop_guard
    def stop(self):
        from inspect import signature
        if self.stop_fn is not None:
            self.stop_fn(**{k: self._kwargs[k] for k in (signature(self.stop_fn).parameters.keys())})

    def dispose(self):
        self._kwargs = None  # For neatness purposes only, not required here.

    def notify(self):
        """Notify the graph that this node needs to be evaluated."""
        if self.is_started or self.is_starting:
            self.graph.schedule_node(self.node_ndx, self.graph.evaluation_clock.evaluation_time)
        else:
            self.scheduler.schedule(when=MIN_ST, tag="start")


class NodeSchedulerImpl(NodeScheduler):

    def __init__(self, node: NodeImpl):
        self._node = node
        self._scheduled_events: SortedList[tuple[datetime, str]] = SortedList[tuple[datetime, str]]()
        self._tags: dict[str, datetime] = {}

    @property
    def next_scheduled_time(self) -> datetime:
        return self._scheduled_events[0][0] if self._scheduled_events else MIN_DT

    @property
    def is_scheduled(self) -> bool:
        return bool(self._scheduled_events)

    @property
    def is_scheduled_now(self) -> bool:
        return self._scheduled_events and self._scheduled_events[0][
            0] == self._node.graph.evaluation_clock.evaluation_time

    def has_tag(self, tag: str) -> bool:
        return tag in self._tags

    def pop_tag(self, tag: str, default=None) -> datetime:
        if tag in self._tags:
            dt = self._tags.pop(tag)
            self._scheduled_events.remove((dt, tag))
            return dt
        else:
            return default

    def schedule(self, when: datetime | timedelta, tag: str = None):
        if tag is not None:
            if tag in self._tags:
                self._scheduled_events.remove((self._tags[tag], tag))
        if type(when) is timedelta:
            when = self._node.graph.evaluation_clock.evaluation_time + when
        if when > (
                self._node.graph.evaluation_clock.evaluation_time if (is_stated := self._node.is_started) else MIN_DT):
            self._tags[tag] = when
            current_first = self._scheduled_events[0][0] if self._scheduled_events else MAX_DT
            self._scheduled_events.add((when, "" if tag is None else tag))
            if is_stated and current_first > (next := self.next_scheduled_time):
                self._node.graph.schedule_node(self._node.node_ndx, next)

    def un_schedule(self, tag: str = None):
        if tag is not None:
            if tag in self._tags:
                self._scheduled_events.remove((self._tags[tag], tag))
                del self._tags[tag]
        elif self._scheduled_events:
            self._scheduled_events.pop(0)

    def reset(self):
        self._scheduled_events.clear()
        self._tags.clear()

    def advance(self):
        until = self._node.graph.evaluation_clock.evaluation_time
        while self._scheduled_events and self._scheduled_events[0][0] <= until:
            self._scheduled_events.pop(0)
        if self._scheduled_events:
            self._node.graph.schedule_node(self._node.node_ndx, self._scheduled_events[0][0])


class GeneratorNodeImpl(NodeImpl):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generator: Iterator = None
        self.next_value: object = None

    @start_guard
    def start(self):
        self._initialise_kwargs()
        self.generator = self.eval_fn(**self._kwargs)
        self.graph.schedule_node(self.node_ndx, self.graph.evaluation_clock.evaluation_time)

    def eval(self):
        time, out = next(self.generator, (None, None))
        if out is not None and time is not None and time <= self.graph.evaluation_clock.evaluation_time:
            self.output.apply_result(out)
            self.next_value = None
            self.eval()  # We are going to apply now! Prepare next step,
            return
            # This should ultimately either produce no result or a result that is to be scheduled

        if self.next_value is not None:
            self.output.apply_result(self.next_value)
            self.next_value = None

        if time is not None and out is not None:
            self.next_value = out
            self.graph.schedule_node(self.node_ndx, time)


@dataclass
class PythonPushQueueNodeImpl(NodeImpl):  # Node

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.receiver: "_SenderReceiverState" = None

    @start_guard
    def start(self):
        self._initialise_kwargs()
        self.receiver = _SenderReceiverState(lock=threading.RLock(), queue=deque(),
                                             evaluation_evaluation_clock=self.graph.engine_evaluation_clock)
        self.eval_fn(self.receiver, **self._kwargs)

    def eval(self):
        value = self.receiver.dequeue()
        if value is None:
            return
        self.graph.engine_evaluation_clock.mark_push_node_requires_scheduling()
        self.output.apply_result(value)

    @stop_guard
    def stop(self):
        self.receiver.stopped = True
        self.receiver = None


@dataclass
class _SenderReceiverState:
    lock: threading.RLock
    queue: deque
    evaluation_evaluation_clock: EngineEvaluationClock
    stopped: bool = False

    def __call__(self, value):
        self.enqueue(value)

    def enqueue(self, value):
        with self.lock:
            if self.stopped:
                raise RuntimeError("Cannot enqueue into a stopped receiver")
            self.queue.append(value)
            self.evaluation_evaluation_clock.mark_push_node_requires_scheduling()

    def dequeue(self):
        with self.lock:
            return self.queue.popleft() if self.queue else None

    def __bool__(self):
        with self.lock:
            return bool(self.queue)

    def __enter__(self):
        self.lock.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.lock.release()
