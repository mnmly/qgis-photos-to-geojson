import os

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsEditorWidgetSetup,
    QgsExifTools,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputLayerDefinition,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsPointXY,
    QgsProperty,
)
from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType, QTime, QTimeZone
from qgis.PyQt.QtGui import QImageReader

DEFAULT_EXTENSIONS = 'jpg,jpeg,tif,tiff,heic,heif,png,dng,webp'
EXIF_DATETIME_FORMAT = 'yyyy:MM:dd HH:mm:ss'
UTC = QTimeZone(b'UTC')

# (name, type) — kept in one place so the schema and the feature values stay in sync.
FIELD_DEFS = [
    ('seq', QMetaType.Type.Int),
    ('filename', QMetaType.Type.QString),
    ('path', QMetaType.Type.QString),
    ('datetime', QMetaType.Type.QDateTime),      # camera wall-clock time (DateTimeOriginal)
    ('utc_offset', QMetaType.Type.QString),      # e.g. "+01:00", from OffsetTimeOriginal
    ('datetime_utc', QMetaType.Type.QDateTime),  # from offset, else from GPS time stamp
    ('epoch_ms', QMetaType.Type.LongLong),       # datetime_utc (or datetime) as ms since epoch
    ('longitude', QMetaType.Type.Double),
    ('latitude', QMetaType.Type.Double),
    ('altitude', QMetaType.Type.Double),
    ('direction', QMetaType.Type.Double),        # GPSImgDirection, degrees
    ('make', QMetaType.Type.QString),
    ('model', QMetaType.Type.QString),
    ('lens', QMetaType.Type.QString),
    ('focal_length', QMetaType.Type.Double),
    ('f_number', QMetaType.Type.Double),
    ('exposure_time', QMetaType.Type.Double),
    ('iso', QMetaType.Type.Int),
    ('width', QMetaType.Type.Int),
    ('height', QMetaType.Type.Int),
    ('orientation', QMetaType.Type.Int),
]

TRACK_FIELD_DEFS = [
    ('trip_id', QMetaType.Type.Int),             # increments whenever the time gap exceeds the limit
    ('from_seq', QMetaType.Type.Int),
    ('to_seq', QMetaType.Type.Int),
    ('start_time', QMetaType.Type.QDateTime),    # "datetime" of the first photo
    ('end_time', QMetaType.Type.QDateTime),      # "datetime" of the second photo
    ('duration_s', QMetaType.Type.Double),
    ('distance_m', QMetaType.Type.Double),
    ('speed_kmh', QMetaType.Type.Double),
]


def _make_fields(field_defs):
    fields = QgsFields()
    for name, field_type in field_defs:
        fields.append(QgsField(name, field_type))
    return fields


def _first(tags, *keys):
    for key in keys:
        value = tags.get(key)
        if value not in (None, ''):
            return value
    return None


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    try:
        return float(value)
    except (TypeError, ValueError):
        # Exiv2 can hand back rationals as "num/den" strings.
        if isinstance(value, str) and '/' in value:
            num, _, den = value.partition('/')
            try:
                return float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return None
        return None


def _to_int(value):
    number = _to_float(value)
    return int(number) if number is not None else None


def _to_str(value):
    return str(value).strip().strip('\x00') if value not in (None, '') else None


def _parse_datetime(value):
    """EXIF datetime → naive (wall-clock) QDateTime, or None."""
    if isinstance(value, QDateTime):
        dt = QDateTime(value.date(), value.time())
    elif isinstance(value, str):
        dt = QDateTime.fromString(value.strip()[:19], EXIF_DATETIME_FORMAT)
    else:
        return None
    return dt if dt.isValid() else None


def _parse_offset_seconds(offset):
    """'+01:00' → 3600, or None."""
    if not offset or len(offset) < 6 or offset[0] not in '+-':
        return None
    try:
        hours, minutes = int(offset[1:3]), int(offset[4:6])
    except ValueError:
        return None
    sign = -1 if offset[0] == '-' else 1
    return sign * (hours * 3600 + minutes * 60)


