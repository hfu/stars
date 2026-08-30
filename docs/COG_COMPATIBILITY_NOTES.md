# Martin Experimental COG Compatibility Notes

> **Status note (2026-08-28, version updated 2026-08-30):** production's Martin binary
> (`/home/stars/.local/bin/martin`, now **v1.14.0**) is a normal release build with no
> COG-related flags — `unstable-cog` has not been built or deployed there, and remains a
> non-default opt-in Cargo feature even in 1.14.0 (confirmed against upstream's Cargo.toml),
> so the version upgrade didn't change this. COG is not currently served in production at
> all. This document remains a target-design reference for when that build is undertaken.
> See [KNOWN_FACTS.md](KNOWN_FACTS.md) Section A.

## 1. Source of findings
This note is based on practical findings shared in UNopenGIS issue 893.

## 2. What was confirmed
- Installing Martin with unstable COG support succeeded using:
  cargo install martin --features=unstable-cog
- Some GeoTIFF or COG files that look valid in GDAL still fail in Martin.
- Martin fixture COG files are accepted, which indicates build/runtime setup can be correct even when user data fails.

## 3. Compatibility implications
A simple conversion to EPSG:3857 is not always enough.
Martin unstable COG support may require stricter structure constraints, including:
- WebMercator-compatible tiling scheme
- expected georeferencing tags and image layout patterns
- overview and IFD structure alignment

## 4. Practical recipe direction
When generating COG for Martin validation, prefer settings aligned with Martin's documented examples, including:
- TILING_SCHEME=GoogleMapsCompatible
- OVERVIEWS generation policy
- ALIGNED_LEVELS and zoom strategy
- explicit compression and block size selection

## 5. Operational guidance for stars
- Keep original PMTiles workflow available while COG support remains experimental.
- Record command history and metadata checks for each tested COG.
- Treat COG compatibility as testable behavior, not format-label-only compliance.
- Maintain at least one known-good sample to validate runtime quickly after upgrades.
