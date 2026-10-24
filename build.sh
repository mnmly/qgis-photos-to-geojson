#!/bin/sh
# Builds dist/photo_geojson-<version>.zip from the committed files (installable via "Install from ZIP"),
# and regenerates plugins.xml, the custom plugin repository pointing at the matching GitHub release asset.
set -e
cd "$(dirname "$0")"
meta() { sed -n "s/^$1=//p" metadata.txt; }
version=$(meta version)
repo=$(meta repository)
mkdir -p dist
git archive --format=zip --prefix=photo_geojson/ -o "dist/photo_geojson-$version.zip" HEAD \
  -- ':!.gitignore' ':!build.sh' ':!README.md' ':!plugins.xml'
echo "dist/photo_geojson-$version.zip"

# QGIS derives the plugin id from file_name up to the first ".", so it must start with "photo_geojson.".
cat > plugins.xml <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<plugins>
  <pyqgis_plugin name="$(meta name)" version="$version">
    <description><![CDATA[$(meta description)]]></description>
    <about><![CDATA[$(meta about)]]></about>
    <version>$version</version>
    <qgis_minimum_version>$(meta qgisMinimumVersion)</qgis_minimum_version>
    <qgis_maximum_version>$(meta qgisMaximumVersion)</qgis_maximum_version>
    <homepage>$(meta homepage)</homepage>
    <file_name>photo_geojson.$version.zip</file_name>
    <icon>https://raw.githubusercontent.com/${repo#https://github.com/}/main/icon.png</icon>
    <author_name>$(meta author)</author_name>
    <download_url>$repo/releases/download/v$version/photo_geojson-$version.zip</download_url>
    <experimental>$(meta experimental)</experimental>
    <tracker>$(meta tracker)</tracker>
    <repository>$repo</repository>
    <tags>$(meta tags)</tags>
    <category>$(meta category)</category>
  </pyqgis_plugin>
</plugins>
EOF
echo "plugins.xml"