def _parse_gps_datetime(date_value, time_value):
    """GPSDateStamp + GPSTimeStamp (always UTC) → UTC QDateTime, or None."""
    if isinstance(date_value, QDate):
        date = date_value
    elif isinstance(date_value, str):
        date = QDate.fromString(date_value.strip()[:10], 'yyyy:MM:dd')
    else:
        return None

    if isinstance(time_value, QTime):
        time = time_value
    elif isinstance(time_value, str):
        time = QTime.fromString(time_value.strip()[:8], 'HH:mm:ss')
    elif isinstance(time_value, (list, tuple)) and len(time_value) == 3:
        h, m, s = (_to_float(v) or 0 for v in time_value)
        time = QTime(int(h), int(m), int(s))
    else:
        return None

    if not (date.isValid() and time.isValid()):
        return None
    return QDateTime(date, time, UTC)


class _PhotoLayerPostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Sets up the loaded photo points for the Temporal Controller and photo preview."""

    instance = None

    def postProcessLayer(self, layer, context, feedback):
        temporal = layer.temporalProperties()
        temporal.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
        temporal.setStartField('datetime')
        temporal.setIsActive(True)

        path_index = layer.fields().indexOf('path')
        if path_index >= 0:
            # DocumentViewer 1 = image: shows the photo in the identify/attribute form.
            layer.setEditorWidgetSetup(
                path_index,
                QgsEditorWidgetSetup('ExternalResource', {'DocumentViewer': 1, 'FileWidget': True}),
            )
        layer.setMapTipTemplate(
            '<img src="file://[% "path" %]" width="320"/><br/>'
            '<b>[% "filename" %]</b><br/>[% "datetime" %]'
        )

    @staticmethod
    def create():
        # Processing only keeps a raw pointer, so we must keep the Python object alive.
        _PhotoLayerPostProcessor.instance = _PhotoLayerPostProcessor()
        return _PhotoLayerPostProcessor.instance


class _TrackLayerPostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Makes the track grow over time: each segment appears at its end_time and stays."""

    instance = None

    def postProcessLayer(self, layer, context, feedback):
        temporal = layer.temporalProperties()
        temporal.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
        temporal.setStartField('end_time')
        temporal.setAccumulateFeatures(True)
        temporal.setIsActive(True)

    @staticmethod
    def create():
        _TrackLayerPostProcessor.instance = _TrackLayerPostProcessor()
        return _TrackLayerPostProcessor.instance


