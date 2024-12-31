#!/usr/bin/env python3
import os
import sys
import shutil
import json
import re
from datetime import datetime
from PIL import Image, ExifTags

# If you have pillow-heif installed, we'll try registering it for .heic
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass


def debug_print(msg):
    """Simple helper for debug output."""
    print("[DEBUG]", msg)


def is_reasonable_year(year, min_year=2000, max_year=2100):
    """Check if a year is within a reasonable range."""
    return min_year <= year <= max_year


def get_exif_datetime(original_file):
    """Extract DateTimeOriginal from EXIF, if available."""
    try:
        with Image.open(original_file) as img:
            exif_data = img.getexif()
            if not exif_data:
                debug_print(f"No EXIF for {original_file}")
                return None

            for tag_id, value in exif_data.items():
                tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                if tag_name in ("DateTimeOriginal", "DateTime"):
                    # Typically "YYYY:MM:DD HH:MM:SS"
                    try:
                        dt_obj = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        # Quick sanity check on year
                        if is_reasonable_year(dt_obj.year):
                            debug_print(f"EXIF date => {dt_obj} for {original_file}")
                            return dt_obj
                        else:
                            debug_print(f"EXIF year out of range ({dt_obj.year}) in {original_file}")
                            return None
                    except ValueError:
                        debug_print(f"Bad EXIF format '{value}' in {original_file}")
                        return None
    except Exception as e:
        debug_print(f"Failed reading EXIF from {original_file}: {e}")
    return None


def find_companion_json(media_path):
    """
    Look for sidecar JSON that Google Takeout usually provides.
    For example: "IMG_20200101.jpg.json" next to "IMG_20200101.jpg".
    """
    base, _ = os.path.splitext(media_path)
    directory = os.path.dirname(media_path)
    filename_no_ext = os.path.basename(base)

    # 1) The simplest guess: same exact name with .json appended
    guess_1 = media_path + ".json"
    if os.path.isfile(guess_1):
        return guess_1

    # 2) Or something like "IMG_20200101(1).jpg.json"
    for f in os.listdir(directory):
        if not f.lower().endswith(".json"):
            continue
        if f.startswith(filename_no_ext):
            candidate = os.path.join(directory, f)
            if os.path.isfile(candidate):
                return candidate
    return None


