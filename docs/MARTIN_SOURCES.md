# Martin Sources for stars

> **Status note (2026-08-28):** describes the target convention this repo originally used
> for `config/martin.yaml`. Production's actual config
> (`/home/stars/.config/martin/config.yaml`) relies mostly on directory auto-discovery
> under `/home/stars/data` — source IDs there are plain filename stems (e.g.
> `kitaphoto`, `z18` families), not the `pmtiles_<theme>` convention below — plus a
> handful of explicit entries for remote/renamed sources. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.
>
> **Correction (2026-08-30):** `config/martin.yaml` has since been overwritten with a
> verbatim mirror of production's actual config (see CLAUDE.md's "config.yaml gatekeeper
> responsibility") — it no longer follows the `pmtiles_<theme>` / `./data`-relative
> conventions described below, and there's no separate target-design example file anymore.
> The conventions and settings on this page remain useful as *aspirational* design intent
> (naming conventions, COG publishing policy, and the server-tuning settings preserved in
> "Target-design server tuning (not applied)" below) for whenever this repo's config
> actually gets adopted in production, but treat nothing on this page as describing
> `config/martin.yaml`'s current content.

## Purpose
Define how files under data/ are published by Martin in this project.

## Active configuration file
- config/martin.yaml

## Publishing policy
- PMTiles:
  - Directory auto discovery is enabled through pmtiles.paths.
  - Stable production IDs should be added explicitly under pmtiles.sources.
- COG:
  - Publish with explicit IDs under cog.sources.
  - Only add COG files that pass Martin experimental compatibility checks.

## Source ID conventions
- Use lowercase IDs with underscores.
- Keep IDs stable even if file names change.
- Recommended pattern:
  - pmtiles_<theme>
  - cog_<dataset>_<year>

## Data placement rules
- Put all data files under data/.
- Recommended naming:
  - PMTiles: *.pmtiles
  - COG: *_martin_compatible_cog.tif

## Example source entries
Add entries in config/martin.yaml:

```yaml
pmtiles:
  sources:
    pmtiles_basemap:
      path: ./data/basemap.pmtiles

cog:
  sources:
    cog_abidjan_2019:
      path: ./data/abidjan_martin_compatible_cog.tif
```

## Validation checklist
1. Start Martin with config/martin.yaml.
2. Open /catalog to verify source IDs appear.
3. Open TileJSON endpoint for each source and confirm minzoom/maxzoom.
4. Request representative tiles and confirm 200 response.

## COG compatibility note
Based on issue-driven findings, COG acceptance may depend on more than EPSG:3857.
For stable behavior with experimental COG support, keep generation profiles aligned with Martin compatibility guidance.

## Target-design server tuning (not applied, 2026-08-30)

Preserved from the pre-2026-08-30 `config/martin.yaml` (now overwritten with production's
verbatim config, which has none of this) so the tuning rationale isn't lost:

```yaml
listen_addresses: 0.0.0.0:3000
worker_processes: 4

# Keep startup tolerant while data and conversion profile are still experimental.
on_invalid: warn

# Keep cache conservative for Raspberry Pi baseline. Tune after measurements.
cache:
  size_mb: 128
  minzoom: 0
  maxzoom: 18

pmtiles:
  # Needed for a remote, HTTP-fetched pmtiles source (e.g. a whole-planet archive too
  # large to mirror locally) -- everything else should stay local-file-based.
  allow_http: true

# Optional version parameter for cache-busting TileJSON -> tiles URLs.
tilejson_url_version_param: version
```

Production currently runs with none of these set (no explicit `worker_processes`, no
`cache` block, no `on_invalid`, and `allow_http` presumably defaulted since
`openstreetmap_jp_planet`/`bvmap` are remote URL sources that work today) — revisit this
tuning if/when Martin's resource usage on the Pi actually becomes a problem worth
measuring against.
