# Google Photos Takeout Sorter
#### By: [Daniel Nazarian](https://www.danielnazarian.com) 🐧👹
##### Contact me at <dnaz@danielnazarian.com>

-------------------------------------------------------

## Description

This project contains a Python script for organizing Google Takeout media exports. It sorts photos and videos by year, handles `.heic` files by converting them to `.jpg`, and includes special logic for Snapchat files and out-of-range dates.

### Key Features:
1. **Sorts by Year**: Places media into folders named after the year it was taken, based on EXIF metadata, JSON sidecar files, filename patterns, directory names, or file modification time.
2. **Snapchat Handling**: Any file with "snapchat" in its name is automatically placed in a `Snapchat/` folder, bypassing date parsing.
3. **Unknown Folder**: Files with no valid year (outside 2000–current year) are placed in an `Unknown/` folder.
4. **HEIC Conversion**: Converts `.heic/.heif` files to `.jpg` using `Pillow` and `pillow-heif`.
5. **Test Mode**: A `--test` flag allows you to process only 100 files at a time, ensuring safety and correctness.

-------------------------------------------------------

## Installation

1. Clone the repository:

 ```bash
 git clone https://github.com/your-repo-name/GoogleTakeout_Organizer.git
 cd GoogleTakeout_Organizer
 ```
   
### Install required dependencies:

```
pip install pillow pillow-heif
```

Note: If pillow-heif is unavailable on your platform, you can still run the script, but .heic files will not be converted.

### Usage

Run the script to organize your Google Takeout media:

python organize_takeout.py /path/to/Takeout /path/to/Output

### Example

If your Google Takeout is stored in /Users/username/Downloads/Takeout, and you want the organized media in /Users/username/MediaOrganized, run:

python organize_takeout.py /Users/username/Downloads/Takeout /Users/username/MediaOrganized

The script will:

 - Sort photos/videos into folders like 2020/, 2021/, etc.
 - Place files with "snapchat" in the name into Snapchat/.
 - Place files with no valid year into Unknown/.

#### Test Mode

To process only 100 files and review debug output:

python organize_takeout.py /path/to/Takeout /path/to/Output --test

Requirements

- Python 3.8+
- pip install pillow pillow-heif (optional but recommended for .heic support)

---

[https://danielnazarian.com](https://www.danielnazarian.com)
Copyright 2024 © Daniel Nazarian.
