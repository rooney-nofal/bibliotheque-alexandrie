"""Loads config.yaml once and shares its settings with every part of the assistant."""  # what this file is for

from pathlib import Path                                    # tools for building file paths that work on any system
import yaml                                                 # the library that reads YAML files like our config.yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent       # the project folder, found from this file's own location
CONFIG_PATH = PROJECT_ROOT / "config.yaml"                  # the full path to config.yaml, built from the project folder


def load_config() -> dict:                                  # a function that hands back the whole configuration
    """Read config.yaml and return it as a plain Python dictionary."""   # short description for anyone reading the code
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:              # open the file for reading, as UTF-8 text
        return yaml.safe_load(handle)                                    # parse it safely and give back the result


def project_path(relative: str) -> Path:                    # turns a path written in config.yaml into a real one
    """Turn a path like 'data/raw' from config.yaml into a full path on this machine."""
    return PROJECT_ROOT / relative                          # attach it to the project folder and return it