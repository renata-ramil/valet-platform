from app.models import RequestState

TRANSITIONS: dict[RequestState, set[RequestState]] = {
    RequestState.scheduled: {RequestState.queued, RequestState.cancelled},
    RequestState.queued: {RequestState.assigned, RequestState.cancelled},
    RequestState.assigned: {
        RequestState.retrieving,
        RequestState.cancelled,
        RequestState.failed,
    },
    RequestState.retrieving: {RequestState.en_route, RequestState.failed},
    RequestState.en_route: {RequestState.delivered, RequestState.failed},
    RequestState.delivered: set(),
    RequestState.cancelled: set(),
    RequestState.failed: set(),
}

TERMINAL_STATES = {state for state, targets in TRANSITIONS.items() if not targets}

# Resident-facing labels: Scheduled, Called, On the way, Delivered
RESIDENT_LABELS: dict[RequestState, str] = {
    RequestState.scheduled: "Scheduled",
    RequestState.queued: "Called",
    RequestState.assigned: "Called",
    RequestState.retrieving: "Called",
    RequestState.en_route: "On the way",
    RequestState.delivered: "Delivered",
    RequestState.cancelled: "Cancelled",
    RequestState.failed: "Failed",
}


class IllegalTransitionError(Exception):
    def __init__(self, current: RequestState, target: RequestState):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


def validate_transition(current: RequestState, target: RequestState) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise IllegalTransitionError(current, target)


def resident_label(state: RequestState) -> str:
    return RESIDENT_LABELS[state]
