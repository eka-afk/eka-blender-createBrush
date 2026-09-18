from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.props import PointerProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ImportHelper

from .library import BrushLibraryError
from . import runtime


TOOL_ITEMS = (
    ("DRAW", "Draw", "Displace the surface using the image height"),
    ("CLAY", "Clay", "Build material with a clay-like response"),
    ("CLAY_STRIPS", "Clay Strips", "Build faceted strips of material"),
    ("INFLATE", "Inflate", "Push vertices along their normals"),
    ("CREASE", "Crease", "Pinch while drawing a sharp groove"),
    ("SCRAPE", "Scrape", "Flatten high points against a plane"),
    ("FILL", "Fill", "Fill low points toward a plane"),
    ("SMOOTH", "Smooth", "Smooth the surface through the image mask"),
)

MAPPING_ITEMS = (
    ("AREA_PLANE", "Area Plane", "Project the texture along the local surface normal"),
    ("VIEW_PLANE", "View Plane", "Project the texture from the current view"),
    ("STENCIL", "Stencil", "Position and transform one stencil in the viewport"),
    ("TILED", "Tiled", "Repeat the image across the sculpted surface"),
    ("RANDOM", "Random", "Randomize the image placement for every dab"),
)

STROKE_ITEMS = (
    ("SPACE", "Space", "Apply repeated dabs along the stroke"),
    ("DOTS", "Dots", "Apply a dab for each pointer movement"),
    ("DRAG_DOT", "Drag Dot", "Position one image dab before applying it"),
    ("ANCHORED", "Anchored", "Drag from the center to size one anchored dab"),
)

FALLOFF_ITEMS = (
    ("SMOOTH", "Smooth", "Smooth radial fade at the brush edge"),
    ("SHARP", "Sharp", "Concentrate influence near the center"),
    ("ROUND", "Round", "Rounded radial influence"),
    ("LINE", "Linear", "Linear fade to the brush edge"),
    ("CONSTANT", "Constant", "Use the image without an extra radial fade"),
)


def _addon_preferences(context):
    addon = context.preferences.addons.get(__package__)
    if addon is None:
        addon = next(
            (
                entry
                for key, entry in context.preferences.addons.items()
                if key.endswith(".eka_create_brush")
            ),
            None,
        )
    return addon.preferences if addon is not None else None


def _repair_panel_selection(settings, items):
    visible_numbers = {item[4] for item in items}
    if settings.get("selected_brush") not in visible_numbers:
        settings.selected_brush = items[0][0] if items else "__EMPTY__"


def _library_directory_updated(preferences, context):
    runtime.set_library_directory(preferences.library_directory)
    items = runtime.refresh_previews(force=True)
    if context is not None and context.window_manager is not None:
        settings = getattr(context.window_manager, "eka_create_brush", None)
        if settings is not None:
            _repair_panel_selection(settings, items)
            settings.status = f"Watching folder: {runtime.library_root()}"


def _enum_brush_items(settings, _context):
    return runtime.preview_items(settings.search)


def _search_updated(settings, _context):
    visible_items = runtime.preview_items(settings.search)
    visible_numbers = {item[4] for item in visible_items}
    if settings.get("selected_brush") not in visible_numbers:
        settings.selected_brush = visible_items[0][0]


def _selected_item(settings):
    brush_id = settings.selected_brush
    if not brush_id or brush_id == "__EMPTY__":
        return None
    try:
        return runtime.library().get(brush_id)
    except BrushLibraryError:
        return None


def _selection_updated(settings, context):
    item = _selected_item(settings)
    if item is None or context is None:
        return
    target = context.object
    if target is None or target.type != "MESH" or target.mode != "SCULPT":
        settings.status = "Selected. Use Brush will enter Sculpt Mode."
        return
    try:
        runtime.activate_brush(context, item, enter_sculpt=False)
        settings.status = f"Active: {item['name']}"
    except runtime.BrushActivationError as error:
        settings.status = str(error)


