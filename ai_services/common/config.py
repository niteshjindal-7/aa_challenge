"""
Config loader — reads vendor configs and test type configs from JSON files.
Later this swaps to MongoDB reads with zero code change in the consumers.
"""
import json
from pathlib import Path
from typing import Any


def load_json_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return json.load(f)


def load_vendor_config(vendor_id: str, config_dir: str | Path) -> dict[str, Any]:
    config_dir = Path(config_dir)
    vendor_file = config_dir / f"{vendor_id}.json"
    if not vendor_file.exists():
        raise FileNotFoundError(f"No config for vendor '{vendor_id}' at {vendor_file}")
    return load_json_config(vendor_file)


def list_vendors(config_dir: str | Path) -> list[str]:
    config_dir = Path(config_dir)
    return [f.stem for f in config_dir.glob("*.json")]


def load_prompt_template(vendor_config: dict, base_dir: str | Path) -> str:
    """Load the prompt template file referenced in a vendor config.
    Resolves the prompt_template_file path relative to base_dir."""
    base_dir = Path(base_dir)
    template_file = vendor_config.get("prompt_template_file")
    if not template_file:
        raise ValueError(f"Vendor '{vendor_config.get('vendor_id')}' has no prompt_template_file")
    full_path = base_dir / template_file
    if not full_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {full_path}")
    return full_path.read_text()
