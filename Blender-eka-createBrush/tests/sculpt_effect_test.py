import importlib.util
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

import bpy
from mathutils import Quaternion


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "eka_create_brush" / "__init__.py"
TEMPORARY_DIRECTORY = Path(tempfile.mkdtemp(prefix="eka-create-brush-effect-"))

TARGET = None
BEFORE = []
STROKE_POINTS = []
STROKE_INDEX = 0


def load_addon():
    spec = importlib.util.spec_from_file_location(
        "eka_create_brush",
        ADDON_PATH,
        submodule_search_locations=[str(ADDON_PATH.parent)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    return addon


def save_pattern(path):
    size = 256
    image = bpy.data.images.new(path.stem, width=size, height=size, alpha=True)
    pixels = []
    for y_coordinate in range(size):
        y_value = ((y_coordinate / (size - 1)) * 2.0) - 1.0
        for x_coordinate in range(size):
            x_value = ((x_coordinate / (size - 1)) * 2.0) - 1.0
            radius = math.hypot(x_value, y_value)
            value = 0.5 + (0.42 * math.sin((radius * 34.0) + (x_value * 5.0)))
            value *= max(0.0, min(1.0, (1.0 - radius) * 3.0))
            value = max(0.0, min(1.0, value))
            pixels.extend((value, value, value, 1.0))
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def view3d_context():
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    return window, area, region


def set_up_scene():
    global TARGET, BEFORE, STROKE_POINTS
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=2.0)
    TARGET = bpy.context.object
    TARGET.name = "Textured Stroke Test"
    for polygon in TARGET.data.polygons:
        polygon.use_smooth = True

    pattern_path = TEMPORARY_DIRECTORY / "Visible Stone Rings.png"
    save_pattern(pattern_path)
    addon = load_addon()
    analysis = addon.runtime.analyze_brush_image(str(pattern_path))
    item = addon.runtime.library().add_image(
        pattern_path,
        "Visible Stone Rings",
        analysis,
        {
            "strength": 1.0,
            "size": 190,
            "spacing": 18,
            "mapping": "AREA_PLANE",
            "stroke_method": "SPACE",
            "falloff": "SMOOTH",
            "use_pressure_size": False,
            "use_pressure_strength": False,
        },
    )
    addon.runtime.refresh_previews(force=True)
    addon.runtime.activate_brush(bpy.context, item)

    window, area, region = view3d_context()
    space = area.spaces.active
    space.overlay.show_floor = False
    space.region_3d.view_location = TARGET.location
    space.region_3d.view_distance = 5.4
    space.region_3d.view_rotation = Quaternion((1.0, 0.0, 0.0, 0.0))
    BEFORE = [vertex.co.copy() for vertex in TARGET.data.vertices]
    center_x = region.x + (region.width * 0.5)
    center_y = region.y + (region.height * 0.5)
    STROKE_POINTS = [
        (int(center_x - 180 + (index * 36)), int(center_y + (32 * math.sin(index * 0.65))))
        for index in range(11)
    ]
    return window


def fail(error):
    traceback.print_exception(type(error), error, error.__traceback__)
    shutil.rmtree(TEMPORARY_DIRECTORY, ignore_errors=True)
    os._exit(1)


def verify_stroke():
    try:
        TARGET.data.update()
        maximum_displacement = max(
            (vertex.co - original).length
            for vertex, original in zip(TARGET.data.vertices, BEFORE)
        )
        if maximum_displacement <= 1e-5:
            raise AssertionError(f"Sculpt stroke did not deform the mesh: {maximum_displacement}")
        print(
            "EKA_CREATE_BRUSH_SCULPT_EFFECT_PASS "
            f"blender={bpy.app.version_string} displacement={maximum_displacement:.6f}"
        )
        shutil.rmtree(TEMPORARY_DIRECTORY, ignore_errors=True)
        bpy.ops.wm.quit_blender()
    except Exception as error:
        fail(error)
    return None


def release_stroke():
    try:
        window, _area, _region = view3d_context()
        x_coordinate, y_coordinate = STROKE_POINTS[-1]
        window.event_simulate(
            type="LEFTMOUSE",
            value="RELEASE",
            x=x_coordinate,
            y=y_coordinate,
        )
        bpy.app.timers.register(verify_stroke, first_interval=0.75)
    except Exception as error:
        fail(error)
    return None


def drag_stroke():
    global STROKE_INDEX
    try:
        window, _area, _region = view3d_context()
        STROKE_INDEX += 1
        if STROKE_INDEX >= len(STROKE_POINTS):
            bpy.app.timers.register(release_stroke, first_interval=0.08)
            return None
        x_coordinate, y_coordinate = STROKE_POINTS[STROKE_INDEX]
        window.event_simulate(
            type="MOUSEMOVE",
            value="NOTHING",
            x=x_coordinate,
            y=y_coordinate,
        )
        return 0.08
    except Exception as error:
        fail(error)
    return None


def press_stroke():
    try:
        window, _area, _region = view3d_context()
        x_coordinate, y_coordinate = STROKE_POINTS[0]
        window.event_simulate(
            type="LEFTMOUSE",
            value="PRESS",
            x=x_coordinate,
            y=y_coordinate,
        )
        bpy.app.timers.register(drag_stroke, first_interval=0.08)
    except Exception as error:
        fail(error)
    return None


def begin_stroke():
    try:
        window, _area, _region = view3d_context()
        x_coordinate, y_coordinate = STROKE_POINTS[0]
        window.cursor_warp(x_coordinate, y_coordinate)
        window.event_simulate(
            type="MOUSEMOVE",
            value="NOTHING",
            x=x_coordinate,
            y=y_coordinate,
        )
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3)
        bpy.app.timers.register(press_stroke, first_interval=0.25)
    except Exception as error:
        fail(error)
    return None


def dismiss_splash():
    try:
        window = bpy.context.window
        window.event_simulate(type="ESC", value="PRESS")
        window.event_simulate(type="ESC", value="RELEASE")
        bpy.app.timers.register(begin_stroke, first_interval=0.75)
    except Exception as error:
        fail(error)
    return None


def main():
    os.environ["EKA_CREATE_BRUSH_LIBRARY"] = str(TEMPORARY_DIRECTORY / "library")
    set_up_scene()
    bpy.app.timers.register(dismiss_splash, first_interval=0.75)


main()