#!/usr/bin/env python3
"""
Organize Google Takeout Photos/Videos by year, with robust fallback logic:
1. Files containing "snapchat" in their name => 'Snapchat/' folder (no date parsing).
2. Other files: Use EXIF -> JSON -> filename -> directory -> mod-time to guess a year.
   If the year is outside [2000..current_year], place in 'Unknown/'.
   Otherwise, place in 'YYYY/' (e.g., '2021/').
3. .heic/.heif files are converted to .jpg; others are copied as-is.
4. Use '--test' to limit to 100 files and print debug logs.

Requires:
   pip install pillow pillow-heif  (optional but recommended for .heic support)
"""

import os
import sys
import shutil
import json
import re
from datetime import datetime, date
from PIL import Image, ExifTags

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def debug_print(msg: str) -> None:
    """Print debug messages (you can silence them in production if desired)."""
    print(f"[DEBUG] {msg}")


def current_year() -> int:
    """Return the current calendar year as an integer."""
    return date.today().year


def is_reasonable_year(year: int, min_year: int = 2000) -> bool:
    """
    Check if a 'year' is in the inclusive range [min_year..current_year].
    """
    return min_year <= year <= current_year()


def get_exif_datetime(path: str) -> datetime | None:
    """
    Attempt to read EXIF 'DateTimeOriginal' from an image.
    Return a datetime if found and the year is reasonable, else None.
    """
    try:
        with Image.open(path) as img:
            exif_data = img.getexif()
            if not exif_data:
                debug_print(f"No EXIF in {path}")
                return None

            for tag_id, value in exif_data.items():
                tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                if tag_name in ("DateTimeOriginal", "DateTime"):
                    # EXIF date is usually "YYYY:MM:DD HH:MM:SS"
                    try:
                        dt_obj = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        if is_reasonable_year(dt_obj.year):
                            debug_print(f"EXIF => {dt_obj} for {path}")
                            return dt_obj
                        else:
                            debug_print(f"EXIF year out of range ({dt_obj.year}) in {path}")
                            return None
                    except ValueError:
                        debug_print(f"Invalid EXIF date '{value}' in {path}")
                        return None
    except Exception as e:
        debug_print(f"Failed to read EXIF from {path}: {e}")
    return None


def find_companion_json(path: str) -> str | None:
    """
    Locate a Google Takeout sidecar JSON (e.g., 'IMG_1234.jpg.json') if it exists.
    Return the JSON path if found, else None.
    """
    base, _ = os.path.splitext(path)
    directory = os.path.dirname(path)
    filename_no_ext = os.path.basename(base)

    # 1) <filename>.<ext>.json
    guess = path + ".json"
    if os.path.isfile(guess):
        return guess

    # 2) <filename>(1).jpg.json or similar
    for fname in os.listdir(directory):
        if not fname.lower().endswith(".json"):
            continue
        if fname.startswith(filename_no_ext):
            candidate = os.path.join(directory, fname)
            if os.path.isfile(candidate):
                return candidate

    return None


