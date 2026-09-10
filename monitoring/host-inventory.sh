#!/bin/bash
# Snapshot which pmtiles files actually exist on disk, as JSON served
# statically by depot.optgeo.org. The daily specs collector reconciles this
# against Martin's catalog -- /home/stars/data is writable directly by trusted
# contributors, so a source can vanish (or appear) without any config change,
# and only a disk-side view catches that.
#
# Deliberately separate from host-status.sh (which runs every 2 minutes): this
# output is much larger and changes rarely, so it runs hourly to keep both the
# file churn in Martin's watched directory and the payload size down.
set -euo pipefail

OUT="${HOST_INVENTORY_OUT:-/home/stars/data/host-inventory.json}"
DATA_DIR="${HOST_INVENTORY_DIR:-/home/stars/data}"
TMP="${OUT}.tmp"

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# One JSON object per file, keyed by filename stem (which is exactly the
# source id Martin derives for auto-discovered sources). mtime is emitted as
# epoch seconds (%Ts) and converted to UTC in jq -- find's %T date formats
# render local time, so formatting a "Z" timestamp directly there would label
# JST as UTC.
find "$DATA_DIR" -maxdepth 1 -name '*.pmtiles' -printf '%f\t%s\t%Ts\n' \
  | jq -R -s --arg ts "$ts" '
      {ts: $ts,
       pmtiles: (
         split("\n")
         | map(select(length > 0) | split("\t"))
         | map({key: (.[0] | rtrimstr(".pmtiles")),
                value: {size: (.[1] | tonumber),
                        mtime: (.[2] | tonumber | todate)}})
         | from_entries
       )}' > "$TMP"

mv "$TMP" "$OUT"
