def classFactory(iface):
    from .plugin import PhotosToGeoJsonPlugin
    return PhotosToGeoJsonPlugin(iface)
