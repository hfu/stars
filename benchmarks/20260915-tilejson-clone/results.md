# Martin per-request CPU vs TileJSON size (2026-09-15)

Tool: `monitoring/bench/tilejson-probe.sh` (throwaway Martin 1.14.0 on 127.0.0.1:3999 on
the Pi; production Martin untouched). Sequential keep-alive requests over loopback,
`Accept-Encoding: gzip, deflate, br`. Martin CPU from `/proc/<pid>/stat` utime+stime.
Two passes each; the second pass is warmer (tile cache, page cache).

Same tile bytes in all three variants of an archive; only the metadata differs.

## vbm (600 tiles, mean 51.7 KB)

| variant | TileJSON | pass 1 ms/req | pass 2 ms/req | pass 2 rps |
|---|---:|---:|---:|---:|
| full | 73,534 B | 4.88 | 4.02 | 222 |
| no `tilestats` | 11,889 B | 1.47 | 0.92 | 733 |
| no `tilestats`, no `vector_layers` | 1,044 B | 0.82 | 0.37 | 1,383 |

## vlcm (1,200 tiles, mean 6.5 KB)

| variant | TileJSON | pass 1 ms/req | pass 2 ms/req | pass 2 rps |
|---|---:|---:|---:|---:|
| full | 11,953 B | 1.27 | 0.73 | 914 |
| no `tilestats` | 1,944 B | 0.55 | 0.30 | 1,735 |
| no `tilestats`, no `vector_layers` | 1,307 B | 0.50 | 0.23 | 2,063 |

## Ruled out along the way (same session)

- **Compression work:** Martin's gzip response is byte-identical to the stored tile
  (sha256 of `pmtiles tile` output = response body); `identity` and no `Accept-Encoding`
  cost about the same as gzip pass-through. Only `br`-only clients trigger real
  re-encoding (23 ms/req on vbm).
- **Declared format:** the vbm archive with its header rewritten to "PNG, uncompressed"
  was exactly as slow as the MVT original.
- **File size:** a 2.3 MB archive padded to 64 MB with trailing zeros was no slower.
- **Tile cache:** vbm stays ~4–5.5 ms per request even on tile-cache hits (confirmed via
  the test instance's `/_/metrics`: hit=4 miss=1 for five identical requests), while
  kitaphoto17 hits drop to ~0.4–1 ms. The cost is outside the cache.
- **Kernel/network:** on production vbm, Martin's time was 488 cs user vs 16 cs system.

## Cause (source reading, martin-v1.14.0; unchanged on main as of 1.16.1)

`PmtilesSource` holds `tilejson: TileJSON` by value and derives `Clone`. Each tile request
clones the boxed source at least twice: `TileSources::get_source` returns
`.value().clone()` (`martin/src/source.rs`), and `fetch_tile_content_with_cache` calls
`s.clone_source()` (`martin/src/srv/tiles/content.rs`). Each clone deep-copies the
TileJSON, including `tilestats` / `vector_layers` as `serde_json::Value` trees, so the
cost grows with metadata size, not tile size.

## Production TileJSON sizes (top of list)

vbm 73,533 B · openstreetmap_jp_planet 18,508 · bvmap 15,153 · vlcm 11,953 ·
pmtiles_ksj_n03_hkd 5,001 · everything else ≤ 2.7 KB.
