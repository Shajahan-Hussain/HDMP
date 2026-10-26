import json
from pathlib import Path


def load_config():
    """
    Load application configuration from config/config.json.
    """

    config_path = (
        Path(__file__).resolve().parent.parent
        / "config"
        / "config.json"
    )

    with open(config_path, "r", encoding="utf-8") as file:
        return json.load(file)