from qgis.core import QgsApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .provider import PhotosProvider, ALGORITHM_ID, ICON_PATH


class PhotosToGeoJsonPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None

    def initProcessing(self):
        self.provider = PhotosProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        self.action = QAction(
            QIcon(ICON_PATH),
            'Import Geotagged Photos to GeoJSON…',
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu('Photos to GeoJSON', self.action)
        self.iface.addVectorToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginVectorMenu('Photos to GeoJSON', self.action)
            self.iface.removeVectorToolBarIcon(self.action)
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    def run(self):
        import processing
        processing.execAlgorithmDialog(ALGORITHM_ID)
