# Map display resources

Fetched on 2026-10-16. These resources affect webpage display only.

- Leaflet 1.9.4, https://github.com/Leaflet/Leaflet/tree/v1.9.4 .
  `leaflet-1.9.4/leaflet.js` and `leaflet.css` are the unmodified published distribution from
  https://unpkg.com/leaflet@1.9.4/dist/ . No package manager or build step is required.
  BSD-2-Clause copyright and licence are preserved in `leaflet-1.9.4/LICENSE`.
- `../plate_boundaries.json` is the unmodified GeoJSON from
  https://github.com/fraxen/tectonicplates/blob/339b0c56563c118307b1f4542703047f5f698fae/GeoJSON/PB2002_boundaries.json .
  This collection is explicitly offered under ODC-By 1.0; the source licence notice
  is preserved in `plate_boundaries_LICENSE.md`.
  Credit: Peter Bird (2003), *An updated digital model of plate boundaries*,
  https://doi.org/10.1029/2001GC000252 ; Hugo Ahlenius / Nordpil (conversion),
  and csterling (GeoJSON). This is a historical plate-boundary context layer.
- OpenStreetMap Standard raster tiles are requested by the browser only for the
  displayed view, from https://tile.openstreetmap.org/{z}/{x}/{y}.png .
  Visible attribution links to https://www.openstreetmap.org/copyright .
  Tile use follows https://operations.osmfoundation.org/policies/tiles/ ;
  tiles are not downloaded or packaged with the monitor.

The existing local `coast.json` is retained as a fallback when the online basemap
is unavailable. No third-party application code from `earthquake_weekly` is copied.
