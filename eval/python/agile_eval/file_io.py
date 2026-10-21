"""Bounded evaluation file I/O, path safeguards, and byte/canonical-JSON digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

MAX_BYTES = 4 * 1024 * 1024
MAX_FILES = 20000
MAX_JSON_DEPTH = 64


def checked_path(path: Path) -> Path:
    """Reject symlinks, Windows junctions/reparse points, traversal and special files."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("provenance path traversal forbidden")
    for part in (path, *path.parents):
        if part.is_symlink() or (
            part.exists() and getattr(part.lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("symlink/reparse provenance path forbidden")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise ValueError("special provenance path forbidden")
    return path


def read_bytes(path: Path) -> bytes:
    path = checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("provenance input exceeds size limit")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode("utf-8"))


def _check_json_depth(text: str) -> None:
    """Bound container nesting before decoding; leave JSON syntax to json.loads."""
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("provenance JSON exceeds nesting limit")
        elif character in "}]":
            depth -= 1


def read_json(path: Path) -> dict:
    text = read_bytes(path).decode("utf-8-sig")
    _check_json_depth(text)
    try:
        value = json.loads(text)
    except RecursionError as exc:
        raise ValueError("provenance JSON exceeds nesting limit") from exc
    if not isinstance(value, dict):
        raise ValueError("provenance object required")
    return value


def write_json(path: Path, value: dict) -> None:
    checked_path(path)
    data = json.dumps(value, indent=2, ensure_ascii=True) + "\n"
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("provenance output exceeds size limit")
    path.write_text(data, encoding="utf-8")


def file_hash(path: Path) -> str | None:
    checked_path(path)
    return digest(read_bytes(path)) if path.is_file() else None
