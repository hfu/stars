**Title:** Per-tile CPU cost grows with the source's TileJSON size (source + TileJSON deep-cloned on every tile request)

## Summary

Serving a tile costs CPU proportional to the size of the source's TileJSON, even on a tile-cache hit, because the source — including its `TileJSON` held by value — is deep-cloned at least twice per tile request. Archives with large metadata (e.g. tippecanoe's `tilestats`, often tens of KB) pay this on every tile. On `main` (d9ab38a), a 87 KB TileJSON makes a tiny PNG tile ~25× more expensive to serve than the same archive with ~0.3 KB of metadata. Wrapping `PmtilesSource::tilejson` in an `Arc` (2-line change) makes the cost independent of metadata size; responses are byte-identical.

## Where the clones happen (at d9ab38a)

- `TileSources::get_source` returns `.value().clone()` of `(BoxedSource, ResolvedProcess)`:
  https://github.com/maplibre/martin/blob/d9ab38ad1440d9d1cbabc8473fa57d67ef5ba1bc/martin/src/source.rs#L228-L235
- `impl Clone for BoxedSource` calls `clone_source()`, i.e. `Box::new(self.clone())`:
  https://github.com/maplibre/martin/blob/d9ab38ad1440d9d1cbabc8473fa57d67ef5ba1bc/martin-core/src/tiles/source.rs#L134-L138
- `fetch_tile_content_with_cache` calls `s.clone_source()` *before* the cache lookup, so hits pay it too:
  https://github.com/maplibre/martin/blob/d9ab38ad1440d9d1cbabc8473fa57d67ef5ba1bc/martin/src/srv/tiles/content.rs#L649
- The sources hold `tilejson: TileJSON` by value (pmtiles, mbtiles, postgres, passthrough, geojson, duckdb, cog), e.g.:
  https://github.com/maplibre/martin/blob/d9ab38ad1440d9d1cbabc8473fa57d67ef5ba1bc/martin-core/src/tiles/pmtiles/source.rs#L39

`tilestats` / `vector_layers` land in TileJSON as `serde_json::Value` trees, so each clone is many small allocations.

## Measurements

Sequential keep-alive GETs over loopback (`curl -K`, `Accept-Encoding: gzip`), 3,000 requests per row, Martin CPU from `ps -o cputime`. Build: `cargo build --release -p martin --no-default-features --features pmtiles,metrics`, Apple M1, macOS. The 0.3 KB and 87.3 KB rows and the real-archive rows were run interleaved (main, patched, main, patched); the large-metadata rows agreed across rounds within ~4%. The 9.1 KB and 26.6 KB rows are from a separate run of main only.

**Synthetic:** `tests/fixtures/pmtiles/png.pmtiles` (5 tiles) with a tilestats-shaped block injected into its metadata.

| TileJSON size | main: ms CPU/req | main: req/s | patched: ms CPU/req | patched: req/s |
|---:|---:|---:|---:|---:|
| 0.3 KB | 0.037 | 8,600 | 0.033 | 8,700 |
| 9.1 KB | 0.12 | 4,800 | — | — |
| 26.6 KB | 0.28 | 2,400 | — | — |
| 87.3 KB | 0.83 | 1,020 | 0.033 | 8,700 |

**Real archive:** a 64 MB vector PMTiles (1,531 gzip MVT tiles) whose metadata is 73.5 KB, almost all `tilestats`; "minimal" is the same file with `tilestats` and `vector_layers` removed via `pmtiles edit --metadata` (tile bytes unchanged).

| variant | main: ms CPU/req | patched: ms CPU/req |
|---|---:|---:|
| full (73.5 KB TileJSON) | 0.39–0.41 | 0.030 |
| minimal (1.0 KB TileJSON) | 0.033–0.040 | 0.030 |

This is how we found it: in production on a Raspberry Pi 4B (Martin 1.14.0), that archive cost ~4–5 ms of CPU per tile even on tile-cache hits, vs ~0.4–1 ms for sources with small metadata. There, gzip pass-through, declared tile format, file size, the tile cache and kernel time were each ruled out by experiment before we read the code.

## Reproduce

```bash
F=tests/fixtures/pmtiles/png.pmtiles
pmtiles show --metadata $F > meta.json
python3 - <<'EOF'
import json
d = json.load(open("meta.json"))
layers = [{"layer": f"l{i}", "count": i, "geometry": "Polygon", "attributeCount": 3,
           "attributes": [{"attribute": f"a{j}", "count": 10, "type": "string",
                           "values": [f"v{k}" for k in range(20)]} for j in range(3)]}
          for i in range(330)]
d["tilestats"] = {"layerCount": len(layers), "layers": layers}
json.dump(d, open("big.json", "w"))
EOF
cp $F small.pmtiles; cp $F big.pmtiles
pmtiles edit big.pmtiles --metadata big.json
martin small.pmtiles big.pmtiles &
# then load /small/1/0/0 and /big/1/0/0 with any HTTP load tool and compare req/s or CPU.
# On an M1 with sequential curl this gave ~3,400 req/s (306 B TileJSON) vs ~360 req/s (193 KB TileJSON).
```

## Possible fixes

1. **Targeted:** `tilejson: Arc<TileJSON>` in each source. For pmtiles it compiles as-is, because `get_tilejson(&self) -> &TileJSON` derefs:
   ```diff
   -    tilejson: TileJSON,
   +    tilejson: Arc<TileJSON>,
   ...
   -            tilejson,
   +            tilejson: Arc::new(tilejson),
   ```
   With this change, `cargo test -p martin-core --no-default-features --features pmtiles` passes (including all 38 tests in `pmtiles_test.rs`), and `/catalog`, TileJSON and tile responses are byte-identical to `main`.
2. **Broader:** avoid the deep clone per request altogether, e.g. store `Arc<dyn Source>` in `TileSources` so `get_source` / `clone_source` become refcount bumps. That would also cover other per-source fields, but it's a larger change; happy to leave the choice to you.

The criterion benchmark added in #3291 (`martin/benches/sources.rs`) uses a `NullSource` with a one-URL TileJSON, so it can't see this; a variant with a large TileJSON would guard against regressions.

If the targeted fix is welcome, I can open a PR covering all source types.

---
Investigated with the help of Claude Code (an AI assistant). I reviewed the analysis, and the numbers above come from runs on my machines.
