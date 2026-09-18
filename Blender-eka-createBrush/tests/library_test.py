from pathlib import Path
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "eka_create_brush"))

from library import BrushLibrary, BrushLibraryError, DEFAULT_SETTINGS, clean_name


def main():
    assert clean_name(" Stone/\\Pore ") == "Stone Pore"
    with tempfile.TemporaryDirectory(prefix="eka-create-brush-library-") as temporary_directory:
        root = Path(temporary_directory)
        source = root / "source.png"
        source.write_bytes(b"synthetic grayscale image")
        library = BrushLibrary(root / "library")

        first = library.add_image(
            source,
            "Stone Pore",
            {"width": 512, "height": 512, "dynamic_range": 0.82},
            {"strength": 0.7, "mapping": "AREA_PLANE"},
        )
        second = library.add_image(
            source,
            "Stone Pore",
            {"width": 512, "height": 512, "dynamic_range": 0.82},
        )

        assert first["name"] == "Stone Pore"
        assert second["name"] == "Stone Pore 2"
        assert library.image_path(first).read_bytes() == source.read_bytes()
        assert first["settings"]["strength"] == 0.7
        assert first["settings"]["spacing"] == DEFAULT_SETTINGS["spacing"]
        assert len(library.items()) == 2

        updated = library.update(
            first["id"],
            name="  Stone   Detail  ",
            settings={**first["settings"], "size": 140, "invert": True},
        )
        assert updated["name"] == "Stone Detail"
        assert updated["settings"]["size"] == 140
        assert updated["settings"]["invert"] is True

        removed = library.remove(second["id"])
        assert removed["id"] == second["id"]
        assert not library.image_path(second).exists()
        assert [item["id"] for item in library.items()] == [first["id"]]
        assert not list(library.root.glob("*.partial"))

        dropped_path = library.root / "Dropped Detail.png"
        dropped_path.write_bytes(b"externally added grayscale image")

        def inspect_image(path):
            if Path(path).name == "Invalid.png":
                raise ValueError("not grayscale")
            return {"width": 256, "height": 256, "dynamic_range": 0.9}

        synchronized = library.synchronize(inspect_image)
        dropped = next(item for item in synchronized["items"] if item["image"] == dropped_path.name)
        assert dropped["name"] == "Dropped Detail"
        assert dropped["id"] in synchronized["added_ids"]

        dropped_settings = {**dropped["settings"], "strength": 0.82}
        dropped = library.update(dropped["id"], settings=dropped_settings)
        renamed_path = dropped_path.with_name("Renamed Detail.png")
        dropped_path.rename(renamed_path)
        synchronized = library.synchronize(inspect_image)
        renamed = next(item for item in synchronized["items"] if item["image"] == renamed_path.name)
        assert renamed["id"] == dropped["id"]
        assert renamed["name"] == "Renamed Detail"
        assert renamed["settings"]["strength"] == 0.82

        renamed_path.unlink()
        synchronized = library.synchronize(inspect_image)
        assert dropped["id"] in synchronized["removed_ids"]
        assert library.get(dropped["id"]) is None

        invalid_path = library.root / "Invalid.png"
        invalid_path.write_bytes(b"colored image")
        synchronized = library.synchronize(inspect_image)
        assert synchronized["invalid"] == [{"image": "Invalid.png", "error": "not grayscale"}]
        assert all(item["image"] != invalid_path.name for item in library.items())

        bad_source = root / "source.txt"
        bad_source.write_text("not an image", encoding="utf-8")
        try:
            library.add_image(
                bad_source,
                "Bad",
                {"width": 32, "height": 32, "dynamic_range": 1.0},
            )
        except BrushLibraryError as error:
            assert "Unsupported image format" in str(error)
        else:
            raise AssertionError("Unsupported image format was accepted")

        print("EKA_CREATE_BRUSH_LIBRARY_TEST_PASS")


if __name__ == "__main__":
    main()