class EKACREATEBRUSH_PG_settings(PropertyGroup):
    search: StringProperty(
        name="Search",
        description="Filter the brush library by name",
        update=_search_updated,
        options={"SKIP_SAVE"},
    )
    selected_brush: EnumProperty(
        name="Brush Library",
        description="Select a brush; selections activate immediately in Sculpt Mode",
        items=_enum_brush_items,
        update=_selection_updated,
        options={"SKIP_SAVE"},
    )
    status: StringProperty(options={"SKIP_SAVE"})


def _settings_dictionary(operator):
    return {
        "tool": operator.tool,
        "mapping": operator.mapping,
        "stroke_method": operator.stroke_method,
        "falloff": operator.falloff,
        "strength": operator.strength,
        "size": operator.size,
        "spacing": operator.spacing,
        "texture_bias": operator.texture_bias,
        "invert": operator.invert,
        "use_pressure_size": operator.use_pressure_size,
        "use_pressure_strength": operator.use_pressure_strength,
        "front_faces_only": operator.front_faces_only,
        "accumulate": operator.accumulate,
    }


def _load_operator_settings(operator, item):
    settings = item["settings"]
    operator.brush_name = item["name"]
    operator.tool = settings["tool"]
    operator.mapping = settings["mapping"]
    operator.stroke_method = settings["stroke_method"]
    operator.falloff = settings["falloff"]
    operator.strength = settings["strength"]
    operator.size = settings["size"]
    operator.spacing = settings["spacing"]
    operator.texture_bias = settings["texture_bias"]
    operator.invert = settings["invert"]
    operator.use_pressure_size = settings["use_pressure_size"]
    operator.use_pressure_strength = settings["use_pressure_strength"]
    operator.front_faces_only = settings["front_faces_only"]
    operator.accumulate = settings["accumulate"]


def _draw_operator_settings(layout, operator, *, show_name=True):
    layout.use_property_split = True
    layout.use_property_decorate = False
    if show_name:
        layout.prop(operator, "brush_name")

    sculpt_box = layout.box()
    sculpt_box.label(text="Sculpt Behavior", icon="SCULPTMODE_HLT")
    sculpt_box.prop(operator, "tool")
    sculpt_box.prop(operator, "strength")
    sculpt_box.prop(operator, "size")
    sculpt_box.prop(operator, "falloff")

    stamp_box = layout.box()
    stamp_box.label(text="Image Stamp", icon="TEXTURE")
    stamp_box.prop(operator, "mapping")
    stamp_box.prop(operator, "stroke_method")
    stamp_box.prop(operator, "spacing")
    stamp_box.prop(operator, "texture_bias")
    stamp_box.prop(operator, "invert")

    response_box = layout.box()
    response_box.label(text="Stroke Response", icon="STYLUS_PRESSURE")
    response_box.prop(operator, "use_pressure_size")
    response_box.prop(operator, "use_pressure_strength")
    response_box.prop(operator, "front_faces_only")
    response_box.prop(operator, "accumulate")


