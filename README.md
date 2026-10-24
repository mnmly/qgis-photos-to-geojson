# Photos to GeoJSON (QGIS plugin)

Turn a folder of geotagged photos into a time-enabled GeoJSON layer, plus an
optional track that draws itself as you scrub the Temporal Controller.

Uses QGIS's built-in EXIF reader, so there are no extra dependencies.
Requires QGIS 3.38 or newer (tested on QGIS 4.0).

## Usage

**Vector → Photos to GeoJSON → Import Geotagged Photos to GeoJSON…** (also in the
Processing Toolbox, so it works in batch mode and the model builder).

| Parameter | Default | |
|---|---|---|
| Photo folder | | Folder to scan |
| Scan subfolders | on | |
| File extensions | `jpg,jpeg,tif,tiff,heic,heif,png,dng,webp` | |
| Max time gap | 2 hours | Photos further apart start a new `trip_id` and are not joined (0 = no limit) |
| Photos | `<folder>/<folder name>.geojson` | Used when left as a temporary layer |
| Track | `<folder>/<folder name>_track.geojson` | Choose **Skip Output** to omit |

Existing files with those names are overwritten. Photos without GPS tags are
skipped and listed in the log.

### Photo points (`Point`, EPSG:4326)

`seq`, `filename`, `path`, `datetime` (camera clock, DateTimeOriginal),
`utc_offset`, `datetime_utc` (from OffsetTimeOriginal, else the GPS time stamp),
`epoch_ms`, `longitude`, `latitude`, `altitude`, `direction`, `make`, `model`,
`lens`, `focal_length`, `f_number`, `exposure_time`, `iso`, `width`, `height`,
`orientation`.

Loaded with the Temporal Controller enabled on `datetime`, and with the photo
shown in the identify / attribute form.

### Track (`LineString`, EPSG:4326)

One segment per pair of consecutive timestamped photos: `trip_id`, `from_seq`,
`to_seq`, `start_time`, `end_time`, `duration_s`, `distance_m` (ellipsoidal),
`speed_kmh`. Loaded with the Temporal Controller set to accumulate, so the
trace grows over time.

## Notes

- Shared or exported photos often have their location stripped (e.g. iOS
  share sheet with *Location* off, messaging apps). Those are skipped.
- `datetime` is the camera's wall-clock time; mixing cameras set to different
  time zones can reorder photos. `datetime_utc` is consistent when available.

## Install

### From this repository (recommended)

1. **Plugins → Manage and Install Plugins → Settings**, then click **Add…**
2. Enter any name and this URL, then click **OK**:
   ```
   https://raw.githubusercontent.com/mnmly/qgis-photos-to-geojson/main/plugins.xml
   ```
3. Go to **All**, search for *Photos to GeoJSON* and click **Install**.

QGIS downloads the zip itself, so browser quirks don't matter, and it will
notify you of new versions.

### Other ways

- From a release: download `photo_geojson-<version>.zip` and use
  **Install from ZIP**. In Safari, turn off *Open safe files after downloading*
  first: Safari unzips the file, and re-zipping it in Finder adds a `__MACOSX`
  folder that QGIS cannot install.
- From source: `./build.sh` builds the same zip from the committed files and
  regenerates `plugins.xml`.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
