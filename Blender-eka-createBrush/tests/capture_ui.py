import importlib.util
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

import bpy
from mathutils import Quaternion


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "eka_create_brush" / "__init__.py"
SCREENSHOT_PATH = PROJECT_ROOT / "docs" / "eka-createBrush-ui.png"
TEMPORARY_DIRECTORY = Path(tempfile.mkdtemp(prefix="eka-create-brush-ui-"))
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


def save_pattern(path, pattern):
    size = 128
    image = bpy.data.images.new(path.stem, width=size, height=size, alpha=True)
    pixels = []
    for y_coordinate in range(size):
        y_value = ((y_coordinate / (size - 1)) * 2.0) - 1.0
        for x_coordinate in range(size):
            x_value = ((x_coordinate / (size - 1)) * 2.0) - 1.0
            value = max(0.0, min(1.0, pattern(x_value, y_value)))
            pixels.extend((value, value, value, 1.0))
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def create_patterns():
    patterns = {
        "Stone Pores": lambda x, y: 0.5
        + (0.28 * math.sin((x * 18.0) + math.sin(y * 11.0)))
        + (0.18 * math.cos((y * 25.0) - (x * 7.0))),
        "Rock Cracks": lambda x, y: min(
            1.0,
            0.12
            + (5.5 * abs(math.sin((x * 5.0) + (y * 2.4) + math.sin(y * 8.0))))
            + (0.18 * math.hypot(x, y)),
        ),
        "Skin Detail": lambda x, y: 0.48
        + (0.15 * math.sin((x + y) * 38.0))
        + (0.12 * math.sin((x * 55.0) - (y * 23.0)))
        + (0.1 * math.cos((x * 17.0) + (y * 61.0))),
        "Fabric Weave": lambda x, y: 0.22
        + (0.42 * (0.5 + (0.5 * math.sin(x * 42.0))))
        + (0.32 * (0.5 + (0.5 * math.sin(y * 42.0)))),
    }
    paths = {}
    for name, pattern in patterns.items():
        path = TEMPORARY_DIRECTORY / f"{name.lower().replace(' ', '-')}.png"
        save_pattern(path, pattern)
        paths[name] = path
    return paths


def create_scene(addon):
    global TARGET
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=2.1)
    target = bpy.context.object
    target.name = "Sculpt Surface"
    subdivision = target.modifiers.new("Sculpt Detail", "SUBSURF")
    subdivision.subdivision_type = "SIMPLE"
    subdivision.levels = 2
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=subdivision.name)
    TARGET = target
    for polygon in target.data.polygons:
        polygon.use_smooth = True

    for index, (name, path) in enumerate(create_patterns().items()):
        analysis = addon.runtime.analyze_brush_image(str(path))
        item = addon.runtime.library().add_image(
            path,
            name,
            analysis,
            {
                "strength": 0.65 if name == "Stone Pores" else 0.5 + (index * 0.08),
                "size": 180 if name == "Stone Pores" else 105 + (index * 15),
                "spacing": 25 if name == "Stone Pores" else 12 + (index * 3),
                "mapping": "TILED" if name in {"Stone Pores", "Fabric Weave"} else "AREA_PLANE",
            },
        )
        if name == "Stone Pores":
            active_item = item

    addon.runtime.refresh_previews(force=True)
    panel_settings = bpy.context.window_manager.eka_create_brush
    panel_settings.selected_brush = active_item["id"]
    addon.runtime.activate_brush(bpy.context, active_item)
    panel_settings.status = "Active: Stone Pores"
    return target


def prepare_viewport(target):
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    window_region = next(region for region in area.regions if region.type == "WINDOW")
    with bpy.context.temp_override(window=window, area=area, region=window_region):
        bpy.ops.screen.screen_full_area()

    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    space = area.spaces.active
    space.show_region_ui = True
    space.overlay.show_floor = False
    space.overlay.show_axis_x = False
    space.overlay.show_axis_y = False
    space.shading.type = "SOLID"
    space.shading.light = "STUDIO"
    space.shading.show_shadows = True
    space.shading.show_cavity = True
    space.shading.cavity_type = "WORLD"
    space.shading.curvature_ridge_factor = 2.0
    space.shading.curvature_valley_factor = 1.5

    region_3d = space.region_3d
    region_3d.view_location = target.location
    region_3d.view_distance = 5.8
    region_3d.view_rotation = Quaternion((0.9239, 0.205, 0.318, -0.075))
    return window


def viewport_stroke_coordinates():
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    region = next(region for region in area.regions if region.type == "WINDOW")
    center_x = region.x + (region.width * 0.5)
    center_y = region.y + (region.height * 0.5)
    points = [
        (int(center_x - 230 + (index * 46)), int(center_y + (45 * math.sin(index * 0.62))))
        for index in range(11)
    ]
    return window, points


