class Intersection:

    def __init__(
        self,
        latitude,
        longitude,
        speed_limit,
        lanes,
        crosswalk,
        traffic_signal,
        lighting,
        pedestrian_crashes
    ):
        self.latitude = latitude
        self.longitude = longitude
        self.speed_limit = speed_limit
        self.lanes = lanes
        self.crosswalk = crosswalk
        self.traffic_signal = traffic_signal
        self.lighting = lighting
        self.pedestrian_crashes = pedestrian_crashes

    def summary(self):
        return {
            "Latitude": self.latitude,
            "Longitude": self.longitude,
            "Speed Limit": self.speed_limit,
            "Lanes": self.lanes,
            "Crosswalk": self.crosswalk,
            "Traffic Signal": self.traffic_signal,
            "Lighting": self.lighting,
            "Pedestrian Crashes": self.pedestrian_crashes
        }
