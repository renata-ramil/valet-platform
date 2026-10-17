import heapq
from dataclasses import dataclass, field

LOBBY = "lobby"
DESK = "desk"


def lane_head(lane: int) -> str:
    return f"lane_{lane}_head"


class TravelGraph:
    """A small weighted graph between the lobby, the valet desk and each lane head.

    Built from the seeded layout: the desk sits between the lobby and the lanes,
    and each lane head is one edge away from the desk, with a distance that grows
    with the lane's index (farther lanes take longer to walk to).
    """

    def __init__(
        self, num_lanes: int, desk_to_lobby: float = 15.0, desk_to_lane_base: float = 10.0
    ):
        self.edges: dict[str, dict[str, float]] = {}
        self._add_edge(LOBBY, DESK, desk_to_lobby)
        for lane in range(1, num_lanes + 1):
            distance = desk_to_lane_base + lane * 2.0
            self._add_edge(DESK, lane_head(lane), distance)

    def _add_edge(self, a: str, b: str, weight: float) -> None:
        self.edges.setdefault(a, {})[b] = weight
        self.edges.setdefault(b, {})[a] = weight

    def shortest_path_time(self, start: str, end: str) -> float:
        if start == end:
            return 0.0
        distances = {start: 0.0}
        queue = [(0.0, start)]
        visited = set()
        while queue:
            dist, node = heapq.heappop(queue)
            if node in visited:
                continue
            visited.add(node)
            if node == end:
                return dist
            for neighbor, weight in self.edges.get(node, {}).items():
                new_dist = dist + weight
                if new_dist < distances.get(neighbor, float("inf")):
                    distances[neighbor] = new_dist
                    heapq.heappush(queue, (new_dist, neighbor))
        raise ValueError(f"No path from {start} to {end}")


@dataclass
class Spot:
    lane: int
    depth: int


@dataclass
class Garage:
    """Each lane is a stack: a car at depth k is blocked by every car at a smaller
    depth in the same lane. Retrieving it costs k relocations (moving the k - 1
    blockers aside, plus the final extraction) plus travel time.
    """

    num_lanes: int
    max_depth: int
    seconds_per_depth: float = 20.0
    occupancy: dict[int, dict[int, str]] = field(default_factory=dict)
    travel: TravelGraph = field(init=False)

    def __post_init__(self):
        self.travel = TravelGraph(self.num_lanes)
        for lane in range(1, self.num_lanes + 1):
            self.occupancy.setdefault(lane, {})

    def park(self, car_id: str, lane: int, depth: int) -> None:
        if self.occupancy[lane].get(depth) is not None:
            raise ValueError(f"Spot lane {lane} depth {depth} is already occupied")
        self.occupancy[lane][depth] = car_id

    def remove(self, lane: int, depth: int) -> str:
        car_id = self.occupancy[lane].pop(depth, None)
        if car_id is None:
            raise ValueError(f"Spot lane {lane} depth {depth} is empty")
        return car_id

    def find_car(self, car_id: str) -> Spot | None:
        for lane, depths in self.occupancy.items():
            for depth, occupant in depths.items():
                if occupant == car_id:
                    return Spot(lane, depth)
        return None

    def is_occupied(self, lane: int, depth: int) -> bool:
        return self.occupancy[lane].get(depth) is not None

    def free_spots(self) -> list[Spot]:
        return [
            Spot(lane, depth)
            for lane in range(1, self.num_lanes + 1)
            for depth in range(1, self.max_depth + 1)
            if not self.is_occupied(lane, depth)
        ]

    def blockers_of(self, lane: int, depth: int) -> list[Spot]:
        return [
            Spot(lane, d) for d in range(1, depth) if self.is_occupied(lane, d)
        ]

    def relocation_count(self, lane: int, depth: int) -> int:
        """Blockers moved aside plus the final extraction, the "k relocations"."""
        if not self.is_occupied(lane, depth):
            return 0
        return len(self.blockers_of(lane, depth)) + 1

    def relocation_destinations(
        self, lane: int, depth: int, exclude: set[tuple[int, int]] | None = None
    ) -> list[Spot]:
        """Pick a free spot for each blocker of (lane, depth), nearest lane first."""
        exclude = exclude or set()
        blockers = self.blockers_of(lane, depth)
        free = [s for s in self.free_spots() if (s.lane, s.depth) not in exclude]
        free.sort(key=lambda s: abs(s.lane - lane))
        destinations = []
        for _ in blockers:
            if not free:
                raise ValueError("Not enough free spots to relocate blockers")
            dest = free.pop(0)
            destinations.append(dest)
            exclude.add((dest.lane, dest.depth))
        return destinations

    def travel_time(self, origin: str, lane: int, depth: int) -> float:
        to_lane_head = self.travel.shortest_path_time(origin, lane_head(lane))
        within_lane = depth * self.seconds_per_depth
        return to_lane_head + within_lane

    def occupied_count(self) -> int:
        return sum(
            1 for depths in self.occupancy.values() for v in depths.values() if v is not None
        )

    def capacity(self) -> int:
        return self.num_lanes * self.max_depth
