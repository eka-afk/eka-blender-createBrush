from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid


SCHEMA_VERSION = 1
INDEX_FILENAME = "brushes.json"
SUPPORTED_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
DEFAULT_SETTINGS = {
    "tool": "DRAW",
    "mapping": "TILED",
    "stroke_method": "SPACE",
    "falloff": "SMOOTH",
    "strength": 0.5,
    "size": 75,
    "spacing": 25,
    "texture_bias": 0.0,
    "invert": False,
    "use_pressure_size": True,
    "use_pressure_strength": True,
    "front_faces_only": False,
    "accumulate": False,
}

ENUM_VALUES = {
    "tool": {"CLAY", "CLAY_STRIPS", "CREASE", "DRAW", "FILL", "INFLATE", "SCRAPE", "SMOOTH"},
    "mapping": {"AREA_PLANE", "RANDOM", "STENCIL", "TILED", "VIEW_PLANE"},
    "stroke_method": {"ANCHORED", "DOTS", "DRAG_DOT", "SPACE"},
    "falloff": {"CONSTANT", "LINE", "ROUND", "SHARP", "SMOOTH"},
}


class BrushLibraryError(RuntimeError):
    pass


def clean_name(value: str) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "")
    value = re.sub(r"[\\/]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:80] or "Untitled Brush"


def safe_filename_stem(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:80] or "Untitled Brush"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_settings(settings: dict | None = None) -> dict:
    normalized = deepcopy(DEFAULT_SETTINGS)
    if settings:
        normalized.update({key: value for key, value in settings.items() if key in normalized})

    for key, values in ENUM_VALUES.items():
        if normalized[key] not in values:
            raise BrushLibraryError(f"Unsupported {key.replace('_', ' ')}: {normalized[key]}")

    normalized["strength"] = max(0.0, min(10.0, float(normalized["strength"])))
    normalized["size"] = max(1, min(5000, int(normalized["size"])))
    normalized["spacing"] = max(1, min(1000, int(normalized["spacing"])))
    normalized["texture_bias"] = max(-1.0, min(1.0, float(normalized["texture_bias"])))
    for key in (
        "invert",
        "use_pressure_size",
        "use_pressure_strength",
        "front_faces_only",
        "accumulate",
    ):
        normalized[key] = bool(normalized[key])
    return normalized


class BrushLibrary:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.index_path = self.root / INDEX_FILENAME

    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def load(self) -> dict:
        if not self.index_path.exists():
            return {"schema_version": SCHEMA_VERSION, "brushes": []}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BrushLibraryError(f"Could not read {INDEX_FILENAME}: {error}") from error

        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise BrushLibraryError("The brush library uses an unsupported metadata version")
        if not isinstance(data.get("brushes"), list):
            raise BrushLibraryError("The brush library metadata is missing its brush list")
        return data

    def save(self, data: dict) -> None:
        self.ensure()
        temporary_path = self.index_path.with_suffix(".json.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.index_path)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise BrushLibraryError(f"Could not save {INDEX_FILENAME}: {error}") from error

    def items(self) -> list[dict]:
        return self.load()["brushes"]

    def get(self, brush_id: str) -> dict | None:
        return next((item for item in self.items() if item.get("id") == brush_id), None)

    def image_path(self, item: dict) -> Path:
        filename = Path(str(item.get("image", ""))).name
        return self.root / filename

    def image_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        try:
            return sorted(
                (
                    path
                    for path in self.root.iterdir()
                    if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
                ),
                key=lambda path: path.name.casefold(),
            )
        except OSError as error:
            raise BrushLibraryError(f"Could not scan the brush folder: {error}") from error

    def folder_stamp(self) -> tuple:
        stamp = []
        for path in self.image_files():
            try:
                statistics = path.stat()
            except OSError as error:
                raise BrushLibraryError(f"Could not inspect {path.name}: {error}") from error
            stamp.append((path.name, statistics.st_size, statistics.st_mtime_ns))
        return tuple(stamp)

    def unique_name(
        self,
        requested_name: str,
        *,
        exclude_id: str = "",
        items: list[dict] | None = None,
    ) -> str:
        base_name = clean_name(requested_name)
        used_names = {
            str(item.get("name", "")).casefold()
            for item in (self.items() if items is None else items)
            if item.get("id") != exclude_id
        }
        if base_name.casefold() not in used_names:
            return base_name
        suffix = 2
        while f"{base_name} {suffix}".casefold() in used_names:
            suffix += 1
        return f"{base_name} {suffix}"

    def unique_image_filename(self, requested_name: str, extension: str) -> str:
        stem = safe_filename_stem(requested_name)
        extension = extension.lower()
        used_names = {path.name.casefold() for path in self.image_files()}
        candidate = f"{stem}{extension}"
        suffix = 2
        while candidate.casefold() in used_names:
            candidate = f"{stem} {suffix}{extension}"
            suffix += 1
        return candidate

    def _item_from_file(
        self,
        path: Path,
        name: str,
        image_info: dict,
        settings: dict | None,
        *,
        brush_id: str | None = None,
        items: list[dict] | None = None,
    ) -> dict:
        statistics = path.stat()
        return {
            "id": brush_id or uuid.uuid4().hex,
            "name": self.unique_name(name, items=items),
            "image": path.name,
            "source_name": path.name,
            "sha256": file_digest(path),
            "file_size": statistics.st_size,
            "file_mtime_ns": statistics.st_mtime_ns,
            "width": int(image_info["width"]),
            "height": int(image_info["height"]),
            "dynamic_range": round(float(image_info.get("dynamic_range", 0.0)), 6),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "settings": normalize_settings(settings),
        }

    def add_image(
        self,
        source_path: str | os.PathLike[str],
        name: str,
        image_info: dict,
        settings: dict | None = None,
    ) -> dict:
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise BrushLibraryError(f"Image file does not exist: {source}")
        extension = source.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise BrushLibraryError(f"Unsupported image format: {extension or 'none'}")

        data = self.load()
        normalized_settings = normalize_settings(settings)
        width = int(image_info["width"])
        height = int(image_info["height"])
        dynamic_range = round(float(image_info.get("dynamic_range", 0.0)), 6)
        root = self.ensure()
        source_is_stored = source.parent == root
        if source_is_stored:
            existing = next(
                (
                    item
                    for item in data["brushes"]
                    if str(item.get("image", "")).casefold() == source.name.casefold()
                ),
                None,
            )
            if existing is not None:
                existing["name"] = self.unique_name(
                    name,
                    exclude_id=existing["id"],
                    items=data["brushes"],
                )
                existing["settings"] = normalized_settings
                self.save(data)
                return existing
            destination = source
        else:
            stored_name = self.unique_image_filename(name, extension)
            destination = root / stored_name
            partial_path = destination.with_suffix(f"{extension}.partial")
            try:
                shutil.copy2(source, partial_path)
                os.replace(partial_path, destination)
            except OSError as error:
                partial_path.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise BrushLibraryError(f"Could not copy the brush image: {error}") from error

        try:
            item = self._item_from_file(
                destination,
                name,
                {"width": width, "height": height, "dynamic_range": dynamic_range},
                normalized_settings,
                items=data["brushes"],
            )
        except OSError as error:
            if not source_is_stored:
                destination.unlink(missing_ok=True)
            raise BrushLibraryError(f"Could not inspect the stored brush image: {error}") from error

        data["brushes"].append(item)
        try:
            self.save(data)
        except BrushLibraryError:
            if not source_is_stored:
                destination.unlink(missing_ok=True)
            raise
        return item

    def synchronize(self, inspect_image) -> dict:
        self.ensure()
        data = self.load()
        original_data = deepcopy(data)
        files = self.image_files()
        files_by_name = {path.name.casefold(): path for path in files}
        existing_by_name = {
            str(item.get("image", "")).casefold(): item
            for item in data["brushes"]
            if item.get("image")
        }
        missing_items = [
            item
            for item in data["brushes"]
            if str(item.get("image", "")).casefold() not in files_by_name
        ]
        unmatched_missing = list(missing_items)
        added_ids = []
        updated_ids = []
        invalid = []
        invalid_ids = []

        for path in files:
            item = existing_by_name.get(path.name.casefold())
            statistics = path.stat()
            unchanged = (
                item is not None
                and item.get("file_size") == statistics.st_size
                and item.get("file_mtime_ns") == statistics.st_mtime_ns
                and not item.get("validation_error")
            )
            if unchanged:
                continue

            try:
                image_info = inspect_image(str(path))
                digest = file_digest(path)
            except Exception as error:
                message = str(error)
                invalid.append({"image": path.name, "error": message})
                if item is not None:
                    item["validation_error"] = message
                    item["file_size"] = statistics.st_size
                    item["file_mtime_ns"] = statistics.st_mtime_ns
                    invalid_ids.append(item["id"])
                continue

            if item is None:
                renamed_item = next(
                    (
                        candidate
                        for candidate in unmatched_missing
                        if candidate.get("sha256") == digest
                    ),
                    None,
                )
                if renamed_item is not None:
                    unmatched_missing.remove(renamed_item)
                    item = renamed_item
                    item["name"] = self.unique_name(
                        path.stem,
                        exclude_id=item["id"],
                        items=data["brushes"],
                    )
                    item["image"] = path.name
                    item["source_name"] = path.name
                    updated_ids.append(item["id"])
                else:
                    item = self._item_from_file(
                        path,
                        path.stem,
                        image_info,
                        None,
                        items=data["brushes"],
                    )
                    data["brushes"].append(item)
                    added_ids.append(item["id"])

            item["sha256"] = digest
            item["file_size"] = statistics.st_size
            item["file_mtime_ns"] = statistics.st_mtime_ns
            item["width"] = int(image_info["width"])
            item["height"] = int(image_info["height"])
            item["dynamic_range"] = round(float(image_info.get("dynamic_range", 0.0)), 6)
            item.pop("validation_error", None)
            if item["id"] not in added_ids and item["id"] not in updated_ids:
                updated_ids.append(item["id"])

        removed_ids = {item["id"] for item in unmatched_missing}
        if removed_ids:
            data["brushes"] = [item for item in data["brushes"] if item["id"] not in removed_ids]

        if data != original_data:
            self.save(data)

        visible_items = [
            item
            for item in data["brushes"]
            if not item.get("validation_error") and self.image_path(item).is_file()
        ]
        return {
            "items": visible_items,
            "added_ids": added_ids,
            "updated_ids": updated_ids,
            "removed_ids": sorted(removed_ids),
            "invalid_ids": invalid_ids,
            "invalid": invalid,
            "changed": data != original_data,
        }

    def update(self, brush_id: str, *, name: str | None = None, settings: dict | None = None) -> dict:
        data = self.load()
        item = next((entry for entry in data["brushes"] if entry.get("id") == brush_id), None)
        if item is None:
            raise BrushLibraryError("The selected brush is no longer in the library")
        if name is not None:
            item["name"] = self.unique_name(
                name,
                exclude_id=brush_id,
                items=data["brushes"],
            )
        if settings is not None:
            item["settings"] = normalize_settings(settings)
        self.save(data)
        return item

    def remove(self, brush_id: str) -> dict:
        data = self.load()
        index = next(
            (position for position, item in enumerate(data["brushes"]) if item.get("id") == brush_id),
            None,
        )
        if index is None:
            raise BrushLibraryError("The selected brush is no longer in the library")
        item = data["brushes"].pop(index)
        self.save(data)
        try:
            self.image_path(item).unlink(missing_ok=True)
        except OSError as error:
            raise BrushLibraryError(f"Brush removed, but its image could not be deleted: {error}") from error
        return item

    def missing_images(self) -> list[dict]:
        return [item for item in self.items() if not self.image_path(item).is_file()]