class EKACREATEBRUSH_OT_import(Operator, ImportHelper):
    bl_idname = "eka_create_brush.import_brush"
    bl_label = "Import Grayscale Brush"
    bl_description = "Create and store a Sculpt brush from a square grayscale image"
    bl_options = {"REGISTER"}

    filename_ext = ""
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp",
        options={"HIDDEN"},
    )
    brush_name: StringProperty(name="Brush Name", maxlen=80)
    tool: EnumProperty(name="Tool", items=TOOL_ITEMS, default="DRAW")
    mapping: EnumProperty(name="Mapping", items=MAPPING_ITEMS, default="AREA_PLANE")
    stroke_method: EnumProperty(name="Stroke", items=STROKE_ITEMS, default="SPACE")
    falloff: EnumProperty(name="Falloff", items=FALLOFF_ITEMS, default="SMOOTH")
    strength: FloatProperty(name="Strength", default=0.5, min=0.0, max=10.0)
    size: IntProperty(name="Size", default=75, min=1, max=5000, subtype="PIXEL")
    spacing: IntProperty(name="Spacing", default=12, min=1, max=1000, subtype="PERCENTAGE")
    texture_bias: FloatProperty(
        name="Height Bias",
        description="Shift image values before they affect the surface",
        default=0.0,
        min=-1.0,
        max=1.0,
    )
    invert: BoolProperty(name="Invert Image", default=False)
    use_pressure_size: BoolProperty(name="Pressure Size", default=True)
    use_pressure_strength: BoolProperty(name="Pressure Strength", default=True)
    front_faces_only: BoolProperty(name="Front Faces Only", default=False)
    accumulate: BoolProperty(name="Accumulate", default=False)
    activate_after_import: BoolProperty(
        name="Use After Import",
        description="Enter Sculpt Mode and activate the new brush when a mesh is selected",
        default=True,
    )

    def draw(self, _context):
        _draw_operator_settings(self.layout, self)
        self.layout.prop(self, "activate_after_import")

    def execute(self, context):
        try:
            image_info = runtime.analyze_brush_image(self.filepath)
            name = self.brush_name or Path(self.filepath).stem
            item = runtime.library().add_image(
                image_info["path"],
                name,
                image_info,
                _settings_dictionary(self),
            )
            runtime.refresh_previews(force=True)
            panel_settings = context.window_manager.eka_create_brush
            panel_settings.selected_brush = item["id"]
            panel_settings.status = f"Imported: {item['name']}"
        except (BrushLibraryError, runtime.BrushImageError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        activation_warning = ""
        if self.activate_after_import and context.object is not None and context.object.type == "MESH":
            try:
                runtime.activate_brush(context, item)
                panel_settings.status = f"Active: {item['name']}"
            except runtime.BrushActivationError as error:
                panel_settings.status = str(error)
                activation_warning = f"Brush imported, but not activated: {error}"

        if activation_warning:
            self.report({"WARNING"}, activation_warning)
        elif image_info["low_contrast"]:
            self.report({"WARNING"}, "Brush imported, but the image has very low tonal contrast")
        else:
            self.report({"INFO"}, f"Imported {item['name']}")
        return {"FINISHED"}


class EKACREATEBRUSH_OT_use(Operator):
    bl_idname = "eka_create_brush.use"
    bl_label = "Use Brush"
    bl_description = "Activate the selected brush and enter Sculpt Mode"
    bl_options = {"REGISTER"}

    brush_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        panel_settings = context.window_manager.eka_create_brush
        brush_id = self.brush_id or panel_settings.selected_brush
        try:
            item = runtime.library().get(brush_id)
            if item is None:
                raise runtime.BrushActivationError("Select a brush from the library")
            brush = runtime.activate_brush(context, item)
        except (BrushLibraryError, runtime.BrushActivationError) as error:
            panel_settings.status = str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        panel_settings.selected_brush = item["id"]
        panel_settings.status = f"Active: {item['name']}"
        self.report({"INFO"}, f"Using {brush.name}")
        return {"FINISHED"}


class EKACREATEBRUSH_OT_select(Operator):
    bl_idname = "eka_create_brush.select"
    bl_label = "Select Brush"
    bl_description = "Select this library brush and activate it when already in Sculpt Mode"

    brush_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        try:
            item = runtime.library().get(self.brush_id)
        except BrushLibraryError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if item is None or item.get("validation_error"):
            self.report({"ERROR"}, "This brush is no longer available in the watched folder")
            return {"CANCELLED"}
        context.window_manager.eka_create_brush.selected_brush = item["id"]
        return {"FINISHED"}


class EKACREATEBRUSH_OT_edit(Operator):
    bl_idname = "eka_create_brush.edit"
    bl_label = "Edit Brush"
    bl_description = "Rename the selected brush or change its persistent Sculpt settings"
    bl_options = {"REGISTER"}

    brush_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    brush_name: StringProperty(name="Brush Name", maxlen=80)
    tool: EnumProperty(name="Tool", items=TOOL_ITEMS, default="DRAW")
    mapping: EnumProperty(name="Mapping", items=MAPPING_ITEMS, default="AREA_PLANE")
    stroke_method: EnumProperty(name="Stroke", items=STROKE_ITEMS, default="SPACE")
    falloff: EnumProperty(name="Falloff", items=FALLOFF_ITEMS, default="SMOOTH")
    strength: FloatProperty(name="Strength", default=0.5, min=0.0, max=10.0)
    size: IntProperty(name="Size", default=75, min=1, max=5000, subtype="PIXEL")
    spacing: IntProperty(name="Spacing", default=12, min=1, max=1000, subtype="PERCENTAGE")
    texture_bias: FloatProperty(name="Height Bias", default=0.0, min=-1.0, max=1.0)
    invert: BoolProperty(name="Invert Image", default=False)
    use_pressure_size: BoolProperty(name="Pressure Size", default=True)
    use_pressure_strength: BoolProperty(name="Pressure Strength", default=True)
    front_faces_only: BoolProperty(name="Front Faces Only", default=False)
    accumulate: BoolProperty(name="Accumulate", default=False)

    def draw(self, _context):
        _draw_operator_settings(self.layout, self)

    def invoke(self, context, _event):
        panel_settings = context.window_manager.eka_create_brush
        self.brush_id = self.brush_id or panel_settings.selected_brush
        try:
            item = runtime.library().get(self.brush_id)
        except BrushLibraryError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        if item is None:
            self.report({"ERROR"}, "Select a brush from the library")
            return {"CANCELLED"}
        _load_operator_settings(self, item)
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        panel_settings = context.window_manager.eka_create_brush
        self.brush_id = self.brush_id or panel_settings.selected_brush
        try:
            item = runtime.library().update(
                self.brush_id,
                name=self.brush_name,
                settings=_settings_dictionary(self),
            )
            if runtime.find_runtime_brush(self.brush_id) is not None:
                runtime.ensure_runtime_brush(item)
            runtime.refresh_previews(force=True)
            panel_settings.selected_brush = item["id"]
        except (BrushLibraryError, runtime.BrushActivationError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        panel_settings.status = f"Updated: {item['name']}"
        self.report({"INFO"}, f"Updated {item['name']}")
        return {"FINISHED"}


class EKACREATEBRUSH_OT_delete(Operator):
    bl_idname = "eka_create_brush.delete"
    bl_label = "Delete Brush"
    bl_description = "Permanently remove the selected brush and its stored image"
    bl_options = {"REGISTER"}

    brush_id: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        panel_settings = context.window_manager.eka_create_brush
        brush_id = self.brush_id or panel_settings.selected_brush
        try:
            item = runtime.library().remove(brush_id)
            runtime.remove_runtime_data(brush_id)
            remaining = runtime.refresh_previews(force=True)
        except BrushLibraryError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        panel_settings.selected_brush = remaining[0][0] if remaining else "__EMPTY__"
        panel_settings.status = f"Deleted: {item['name']}"
        self.report({"INFO"}, f"Deleted {item['name']}")
        return {"FINISHED"}


class EKACREATEBRUSH_OT_refresh(Operator):
    bl_idname = "eka_create_brush.refresh"
    bl_label = "Refresh Brush Library"
    bl_description = "Reload brush metadata and image previews from disk"

    def execute(self, context):
        result = runtime.synchronize_library(force=True)
        items = runtime.refresh_previews(force=True, synchronize=False)
        panel_settings = context.window_manager.eka_create_brush
        _repair_panel_selection(panel_settings, items)
        panel_settings.status = f"Library refreshed: {len(items)} brush{'es' if len(items) != 1 else ''}"
        if result["invalid"]:
            panel_settings.status += f"; skipped {len(result['invalid'])} invalid image(s)"
        return {"FINISHED"}


class EKACREATEBRUSH_OT_open_library(Operator):
    bl_idname = "eka_create_brush.open_library"
    bl_label = "Open Brush Library Folder"
    bl_description = "Open the persistent folder containing brush images and metadata"

    def execute(self, _context):
        path = runtime.library().ensure()
        try:
            bpy.ops.wm.path_open(filepath=str(path))
        except RuntimeError as error:
            self.report({"ERROR"}, f"Could not open the library folder: {error}")
            return {"CANCELLED"}
        return {"FINISHED"}


class EKACREATEBRUSH_OT_choose_library(Operator):
    bl_idname = "eka_create_brush.choose_library"
    bl_label = "Choose Brush Folder"
    bl_description = "Choose the folder that eka-createBrush watches for grayscale images"

    directory: StringProperty(name="Brush Folder", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, _event):
        self.directory = str(runtime.library_root())
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = Path(bpy.path.abspath(self.directory)).expanduser()
        if not self.directory or not folder.is_dir():
            self.report({"ERROR"}, "Choose an existing folder")
            return {"CANCELLED"}
        preferences = _addon_preferences(context)
        if preferences is not None:
            preferences.library_directory = str(folder.resolve())
        else:
            runtime.set_library_directory(str(folder.resolve()))
            items = runtime.refresh_previews(force=True)
            _repair_panel_selection(context.window_manager.eka_create_brush, items)
        context.window_manager.eka_create_brush.status = f"Watching folder: {folder.resolve()}"
        return {"FINISHED"}


class EKACREATEBRUSH_PT_main(Panel):
    bl_label = "eka-createBrush"
    bl_idname = "EKACREATEBRUSH_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "eka-createBrush"

    def draw(self, context):
        layout = self.layout
        panel_settings = context.window_manager.eka_create_brush

        folder_box = layout.box()
        folder_header = folder_box.row(align=True)
        folder_header.label(text="Brush Folder", icon="FILE_FOLDER")
        folder_header.operator("eka_create_brush.choose_library", text="", icon="FILE_FOLDER")
        folder_header.operator("eka_create_brush.open_library", text="", icon="FILEBROWSER")
        preferences = _addon_preferences(context)
        if preferences is not None:
            folder_box.prop(preferences, "library_directory", text="")
        folder_box.label(text=str(runtime.library_root()))

        import_row = layout.row(align=True)
        import_row.scale_y = 1.25
        import_row.operator("eka_create_brush.import_brush", text="Import Brush", icon="IMPORT")
        import_row.operator("eka_create_brush.refresh", text="", icon="FILE_REFRESH")

        preview_entries = [
            item
            for item in runtime.preview_items(panel_settings.search)
            if item[0] != "__EMPTY__"
        ]
        error = runtime.library_error()
        if error:
            warning = layout.row()
            warning.alert = True
            warning.label(text=error, icon="ERROR")

        for message in runtime.library_warnings()[:3]:
            warning = layout.row()
            warning.alert = True
            warning.label(text=f"Skipped {message}", icon="ERROR")

        layout.prop(panel_settings, "search", text="", icon="VIEWZOOM")

        gallery_box = layout.box()
        gallery_header = gallery_box.row()
        gallery_header.label(
            text=f"Brush Library ({len(preview_entries)})",
            icon="ASSET_MANAGER",
        )
        if preview_entries:
            gallery = gallery_box.grid_flow(
                row_major=True,
                columns=2,
                even_columns=True,
                even_rows=False,
                align=True,
            )
            for brush_id, name, _description, icon_id, _number in preview_entries:
                tile = gallery.column(align=True)
                tile.template_icon(icon_value=icon_id, scale=4.0)
                operator = tile.operator(
                    "eka_create_brush.select",
                    text=name if len(name) <= 18 else f"{name[:17]}...",
                    depress=panel_settings.get("selected_brush") == _number,
                )
                operator.brush_id = brush_id
        else:
            empty_gallery = gallery_box.column(align=True)
            empty_gallery.enabled = False
            empty_gallery.label(
                text="No matching brushes" if panel_settings.search else "No brushes in this folder",
                icon="IMAGE_DATA",
            )
            empty_gallery.label(text="Import an image or add one in Explorer")

        item = _selected_item(panel_settings)
        if item is None:
            empty = layout.column(align=True)
            empty.enabled = False
            empty.label(text="Import a square grayscale image", icon="IMAGE_DATA")
            empty.label(text="PNG, JPEG, TIFF, or BMP")
        else:
            image_path = runtime.library().image_path(item)
            details = layout.box()
            details.label(text=item["name"], icon="BRUSH_DATA")
            details.label(text=f"{item['width']} x {item['height']}  |  {item['settings']['tool'].replace('_', ' ').title()}")
            if not image_path.is_file():
                missing = details.row()
                missing.alert = True
                missing.label(text="Stored image is missing", icon="ERROR")

            actions = layout.row(align=True)
            actions.scale_y = 1.25
            use = actions.row(align=True)
            use.enabled = image_path.is_file()
            use.operator("eka_create_brush.use", text="Use Brush", icon="SCULPTMODE_HLT").brush_id = item["id"]
            actions.operator("eka_create_brush.edit", text="", icon="PREFERENCES").brush_id = item["id"]
            actions.operator("eka_create_brush.delete", text="", icon="TRASH").brush_id = item["id"]

            active = runtime.find_runtime_brush(item["id"])
            sculpt_paint = getattr(context.tool_settings, "sculpt", None)
            if active is not None and sculpt_paint is not None and sculpt_paint.brush == active:
                active_row = layout.row()
                active_row.label(text="Active Sculpt brush", icon="CHECKMARK")

        if panel_settings.status:
            status_row = layout.row()
            status_row.label(text=panel_settings.status, icon="INFO")


class EKACREATEBRUSH_Preferences(AddonPreferences):
    bl_idname = __package__

    library_directory: StringProperty(
        name="Brush Folder",
        description="Folder watched for square grayscale brush images",
        subtype="DIR_PATH",
        update=_library_directory_updated,
    )

    def draw(self, _context):
        layout = self.layout
        layout.label(text="Watched Brush Folder")
        layout.prop(self, "library_directory", text="")
        row = layout.row(align=True)
        row.label(text=str(runtime.library_root()), icon="FILE_FOLDER")
        row.operator("eka_create_brush.open_library", text="Open")


CLASSES = (
    EKACREATEBRUSH_PG_settings,
    EKACREATEBRUSH_OT_import,
    EKACREATEBRUSH_OT_use,
    EKACREATEBRUSH_OT_select,
    EKACREATEBRUSH_OT_edit,
    EKACREATEBRUSH_OT_delete,
    EKACREATEBRUSH_OT_refresh,
    EKACREATEBRUSH_OT_open_library,
    EKACREATEBRUSH_OT_choose_library,
    EKACREATEBRUSH_PT_main,
    EKACREATEBRUSH_Preferences,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.eka_create_brush = PointerProperty(type=EKACREATEBRUSH_PG_settings)
    preferences = _addon_preferences(bpy.context)
    if preferences is not None and not preferences.library_directory:
        preferences.library_directory = str(runtime.default_library_root())
    else:
        runtime.set_library_directory(preferences.library_directory if preferences is not None else "")
    runtime.refresh_previews(force=True)
    runtime.start_library_watcher()


def unregister():
    runtime.stop_library_watcher()
    runtime.clear_previews()
    if hasattr(bpy.types.WindowManager, "eka_create_brush"):
        del bpy.types.WindowManager.eka_create_brush
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()