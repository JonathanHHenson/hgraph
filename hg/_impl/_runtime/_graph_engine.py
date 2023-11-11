import threading
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from hg._runtime import Graph, ExecutionContext
from hg._runtime._constants import MAX_DT, MIN_TD
from hg._runtime._graph_engine import RunMode, GraphExecutorLifeCycleObserver
from hg._runtime._lifecycle import start_stop_context, start_guard, stop_guard

__all__ = ("PythonGraphEngine",)


class BaseExecutionContext(ExecutionContext, ABC):

    def __init__(self, current_time: datetime, graph_engine: "PythonGraphEngine"):
        self.current_engine_time = current_time
        self._proposed_next_engine_time: datetime = MAX_DT
        self._stop_requested = False
        self._graph_engine = graph_engine

    @property
    def proposed_next_engine_time(self) -> datetime:
        return self._proposed_next_engine_time

    @property
    def current_engine_time(self) -> datetime:
        return self._current_time

    @current_engine_time.setter
    def current_engine_time(self, value: datetime):
        self._current_time = value
        self._proposed_next_engine_time = MAX_DT

    def update_next_proposed_time(self, next_time: datetime):
        if next_time == self._current_time:
            return  # No proposals necessary
        self._proposed_next_engine_time = max(self.next_cycle_engine_time,
                                              min(self._proposed_next_engine_time, next_time))

    @property
    def next_cycle_engine_time(self) -> datetime:
        return self._current_time + MIN_TD

    def request_engine_stop(self):
        self._stop_requested = True

    @property
    def is_stop_requested(self) -> bool:
        return self._stop_requested


class BackTestExecutionContext(BaseExecutionContext):

    def __init__(self, current_time: datetime, graph_engine: "PythonGraphEngine"):
        super().__init__(current_time, graph_engine)
        self._wall_clock_time_at_current_time = datetime.utcnow()

    def wait_until_proposed_engine_time(self, proposed_engine_time: datetime):
        self.current_engine_time = proposed_engine_time

    @property
    def current_engine_time(self) -> datetime:
        return self._current_time

    @current_engine_time.setter
    def current_engine_time(self, value: datetime):
        self._current_time = value
        self._wall_clock_time_at_current_time = datetime.utcnow()
        self._proposed_next_engine_time = MAX_DT

    @property
    def wall_clock_time(self) -> datetime:
        return self._current_time + self.engine_lag

    @property
    def engine_lag(self) -> timedelta:
        return datetime.utcnow() - self._wall_clock_time_at_current_time

    def mark_push_has_pending_values(self):
        raise NotImplementedError("Back test engines should not contain push source nodes")

    @property
    def push_has_pending_values(self) -> bool:
        return False

    def reset_push_has_pending_values(self):
        pass  # Nothing to do

    def add_before_evaluation_notification(self, fn: callable):
        self._graph_engine._before_evaluation_notification.append(fn)

    def add_after_evaluation_notification(self, fn: callable):
        self._graph_engine._after_evaluation_notification.append(fn)


class RealtimeExecutionContext(BaseExecutionContext):

    def __init__(self, current_time: datetime, graph_engine: "PythonGraphEngine"):
        super().__init__(current_time, graph_engine)
        self._push_has_pending_values: bool = False
        self._push_pending_condition = threading.Condition()

    def wait_until_proposed_engine_time(self, proposed_engine_time: datetime):
        with self._push_pending_condition:
            while datetime.utcnow() < proposed_engine_time and not self._push_has_pending_values:
                sleep_time = (proposed_engine_time - datetime.utcnow()).total_seconds()
                self._push_pending_condition.wait(sleep_time)
            # It could be that a push node has triggered
        self.current_engine_time = min(proposed_engine_time, datetime.utcnow())

    @property
    def wall_clock_time(self) -> datetime:
        return datetime.utcnow()

    @property
    def engine_lag(self) -> timedelta:
        return datetime.utcnow() - self.current_engine_time

    def mark_push_has_pending_values(self):
        with self._push_pending_condition:
            self._push_has_pending_values = True
            self._push_pending_condition.notify()

    @property
    def push_has_pending_values(self) -> bool:
        return self._push_has_pending_values

    def reset_push_has_pending_values(self):
        self._push_has_pending_values = False


