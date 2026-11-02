"""Offline validation, SemVer version updates and an allowlisted HACS release ZIP."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/orvibo_mixpad"
SEMVER = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
FILES = {"__init__.py", "cloud.py", "config_flow.py", "const.py", "diagnostics.py",
         "discovery.py", "light.py", "local.py", "manifest.json", "models.py",
         "protocol.py", "runtime.py", "strings.json", "transport.py", "translations/en.json",
         "brand/icon.png", "brand/icon@2x.png", "LICENSE", "THIRD_PARTY_NOTICES.md"}


def validate(tag=None):
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    assert re.fullmatch(SEMVER, version), "Version must be x.y.z"
    if tag:
        assert tag == f"v{version}", "Tag and manifest versions differ"
    for path in ROOT.rglob("*.py"):
        if any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(ROOT).parts):
            continue
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        assert (COMPONENT / name).read_bytes() == (ROOT / name).read_bytes(), "License copies must match"
    assert strings == json.loads((COMPONENT / "translations/en.json").read_text(encoding="utf-8"))
    assert set(p.relative_to(COMPONENT).as_posix() for p in COMPONENT.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts) == FILES, "Unexpected/missing integration files"
    print(f"Validated {version}: syntax, metadata, translations and package allowlist")
    return version


def package(tag=None):
    version = validate(tag)
    target = ROOT / "dist"
    target.mkdir(exist_ok=True)
    archive = target / "orvibo_mixpad.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name in sorted(FILES):
            # Fixed timestamps make repeat builds reproducible.
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            output.writestr(info, (COMPONENT / name).read_bytes())
    with zipfile.ZipFile(archive) as check:
        assert set(check.namelist()) == FILES
        assert check.testzip() is None
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (target / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Built {version}: {archive.name}")


def icon(size):
    """Original geometric panel illustration; no vendor or HA logo."""
    rows = bytearray()
    scale = size / 256
    for y in range(size):
        rows.append(0)
        for x in range(size):
            px, py = x / scale, y / scale
            color = (0, 0, 0, 0)
            if 32 <= px < 224 and 16 <= py < 240:
                color = (29, 43, 56, 255)
            if 48 <= px < 208 and 32 <= py < 144:
                color = (24, 154, 171, 255)
            if 64 <= px < 120 and 166 <= py < 218:
                color = (249, 204, 90, 255)
            if 136 <= px < 192 and 166 <= py < 218:
                color = (221, 229, 235, 255)
            rows.extend(color)
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    return image + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "package", "version", "icons"))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    if args.action == "version":
        if not args.value or not re.fullmatch(SEMVER, args.value):
            parser.error("version requires x.y.z without leading zeros")
        path = COMPONENT / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = args.value
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        validate()
    elif args.action == "icons":
        target = COMPONENT / "brand"
        target.mkdir(exist_ok=True)
        for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
            (target / name).write_bytes(icon(size))
    elif args.action == "package":
        package(args.value)
    else:
        validate(args.value)
