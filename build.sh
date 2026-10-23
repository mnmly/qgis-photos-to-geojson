#!/bin/sh
# Builds dist/photo_geojson-<version>.zip from the committed files (installable via "Install from ZIP").
set -e
cd "$(dirname "$0")"
version=$(sed -n 's/^version=//p' metadata.txt)
mkdir -p dist
git archive --format=zip --prefix=photo_geojson/ -o "dist/photo_geojson-$version.zip" HEAD \
  -- ':!.gitignore' ':!build.sh' ':!README.md'
echo "dist/photo_geojson-$version.zip"
