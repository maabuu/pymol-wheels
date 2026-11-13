#!/usr/bin/env python3
"""Rename the distribution of a wheel and set its version, or check a wheel's layout.

    rename_wheel.py rename dist/pymol-*.whl --name pymol-open-source --version 3.2.0a0.post5859
    rename_wheel.py check wheelhouse/pymol_open_source-*.whl

A wheel states its distribution name and version in four places that have to
agree: its file name, its `.dist-info` directory, its `.data` directory (if it
has one) and the `Name` and `Version` fields of METADATA. `rename` rewrites all
four, and RECORD with them; `check` reports where they disagree.

Only the standard library is needed, so any of the build Pythons can run this.
"""

import argparse
import base64
import csv
import hashlib
import io
import os
import re
import sys
import zipfile
from pathlib import Path

# The install schemes that a `.data` directory may contain.
SCHEME_KEYS = ("purelib", "platlib", "headers", "scripts", "data")


class WheelError(Exception):
    pass


def escape_name(name: str) -> str:
    """Return the form of a distribution name that is used in file names."""
    return re.sub(r"[-_.]+", "_", name).lower()


def split_filename(wheel: Path) -> tuple[str, str, list[str]]:
    """Split a wheel's file name into distribution, version and the remaining tags."""
    parts = wheel.stem.split("-")
    if wheel.suffix != ".whl" or len(parts) not in (5, 6):
        raise WheelError(f"{wheel.name}: not a wheel file name")
    return parts[0], parts[1], parts[2:]


def top_level(names: list[str], suffix: str) -> list[str]:
    """Return the top-level directories of an archive whose names end in `suffix`."""
    directories = {name.split("/", 1)[0] for name in names if "/" in name}
    return sorted(directory for directory in directories if directory.endswith(suffix))


def header_end(metadata: bytes) -> int:
    # METADATA is a block of header fields, a blank line, and the description.
    match = re.search(rb"\r?\n\r?\n", metadata)
    return match.start() if match else len(metadata)


def field_pattern(field: str) -> bytes:
    return rb"(?mi)^" + field.encode() + rb":[ \t]*([^\r\n]*)"


def get_field(metadata: bytes, field: str) -> str:
    match = re.search(field_pattern(field), metadata[: header_end(metadata)])
    if not match:
        raise WheelError(f"METADATA has no {field} field")
    return match.group(1).decode("utf-8").strip()


def set_field(metadata: bytes, field: str, value: str) -> bytes:
    end = header_end(metadata)
    replacement = f"{field}: {value}".encode("utf-8")
    header, count = re.subn(field_pattern(field), lambda _: replacement, metadata[:end])
    if count != 1:
        raise WheelError(f"METADATA has {count} {field} fields, expected one")
    return header + metadata[end:]


def digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest())
    return "sha256=" + encoded.rstrip(b"=").decode("ascii")


def clone(info: zipfile.ZipInfo, name: str) -> zipfile.ZipInfo:
    """Return a new archive member with the time stamp and permissions of `info`."""
    member = zipfile.ZipInfo(name, date_time=info.date_time)
    member.compress_type = zipfile.ZIP_DEFLATED
    member.create_system = info.create_system
    member.external_attr = info.external_attr
    return member


def rename(wheel: Path, name: str | None, version: str | None, wheel_dir: Path) -> Path:
    """Write a copy of `wheel` with another distribution name and version."""
    tags = split_filename(wheel)[2]

    with zipfile.ZipFile(wheel) as source:
        infos = [info for info in source.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]

        dist_infos = top_level(names, ".dist-info")
        if len(dist_infos) != 1:
            raise WheelError(f"{wheel.name}: expected one .dist-info directory, found {dist_infos}")
        old_dist_info = dist_infos[0]
        old_data = old_dist_info[: -len(".dist-info")] + ".data"
        strays = [directory for directory in top_level(names, ".data") if directory != old_data]
        if strays:
            raise WheelError(f"{wheel.name}: unexpected data directories {strays}")

        metadata = source.read(f"{old_dist_info}/METADATA")
        name = name or get_field(metadata, "Name")
        version = version or get_field(metadata, "Version")
        if not re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?", name):
            raise WheelError(f"invalid distribution name {name!r}")
        if not re.fullmatch(r"[A-Za-z0-9.!+]+", version):
            raise WheelError(f"invalid version {version!r}")

        prefix = f"{escape_name(name)}-{version}"
        renamed = {old_dist_info: f"{prefix}.dist-info", old_data: f"{prefix}.data"}
        metadata_name = f"{prefix}.dist-info/METADATA"
        record_name = f"{prefix}.dist-info/RECORD"

        wheel_dir.mkdir(parents=True, exist_ok=True)
        target = wheel_dir / f"{prefix}-{'-'.join(tags)}.whl"
        partial = target.with_name(target.name + ".part")
        rows = []
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as output:
            for info in infos:
                top, slash, rest = info.filename.partition("/")
                member = renamed.get(top, top) + slash + rest
                if member in (record_name, record_name + ".jws", record_name + ".p7s"):
                    # RECORD is written anew below, which invalidates its signatures.
                    continue
                data = source.read(info)
                if member == metadata_name:
                    data = set_field(set_field(data, "Name", name), "Version", version)
                    record_info = clone(info, record_name)
                output.writestr(clone(info, member), data)
                rows.append((member, digest(data), len(data)))
            rows.append((record_name, "", ""))
            record = io.StringIO(newline="")
            csv.writer(record, lineterminator="\n").writerows(rows)
            output.writestr(record_info, record.getvalue().encode("utf-8"))

    os.replace(partial, target)
    return target