class PhotosToGeoJsonAlgorithm(QgsProcessingAlgorithm):
    FOLDER = 'FOLDER'
    RECURSIVE = 'RECURSIVE'
    EXTENSIONS = 'EXTENSIONS'
    MAX_GAP = 'MAX_GAP'
    OUTPUT = 'OUTPUT'
    TRACK = 'TRACK'

    def name(self):
        return 'photostogeojson'

    def displayName(self):
        return 'Import geotagged photos to GeoJSON'

    def shortHelpString(self):
        return (
            'Creates a point layer (EPSG:4326) from every photo in a folder that carries an '
            'EXIF GPS position. Features are sorted by capture time and numbered in "seq".\n\n'
            '"datetime" is the camera wall-clock time (DateTimeOriginal). "datetime_utc" is derived '
            'from OffsetTimeOriginal when present, otherwise from the GPS time stamp. When loaded, '
            'the layer is enabled for the Temporal Controller on "datetime".\n\n'
            'Photos without GPS tags are skipped and listed in the log.\n\n'
            'Track (skip it if not needed): one line segment between each pair of consecutive photos, with '
            'duration, distance and speed. Photos further apart in time than "Max time gap" '
            'start a new trip_id and are not connected (0 = always connect). Photos without a '
            'timestamp are left out. When loaded, the track grows with the Temporal Controller.\n\n'
            'Outputs left as temporary layers are saved inside the photo folder as '
            '"<folder name>.geojson" and "<folder name>_track.geojson" (overwriting existing files).'
        )

    def createInstance(self):
        return PhotosToGeoJsonAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.FOLDER, 'Photo folder', behavior=QgsProcessingParameterFile.Behavior.Folder))
        self.addParameter(QgsProcessingParameterBoolean(
            self.RECURSIVE, 'Scan subfolders', defaultValue=True))
        self.addParameter(QgsProcessingParameterString(
            self.EXTENSIONS, 'File extensions (comma separated)', defaultValue=DEFAULT_EXTENSIONS))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_GAP, 'Max time gap between connected photos (hours, 0 = no limit)',
            QgsProcessingParameterNumber.Type.Double, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Photos (temporary = save as <folder name>.geojson in the photo folder)',
            QgsProcessing.SourceType.TypeVectorPoint, defaultValue=QgsProcessing.TEMPORARY_OUTPUT))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.TRACK, 'Track (temporary = save as <folder name>_track.geojson in the photo folder)',
            QgsProcessing.SourceType.TypeVectorLine, optional=True, createByDefault=True,
            defaultValue=QgsProcessing.TEMPORARY_OUTPUT))

    def processAlgorithm(self, parameters, context, feedback):
        folder = self.parameterAsFile(parameters, self.FOLDER, context)
        recursive = self.parameterAsBoolean(parameters, self.RECURSIVE, context)
        extensions = {
            '.' + ext.strip().lower().lstrip('.')
            for ext in self.parameterAsString(parameters, self.EXTENSIONS, context).split(',')
            if ext.strip()
        }
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException(f'Not a folder: {folder}')

        paths = sorted(self._list_images(folder, recursive, extensions))
        feedback.pushInfo(f'Found {len(paths)} image file(s).')

        records, skipped = [], []
        for i, path in enumerate(paths):
            if feedback.isCanceled():
                break
            record = self._read_photo(path)
            if record is None:
                skipped.append(path)
            else:
                records.append(record)
            feedback.setProgress(100 * (i + 1) / max(len(paths), 1))

        # Sort chronologically; photos without any timestamp go last, by filename.
        records.sort(key=lambda r: (r['epoch_ms'] is None, r['epoch_ms'] or 0, r['filename']))

        fields = _make_fields(FIELD_DEFS)
        parameters = self._default_output_to_photo_folder(parameters, self.OUTPUT, folder, '.geojson')
        sink, dest_id = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            Qgis.WkbType.PointZ, QgsCoordinateReferenceSystem('EPSG:4326'))
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        for seq, record in enumerate(records):
            record['seq'] = seq
            feature = QgsFeature(fields)
            feature.setGeometry(QgsGeometry(record['geometry'].clone()))
            feature.setAttributes([record.get(name) for name, _ in FIELD_DEFS])
            sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)

        for path in skipped:
            feedback.pushWarning(f'No GPS position, skipped: {path}')
        feedback.pushInfo(f'Wrote {len(records)} photo(s), skipped {len(skipped)}.')

        if context.willLoadLayerOnCompletion(dest_id):
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(
                _PhotoLayerPostProcessor.create())

        results = {self.OUTPUT: dest_id}

        parameters = self._default_output_to_photo_folder(parameters, self.TRACK, folder, '_track.geojson')
        track_fields = _make_fields(TRACK_FIELD_DEFS)
        track_sink, track_id = self.parameterAsSink(
            parameters, self.TRACK, context, track_fields,
            Qgis.WkbType.LineString, QgsCoordinateReferenceSystem('EPSG:4326'))
        if track_sink is not None:
            max_gap_s = self.parameterAsDouble(parameters, self.MAX_GAP, context) * 3600
            segments = self._track_segments(records, max_gap_s, context)
            for attributes, geometry in segments:
                feature = QgsFeature(track_fields)
                feature.setGeometry(geometry)
                feature.setAttributes([attributes[name] for name, _ in TRACK_FIELD_DEFS])
                track_sink.addFeature(feature, QgsFeatureSink.Flag.FastInsert)
            feedback.pushInfo(f'Wrote {len(segments)} track segment(s).')
            if context.willLoadLayerOnCompletion(track_id):
                context.layerToLoadOnCompletionDetails(track_id).setPostProcessor(
                    _TrackLayerPostProcessor.create())
            results[self.TRACK] = track_id

        return results

    @staticmethod
    def _track_segments(records, max_gap_s, context):
        """Segments between consecutive timestamped photos → [(attributes, geometry)]."""
        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(QgsCoordinateReferenceSystem('EPSG:4326'), context.transformContext())
        distance_area.setEllipsoid('EPSG:7030')  # WGS 84

        timed = [r for r in records if r['epoch_ms'] is not None]
        segments, trip_id = [], 0
        for a, b in zip(timed, timed[1:]):
            duration_s = (b['epoch_ms'] - a['epoch_ms']) / 1000
            if max_gap_s > 0 and duration_s > max_gap_s:
                trip_id += 1
                continue
            line = [QgsPointXY(a['geometry'].x(), a['geometry'].y()),
                    QgsPointXY(b['geometry'].x(), b['geometry'].y())]
            distance_m = distance_area.measureLine(line)
            segments.append(({
                'trip_id': trip_id,
                'from_seq': a['seq'],
                'to_seq': b['seq'],
                'start_time': a['datetime'],
                'end_time': b['datetime'],
                'duration_s': duration_s,
                'distance_m': distance_m,
                'speed_kmh': distance_m / duration_s * 3.6 if duration_s > 0 else None,
            }, QgsGeometry.fromPolylineXY(line)))
        return segments

    def _default_output_to_photo_folder(self, parameters, name, folder, suffix):
        """Replace a temporary-layer output with <folder>/<folder name><suffix>."""
        output = parameters.get(name, self.parameterDefinition(name).defaultValue())
        if output in (None, ''):  # skipped optional output
            return parameters
        if isinstance(output, QgsProcessingOutputLayerDefinition):
            definition = QgsProcessingOutputLayerDefinition(output)
            sink = definition.sink.staticValue()
        else:
            definition = QgsProcessingOutputLayerDefinition(output)
            sink = output
        if sink != QgsProcessing.TEMPORARY_OUTPUT and not str(sink).startswith('memory:'):
            return parameters

        folder = os.path.normpath(folder)
        definition.sink = QgsProperty.fromValue(
            os.path.join(folder, os.path.basename(folder) + suffix))
        return {**parameters, name: definition}

    @staticmethod
    def _list_images(folder, recursive, extensions):
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for filename in files:
                if not filename.startswith('.') and os.path.splitext(filename)[1].lower() in extensions:
                    yield os.path.join(root, filename)
            if not recursive:
                break

    @staticmethod
    def _read_photo(path):
        point, ok = QgsExifTools.getGeoTag(path)
        if not ok:
            return None
        tags = QgsExifTools.readTags(path)

        local_dt = _parse_datetime(_first(
            tags, 'Exif.Photo.DateTimeOriginal', 'Exif.Photo.DateTimeDigitized', 'Exif.Image.DateTime'))
        offset = _to_str(_first(
            tags, 'Exif.Photo.OffsetTimeOriginal', 'Exif.Photo.OffsetTimeDigitized', 'Exif.Photo.OffsetTime'))
        offset_seconds = _parse_offset_seconds(offset)

        utc_dt = None
        if local_dt is not None and offset_seconds is not None:
            utc_dt = QDateTime(local_dt.date(), local_dt.time(), UTC).addSecs(-offset_seconds)
        if utc_dt is None:
            utc_dt = _parse_gps_datetime(
                tags.get('Exif.GPSInfo.GPSDateStamp'), tags.get('Exif.GPSInfo.GPSTimeStamp'))

        if utc_dt is not None:
            epoch_ms = utc_dt.toMSecsSinceEpoch()
        elif local_dt is not None:
            epoch_ms = QDateTime(local_dt.date(), local_dt.time(), UTC).toMSecsSinceEpoch()
        else:
            epoch_ms = None

        width = _to_int(_first(tags, 'Exif.Photo.PixelXDimension', 'Exif.Image.ImageWidth'))
        height = _to_int(_first(tags, 'Exif.Photo.PixelYDimension', 'Exif.Image.ImageLength'))
        if width is None or height is None:
            size = QImageReader(path).size()
            if size.isValid():
                width, height = size.width(), size.height()

        return {
            'geometry': point,
            'filename': os.path.basename(path),
            'path': os.path.abspath(path),
            'datetime': local_dt,
            'utc_offset': offset,
            'datetime_utc': utc_dt,
            'epoch_ms': epoch_ms,
            'longitude': point.x(),
            'latitude': point.y(),
            'altitude': point.z() if point.is3D() else None,
            'direction': _to_float(tags.get('Exif.GPSInfo.GPSImgDirection')),
            'make': _to_str(tags.get('Exif.Image.Make')),
            'model': _to_str(tags.get('Exif.Image.Model')),
            'lens': _to_str(_first(tags, 'Exif.Photo.LensModel', 'Exif.Photo.LensSpecification')),
            'focal_length': _to_float(tags.get('Exif.Photo.FocalLength')),
            'f_number': _to_float(tags.get('Exif.Photo.FNumber')),
            'exposure_time': _to_float(tags.get('Exif.Photo.ExposureTime')),
            'iso': _to_int(_first(tags, 'Exif.Photo.ISOSpeedRatings', 'Exif.Photo.PhotographicSensitivity')),
            'width': width,
            'height': height,
            'orientation': _to_int(tags.get('Exif.Image.Orientation')),
        }
