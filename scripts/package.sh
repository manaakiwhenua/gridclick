#!/usr/bin/env sh
# Build dist/gridclick-<version>.zip for upload to https://plugins.qgis.org/plugins/add/
#
# Only git-tracked files under gridclick/ are packaged (so no __pycache__, .pyc or
# stray files), and the repository LICENSE is copied into the package because the
# plugin repository requires <package>/LICENSE inside the zip.
set -eu
cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain -- gridclick LICENSE)" ]; then
    echo "warning: uncommitted changes under gridclick/ or LICENSE are NOT packaged (HEAD is)" >&2
fi

version=$(sed -n 's/^version=//p' gridclick/metadata.txt)
[ -n "$version" ] || { echo "version not found in gridclick/metadata.txt" >&2; exit 1; }

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/gridclick" dist
git archive HEAD gridclick | tar -x -C "$stage"
cp LICENSE "$stage/gridclick/LICENSE"

out="dist/gridclick-$version.zip"
rm -f "$out"
(cd "$stage" && zip -q -r -X "$OLDPWD/$out" gridclick)

# Mirror the checks plugins.qgis.org runs on upload.
listing=$(unzip -Z1 "$out")
for required in gridclick/metadata.txt gridclick/__init__.py gridclick/LICENSE; do
    echo "$listing" | grep -qx "$required" || { echo "missing $required" >&2; exit 1; }
done
if echo "$listing" | grep -qE '\.pyc$|__pycache__|__MACOSX|\.git/'; then
    echo "forbidden files in package" >&2; exit 1
fi
metadata=$(unzip -p "$out" gridclick/metadata.txt)
for key in name description version qgisMinimumVersion author email about tracker repository; do
    echo "$metadata" | grep -q "^$key=" || { echo "packaged metadata.txt lacks $key" >&2; exit 1; }
done
echo "$metadata" | grep -qx "version=$version" || { echo "packaged version differs from working tree" >&2; exit 1; }
echo "built $out ($(du -h "$out" | cut -f1))"
