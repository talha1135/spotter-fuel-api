from dataclasses import dataclass
from typing import List, Tuple, Optional

MAX_RANGE_MILES = 500
MPG = 10


@dataclass
class StationOnRoute:
    name: str
    city: str
    state: str
    price_per_gallon: float
    mile_marker: float


@dataclass
class FuelStop:
    station: StationOnRoute
    gallons_purchased: float
    cost: float


def optimize_fuel_stops(
    total_distance_miles: float,
    stations: List[StationOnRoute],
) -> Tuple[List[FuelStop], float]:
    """
    Greedy fuel optimizer.

    At each stop, look up to MAX_RANGE_MILES ahead:
      - If a cheaper station exists within range -> buy just enough to reach
        the FIRST such cheaper station.
      - Otherwise -> fill up completely and drive to the cheapest station in range.
    Finish is treated as a station with price 0.

    Vehicle is assumed to start with a full tank (free 500-mile range).
    """
    if total_distance_miles <= MAX_RANGE_MILES:
        return [], 0.0

    # Dedupe + sort
    stations = sorted(
        [s for s in stations if 0 < s.mile_marker < total_distance_miles],
        key=lambda s: s.mile_marker,
    )
    unique, seen = [], set()
    for s in stations:
        key = (s.name, round(s.mile_marker))
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    finish = StationOnRoute("FINISH", "", "", 0.0, total_distance_miles)
    all_stops = unique + [finish]

    fuel_stops: List[FuelStop] = []
    total_cost = 0.0

    pos = 0.0
    fuel = float(MAX_RANGE_MILES)
    current_price = 0.0
    current_station: Optional[StationOnRoute] = None

    max_iter = len(all_stops) + 5
    for _ in range(max_iter):
        dist_to_finish = total_distance_miles - pos
        if dist_to_finish <= MAX_RANGE_MILES:
            miles_short = dist_to_finish - fuel
            if miles_short > 0 and current_station and current_price > 0:
                gallons = miles_short / MPG
                cost = gallons * current_price
                fuel_stops.append(FuelStop(current_station, gallons, cost))
                total_cost += cost
            break

        reachable = [
            s for s in all_stops
            if pos < s.mile_marker <= pos + MAX_RANGE_MILES
        ]
        if not reachable:
            raise ValueError(
                f"No fuel station reachable within {MAX_RANGE_MILES} miles "
                f"from mile {pos:.1f}. Route length {total_distance_miles:.1f} mi."
            )

        first_cheaper = next(
            (s for s in reachable if s.price_per_gallon < current_price),
            None,
        )

        if first_cheaper is not None:
            target = first_cheaper
            dist = target.mile_marker - pos
            miles_short = dist - fuel
            if miles_short > 0 and current_station and current_price > 0:
                gallons = miles_short / MPG
                cost = gallons * current_price
                fuel_stops.append(FuelStop(current_station, gallons, cost))
                total_cost += cost
                fuel = dist
        else:
            target = min(reachable, key=lambda s: s.price_per_gallon)
            if current_station and current_price > 0:
                miles_to_fill = MAX_RANGE_MILES - fuel
                if miles_to_fill > 0:
                    gallons = miles_to_fill / MPG
                    cost = gallons * current_price
                    fuel_stops.append(FuelStop(current_station, gallons, cost))
                    total_cost += cost
                    fuel = MAX_RANGE_MILES

        fuel -= target.mile_marker - pos
        pos = target.mile_marker
        current_station = target
        current_price = target.price_per_gallon
    else:
        raise ValueError("Could not compute optimal fuel stops (iteration limit)")

    return fuel_stops, total_cost
