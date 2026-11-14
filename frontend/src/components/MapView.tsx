import maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";
import { fmt, type Dict, type FieldsPayload, type Meta } from "../api";

interface Props {
  meta: Meta;
  fields: FieldsPayload;
  customFields: GeoJSON.Feature[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  drawing: boolean;
  onDrawFinish: (polygon: GeoJSON.Polygon) => void;
  onDrawCancel: () => void;
}

// One hue, light to dark: magnitude only.
const RAMP = ["#E3EEF9", "#B5D0EC", "#7FAEDB", "#3F82C4", "#0B4F99"];

const COLOR_BY: Dict<{ label: string; unit: string; digits: number; note: string }> = {
  irrigation_need_mm: { label: "Irrigation need of the existing rotation", unit: "mm/yr", digits: 0, note: "Crop demand minus usable rain (model estimate)" },
  openet_gs_et_mm: { label: "Water used, Apr–Oct (OpenET, 2021–25)", unit: "mm", digits: 0, note: "Satellite estimate of actual ET" },
  low_cover_months: { label: "Months a year with little green cover", unit: "months", digits: 0, note: "Landsat NDVI below 0.25 in at least half the years" },
  om_pct: { label: "Soil organic matter, top 30 cm", unit: "%", digits: 1, note: "SSURGO soil survey, not a field sample" },
  wind_erodibility_index: { label: "Soil wind-erodibility index", unit: "t/ac/yr", digits: 0, note: "SSURGO: higher blows more easily" },
  ec_dsm: { label: "Soil salinity (EC), top 30 cm", unit: "dS/m", digits: 1, note: "SSURGO soil survey; alfalfa loses yield above 2" },
};

const SAT = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg";
const OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

function rampColor(v: number | null | undefined, min: number, max: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "rgba(0,0,0,0)";
  const t = max > min ? (v - min) / (max - min) : 0.5;
  return RAMP[Math.max(0, Math.min(RAMP.length - 1, Math.floor(t * RAMP.length)))];
}

const emptyFC = (): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features: [] });

