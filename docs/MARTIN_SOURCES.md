# Martin Sources for stars

> **Status note (2026-08-28):** describes the target convention for this repo's
> `config/martin.yaml`. Production's actual config
> (`/home/stars/.config/martin/config.yaml`) relies mostly on directory auto-discovery
> under `/home/stars/data` — source IDs there are plain filename stems (e.g.
> `kitaphoto`, `z18` families), not the `pmtiles_<theme>` convention below — plus a
> handful of explicit entries for remote/renamed sources. See
> [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.

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
