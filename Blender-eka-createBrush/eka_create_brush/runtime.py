from __future__ import annotations

import os
from pathlib import Path

import bpy
import bpy.utils.previews

from .library import BrushLibrary, BrushLibraryError


LIBRARY_ENVIRONMENT_VARIABLE = "EKA_CREATE_BRUSH_LIBRARY"
DATA_TAG = "eka_create_brush_id"
BRUSH_NAME_PREFIX = "eka-createBrush | "
MAX_IMAGE_DIMENSION = 8192
GRAYSCALE_TOLERANCE = 0.035
MAX_ANALYSIS_SAMPLES = 8192

TOOL_IDENTIFIERS = {
    "CLAY": "builtin_brush.Clay",
    "CLAY_STRIPS": "builtin_brush.Clay Strips",
    "CREASE": "builtin_brush.Crease",
    "DRAW": "builtin_brush.Draw",
    "FILL": "builtin_brush.Fill",
    "INFLATE": "builtin_brush.Inflate",
    "SCRAPE": "builtin_brush.Scrape",
    "SMOOTH": "builtin_brush.Smooth",
}

_preview_collection = None
_preview_items: list[tuple] = []
_preview_stamp = None
_library_error = ""
_library_warnings: list[str] = []
_configured_library_root = ""
_folder_stamp = None
_watcher_enabled = False
WATCH_INTERVAL_SECONDS = 2.0


class BrushImageError(RuntimeError):
    pass


class BrushActivationError(RuntimeError):
    pass


def default_library_root() -> Path:
    resource_path = bpy.utils.user_resource("DATAFILES", path="eka-createBrush", create=True)
    if not resource_path:
        resource_path = str(Path.home() / ".eka-createBrush")
    return Path(resource_path).resolve()