export default function MapView({ meta, fields, customFields, selectedId, onSelect, drawing, onDrawFinish, onDrawCancel }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const drawPts = useRef<[number, number][]>([]);
  const drawingRef = useRef(drawing);
  const selectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  const [nPts, setNPts] = useState(0);
  const [basemap, setBasemap] = useState<"satellite" | "streets">("satellite");
  const [group, setGroup] = useState<string>("none");
  const [year, setYear] = useState<number>(2025);
  const [colorBy, setColorBy] = useState<string>("none");
  const [panelOpen, setPanelOpen] = useState(false);
  const [soil, setSoil] = useState<GeoJSON.FeatureCollection | null>(null);

  selectRef.current = onSelect;
  drawingRef.current = drawing;

  const years = useMemo(
    () => Array.from(new Set(meta.overlays.layers.filter((l) => l.year).map((l) => l.year as number))).sort(),
    [meta],
  );

  const allFields = useMemo<GeoJSON.FeatureCollection>(() => {
    const feats = [...fields.pilot.features, ...customFields];
    const vals = feats.map((f) => (f.properties as Dict)?.[colorBy]).filter((v) => typeof v === "number") as number[];
    const [min, max] = vals.length ? [Math.min(...vals), Math.max(...vals)] : [0, 1];
    return {
      type: "FeatureCollection",
      features: feats.map((f) => ({
        ...f,
        properties: { ...(f.properties as Dict), _fill: colorBy === "none" ? "rgba(0,0,0,0)" : rampColor((f.properties as Dict)?.[colorBy], min, max) },
      })),
    };
  }, [fields, customFields, colorBy]);

  const range = useMemo(() => {
    const vals = allFields.features.map((f) => (f.properties as Dict)?.[colorBy]).filter((v) => typeof v === "number") as number[];
    return vals.length ? [Math.min(...vals), Math.max(...vals)] : null;
  }, [allFields, colorBy]);

  // --- create the map once ---------------------------------------------------
  useEffect(() => {
    if (!el.current || mapRef.current) return;
    const [w, s, e, n] = meta.pilot.bbox;
    const map = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        sources: {
          sat: { type: "raster", tiles: [SAT], tileSize: 256, maxzoom: 15, attribution: 'Imagery: <a href="https://s2maps.eu" target="_blank" rel="noreferrer">Sentinel-2 cloudless</a> by EOX (Copernicus Sentinel data 2016, CC BY 4.0)' },
          osm: { type: "raster", tiles: [OSM], tileSize: 256, maxzoom: 19, attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors' },
        },
        layers: [
          { id: "sat", type: "raster", source: "sat" },
          { id: "osm", type: "raster", source: "osm", layout: { visibility: "none" } },
        ],
      },
      bounds: [w, s, e, n],
      fitBoundsOptions: { padding: 28 },
      attributionControl: { compact: true },
      maxZoom: 16,
      minZoom: 8,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");
    mapRef.current = map;

    // Add the field layers as soon as the style is parsed, without waiting for the satellite
    // tiles (which can be slow, or missing offline). The style may already be ready by the
    // time we get here, so check first and guard against running twice.
    let started = false;
    const init = () => {
      if (started) return;
      started = true;
      const box: GeoJSON.Feature = { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] } };
      map.addSource("pilot-box", { type: "geojson", data: box });
      map.addSource("soil", { type: "geojson", data: emptyFC() });
      map.addSource("context", { type: "geojson", data: fields.context });
      map.addSource("fields", { type: "geojson", data: emptyFC() });
      map.addSource("wells", { type: "geojson", data: fields.wells });
      map.addSource("draw", { type: "geojson", data: emptyFC() });

      map.addLayer({ id: "soil-fill", type: "fill", source: "soil", layout: { visibility: "none" }, paint: { "fill-color": ["get", "_c"], "fill-opacity": 0.55 } });
      map.addLayer({ id: "soil-line", type: "line", source: "soil", layout: { visibility: "none" }, paint: { "line-color": "#1d2a2e", "line-width": 0.8, "line-opacity": 0.7 } });
      map.addLayer({ id: "context-line", type: "line", source: "context", paint: { "line-color": "#ffffff", "line-width": 1, "line-opacity": 0.45 } });
      map.addLayer({ id: "fields-fill", type: "fill", source: "fields", paint: { "fill-color": ["get", "_fill"], "fill-opacity": 0.82 } });
      map.addLayer({ id: "fields-casing", type: "line", source: "fields", paint: { "line-color": "#10191c", "line-width": 4.5, "line-opacity": 0.7 } });
      map.addLayer({ id: "fields-line", type: "line", source: "fields", paint: { "line-color": "#ffffff", "line-width": 2.2 } });
      map.addLayer({ id: "fields-selected", type: "line", source: "fields", filter: ["==", ["get", "field_id"], ""], paint: { "line-color": "#FFD23F", "line-width": 5 } });
      map.addLayer({ id: "wells", type: "circle", source: "wells", layout: { visibility: "none" }, paint: { "circle-radius": 5, "circle-color": "#0072B2", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
      map.addLayer({ id: "pilot-box", type: "line", source: "pilot-box", paint: { "line-color": "#ffffff", "line-width": 1.5, "line-dasharray": [3, 3], "line-opacity": 0.85 } });
      map.addLayer({ id: "draw-fill", type: "fill", source: "draw", filter: ["==", ["geometry-type"], "Polygon"], paint: { "fill-color": "#FFD23F", "fill-opacity": 0.25 } });
      map.addLayer({ id: "draw-line", type: "line", source: "draw", paint: { "line-color": "#FFD23F", "line-width": 3 } });
      map.addLayer({ id: "draw-pts", type: "circle", source: "draw", filter: ["==", ["geometry-type"], "Point"], paint: { "circle-radius": 6, "circle-color": "#FFD23F", "circle-stroke-color": "#10191c", "circle-stroke-width": 2 } });

      map.on("click", (ev) => {
        if (drawingRef.current) {
          drawPts.current = [...drawPts.current, [ev.lngLat.lng, ev.lngLat.lat]];
          setNPts(drawPts.current.length);
          renderDraw(map);
          return;
        }
        const hit = map.queryRenderedFeatures(ev.point, { layers: ["fields-fill"] })[0];
        if (hit?.properties?.field_id) selectRef.current(hit.properties.field_id as string);
      });
      map.on("mousemove", (ev) => {
        if (drawingRef.current) return;
        const hit = map.queryRenderedFeatures(ev.point, { layers: ["fields-fill"] })[0];
        map.getCanvas().style.cursor = hit ? "pointer" : "";
      });
      // start with the attribution folded away so it does not cover fields on a phone
      const attrib = el.current?.querySelector(".maplibregl-ctrl-attrib");
      attrib?.classList.remove("maplibregl-compact-show");
      attrib?.removeAttribute("open");
      setReady(true);
    };
    if (map.isStyleLoaded()) init();
    else {
      map.once("style.load", init);
      map.once("load", init);
    }
    return () => {
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function renderDraw(map: maplibregl.Map) {
    const pts = drawPts.current;
    const feats: GeoJSON.Feature[] = pts.map((p) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } }));
    if (pts.length >= 2) feats.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts.length >= 3 ? [...pts, pts[0]] : pts } });
    if (pts.length >= 3) feats.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });
    (map.getSource("draw") as maplibregl.GeoJSONSource | undefined)?.setData({ type: "FeatureCollection", features: feats });
  }

  // --- drawing mode -----------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    drawPts.current = [];
    setNPts(0);
    renderDraw(map);
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
  }, [drawing, ready]);

  const finishDraw = () => {
    const pts = drawPts.current;
    if (pts.length >= 3) onDrawFinish({ type: "Polygon", coordinates: [[...pts, pts[0]]] });
  };
  const undoPoint = () => {
    drawPts.current = drawPts.current.slice(0, -1);
    setNPts(drawPts.current.length);
    if (mapRef.current) renderDraw(mapRef.current);
  };

  // --- field data, labels, selection ------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    (map.getSource("fields") as maplibregl.GeoJSONSource).setData(allFields);
    markers.current.forEach((m) => m.remove());
    markers.current = allFields.features.map((f) => {
      const p = f.properties as Dict;
      const node = document.createElement("button");
      node.className = "field-label" + (p.field_id === selectedId ? " is-selected" : "");
      node.textContent = p.is_custom ? "★" : String(p.field_id).replace("DV-", "").replace(/^0/, "");
      node.title = `${p.name}: ${p.crop_latest ?? ""}`;
      node.setAttribute("aria-label", `Select ${p.name}`);
      node.onclick = (e) => {
        e.stopPropagation();
        if (!drawingRef.current) selectRef.current(p.field_id);
      };
      return new maplibregl.Marker({ element: node }).setLngLat([p.lon, p.lat]).addTo(map);
    });
  }, [allFields, ready, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    map.setFilter("fields-selected", ["==", ["get", "field_id"], selectedId ?? ""]);
    const f = allFields.features.find((x) => (x.properties as Dict).field_id === selectedId);
    if (f) {
      const p = f.properties as Dict;
      if (!map.getBounds().contains([p.lon, p.lat])) map.easeTo({ center: [p.lon, p.lat] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, ready]);

  // --- basemap -------------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    map.setLayoutProperty("sat", "visibility", basemap === "satellite" ? "visible" : "none");
    map.setLayoutProperty("osm", "visibility", basemap === "streets" ? "visible" : "none");
    map.setPaintProperty("context-line", "line-color", basemap === "satellite" ? "#ffffff" : "#1d2a2e");
    map.setPaintProperty("pilot-box", "line-color", basemap === "satellite" ? "#ffffff" : "#1d2a2e");
  }, [basemap, ready]);

  // --- raster and vector overlays ------------------------------------------------
  const overlay = useMemo(() => {
    if (group === "none" || group === "soil" || group === "wells") return null;
    const list = meta.overlays.layers.filter((l) => l.group === group);
    return list.find((l) => l.year === year) ?? list[list.length - 1] ?? null;
  }, [group, year, meta]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    if (map.getLayer("overlay")) map.removeLayer("overlay");
    if (map.getSource("overlay")) map.removeSource("overlay");
    if (overlay) {
      map.addSource("overlay", { type: "image", url: `/overlays/${overlay.file}`, coordinates: meta.overlays.corners as any });
      map.addLayer({ id: "overlay", type: "raster", source: "overlay", paint: { "raster-opacity": 0.88, "raster-resampling": "nearest" } }, "soil-fill");
    }
    map.setLayoutProperty("soil-fill", "visibility", group === "soil" ? "visible" : "none");
    map.setLayoutProperty("soil-line", "visibility", group === "soil" ? "visible" : "none");
    map.setLayoutProperty("wells", "visibility", group === "wells" ? "visible" : "none");
  }, [overlay, group, ready, meta]);

  useEffect(() => {
    if (group !== "soil" || soil) return;
    fetch("/api/soil-mapunits")
      .then((r) => r.json())
      .then((fc: GeoJSON.FeatureCollection) => {
        const oms = fc.features.map((f) => (f.properties as Dict)?.om_pct_0_30).filter((v) => typeof v === "number") as number[];
        const [min, max] = [Math.min(...oms), Math.max(...oms)];
        fc.features.forEach((f) => ((f.properties as Dict)._c = rampColor((f.properties as Dict)?.om_pct_0_30, min, max)));
        setSoil(fc);
      })
      .catch(() => setSoil(emptyFC()));
  }, [group, soil]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !soil) return;
    (map.getSource("soil") as maplibregl.GeoJSONSource).setData(soil);
  }, [soil, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getSource("fields")) return;
    const onSoilClick = (ev: maplibregl.MapLayerMouseEvent) => {
      const p = ev.features?.[0]?.properties as Dict | undefined;
      if (!p || drawingRef.current) return;
      new maplibregl.Popup({ maxWidth: "280px" })
        .setLngLat(ev.lngLat)
        .setHTML(
          `<strong>${p.muname ?? "Soil map unit"}</strong><br/>Surface: ${p.surface_texture ?? "–"}<br/>Organic matter: ${p.om_pct_0_30 != null ? Number(p.om_pct_0_30).toFixed(1) + " %" : "–"}<br/>Drainage: ${p.drainage_class ?? "–"}<br/><em>USDA NRCS soil survey map unit</em>`,
        )
        .addTo(map);
    };
    const onWellClick = (ev: maplibregl.MapLayerMouseEvent) => {
      const p = ev.features?.[0]?.properties as Dict | undefined;
      if (!p) return;
      const tr = p.trend_m_per_decade_since_1990;
      new maplibregl.Popup({ maxWidth: "280px" })
        .setLngLat(ev.lngLat)
        .setHTML(
          `<strong>USGS well ${String(p.site_id).replace("USGS-", "")}</strong><br/>Measured ${p.first_year}–${p.last_year} (${p.n_measurements} readings)<br/>Depth to water: ${Number(p.depth_m_first).toFixed(1)} m → ${Number(p.depth_m_last).toFixed(1)} m` +
            (tr != null && tr !== "null" ? `<br/>Since 1990: ${Number(tr) > 0 ? "deeper" : "shallower"} by ${Math.abs(Number(tr)).toFixed(1)} m per decade` : ""),
        )
        .addTo(map);
    };
    map.on("click", "soil-fill", onSoilClick);
    map.on("click", "wells", onWellClick);
    return () => {
      map.off("click", "soil-fill", onSoilClick);
      map.off("click", "wells", onWellClick);
    };
  }, [ready]);

  const legend = overlay ? meta.overlays.legends[overlay.group] : null;
  const hasYears = group === "ndvi" || group === "cdl";

  return (
    <div className="map-wrap">
      <div ref={el} className="map" role="application" aria-label="Map of pilot fields in Diamond Valley, Nevada" />

      <div className="map-tools">
        <button className="btn btn-map" onClick={() => setPanelOpen((v) => !v)} aria-expanded={panelOpen}>
          Map layers
        </button>
        {panelOpen && (
          <div className="layer-panel">
            <label className="lp-row">
              <span>Background</span>
              <select value={basemap} onChange={(e) => setBasemap(e.target.value as any)}>
                <option value="satellite">Satellite photo</option>
                <option value="streets">Street map</option>
              </select>
            </label>
            <label className="lp-row">
              <span>Show on the map</span>
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="none">Fields only</option>
                <option value="ndvi">Summer greenness (Landsat)</option>
                <option value="cdl">Crop map (USDA)</option>
                <option value="low_cover">Months with little green cover</option>
                <option value="slope">Slope (SRTM)</option>
                <option value="soil">Soil map units (organic matter)</option>
                <option value="wells">Groundwater wells (USGS)</option>
              </select>
            </label>
            {hasYears && (
              <label className="lp-row">
                <span>
                  Year <strong>{year}</strong>
                </span>
                <input type="range" min={years[0]} max={years[years.length - 1]} step={1} value={year} onChange={(e) => setYear(Number(e.target.value))} />
              </label>
            )}
            <label className="lp-row">
              <span>Colour the fields by</span>
              <select value={colorBy} onChange={(e) => setColorBy(e.target.value)}>
                <option value="none">Outline only</option>
                {Object.entries(COLOR_BY).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {drawing && (
        <div className="draw-bar" role="status">
          <span>{nPts < 3 ? `Tap the corners of your field (${nPts} so far, at least 3).` : `${nPts} corners. Add more or finish.`}</span>
          <span className="draw-actions">
            <button className="btn btn-quiet" onClick={undoPoint} disabled={nPts === 0}>
              Undo corner
            </button>
            <button className="btn btn-quiet" onClick={onDrawCancel}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={finishDraw} disabled={nPts < 3}>
              Finish field
            </button>
          </span>
        </div>
      )}

      {(legend || (colorBy !== "none" && range) || group === "soil") && (
        <div className="legend">
          {legend?.type === "ramp" && (
            <div className="legend-block">
              <div className="legend-title">{legend.title}</div>
              <div className="legend-ramp" style={{ background: `linear-gradient(90deg, ${legend.colors.map((c: number[]) => `rgb(${c.join(",")})`).join(",")})` }} />
              <div className="legend-ends">
                <span>{legend.min}</span>
                <span>{legend.max}</span>
              </div>
              <div className="legend-src">{legend.source}</div>
            </div>
          )}
          {legend?.type === "classes" && (
            <div className="legend-block">
              <div className="legend-title">
                {legend.title} {overlay?.year}
              </div>
              <ul className="legend-classes">
                {legend.classes.map((c: Dict) => (
                  <li key={c.label}>
                    <i style={{ background: `rgb(${c.color.join(",")})` }} />
                    {c.label}
                  </li>
                ))}
              </ul>
              <div className="legend-src">{legend.source}. A classification, not a ground record.</div>
            </div>
          )}
          {group === "soil" && (
            <div className="legend-block">
              <div className="legend-title">Soil organic matter by map unit</div>
              <div className="legend-ramp" style={{ background: `linear-gradient(90deg, ${RAMP.join(",")})` }} />
              <div className="legend-ends">
                <span>lower</span>
                <span>higher</span>
              </div>
              <div className="legend-src">USDA NRCS SSURGO. Tap a unit for details.</div>
            </div>
          )}
          {colorBy !== "none" && range && (
            <div className="legend-block">
              <div className="legend-title">Fields: {COLOR_BY[colorBy].label}</div>
              <div className="legend-steps">
                {RAMP.map((c) => (
                  <i key={c} style={{ background: c }} />
                ))}
              </div>
              <div className="legend-ends">
                <span>
                  {fmt(range[0], COLOR_BY[colorBy].digits)} {COLOR_BY[colorBy].unit}
                </span>
                <span>
                  {fmt(range[1], COLOR_BY[colorBy].digits)} {COLOR_BY[colorBy].unit}
                </span>
              </div>
              <div className="legend-src">{COLOR_BY[colorBy].note}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
