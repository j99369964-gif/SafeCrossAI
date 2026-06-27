from dataclasses import dataclass
from typing import Optional


@dataclass
class IntersectionFeatures:

    latitude: float
    longitude: float

    road_name: Optional[str]

    highway_type: Optional[str]

    lanes: Optional[int]

    max_speed: Optional[str]

    oneway: Optional[bool]

    traffic_signal: bool

    crosswalk: bool

    intersection_degree: int

    nearby_crosswalks: int

    nearby_signals: int
