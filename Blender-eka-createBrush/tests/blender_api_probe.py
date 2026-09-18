import bpy


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    print(f"BLENDER_VERSION={bpy.app.version_string}")
    print(f"HAS_BRUSH_ASSET_ACTIVATE={hasattr(bpy.ops.brush, 'asset_activate')}")

    try:
        brush = bpy.data.brushes.new("eka-createBrush API Probe", mode="SCULPT")
    except TypeError as error:
        print(f"BRUSH_CREATE_ERROR={error}")
        return

    texture = bpy.data.textures.new("eka-createBrush API Probe", type="IMAGE")
    brush.texture = texture
    print(f"BRUSH_CREATE=OK texture={brush.texture == texture}")
    print(f"BRUSH_HAS_ASSET_DATA={hasattr(brush, 'asset_data')}")
    print(f"BRUSH_HAS_STRENGTH={hasattr(brush, 'strength')}")
    print(f"BRUSH_HAS_TEXTURE_SLOT={hasattr(brush, 'texture_slot')}")

    sculpt = bpy.context.tool_settings.sculpt
    try:
        sculpt.brush = brush
        print(f"SCULPT_BRUSH_ASSIGN={sculpt.brush == brush}")
    except (AttributeError, RuntimeError, TypeError) as error:
        print(f"SCULPT_BRUSH_ASSIGN_ERROR={type(error).__name__}: {error}")


if __name__ == "__main__":
    main()