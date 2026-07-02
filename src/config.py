"""
config.py
=========

Global configuration settings for SafeCross AI.

This module centralizes project-wide constants such as
directory locations, model parameters, geographic settings,
and default values.

Nothing in this file should depend on any other project modules.

Author: Joseph Wu-Oswald
Project: SafeCross AI
"""

from pathlib import Path

###############################################################################
# Project Directories
###############################################################################

# Root directory of the project
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"

RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
CACHE_DIR = DATA_DIR / "cache"

NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"

SRC_DIR = PROJECT_ROOT / "src"

MODEL_DIR = PROJECT_ROOT / "models"

OUTPUT_DIR = PROJECT_ROOT / "outputs"

LOG_DIR = PROJECT_ROOT / "logs"

###############################################################################
# Dataset Files
###############################################################################

CRASH_DATA = RAW_DATA_DIR / "crashes.csv"

ROAD_DATA = RAW_DATA_DIR / "roads.geojson"

WEATHER_DATA = RAW_DATA_DIR / "weather.csv"

INTERSECTION_DATA = PROCESSED_DATA_DIR / "intersections.parquet"

###############################################################################
# Geographic Settings
###############################################################################

# Coordinate Reference System

CRS_WGS84 = "EPSG:4326"

CRS_PROJECTED = "EPSG:3857"

# Distance (meters)

DEFAULT_SEARCH_RADIUS = 75

MAX_SEARCH_RADIUS = 300

###############################################################################
# Machine Learning
###############################################################################

RANDOM_SEED = 42

TEST_SIZE = 0.20

VALIDATION_SIZE = 0.20

TARGET_COLUMN = "high_risk"

###############################################################################
# Model Defaults
###############################################################################

LOGISTIC_REGRESSION = {

    "max_iter": 1000,

    "random_state": RANDOM_SEED

}

RANDOM_FOREST = {

    "n_estimators": 250,

    "max_depth": None,

    "random_state": RANDOM_SEED

}

###############################################################################
# Feature Engineering
###############################################################################

NUMERIC_FEATURES = [

    "speed_limit",

    "lanes",

    "historical_crashes",

    "pedestrian_volume"

]

CATEGORICAL_FEATURES = [

    "lighting",

    "road_type",

    "weather"

]

BOOLEAN_FEATURES = [

    "crosswalk",

    "traffic_signal",

    "school_zone",

    "bike_lane"

]

###############################################################################
# Logging
###############################################################################

LOG_LEVEL = "INFO"

LOG_FILE = LOG_DIR / "safecross.log"

###############################################################################
# Visualization
###############################################################################

DEFAULT_MAP_ZOOM = 16

HEATMAP_RADIUS = 20

###############################################################################
# Dashboard
###############################################################################

STREAMLIT_TITLE = "SafeCross AI"

###############################################################################
# Helper Functions
###############################################################################

def create_directories() -> None:
    """
    Create all required project directories if they do not exist.
    """

    directories = [

        DATA_DIR,

        RAW_DATA_DIR,

        PROCESSED_DATA_DIR,

        CACHE_DIR,

        MODEL_DIR,

        OUTPUT_DIR,

        LOG_DIR

    ]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def print_configuration() -> None:
    """
    Print important project configuration.
    Useful for debugging.
    """

    print("=" * 50)
    print("SafeCross AI Configuration")
    print("=" * 50)

    print(f"Project Root:      {PROJECT_ROOT}")
    print(f"Raw Data:          {RAW_DATA_DIR}")
    print(f"Processed Data:    {PROCESSED_DATA_DIR}")
    print(f"Models:            {MODEL_DIR}")
    print(f"Outputs:           {OUTPUT_DIR}")
    print(f"Logs:              {LOG_DIR}")

    print()

    print(f"Search Radius:     {DEFAULT_SEARCH_RADIUS} m")
    print(f"Random Seed:       {RANDOM_SEED}")
    print(f"Target Column:     {TARGET_COLUMN}")


if __name__ == "__main__":

    create_directories()

    print_configuration()