@dataclass
class PythonGraphEngine:  # (GraphEngine):
    """
    A graph engine that runs the graph in python.
    """
    graph: Graph
    run_mode: RunMode
    is_started: bool = False
    _start_time: datetime = None
    _end_time: datetime = None
    _execution_context: ExecutionContext | None = None
    _life_cycle_observers: [GraphExecutorLifeCycleObserver] = field(default_factory=list)
    _before_evaluation_notification: [callable] = field(default_factory=list)
    _after_evaluation_notification: [callable] = field(default_factory=list)

    def initialise(self):
        self.graph.initialise()

    @start_guard
    def start(self):
        match self.run_mode:
            case RunMode.REAL_TIME:
                self._execution_context = RealtimeExecutionContext(self._start_time, self)
            case RunMode.BACK_TEST:
                self._execution_context = BackTestExecutionContext(self._start_time, self)
        self.graph.context = self._execution_context
        self.notify_before_start()
        for node in self.graph.nodes:
            self.notify_before_start_node(node)
            node.start()
            self.notify_after_start_node(node)
        self.notify_after_start()

    @stop_guard
    def stop(self):
        self.notify_before_stop()
        for node in self.graph.nodes:
            self.notify_before_stop_node(node)
            node.stop()
            self.notify_before_start_node(node)
        self.notify_after_stop()
        self._execution_context = None

    def dispose(self):
        self.graph.dispose()

    def advance_engine_time(self):
        if self._execution_context.is_stop_requested:
            self._execution_context.current_engine_time = self._end_time + MIN_TD
            return

        proposed_next_engine_time = min(self._execution_context.proposed_next_engine_time, self._end_time + MIN_TD)
        wall_clock_time = self._execution_context.wall_clock_time
        if wall_clock_time >= proposed_next_engine_time:
            self._execution_context.current_engine_time = proposed_next_engine_time
            return

        if self._execution_context.push_has_pending_values:
            self._execution_context.current_engine_time = wall_clock_time
            return

        # We have nothing to do just yet, wait until the next proposed engine time (or a push node is scheduled)
        self._execution_context.wait_until_proposed_engine_time(proposed_next_engine_time)

    def evaluate_graph(self):
        self.notify_before_evaluation()
        now = self._execution_context.current_engine_time
        nodes = self.graph.nodes

        if self._execution_context.push_has_pending_values:
            self._execution_context.reset_push_has_pending_values()
            for i in range(self.graph.push_source_nodes_end):
                nodes[i].eval()  # This is only to move nodes on, won't call the before and after node eval here

        for i in range(self.graph.push_source_nodes_end, len(nodes)):
            scheduled_time, node = self.graph.schedule[i], nodes[i]
            if scheduled_time == now:
                self.notify_before_node_evaluation(node)
                node.eval()
                self.notify_after_node_evaluation(node)
            elif scheduled_time > now:
                # If the node has a scheduled time in the future, we need to let the execution context know.
                self._execution_context.update_next_proposed_time(scheduled_time)

        self.notify_after_evaluation()

    def run(self, start_time: datetime, end_time: datetime):
        self._start_time = start_time
        self._end_time = end_time

        if end_time < start_time:
            raise ValueError("End time cannot be before the start time")

        with start_stop_context(self):
            while self._execution_context.current_engine_time <= end_time:
                self.evaluate_graph()
                self.advance_engine_time()

    def add_life_cycle_observer(self, observer: GraphExecutorLifeCycleObserver):
        self._life_cycle_observers.append(observer)

    def remove_life_cycle_observer(self, observer: GraphExecutorLifeCycleObserver):
        self._life_cycle_observers.remove(observer)

    def notify_before_evaluation(self):
        for notification_receiver in self._before_evaluation_notification:
            notification_receiver()
        self._before_evaluation_notification.clear()
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_evaluation(self.graph)

    def notify_after_evaluation(self):
        for notification_receiver in reversed(self._after_evaluation_notification):
            notification_receiver()
        self._after_evaluation_notification.clear()
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_evaluation(self.graph)

    def notify_before_node_evaluation(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_node_evaluation(node)

    def notify_after_node_evaluation(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_node_evaluation(node)

    def notify_before_start(self):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_start(self.graph)

    def notify_after_start(self):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_start(self.graph)

    def notify_before_stop(self):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_stop(self.graph)

    def notify_after_stop(self):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_stop(self.graph)

    def notify_before_start_node(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_start_node(node)

    def notify_after_start_node(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_start_node(node)

    def notify_before_stop_node(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_before_stop_node(node)

    def notify_after_stop_node(self, node):
        for life_cycle_observer in self._life_cycle_observers:
            life_cycle_observer.on_after_stop_node(node)
