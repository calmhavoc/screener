#!/bin/sh
# docker-entrypoint.sh
# Ensures the container working directory is /work (the bind-mount point for the
# host's current directory) and gives an actionable error if the input file is
# missing, which usually means -v "$PWD:/work" was omitted.

set -e

# The Dockerfile already sets WORKDIR /work, but be explicit.
cd /work

# ── Quick sanity check: if the first positional argument (url_file) is given
#   and does not exist, print a helpful message before Python does.
URL_FILE=""
for arg in "$@"; do
    case "$arg" in
        --*) ;;               # skip flags
        *) URL_FILE="$arg"; break ;;   # first non-flag = url_file
    esac
done

if [ -n "$URL_FILE" ] && [ ! -f "$URL_FILE" ]; then
    echo ""
    echo "ERROR: URL file not found: $URL_FILE"
    echo ""
    echo "Make sure your current directory is bind-mounted into the container:"
    echo ""
    echo "  docker run --rm -v \"\$PWD:/work\" screener $*"
    echo ""
    echo "Files passed as relative paths (e.g. ./urls.txt) must exist in the"
    echo "directory you mount at /work (i.e. your host current directory)."
    echo ""
    exit 1
fi

exec python /app/screener.py "$@"
