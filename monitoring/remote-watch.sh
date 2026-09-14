#!/bin/bash
# Restart Martin when an upstream remote PMTiles archive is replaced.
#
# Why this exists: Martin caches a remote archive's header and directory at
# startup and never re-reads them. When the upstream file is replaced in place
# (same URL, new content), Martin keeps seeking to the *old* offsets in the
# *new* file and every uncached tile fails with HTTP 500 ("Moka cache fetch
# error: IO Error Invalid gzip header"). This happened to
# openstreetmap_jp_planet on 2026-09-11 and went unnoticed for ~4 days.
# Martin 1.14.0 has no reload endpoint, and its remote reloader explicitly
# skips individually-configured URLs (it only re-lists prefixes) -- so the fix
# is to watch upstream ourselves and restart.
#
# How: HEAD each remote URL in Martin's config, fingerprint it by
# ETag + Last-Modified + Content-Length, and compare with the last run.
#
# Safety:
#   - A change is only acted on once the *same* new fingerprint has been seen on
#     two consecutive runs, so a restart never lands mid-upload upstream.
#   - A failed HEAD is never treated as a change (upstream down != replaced).
#   - At most one restart per MIN_RESTART_GAP_S.
#   - The first run only records fingerprints.
#   - DRY_RUN=1 logs what it would do without restarting.
set -euo pipefail

CONFIG="${MARTIN_CONFIG:-/home/stars/.config/martin/config.yaml}"
STATE_DIR="${REMOTE_WATCH_STATE_DIR:-$HOME/.local/state/stars-remote-watch}"
STATE="$STATE_DIR/state.json"
MIN_RESTART_GAP_S="${MIN_RESTART_GAP_S:-1800}"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "remote-watch: $*"; }

mkdir -p "$STATE_DIR"
[ -f "$STATE" ] || echo '{"committed":{},"pending":{},"last_restart":0}' > "$STATE"
state=$(cat "$STATE")
now=$(date +%s)

# config/martin.yaml is simple and canonical-controlled (see CLAUDE.md), so a
# line match on `  <id>: http(s)://...` is sufficient here.
mapfile -t entries < <(grep -E '^[[:space:]]+[A-Za-z0-9_.-]+:[[:space:]]+https?://' "$CONFIG" \
  | sed -E 's/^[[:space:]]+([A-Za-z0-9_.-]+):[[:space:]]+(https?:\/\/[^[:space:]#]+).*/\1 \2/')

first_run=$(jq '.committed | length == 0' <<< "$state")
confirmed=()

for entry in "${entries[@]}"; do
  id=${entry%% *}
  url=${entry#* }
  headers=$(curl -sfI --max-time 30 "$url" | tr -d '\r') || {
    log "$id: HEAD failed; skipping (not treated as a change)"
    continue
  }
  etag=$(grep -i '^etag:' <<< "$headers" | cut -d' ' -f2- || true)
  lm=$(grep -i '^last-modified:' <<< "$headers" | cut -d' ' -f2- || true)
  len=$(grep -i '^content-length:' <<< "$headers" | cut -d' ' -f2- || true)
  fp="$etag|$lm|$len"

  committed=$(jq -r --arg u "$url" '.committed[$u] // empty' <<< "$state")
  pending=$(jq -r --arg u "$url" '.pending[$u] // empty' <<< "$state")

  if [ -z "$committed" ]; then
    state=$(jq --arg u "$url" --arg f "$fp" '.committed[$u] = $f | del(.pending[$u])' <<< "$state")
    [ "$first_run" = "true" ] || log "$id: new remote source recorded"
  elif [ "$fp" = "$committed" ]; then
    state=$(jq --arg u "$url" 'del(.pending[$u])' <<< "$state")
  elif [ "$fp" = "$pending" ]; then
    log "$id: upstream change confirmed on two consecutive runs ($lm)"
    confirmed+=("$url")
  else
    log "$id: upstream fingerprint changed ($lm); waiting one more run to confirm it is stable"
    state=$(jq --arg u "$url" --arg f "$fp" '.pending[$u] = $f' <<< "$state")
  fi
done

if [ "$first_run" = "true" ]; then
  log "first run: recorded ${#entries[@]} remote sources, no action"
elif [ "${#confirmed[@]}" -gt 0 ]; then
  last_restart=$(jq -r '.last_restart' <<< "$state")
  if [ $((now - last_restart)) -lt "$MIN_RESTART_GAP_S" ]; then
    log "restart needed but last restart was $((now - last_restart))s ago; deferring"
  elif [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN: would restart martin for ${#confirmed[@]} changed source(s)"
  else
    log "restarting martin for ${#confirmed[@]} changed source(s)"
    systemctl --user restart martin
    sleep 5
    if curl -sf --max-time 10 http://127.0.0.1:3000/health > /dev/null; then
      log "martin healthy after restart"
    else
      log "WARNING: martin health check failed after restart"
    fi
    state=$(jq --argjson t "$now" '.last_restart = $t' <<< "$state")
  fi
  # Commit only what was actually handled, so a deferred/dry-run change is
  # re-evaluated next time rather than silently forgotten.
  if [ "$DRY_RUN" != "1" ] && [ "$(jq -r '.last_restart' <<< "$state")" = "$now" ]; then
    for url in "${confirmed[@]}"; do
      state=$(jq --arg u "$url" '.committed[$u] = .pending[$u] | del(.pending[$u])' <<< "$state")
    done
  fi
fi

echo "$state" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
