import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithm import PhotosToGeoJsonAlgorithm

ALGORITHM_ID = 'photogeojson:photostogeojson'
ICON_PATH = os.path.join(os.path.dirname(__file__), 'icon.png')


class PhotosProvider(QgsProcessingProvider):
    def id(self):
        return 'photogeojson'

    def name(self):
        return 'Photos to GeoJSON'

    def icon(self):
        return QIcon(ICON_PATH)

    def defaultVectorFileExtension(self, hasGeometry=True):
        return 'geojson'

    def loadAlgorithms(self):
        self.addAlgorithm(PhotosToGeoJsonAlgorithm())