def library_root() -> Path:
    override = os.environ.get(LIBRARY_ENVIRONMENT_VARIABLE, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if _configured_library_root:
        return Path(bpy.path.abspath(_configured_library_root)).expanduser().resolve()
    return default_library_root()


def set_library_directory(path: str) -> None:
    global _configured_library_root, _folder_stamp
    _configured_library_root = path.strip()
    _folder_stamp = None
    clear_previews()


def library() -> BrushLibrary:
    return BrushLibrary(library_root())


def library_error() -> str:
    return _library_error


def library_warnings() -> list[str]:
    return list(_library_warnings)


def analyze_brush_image(filepath: str) -> dict:
    path = Path(bpy.path.abspath(filepath)).expanduser().resolve()
    if not path.is_file():
        raise BrushImageError(f"Image file does not exist: {path}")

    image = None
    try:
        image = bpy.data.images.load(str(path), check_existing=False)
        width, height = (int(value) for value in image.size)
        if width <= 0 or height <= 0:
            raise BrushImageError("Blender could not read the image dimensions")
        if width != height:
            raise BrushImageError(f"Brush images must be square; this image is {width} x {height}")
        if width > MAX_IMAGE_DIMENSION:
            raise BrushImageError(
                f"Brush images cannot exceed {MAX_IMAGE_DIMENSION} x {MAX_IMAGE_DIMENSION} pixels"
            )

        pixels = image.pixels
        pixel_count = width * height
        sample_count = min(pixel_count, MAX_ANALYSIS_SAMPLES)
        minimum_luminance = 1.0
        maximum_luminance = 0.0
        maximum_chroma = 0.0
        visible_samples = 0
        divisor = max(1, sample_count - 1)
        for sample_index in range(sample_count):
            pixel_index = ((sample_index * (pixel_count - 1)) // divisor) * 4
            red = float(pixels[pixel_index])
            green = float(pixels[pixel_index + 1])
            blue = float(pixels[pixel_index + 2])
            alpha = float(pixels[pixel_index + 3])
            if alpha <= 0.01:
                continue
            visible_samples += 1
            maximum_chroma = max(
                maximum_chroma,
                abs(red - green),
                abs(red - blue),
                abs(green - blue),
            )
            luminance = (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)
            minimum_luminance = min(minimum_luminance, luminance)
            maximum_luminance = max(maximum_luminance, luminance)

        if visible_samples == 0:
            raise BrushImageError("The image is fully transparent")
        if maximum_chroma > GRAYSCALE_TOLERANCE:
            raise BrushImageError(
                "Brush images must be grayscale; RGB color differences were detected"
            )

        return {
            "path": str(path),
            "width": width,
            "height": height,
            "dynamic_range": max(0.0, maximum_luminance - minimum_luminance),
            "low_contrast": (maximum_luminance - minimum_luminance) < 0.05,
        }
    except BrushImageError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise BrushImageError(f"Blender could not load the brush image: {error}") from error
    finally:
        if image is not None:
            bpy.data.images.remove(image)


def _metadata_stamp():
    index_path = library().index_path
    try:
        return (index_path.stat().st_mtime_ns, index_path.stat().st_size)
    except OSError:
        return None


def synchronize_library(*, force: bool = False) -> dict:
    global _folder_stamp, _library_warnings
    brush_library = library()
    current_stamp = brush_library.folder_stamp()
    if not force and _folder_stamp == current_stamp:
        items = [
            item
            for item in brush_library.items()
            if not item.get("validation_error") and brush_library.image_path(item).is_file()
        ]
        return {
            "items": items,
            "added_ids": [],
            "updated_ids": [],
            "removed_ids": [],
            "invalid_ids": [],
            "invalid": [],
            "changed": False,
        }

    result = brush_library.synchronize(analyze_brush_image)
    for brush_id in {
        *result["removed_ids"],
        *result["invalid_ids"],
        *result["updated_ids"],
    }:
        remove_runtime_data(brush_id)
    _library_warnings = [
        f"{entry['image']}: {entry['error']}"
        for entry in result["invalid"]
    ]
    _folder_stamp = brush_library.folder_stamp()
    return result


def clear_previews() -> None:
    global _preview_collection, _preview_items, _preview_stamp
    if _preview_collection is not None:
        bpy.utils.previews.remove(_preview_collection)
    _preview_collection = None
    _preview_items = []
    _preview_stamp = None


def refresh_previews(*, force: bool = False, synchronize: bool = True) -> list[tuple]:
    global _preview_collection, _preview_items, _preview_stamp, _library_error
    try:
        if synchronize:
            synchronize_library(force=force)
        stamp = (_metadata_stamp(), library().folder_stamp())
    except BrushLibraryError as error:
        _library_error = str(error)
        clear_previews()
        _preview_collection = bpy.utils.previews.new()
        return []
    if not force and _preview_collection is not None and stamp == _preview_stamp:
        return _preview_items

    clear_previews()
    _preview_collection = bpy.utils.previews.new()
    _preview_stamp = stamp
    try:
        items = [item for item in library().items() if not item.get("validation_error")]
        _library_error = ""
    except BrushLibraryError as error:
        _library_error = str(error)
        items = []

    enum_items = []
    used_numbers = set()
    for index, item in enumerate(sorted(items, key=lambda value: value.get("name", "").casefold())):
        brush_id = str(item.get("id", ""))
        image_path = library().image_path(item)
        icon_id = 0
        description = f"{item.get('width', '?')} x {item.get('height', '?')} grayscale brush"
        if image_path.is_file():
            try:
                preview = _preview_collection.load(brush_id, str(image_path), "IMAGE", force_reload=True)
                icon_id = preview.icon_id
            except (KeyError, OSError, RuntimeError):
                description = f"Preview unavailable - {description}"
        else:
            description = f"Image missing - {description}"
        try:
            enum_number = int(brush_id[:8], 16) & 0x7FFFFFFF
        except ValueError:
            enum_number = index + 1
        enum_number = enum_number or index + 1
        while enum_number in used_numbers:
            enum_number += 1
        used_numbers.add(enum_number)
        enum_items.append(
            (brush_id, str(item.get("name", "Untitled Brush")), description, icon_id, enum_number)
        )
    _preview_items = enum_items
    return _preview_items


def _repair_selections(items: list[tuple]) -> None:
    visible_numbers = {item[4] for item in items}
    first_identifier = items[0][0] if items else "__EMPTY__"
    for window_manager in bpy.data.window_managers:
        settings = getattr(window_manager, "eka_create_brush", None)
        if settings is not None and settings.get("selected_brush") not in visible_numbers:
            settings.selected_brush = first_identifier


def _tag_sidebar_redraw() -> None:
    for window_manager in bpy.data.window_managers:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()


def _watch_library():
    global _library_error
    if not _watcher_enabled:
        return None
    try:
        current_stamp = library().folder_stamp()
        if current_stamp != _folder_stamp:
            synchronize_library(force=True)
            items = refresh_previews(force=True, synchronize=False)
            _repair_selections(items)
            _tag_sidebar_redraw()
        _library_error = ""
    except BrushLibraryError as error:
        _library_error = str(error)
        _tag_sidebar_redraw()
    return WATCH_INTERVAL_SECONDS


def start_library_watcher() -> None:
    global _watcher_enabled
    _watcher_enabled = True
    if not bpy.app.timers.is_registered(_watch_library):
        bpy.app.timers.register(_watch_library, first_interval=WATCH_INTERVAL_SECONDS, persistent=True)


def stop_library_watcher() -> None:
    global _watcher_enabled
    _watcher_enabled = False
    if bpy.app.timers.is_registered(_watch_library):
        bpy.app.timers.unregister(_watch_library)


def preview_items(search: str = "") -> list[tuple]:
    items = refresh_previews()
    query = search.strip().casefold()
    if query:
        items = [item for item in items if query in item[1].casefold()]
    if not items:
        message = "No matching brushes" if query else "No brushes imported"
        return [("__EMPTY__", message, message, 0, 1)]
    return items


def _has_tag(data_block, brush_id: str) -> bool:
    try:
        return data_block.get(DATA_TAG) == brush_id
    except (AttributeError, TypeError):
        return False


def _set_tag(data_block, brush_id: str) -> None:
    try:
        data_block[DATA_TAG] = brush_id
    except (AttributeError, RuntimeError, TypeError):
        pass


def find_runtime_brush(brush_id: str):
    return next((brush for brush in bpy.data.brushes if _has_tag(brush, brush_id)), None)


def _find_tagged(collection, brush_id: str):
    return next((data_block for data_block in collection if _has_tag(data_block, brush_id)), None)


def _set_enum_value(owner, property_name: str, value: str, fallback: str | None = None) -> str:
    if not hasattr(owner, property_name):
        return ""
    enum_property = owner.bl_rna.properties.get(property_name)
    identifiers = {item.identifier for item in enum_property.enum_items} if enum_property else set()
    selected = value if value in identifiers else fallback
    if selected and (not identifiers or selected in identifiers):
        try:
            setattr(owner, property_name, selected)
            return selected
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    return ""


def _load_runtime_image(item: dict):
    brush_id = item["id"]
    image = _find_tagged(bpy.data.images, brush_id)
    path = library().image_path(item)
    if not path.is_file():
        raise BrushActivationError(f"The stored image for {item['name']} is missing")
    if image is None:
        try:
            image = bpy.data.images.load(str(path), check_existing=False)
        except (OSError, RuntimeError) as error:
            raise BrushActivationError(f"Could not load the stored brush image: {error}") from error
        _set_tag(image, brush_id)
    image.name = f"{BRUSH_NAME_PREFIX}{item['name']} Image"
    image.filepath = str(path)
    image.use_fake_user = True
    for color_space in ("Non-Color", "Non-Colour Data", "Linear Rec.709"):
        try:
            image.colorspace_settings.name = color_space
            break
        except TypeError:
            continue
    return image


def _ensure_runtime_texture(item: dict, image):
    brush_id = item["id"]
    texture = _find_tagged(bpy.data.textures, brush_id)
    if texture is None:
        texture = bpy.data.textures.new(f"{BRUSH_NAME_PREFIX}{item['name']} Texture", type="IMAGE")
        _set_tag(texture, brush_id)
    texture.name = f"{BRUSH_NAME_PREFIX}{item['name']} Texture"
    texture.image = image
    texture.use_fake_user = True
    if hasattr(texture, "extension"):
        texture.extension = "EXTEND"
    invert = item["settings"]["invert"]
    texture.use_color_ramp = invert
    if invert:
        color_ramp = texture.color_ramp
        color_ramp.elements[0].position = 0.0
        color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)
        color_ramp.elements[-1].position = 1.0
        color_ramp.elements[-1].color = (0.0, 0.0, 0.0, 1.0)
    return texture


def _new_sculpt_brush(name: str):
    try:
        return bpy.data.brushes.new(name, mode="SCULPT")
    except TypeError:
        brush = bpy.data.brushes.new(name)
        if hasattr(brush, "use_paint_sculpt"):
            brush.use_paint_sculpt = True
        return brush


def ensure_runtime_brush(item: dict):
    brush_id = item["id"]
    brush = find_runtime_brush(brush_id)
    image = _load_runtime_image(item)
    texture = _ensure_runtime_texture(item, image)
    if brush is None:
        try:
            brush = _new_sculpt_brush(f"{BRUSH_NAME_PREFIX}{item['name']}")
        except (RuntimeError, TypeError) as error:
            raise BrushActivationError(f"Could not create the Sculpt brush: {error}") from error
        _set_tag(brush, brush_id)

    settings = item["settings"]
    brush.name = f"{BRUSH_NAME_PREFIX}{item['name']}"
    brush.use_fake_user = True
    if hasattr(brush, "use_paint_sculpt"):
        brush.use_paint_sculpt = True
    brush.texture = texture
    brush.strength = settings["strength"]
    brush.size = settings["size"]
    brush.spacing = settings["spacing"]
    brush.texture_sample_bias = settings["texture_bias"]
    brush.use_pressure_size = settings["use_pressure_size"]
    brush.use_pressure_strength = settings["use_pressure_strength"]
    brush.use_frontface = settings["front_faces_only"]
    brush.use_accumulate = settings["accumulate"]
    if hasattr(brush, "use_primary_overlay"):
        brush.use_primary_overlay = True
    if hasattr(brush, "texture_overlay_alpha"):
        brush.texture_overlay_alpha = 42

    _set_enum_value(brush, "sculpt_tool", settings["tool"], "DRAW")
    _set_enum_value(brush, "sculpt_brush_type", settings["tool"], "DRAW")
    _set_enum_value(brush, "stroke_method", settings["stroke_method"], "SPACE")
    _set_enum_value(brush.texture_slot, "map_mode", settings["mapping"], "AREA_PLANE")
    falloff = "MAX" if settings["falloff"] == "CONSTANT" else settings["falloff"]
    _set_enum_value(brush, "curve_preset", falloff, "SMOOTH")
    _set_enum_value(brush, "curve_distance_falloff_preset", falloff, "SMOOTH")

    image_path = str(library().image_path(item))
    if hasattr(brush, "use_custom_icon") and hasattr(brush, "icon_filepath"):
        brush.use_custom_icon = True
        brush.icon_filepath = image_path
    if bpy.app.version >= (4, 3, 0) and brush.asset_data is None:
        try:
            brush.asset_mark()
        except RuntimeError:
            pass
    if brush.asset_data is not None:
        brush.asset_data.author = "eka-createBrush"
        brush.asset_data.description = f"Sculpt brush created from {item['source_name']}"
        existing_tags = {tag.name for tag in brush.asset_data.tags}
        for tag_name in ("Sculpt", "eka-createBrush"):
            if tag_name not in existing_tags:
                brush.asset_data.tags.new(tag_name)
    return brush


def _view3d_override(context):
    if context.area is not None and context.area.type == "VIEW_3D":
        region = next((region for region in context.area.regions if region.type == "WINDOW"), context.region)
        return {"window": context.window, "area": context.area, "region": region}
    if context.window is not None and context.window.screen is not None:
        area = next((area for area in context.window.screen.areas if area.type == "VIEW_3D"), None)
        if area is not None:
            region = next((region for region in area.regions if region.type == "WINDOW"), None)
            return {"window": context.window, "area": area, "region": region}
    return None


def _set_sculpt_tool(context, tool: str) -> None:
    tool_identifier = TOOL_IDENTIFIERS.get(tool, TOOL_IDENTIFIERS["DRAW"])
    override = _view3d_override(context)
    try:
        if override:
            with context.temp_override(**override):
                bpy.ops.wm.tool_set_by_id(name=tool_identifier)
        elif not bpy.app.background:
            bpy.ops.wm.tool_set_by_id(name=tool_identifier)
    except RuntimeError:
        pass


def _asset_activate(context, brush) -> bool:
    if not hasattr(bpy.ops.brush, "asset_activate"):
        return False
    if brush.asset_data is None:
        try:
            brush.asset_mark()
        except RuntimeError:
            return False
    override = _view3d_override(context)
    identifiers = (f"Brush/{brush.name}", f"Brush\\{brush.name}")
    for identifier in identifiers:
        try:
            if override:
                with context.temp_override(**override):
                    result = bpy.ops.brush.asset_activate(
                        asset_library_type="LOCAL",
                        relative_asset_identifier=identifier,
                    )
            else:
                result = bpy.ops.brush.asset_activate(
                    asset_library_type="LOCAL",
                    relative_asset_identifier=identifier,
                )
            if "FINISHED" in result:
                return True
        except RuntimeError:
            continue
    return False


def activate_brush(context, item: dict, *, enter_sculpt: bool = True):
    target = context.object
    if target is None or target.type != "MESH":
        raise BrushActivationError("Select a mesh object before using a Sculpt brush")
    if target.mode != "SCULPT":
        if not enter_sculpt:
            raise BrushActivationError("Enter Sculpt Mode to use the selected brush")
        try:
            if target.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.mode_set(mode="SCULPT")
        except RuntimeError as error:
            raise BrushActivationError(f"Could not enter Sculpt Mode: {error}") from error

    brush = ensure_runtime_brush(item)
    paint = context.tool_settings.sculpt
    try:
        paint.brush = brush
    except (AttributeError, RuntimeError, TypeError):
        if not _asset_activate(context, brush):
            raise BrushActivationError("Blender did not allow the custom brush to become active")
    else:
        _set_sculpt_tool(context, item["settings"]["tool"])
    return brush


def remove_runtime_data(brush_id: str) -> None:
    brushes = [brush for brush in bpy.data.brushes if _has_tag(brush, brush_id)]
    textures = [texture for texture in bpy.data.textures if _has_tag(texture, brush_id)]
    images = [image for image in bpy.data.images if _has_tag(image, brush_id)]
    active_brush = getattr(getattr(bpy.context.tool_settings, "sculpt", None), "brush", None)
    if active_brush in brushes:
        try:
            bpy.context.tool_settings.sculpt.brush = None
        except (AttributeError, RuntimeError, TypeError):
            pass
    for brush in brushes:
        bpy.data.brushes.remove(brush)
    for texture in textures:
        texture.use_fake_user = False
        if texture.users == 0:
            bpy.data.textures.remove(texture)
    for image in images:
        image.use_fake_user = False
        if image.users == 0:
            bpy.data.images.remove(image)