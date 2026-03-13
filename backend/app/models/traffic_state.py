# backend/app/models/traffic_state.py

"""
TrafficState

Represents the entire intersection state at a specific moment.
Contains traffic metrics for each direction as well as environmental data.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DirectionState :

    """
    Represents traffic metrics for one direction.
    """

    vehicle_count           : int
    vehicle_breakdown       : dict
    weighted_vehicle_score  : float
    density_ratio           : float


class TrafficState :

    """
    Represents the full intersection state.
    """

    def __init__(self,
                 north  : DirectionState,
                 south  : DirectionState,
                 east   : DirectionState,
                 west   : DirectionState,
                 temperature : float,
                 light_intensity : float) :

        self.north = north
        self.south = south
        self.east = east
        self.west = west

        self.temperature = temperature
        self.light_intensity = light_intensity

        self.timestamp = datetime.now()