def release_stroke():
    window, points = viewport_stroke_coordinates()
    x_coordinate, y_coordinate = points[-1]
    window.event_simulate(
        type="LEFTMOUSE",
        value="RELEASE",
        x=x_coordinate,
        y=y_coordinate,
    )
    bpy.app.timers.register(activate_tab, first_interval=0.75)
    return None


def drag_stroke():
    global STROKE_INDEX
    window, points = viewport_stroke_coordinates()
    STROKE_INDEX += 1
    if STROKE_INDEX >= len(points):
        bpy.app.timers.register(release_stroke, first_interval=0.08)
        return None
    x_coordinate, y_coordinate = points[STROKE_INDEX]
    window.event_simulate(
        type="MOUSEMOVE",
        value="NOTHING",
        x=x_coordinate,
        y=y_coordinate,
    )
    return 0.08


def press_stroke():
    window, points = viewport_stroke_coordinates()
    x_coordinate, y_coordinate = points[0]
    window.event_simulate(
        type="LEFTMOUSE",
        value="PRESS",
        x=x_coordinate,
        y=y_coordinate,
    )
    bpy.app.timers.register(drag_stroke, first_interval=0.08)
    return None


def begin_stroke():
    global BEFORE, STROKE_POINTS
    window, points = viewport_stroke_coordinates()
    STROKE_POINTS = points
    BEFORE = [vertex.co.copy() for vertex in TARGET.data.vertices]
    x_coordinate, y_coordinate = points[0]
    window.cursor_warp(x_coordinate, y_coordinate)
    window.event_simulate(
        type="MOUSEMOVE",
        value="NOTHING",
        x=x_coordinate,
        y=y_coordinate,
    )
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=3)
    bpy.app.timers.register(press_stroke, first_interval=0.25)
    return None


def sidebar_coordinates():
    window = bpy.context.window
    area = next(area for area in window.screen.areas if area.type == "VIEW_3D")
    sidebar = next(region for region in area.regions if region.type == "UI")
    tab_x = sidebar.x + sidebar.width - 14
    tab_y = sidebar.y + sidebar.height - 315
    return window, sidebar, tab_x, tab_y


def release_tab():
    window, _sidebar, tab_x, tab_y = sidebar_coordinates()
    window.event_simulate(type="LEFTMOUSE", value="RELEASE", x=tab_x, y=tab_y)
    bpy.app.timers.register(capture, first_interval=1.0)
    return None


def press_tab():
    window, _sidebar, tab_x, tab_y = sidebar_coordinates()
    window.event_simulate(type="LEFTMOUSE", value="PRESS", x=tab_x, y=tab_y)
    bpy.app.timers.register(release_tab, first_interval=0.2)
    return None


def activate_tab():
    window, sidebar, tab_x, tab_y = sidebar_coordinates()
    window.cursor_warp(tab_x, tab_y)
    window.event_simulate(type="MOUSEMOVE", value="NOTHING", x=tab_x, y=tab_y)
    print(f"UI_TAB_CLICK=({tab_x}, {tab_y}) SIDEBAR={sidebar.width}x{sidebar.height}")
    bpy.app.timers.register(press_tab, first_interval=0.2)
    return None


def capture():
    SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _window, sidebar, _tab_x, _tab_y = sidebar_coordinates()
    print(f"UI_ACTIVE_CATEGORY={sidebar.active_panel_category}")
    maximum_displacement = max(
        (vertex.co - original).length
        for vertex, original in zip(TARGET.data.vertices, BEFORE)
    )
    assert maximum_displacement > 1e-5, maximum_displacement
    print(f"UI_SCULPT_DISPLACEMENT={maximum_displacement:.6f}")
    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=4)
    result = bpy.ops.screen.screenshot(filepath=str(SCREENSHOT_PATH), check_existing=False)
    print(f"UI_CAPTURE_RESULT={result} PATH={SCREENSHOT_PATH}")
    shutil.rmtree(TEMPORARY_DIRECTORY, ignore_errors=True)
    bpy.ops.wm.quit_blender()
    return None


def dismiss_splash():
    window = bpy.context.window
    window.event_simulate(type="ESC", value="PRESS")
    window.event_simulate(type="ESC", value="RELEASE")
    bpy.app.timers.register(begin_stroke, first_interval=0.75)
    return None


def main():
    os.environ["EKA_CREATE_BRUSH_LIBRARY"] = str(TEMPORARY_DIRECTORY / "library")
    addon = load_addon()
    target = create_scene(addon)
    prepare_viewport(target)
    bpy.app.timers.register(dismiss_splash, first_interval=0.75)


main()