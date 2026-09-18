from pathlib import Path
from zipfile import ZipFile
import ast
import hashlib
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORY = PROJECT_ROOT / "eka_create_brush"
ARCHIVE_PATH = PROJECT_ROOT / "dist" / "eka-createBrush-1.1.0.zip"
EXPECTED_FILES = {
    "__init__.py",
    "blender_manifest.toml",
    "library.py",
    "runtime.py",
}


def main():
    assert ARCHIVE_PATH.is_file(), ARCHIVE_PATH
    with ZipFile(ARCHIVE_PATH) as archive:
        names = {name.replace("\\", "/") for name in archive.namelist() if not name.endswith("/")}
        assert names == EXPECTED_FILES, names
        for name in EXPECTED_FILES:
            assert archive.read(name) == (SOURCE_DIRECTORY / name).read_bytes(), name
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode("utf-8"))
        ast.parse(archive.read("__init__.py").decode("utf-8"))
        ast.parse(archive.read("library.py").decode("utf-8"))
        ast.parse(archive.read("runtime.py").decode("utf-8"))

    assert manifest["id"] == "eka_create_brush"
    assert manifest["name"] == "eka-createBrush"
    assert manifest["version"] == "1.1.0"
    assert manifest["blender_version_min"] == "4.2.0"
    assert "files" in manifest["permissions"]
    assert set(manifest["build"]["paths"]) == EXPECTED_FILES - {"blender_manifest.toml"}
    print("EKA_CREATE_BRUSH_PACKAGE_TEST_PASS")
    print(f"SHA256={hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()