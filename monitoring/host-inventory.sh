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

# Two lists, because a served archive and one being uploaded to replace it
# look identical as "disk usage" but mean opposite things:
#   pmtiles - files Martin actually serves (exactly *.pmtiles)
#   staging - in-progress transfers, which contributors stage as dotfiles or
#             .new suffixes before an atomic rename (e.g.
#             .foo.pmtiles.new.X4qqja). Martin's *.pmtiles scan can't see
#             these, so without listing them separately a mid-transfer archive
#             reads as "the source was deleted" rather than "it's being
#             replaced" -- which is exactly how a 2026-09-11 publish was
#             initially misread.
# mtime is emitted as epoch seconds (%Ts) and converted to UTC in jq; find's
# %T date formats render local time, so formatting a "Z" timestamp there
# directly would label JST as UTC.
list_files() {
  find "$DATA_DIR" -maxdepth 1 -type f "$@" -printf '%f\t%s\t%Ts\n' 2>/dev/null || true
}

served=$(list_files -name '*.pmtiles')
# Anything mentioning .pmtiles but not ending in it: staged/partial uploads.
staged=$(list_files -name '*.pmtiles*' ! -name '*.pmtiles')

jq -R -s --arg ts "$ts" --arg staged "$staged" '
    def parse:
      split("\n")
      | map(select(length > 0) | split("\t"))
      | map({key: (.[0] | rtrimstr(".pmtiles")),
             value: {size: (.[1] | tonumber),
                     mtime: (.[2] | tonumber | todate)}})
      | from_entries;
    {ts: $ts,
     pmtiles: parse,
     staging: ($staged | parse)}' <<< "$served" > "$TMP"

mv "$TMP" "$OUT"