def parse_date_from_json(json_path):
    """
    Try reading 'photoTakenTime.timestamp', 'creationTime.timestamp',
    or 'videoCreationTime.timestamp' from Google Photos sidecar JSON.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            data = json.load(jf)

        # The typical structure might look like:
        # {
        #   "photoTakenTime": {"timestamp": "1583883667"},
        #   "creationTime": {"timestamp": "1609459200"},
        #   "videoCreationTime": {"timestamp": "1613500800"}
        # }
        for key in ("photoTakenTime", "creationTime", "videoCreationTime"):
            if key in data and "timestamp" in data[key]:
                ts_str = data[key]["timestamp"]
                dt_obj = datetime.fromtimestamp(int(ts_str))
                # Check year plausibility
                if is_reasonable_year(dt_obj.year):
                    debug_print(f"JSON date => {dt_obj} from {json_path} ({key})")
                    return dt_obj
                else:
                    debug_print(f"JSON year out of range ({dt_obj.year}) in {json_path}")
        debug_print(f"No recognized date in {json_path}")
    except Exception as e:
        debug_print(f"JSON parse error {json_path}: {e}")
    return None


def parse_date_from_filename(filename):
    """
    Attempt to parse a date from the filename itself, e.g.:
      - IMG_20190815_123456.jpg -> 2019-08-15
      - 2023-06-15-vacation.png -> 2023-06-15
      - 20211031_mycoolphoto.jpg -> 2021-10-31
      - DSC_2020_07_04.mp4 -> 2020-07-04
    Return a datetime if found and plausible, else None.
    """
    name = filename.lower()

    # We'll define a few patterns to attempt:
    # 1)  YYYY[-_]?MM[-_]?DD  (like 2023-01-31, 20230131, 2023_01_31)
    # This will match 4 digits for year, 2 for month, 2 for day.
    patterns = [
        r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})',
    ]

    for pat in patterns:
        match = re.search(pat, name)
        if match:
            year_str, month_str, day_str = match.groups()
            try:
                year = int(year_str)
                month = int(month_str)
                day = int(day_str)
                if is_reasonable_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
                    dt = datetime(year, month, day)
                    debug_print(f"Filename => {dt} from '{filename}'")
                    return dt
            except ValueError:
                pass

    debug_print(f"No date in filename '{filename}'")
    return None


def parse_date_from_directory(root_path):
    """
    Attempt to parse a date from the *directory name* if all else fails.
    Example path:
      /Users/daniel/Downloads/takeout/Takeout 34/Google Photos/Film 9-12-2022
    We'll look at each folder name (from deepest to top) for a pattern like "9-12-2022".
    We assume month-day-year if it looks like that.
    Return a datetime object if found, else None.
    """
    # We'll split the path into components
    parts = root_path.split(os.sep)
    # We'll go from the end backwards, searching for something like
    #  \d{1,2}[-_]\d{1,2}[-_]\d{4} (then interpret as mm-dd-yyyy)
    pattern = re.compile(r'(\d{1,2})[-_](\d{1,2})[-_](\d{4})')

    for part in reversed(parts):
        match = pattern.search(part)
        if match:
            mm_str, dd_str, yyyy_str = match.groups()
            try:
                month = int(mm_str)
                day = int(dd_str)
                year = int(yyyy_str)
                if is_reasonable_year(year) and 1 <= month <= 12 and 1 <= day <= 31:
                    dt = datetime(year, month, day)
                    debug_print(f"Directory => {dt} from '{part}'")
                    return dt
            except ValueError:
                pass
    debug_print(f"No date from directory path '{root_path}'")
    return None


def get_creation_datetime(file_path):
    """
    The main logic to get a "best guess" of creation date/time:
      1. EXIF metadata
      2. JSON sidecar
      3. Filename date (YYYYMMDD or YYYY-MM-DD, etc.)
      4. Directory name date (e.g., "Film 9-12-2022")
      5. File modification time
    """
    # 1) EXIF
    dt_exif = get_exif_datetime(file_path)
    if dt_exif:
        return dt_exif

    # 2) JSON
    json_path = find_companion_json(file_path)
    if json_path:
        dt_json = parse_date_from_json(json_path)
        if dt_json:
            return dt_json

    # 3) Filename-based
    filename_only = os.path.basename(file_path)
    dt_file = parse_date_from_filename(filename_only)
    if dt_file:
        return dt_file

    # 4) Directory name
    root_dir = os.path.dirname(file_path)
    dt_dir = parse_date_from_directory(root_dir)
    if dt_dir:
        return dt_dir

    # 5) Modification time
    mod_time = os.path.getmtime(file_path)
    dt_mod = datetime.fromtimestamp(mod_time)
    debug_print(f"Mod-time => {dt_mod} for {file_path}")
    return dt_mod


def is_media_file(filename):
    """Check if file is a recognized image or video."""
    ext = os.path.splitext(filename)[1].lower()
    media_extensions = [
        ".jpg", ".jpeg", ".png", ".gif", ".heic", ".heif",
        ".bmp", ".webp", ".tiff", ".tif",
        ".mp4", ".mov", ".m4v", ".avi", ".wmv", ".flv", ".mkv", ".webm"
    ]
    return ext in media_extensions


def convert_heic_to_jpg(source_path, dest_path):
    """Convert .heic/.heif to .jpg using Pillow."""
    with Image.open(source_path) as im:
        im = im.convert("RGB")
        im.save(dest_path, "JPEG", quality=90)
    debug_print(f"Converted HEIC -> JPG: {source_path} -> {dest_path}")


def copy_or_convert_file(source_path, dest_path):
    """
    If file is .heic, convert to .jpg. Otherwise, copy.
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


def main(input_root, output_root, test_mode=False):
    if not os.path.exists(output_root):
        os.makedirs(output_root)

    processed_count = 0
    MAX_TEST_COUNT = 100

    for root, dirs, files in os.walk(input_root):
        # Focus on folders that contain "Google Photos"
        if "Google Photos" not in root:
            continue

        for filename in files:
            # Skip JSON itself (we only read them for data, no copying)
            if filename.lower().endswith(".json"):
                continue

            # Only process recognized media
            if not is_media_file(filename):
                continue

            # Test mode limit
            if test_mode and processed_count >= MAX_TEST_COUNT:
                print(f"\nReached {MAX_TEST_COUNT} files in test mode; stopping.\n")
                return

            source_path = os.path.join(root, filename)
            creation_dt = get_creation_datetime(source_path)
            year = creation_dt.year

            # If year is out of range, clamp to 2000 or something
            if not is_reasonable_year(year):
                debug_print(f"Year {year} out of range; using 2000 for {source_path}")
                year = 2000

            dest_folder = os.path.join(output_root, str(year))
            os.makedirs(dest_folder, exist_ok=True)
            dest_path = os.path.join(dest_folder, filename)

            copy_or_convert_file(source_path, dest_path)
            processed_count += 1
            print(f"[INFO] => {year}: {source_path}")

    if test_mode:
        print(f"\nTest mode finished. Processed {processed_count} files (limit={MAX_TEST_COUNT}).")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Organize Google Takeout media by year with multiple fallback steps, including directory name."
    )
    parser.add_argument("input_root", help="Folder containing all 'Takeout N' subdirs.")
    parser.add_argument("output_root", help="Where to store year-based folders.")
    parser.add_argument("--test", action="store_true", help="Process only up to 100 items.")
    args = parser.parse_args()

    if not os.path.isdir(args.input_root):
        print(f"Error: {args.input_root} is not a directory.")
        sys.exit(1)

    main(args.input_root, args.output_root, test_mode=args.test)