def check(wheel: Path, verify_record: bool = False) -> list[str]:
    """Return what is wrong with the layout of `wheel`; nothing, if all is well."""
    distribution, version, _ = split_filename(wheel)
    dist_info = f"{distribution}-{version}.dist-info"
    data_directory = f"{distribution}-{version}.data"
    problems = []

    with zipfile.ZipFile(wheel) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]

        found = top_level(names, ".dist-info")
        if found != [dist_info]:
            problems.append(f"expected the single metadata directory {dist_info!r}, found {found}")
        for directory in top_level(names, ".data"):
            if directory != data_directory:
                problems.append(f"data directory {directory!r} should be named {data_directory!r}")
        for name in names:
            parts = name.split("/")
            if parts[0] == data_directory and (len(parts) < 3 or parts[1] not in SCHEME_KEYS):
                problems.append(f"{name!r} is not below {data_directory}/<{'|'.join(SCHEME_KEYS)}>/")

        missing = [file for file in ("METADATA", "WHEEL", "RECORD") if f"{dist_info}/{file}" not in names]
        problems.extend(f"{dist_info}/{file} is missing" for file in missing)
        if "METADATA" not in missing:
            metadata = archive.read(f"{dist_info}/METADATA")
            if escape_name(get_field(metadata, "Name")) != escape_name(distribution):
                problems.append(f"METADATA names the distribution {get_field(metadata, 'Name')!r}")
            if get_field(metadata, "Version") != version:
                problems.append(f"METADATA gives the version {get_field(metadata, 'Version')!r}")

        if verify_record and "RECORD" not in missing:
            record_name = f"{dist_info}/RECORD"
            text = archive.read(record_name).decode("utf-8")
            listed = {row[0]: row[1:] for row in csv.reader(io.StringIO(text, newline="")) if row}
            for name in names:
                data = archive.read(name)
                expected = ["", ""] if name == record_name else [digest(data), str(len(data))]
                if listed.get(name) != expected:
                    problems.append(f"RECORD entry of {name!r} is {listed.get(name)}, expected {expected}")
            problems.extend(f"RECORD lists {name!r}, which is missing" for name in listed if name not in names)

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    rename_parser = commands.add_parser("rename", help="rename the distribution and set the version")
    rename_parser.add_argument("wheel", type=Path)
    rename_parser.add_argument("--name", help="new distribution name (default: unchanged)")
    rename_parser.add_argument("--version", help="new version (default: unchanged)")
    rename_parser.add_argument("--wheel-dir", type=Path, help="output directory (default: next to the wheel)")
    check_parser = commands.add_parser("check", help="check that name and version agree everywhere")
    check_parser.add_argument("wheels", type=Path, nargs="+")
    args = parser.parse_args()

    try:
        for wheel in [args.wheel] if args.command == "rename" else args.wheels:
            if not wheel.is_file():
                raise WheelError(f"{wheel}: no such file")
        if args.command == "rename":
            wheels = [rename(args.wheel, args.name, args.version, args.wheel_dir or args.wheel.parent)]
        else:
            wheels = args.wheels
        problems = [
            f"{wheel.name}: {problem}"
            for wheel in wheels
            for problem in check(wheel, verify_record=args.command == "rename")
        ]
    except (WheelError, OSError, KeyError, zipfile.BadZipFile) as error:
        problems = [str(error)]

    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    for wheel in wheels:
        print(f"{wheel}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