def parse_date_from_json(json_path: str) -> datetime | None:
    """
    Check typical fields in Takeout JSON: photoTakenTime, creationTime, videoCreationTime.
    Return a datetime if valid & year in [2000..current_year], else None.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            data = json.load(jf)

        # e.g.,
        # {
        #   "photoTakenTime": {"timestamp": "1583883667"},
        #   "creationTime": {"timestamp": "1609459200"},
        #   "videoCreationTime": {"timestamp": "1613500800"}
        # }
        for key in ("photoTakenTime", "creationTime", "videoCreationTime"):
            if key in data and "timestamp" in data[key]:
                ts_str = data[key]["timestamp"]
                dt_obj = datetime.fromtimestamp(int(ts_str))
                if is_reasonable_year(dt_obj.year):
                    debug_print(f"JSON => {dt_obj} from {json_path} ({key})")
                    return dt_obj
                else:
                    debug_print(f"JSON year out of range ({dt_obj.year}) in {json_path}")
        debug_print(f"No recognized date in {json_path}")
    except Exception as e:
        debug_print(f"JSON parse error {json_path}: {e}")
    return None


def parse_epoch(epoch_str: str) -> datetime | None:
    """
    Try interpreting 'epoch_str' as 9, 10, or 13-digit Unix epoch time.
    Return a datetime if valid and year in [2000..current_year], else None.
    """
    if not epoch_str.isdigit():
        return None

    length = len(epoch_str)
    try:
        if length in (9, 10):
            # seconds
            epoch_val = int(epoch_str)
            dt_obj = datetime.utcfromtimestamp(epoch_val)
            if is_reasonable_year(dt_obj.year):
                debug_print(f"Parsed epoch (seconds) => {dt_obj}")
                return dt_obj
        elif length == 13:
            # milliseconds
            epoch_val = int(epoch_str)
            dt_obj = datetime.utcfromtimestamp(epoch_val / 1000.0)
            if is_reasonable_year(dt_obj.year):
                debug_print(f"Parsed epoch (ms) => {dt_obj}")
                return dt_obj
    except ValueError:
        pass

    return None


def parse_strict_filename_date(filename: str) -> datetime | None:
    """
    Strict pattern: YYYY[-_]MM[-_]DD
    Return a datetime if valid, else None.
    """
    name_lower = filename.lower()
    pattern = r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})'
    m = re.search(pattern, name_lower)
    if m:
        try:
            y_str, m_str, d_str = m.groups()
            year, month, day = int(y_str), int(m_str), int(d_str)
            if is_reasonable_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
                dt = datetime(year, month, day)
                debug_print(f"Filename strict => {dt} from '{filename}'")
                return dt
        except ValueError:
            pass
    return None


def parse_additional_filename_date(filename: str) -> datetime | None:
    """
    Patterns:
      1) 8-digit: YYYYMMDD => date
      2) 6-digit: YYYYMM => date with day=1
    """
    name_lower = filename.lower()

    # 8-digit (YYYYMMDD)
    match_8 = re.search(r'(20[0-9]{2})(0[1-9]|1[0-2])([0-3][0-9])', name_lower)
    if match_8:
        y_str, m_str, d_str = match_8.groups()
        try:
            year, month, day = int(y_str), int(m_str), int(d_str)
            if is_reasonable_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
                dt = datetime(year, month, day)
                debug_print(f"Filename 8-digit => {dt} from '{filename}'")
                return dt
        except ValueError:
            pass

    # 6-digit (YYYYMM => day=1)
    match_6 = re.search(r'(20[0-9]{2})(0[1-9]|1[0-2])', name_lower)
    if match_6:
        y_str, m_str = match_6.groups()
        try:
            year, month = int(y_str), int(m_str)
            if is_reasonable_year(year) and 1 <= month <= 12:
                dt = datetime(year, month, 1)
                debug_print(f"Filename 6-digit => {dt} from '{filename}'")
                return dt
        except ValueError:
            pass

    return None


def parse_all_digits_any_prefix(filename: str) -> datetime | None:
    """
    If a file is named 'IMG123456' or purely digits, attempt parse_epoch.
    Return None if no luck or out of range.
    """
    base_no_ext, _ = os.path.splitext(filename.lower())
    # Remove known prefixes
    known_prefixes = ["img", "img_", "image", "picture", "photo"]
    for p in known_prefixes:
        if base_no_ext.startswith(p):
            base_no_ext = base_no_ext[len(p):]

    if not base_no_ext.isdigit():
        return None

    dt_epoch = parse_epoch(base_no_ext)
    if dt_epoch:
        debug_print(f"All-digits => {dt_epoch} from '{filename}'")
        return dt_epoch

    return None


def parse_date_from_filename(filename: str) -> datetime | None:
    """
    Try filename-based strategies in order:
      1) Strict (YYYY-MM-DD)
      2) Additional (YYYYMMDD, etc.)
      3) All-digits fallback (epoch).
    Return None if nothing found.
    """
    dt_strict = parse_strict_filename_date(filename)
    if dt_strict:
        return dt_strict

    dt_extra = parse_additional_filename_date(filename)
    if dt_extra:
        return dt_extra

    dt_epoch = parse_all_digits_any_prefix(filename)
    if dt_epoch:
        return dt_epoch

    debug_print(f"No date from filename '{filename}'")
    return None


def parse_date_from_directory(dir_path: str) -> datetime | None:
    """
    Check if any parent folder has a pattern like mm[-_]dd[-_]yyyy.
    Return a datetime if valid, else None.
    """
    parts = dir_path.split(os.sep)
    pattern = re.compile(r'(\d{1,2})[-_](\d{1,2})[-_](\d{4})')
    for part in reversed(parts):
        match = pattern.search(part)
        if match:
            mm_str, dd_str, yyyy_str = match.groups()
            try:
                month, day, year = int(mm_str), int(dd_str), int(yyyy_str)
                if is_reasonable_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
                    dt = datetime(year, month, day)
                    debug_print(f"Directory => {dt} from '{part}'")
                    return dt
            except ValueError:
                pass

    debug_print(f"No date from directory path '{dir_path}'")
    return None


def get_creation_datetime(file_path: str) -> datetime:
    """
    Consolidate all fallback logic (EXIF -> JSON -> filename -> directory -> mod-time).
    Return the best guess or fallback to mod-time.
    """
    dt_exif = get_exif_datetime(file_path)
    if dt_exif:
        return dt_exif

    json_path = find_companion_json(file_path)
    if json_path:
        dt_json = parse_date_from_json(json_path)
        if dt_json:
            return dt_json

    filename_only = os.path.basename(file_path)
    dt_file = parse_date_from_filename(filename_only)
    if dt_file:
        return dt_file

    dir_dt = parse_date_from_directory(os.path.dirname(file_path))
    if dir_dt:
        return dir_dt

    # Fallback: modification time
    mod_time = os.path.getmtime(file_path)
    dt_mod = datetime.fromtimestamp(mod_time)
    debug_print(f"Mod-time => {dt_mod} for {file_path}")
    return dt_mod


def is_media_file(filename: str) -> bool:
    """
    Check if the file extension is a recognized image/video format.
    """
    ext = os.path.splitext(filename)[1].lower()
    media_extensions = [
        ".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif",
        ".bmp", ".webp", ".tiff", ".tif",
        ".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".mkv", ".webm"
    ]
    return ext in media_extensions


def convert_heic_to_jpg(source_path: str, dest_path: str) -> None:
    """
    Convert .heic/.heif to .jpg using Pillow.
    If pillow_heif is installed, it can open .heic. Otherwise, this may fail.
    """
    with Image.open(source_path) as im:
        im = im.convert("RGB")
        im.save(dest_path, "JPEG", quality=90)
    debug_print(f"Converted HEIC -> JPG: {source_path} -> {dest_path}")


def copy_or_convert_file(source_path: str, dest_path: str) -> None:
    """
    If the source is .heic/.heif, convert to .jpg. Otherwise, copy as-is.
    Skip if the destination already exists.
    """
    ext = os.path.splitext(source_path)[1].lower()
    if ext in (".heic", ".heif"):
        base_name = os.path.splitext(os.path.basename(dest_path))[0]
        new_dest_path = os.path.join(os.path.dirname(dest_path), base_name + ".jpg")
        if os.path.exists(new_dest_path):
            debug_print(f"Skipping existing {new_dest_path}")
            return
        try:
            convert_heic_to_jpg(source_path, new_dest_path)
        except Exception as e:
            debug_print(f"Error converting {source_path} => .jpg: {e}")
    else:
        if os.path.exists(dest_path):
            debug_print(f"Skipping existing {dest_path}")
            return
        shutil.copy2(source_path, dest_path)
        debug_print(f"Copied {source_path} -> {dest_path}")


def main(input_root: str, output_root: str, test_mode: bool = False) -> None:
    """
    1. Walk subfolders under 'input_root' that contain "Google Photos".
    2. If a filename contains 'snapchat', place in 'Snapchat/' ignoring date logic.
    3. Otherwise:
       - Derive a best-guess year from EXIF/JSON/filename/directory mod-time.
       - If out of [2000..current_year], place in 'Unknown/' folder.
       - Else place in 'YYYY/' folder.
    4. Convert .heic => .jpg, copy everything else.
    5. If test_mode=True, stop after 100 items and show debug logs.
    """
    if not os.path.exists(output_root):
        os.makedirs(output_root)

    processed_count = 0
    MAX_TEST_COUNT = 100

    for root, dirs, files in os.walk(input_root):
        # Only consider folders containing "Google Photos"
        if "Google Photos" not in root:
            continue

        for filename in files:
            # Skip .json sidecar files themselves
            if filename.lower().endswith(".json"):
                continue

            # Only process recognized media
            if not is_media_file(filename):
                continue

            if test_mode and processed_count >= MAX_TEST_COUNT:
                print(f"\nReached {MAX_TEST_COUNT} files in test mode; stopping.\n")
                return

            source_path = os.path.join(root, filename)
            filename_lower = filename.lower()

            # If 'snapchat' is anywhere in the name, place in 'Snapchat/'
            if "snapchat" in filename_lower:
                folder_name = "Snapchat"
            else:
                # Normal date logic
                dt_estimated = get_creation_datetime(source_path)
                year = dt_estimated.year
                if not is_reasonable_year(year):
                    folder_name = "Unknown"
                    debug_print(f"Year {year} out of range => 'Unknown' for {source_path}")
                else:
                    folder_name = str(year)

            dest_folder = os.path.join(output_root, folder_name)
            os.makedirs(dest_folder, exist_ok=True)

            dest_path = os.path.join(dest_folder, filename)
            copy_or_convert_file(source_path, dest_path)

            processed_count += 1
            print(f"[INFO] => {folder_name}: {source_path}")

    if test_mode:
        print(f"\nTest mode finished. Processed {processed_count} files (limit={MAX_TEST_COUNT}).")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Organize Google Takeout media by best guess year "
            "(EXIF/JSON/filename/etc.). "
            "Any file containing 'snapchat' => 'Snapchat/' folder. "
            "Others out-of-range => 'Unknown/'."
        )
    )
    parser.add_argument("input_root", help="Top-level folder with 'Takeout N' subfolders.")
    parser.add_argument("output_root", help="Where to place the organized results.")
    parser.add_argument("--test", action="store_true", help="Process only 100 files, for safety.")
    args = parser.parse_args()

    if not os.path.isdir(args.input_root):
        print(f"Error: {args.input_root} is not a valid directory.")
        sys.exit(1)

    main(args.input_root, args.output_root, test_mode=args.test)
