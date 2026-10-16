"""Versioned TOML configuration with strict, table-driven validation.

Only ``config_schema_version`` is required; every other key has a default (the values documented
in docs/architecture/PROPOSAL.md section 10). Unknown keys are rejected at every level, and every
error names the offending key (``ConfigError.key``). Result files carry a separate
``results_schema_version`` (ADR-014).
"""

from __future__ import annotations

import copy
import math
import tomllib
from collections.abc import Callable
from typing import Any

CONFIG_SCHEMA_VERSION = 1
KNOWN_FORMATS = ("csv", "npy", "npz", "npz_compressed")
KNOWN_OPERATIONS = ("write", "load", "preprocess", "load_preprocess")
KNOWN_THREAD_ENV = ("inherit", "single")

Check = Callable[[str, Any], Any]


class ConfigError(ValueError):
    """A configuration problem. ``key`` is the dotted path of the offending key."""

    def __init__(self, key: str, problem: str):
        self.key = key
        self.problem = problem
        super().__init__(f"config key '{key}': {problem}")


def _int(lo: int | None = None) -> Check:
    def check(key: str, v: Any) -> int:
        if type(v) is not int:  # bool is an int subclass: reject it explicitly
            raise ConfigError(key, f"expected integer, got {type(v).__name__}")
        if lo is not None and v < lo:
            raise ConfigError(key, f"must be >= {lo}, got {v}")
        return v

    return check


def _float(*, gt: float | None = None, ge: float | None = None) -> Check:
    def check(key: str, v: Any) -> float:
        if type(v) not in (int, float):  # TOML 20 and 20.0 are both accepted
            raise ConfigError(key, f"expected number, got {type(v).__name__}")
        x = float(v)
        if not math.isfinite(x):  # nan and inf are valid TOML floats
            raise ConfigError(key, f"must be finite, got {x}")
        if gt is not None and not x > gt:
            raise ConfigError(key, f"must be > {gt}, got {x}")
        if ge is not None and not x >= ge:
            raise ConfigError(key, f"must be >= {ge}, got {x}")
        return x

    return check


def _bool(key: str, v: Any) -> bool:
    if type(v) is not bool:
        raise ConfigError(key, f"expected boolean, got {type(v).__name__}")
    return v


def _str(key: str, v: Any) -> str:
    if type(v) is not str:
        raise ConfigError(key, f"expected string, got {type(v).__name__}")
    if not v.strip():
        raise ConfigError(key, "must not be empty")
    return v


def _enum(allowed: tuple[str, ...]) -> Check:
    def check(key: str, v: Any) -> str:
        if type(v) is not str:
            raise ConfigError(key, f"expected string, got {type(v).__name__}")
        if v not in allowed:
            raise ConfigError(key, f"must be one of {list(allowed)}, got {v!r}")
        return v

    return check


def _list_of(item: Check, *, min_len: int = 1, unique: bool = True) -> Check:
    def check(key: str, v: Any) -> list:
        if type(v) is not list:
            raise ConfigError(key, f"expected array, got {type(v).__name__}")
        if len(v) < min_len:
            raise ConfigError(key, f"needs at least {min_len} entries")
        out = [item(f"{key}[{i}]", x) for i, x in enumerate(v)]
        if unique and len(set(out)) != len(out):
            raise ConfigError(key, "duplicate entries are not allowed")
        return out

    return check


# section -> key -> (validator, default)
SCHEMA: dict[str, dict[str, tuple[Check, Any]]] = {
    "dataset": {
        "seed": (_int(0), 12345),
        "sizes": (_list_of(_int(1)), [10_000, 100_000, 1_000_000]),
        "data_dir": (_str, "data/generated"),
    },
    "formats": {"enabled": (_list_of(_enum(KNOWN_FORMATS)), list(KNOWN_FORMATS))},
    "workload": {
        "pt_cut": (_float(ge=0.0), 20.0),
        "eta_cut": (_float(gt=0.0), 2.4),
        "operations": (_list_of(_enum(KNOWN_OPERATIONS)), list(KNOWN_OPERATIONS)),
    },
    "trials": {
        "warmup_rounds": (_int(0), 2),
        "measured_rounds": (_int(1), 7),
        "order_seed": (_int(0), 777),
        "fsync": (_bool, False),
        "timeout_s": (_float(gt=0.0), 600.0),
    },
    "noise": {
        "outlier_factor": (_float(gt=1.0), 3.0),
        "max_load_per_core": (_float(ge=0.0), 0.5),
    },
    "environment": {"thread_env": (_enum(KNOWN_THREAD_ENV), "inherit")},
    "output": {"results_dir": (_str, "results")},
}


def defaults() -> dict[str, Any]:
    """The full default configuration (a fresh, mutable copy)."""
    cfg: dict[str, Any] = {"config_schema_version": CONFIG_SCHEMA_VERSION}
    for section, keys in SCHEMA.items():
        cfg[section] = {k: copy.deepcopy(default) for k, (_, default) in keys.items()}
    return cfg


def validate(raw: Any) -> dict[str, Any]:
    """Validate a parsed TOML mapping and return the full configuration with defaults filled in."""
    if not isinstance(raw, dict):
        raise ConfigError("<root>", "expected a table")
    if "config_schema_version" not in raw:
        raise ConfigError("config_schema_version", "required key is missing")
    version = raw["config_schema_version"]
    if type(version) is not int or version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            "config_schema_version",
            f"unsupported version {version!r}; expected {CONFIG_SCHEMA_VERSION}",
        )
    for key in raw:
        if key != "config_schema_version" and key not in SCHEMA:
            raise ConfigError(str(key), "unknown key")
    cfg: dict[str, Any] = {"config_schema_version": version}
    for section, keys in SCHEMA.items():
        table = raw.get(section, {})
        if not isinstance(table, dict):
            raise ConfigError(section, f"expected table, got {type(table).__name__}")
        for key in table:
            if key not in keys:
                raise ConfigError(f"{section}.{key}", "unknown key")
        cfg[section] = {}
        for key, (check, default) in keys.items():
            full = f"{section}.{key}"
            cfg[section][key] = check(full, table[key]) if key in table else copy.deepcopy(default)
    return cfg


def loads(text: str) -> dict[str, Any]:
    """Parse and validate TOML text."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("<toml>", f"invalid TOML: {exc}") from exc
    return validate(raw)


def load(path: str) -> dict[str, Any]:
    """Read, parse and validate a TOML config file."""
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except OSError as exc:
        raise ConfigError("<file>", f"cannot read {path}: {exc.strerror}") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError("<toml>", f"invalid TOML in {path}: {exc}") from exc
    return validate(raw)
