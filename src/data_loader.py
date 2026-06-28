"""
Loading local datasets.
"""

import pandas as pd


class CrashDataset:

    def __init__(self, path):

        self.path = path

        self.df = None

    def load(self):

        self.df = pd.read_csv(self.path)

        return self.df

    def summary(self):

        if self.df is None:
            return "Dataset not loaded."

        return self.df.describe(include="all")
