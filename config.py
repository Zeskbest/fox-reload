import os
from configparser import ConfigParser


class Config:
    def __init__(self, filename: str):
        self.config_parser = ConfigParser()
        self.filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        self.config_parser.read([self.filepath])

    def __getattr__(self, item: str):
        for section in self.config_parser.sections():
            result = self.config_parser.get(section, item, fallback=None)
            if result is not None:
                return result
        else:
            raise ValueError(f"Cannot find item '{item}'")


CONFIG = Config("my_config.cfg")
