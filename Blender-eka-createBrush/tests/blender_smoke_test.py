import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile

import bpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADDON_PATH = PROJECT_ROOT / "eka_create_brush" / "__init__.py"


def load_addon():
    spec = importlib.util.spec_from_file_location(
        "eka_create_brush",
        ADDON_PATH,
        submodule_search_locations=[str(ADDON_PATH.parent)],
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    return addon


def save_test_image(path, width, height, pixel_function):
    image = bpy.data.images.new(path.stem, width=width, height=height, alpha=True)
    pixels = []
    for y_coordinate in range(height):
        for x_coordinate in range(width):
            red, green, blue, alpha = pixel_function(x_coordinate, y_coordinate)
            pixels.extend((red, green, blue, alpha))
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def create_sculpt_target():
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
    target = bpy.context.object
    target.name = "eka-createBrush Test Sphere"
    return target


def expect_image_error(addon, path, expected_message):
    try:
        addon.runtime.analyze_brush_image(str(path))
    except addon.runtime.BrushImageError as error:
        assert expected_message in str(error), str(error)
    else:
        raise AssertionError(f"Expected image validation failure: {expected_message}")


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    temporary_directory = Path(tempfile.mkdtemp(prefix="eka-create-brush-smoke-"))
    library_directory = temporary_directory / "library"
    os.environ["EKA_CREATE_BRUSH_LIBRARY"] = str(library_directory)

    try:
        grayscale_path = temporary_directory / "stone_pore.png"
        color_path = temporary_directory / "colored.png"
        rectangle_path = temporary_directory / "rectangle.png"
        save_test_image(
            grayscale_path,
            32,
            32,
            lambda x, y: (
                (x + y) / 62.0,
                (x + y) / 62.0,
                (x + y) / 62.0,
                1.0,
            ),
        )
        save_test_image(
            color_path,
            16,
            16,
            lambda x, y: (x / 15.0, y / 15.0, 0.15, 1.0),
        )
        save_test_image(
            rectangle_path,
            24,
            16,
            lambda x, y: (x / 23.0, x / 23.0, x / 23.0, 1.0),
        )

        addon = load_addon()
        addon.register()
        assert bpy.ops.eka_create_brush.choose_library(
            directory=str(library_directory),
        ) == {"FINISHED"}
        assert addon.runtime.library_root() == library_directory.resolve()
        target = create_sculpt_target()

        analysis = addon.runtime.analyze_brush_image(str(grayscale_path))
        assert analysis["width"] == analysis["height"] == 32
        assert analysis["dynamic_range"] > 0.9
        assert analysis["low_contrast"] is False
        expect_image_error(addon, color_path, "must be grayscale")
        expect_image_error(addon, rectangle_path, "must be square")

        assert bpy.ops.eka_create_brush.import_brush(
            filepath=str(grayscale_path),
            brush_name="Stone Pore",
            tool="DRAW",
            mapping="AREA_PLANE",
            stroke_method="SPACE",
            falloff="SMOOTH",
            strength=0.65,
            size=84,
            spacing=17,
            texture_bias=-0.1,
            invert=False,
            use_pressure_size=True,
            use_pressure_strength=True,
            front_faces_only=True,
            accumulate=False,
            activate_after_import=False,
        ) == {"FINISHED"}
        item = addon.runtime.library().items()[0]
        addon.runtime.refresh_previews(force=True)
        preview_items = addon.runtime.preview_items()
        assert len(preview_items) == 1
        assert preview_items[0][0] == item["id"]
        assert item["id"] in addon.runtime._preview_collection
        panel_settings = bpy.context.window_manager.eka_create_brush
        panel_settings.search = "no matching brush"
        assert panel_settings.selected_brush == "__EMPTY__"
        panel_settings.search = "stone"
        assert panel_settings.selected_brush == item["id"]
        panel_settings.search = ""

        brush = addon.runtime.activate_brush(bpy.context, item)
        assert target.mode == "SCULPT"
        assert brush.texture is not None
        assert brush.texture.image is not None
        assert Path(bpy.path.abspath(brush.texture.image.filepath)).resolve() == addon.runtime.library().image_path(item)
        assert brush.use_fake_user
        assert brush.texture.use_fake_user
        assert brush.texture.image.use_fake_user
        assert abs(brush.strength - 0.65) < 1e-6
        assert brush.size == 84
        assert brush.spacing == 17
        assert brush.use_frontface is True
        assert brush.texture_slot.map_mode == "AREA_PLANE"
        if hasattr(bpy.context.tool_settings.sculpt, "brush"):
            assert bpy.context.tool_settings.sculpt.brush == brush
        assert addon.runtime.find_runtime_brush(item["id"]) == brush

        stored_path = addon.runtime.library().image_path(item)
        assert stored_path.is_file()
        assert stored_path.name == "Stone Pore.png"
        grayscale_path.unlink()
        assert stored_path.is_file()

        dropped_path = library_directory / "Fabric Weave.png"
        save_test_image(
            dropped_path,
            32,
            32,
            lambda x, y: (
                0.25 + (0.5 if (x // 4 + y // 4) % 2 else 0.0),
                0.25 + (0.5 if (x // 4 + y // 4) % 2 else 0.0),
                0.25 + (0.5 if (x // 4 + y // 4) % 2 else 0.0),
                1.0,
            ),
        )
        assert addon.runtime._watch_library() == addon.runtime.WATCH_INTERVAL_SECONDS
        dropped = next(
            entry for entry in addon.runtime.library().items() if entry["image"] == dropped_path.name
        )
        assert dropped["name"] == "Fabric Weave"
        assert dropped["id"] in {entry[0] for entry in addon.runtime.preview_items()}
        dropped_brush = addon.runtime.activate_brush(bpy.context, dropped)
        assert addon.runtime.find_runtime_brush(dropped["id"]) == dropped_brush

        renamed_path = dropped_path.with_name("Fabric Grid.png")
        dropped_path.rename(renamed_path)
        addon.runtime._watch_library()
        renamed = addon.runtime.library().get(dropped["id"])
        assert renamed is not None
        assert renamed["image"] == renamed_path.name
        assert renamed["name"] == "Fabric Grid"

        invalid_path = library_directory / "Invalid Color.png"
        shutil.copy2(color_path, invalid_path)
        addon.runtime._watch_library()
        assert any("Invalid Color.png" in warning for warning in addon.runtime.library_warnings())
        assert all(entry["image"] != invalid_path.name for entry in addon.runtime.library().items())
        invalid_path.unlink()
        addon.runtime._watch_library()

        renamed_path.unlink()
        addon.runtime._watch_library()
        assert addon.runtime.library().get(dropped["id"]) is None
        assert addon.runtime.find_runtime_brush(dropped["id"]) is None

        updated = addon.runtime.library().update(
            item["id"],
            name="Stone Pore Fine",
            settings={**item["settings"], "size": 132, "invert": True},
        )
        updated_brush = addon.runtime.ensure_runtime_brush(updated)
        assert updated_brush == brush
        assert updated_brush.name.endswith("Stone Pore Fine")
        assert updated_brush.size == 132
        assert updated_brush.texture.use_color_ramp is True

        runtime_image = updated_brush.texture.image
        runtime_texture = updated_brush.texture
        runtime_image_name = runtime_image.name
        runtime_texture_name = runtime_texture.name
        addon.runtime.library().remove(item["id"])
        addon.runtime.remove_runtime_data(item["id"])
        assert addon.runtime.find_runtime_brush(item["id"]) is None
        assert runtime_texture_name not in bpy.data.textures
        assert runtime_image_name not in bpy.data.images
        assert not stored_path.exists()

        addon.unregister()
        assert not hasattr(bpy.types.WindowManager, "eka_create_brush")
        print(
            "EKA_CREATE_BRUSH_SMOKE_TEST_PASS "
            f"blender={bpy.app.version_string} preview_loaded=True folder_sync=True"
        )
    finally:
        os.environ.pop("EKA_CREATE_BRUSH_LIBRARY", None)
        shutil.rmtree(temporary_directory, ignore_errors=True)


if __name__ == "__main__":
    main()