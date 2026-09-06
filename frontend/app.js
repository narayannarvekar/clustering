const map = L.map("map", { zoomControl: true }).setView([26.05, -80.25], 10);

const ESRI_ATTRIBUTION =
  "Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS User Community";

L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  { attribution: ESRI_ATTRIBUTION, maxZoom: 16 }
).addTo(map);

L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
  { maxZoom: 16 }
).addTo(map);

let hexLayer = null;
let clusterLayer = null;
let boundaryLayer = null;
let currentMetro = null;
const visible = { hexes: true, clusters: true };

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function lerpColor(c1, c2, t) {
  return [
    Math.round(lerp(c1[0], c2[0], t)),
    Math.round(lerp(c1[1], c2[1], t)),
    Math.round(lerp(c1[2], c2[2], t)),
  ];
}

function rgb([r, g, b]) {
  return `rgb(${r}, ${g}, ${b})`;
}

const FRICTION_STOPS = [
  [255, 255, 255], // white — good performance
  [248, 113, 113], // mid red
  [127, 29, 29],   // dark red — bad performance
];

function frictionColor(score) {
  const t = Math.max(0, Math.min(score, 1));
  if (t <= 0.5) return rgb(lerpColor(FRICTION_STOPS[0], FRICTION_STOPS[1], t / 0.5));
  return rgb(lerpColor(FRICTION_STOPS[1], FRICTION_STOPS[2], (t - 0.5) / 0.5));
}

function severityColor(score) {
  const t = Math.max(0, Math.min(score, 1));
  return rgb(lerpColor([245, 158, 11], [127, 29, 29], t));
}

function styleHex(feature) {
  const p = feature.properties;
  if (p.low_sample) {
    return { fillColor: "#9ca3af", fillOpacity: 0.15, color: "#cbd5e1", weight: 0.4, opacity: 0.5 };
  }
  return {
    fillColor: frictionColor(p.friction_score),
    fillOpacity: 0.5,
    color: "#e2e8f0",
    weight: 0.3,
    opacity: 0.45,
  };
}

function styleCluster(feature) {
  const p = feature.properties;
  return {
    fillColor: severityColor(p.severity_score),
    fillOpacity: 0.35,
    color: severityColor(p.severity_score),
    weight: 2.5,
    dashArray: null,
  };
}

function hexPopup(p) {
  return `
    <div><b>H3 cell</b> ${p.h3}</div>
    <div><b>Orders</b> ${p.order_count}</div>
    <div><b>Late rate</b> ${(p.late_rate * 100).toFixed(1)}%</div>
    <div><b>Avg delay</b> ${p.avg_delay_minutes.toFixed(1)} min</div>
    <div><b>Friction score</b> ${p.friction_score.toFixed(3)}</div>
    <div><b>Gi* z-score</b> ${p.gi_z !== null ? p.gi_z.toFixed(2) : "n/a"}</div>
    <div><b>Confidence</b> ${p.confidence}%</div>
    <div><b>Spot type</b> ${p.spot_type}</div>
  `;
}

function clusterPopup(p) {
  return `
    <div><b>Cluster</b> #${p.cluster_id}</div>
    <div><b>Hex count</b> ${p.hex_count}</div>
    <div><b>Mean friction</b> ${p.mean_friction.toFixed(3)}</div>
    <div><b>Mean Gi* z</b> ${p.mean_z.toFixed(2)}</div>
    <div><b>Confidence</b> ${p.confidence_level}%</div>
    <div><b>Severity score</b> ${p.severity_score.toFixed(3)}</div>
    <div><b>Intervention</b> ${p.intervention_tier}</div>
    <div><b>Suggested bonus</b> +${p.suggested_bonus_pct}%</div>
  `;
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function applyLayerVisibility() {
  if (hexLayer) {
    if (visible.hexes && !map.hasLayer(hexLayer)) hexLayer.addTo(map);
    if (!visible.hexes && map.hasLayer(hexLayer)) map.removeLayer(hexLayer);
  }
  if (clusterLayer) {
    if (visible.clusters && !map.hasLayer(clusterLayer)) clusterLayer.addTo(map);
    if (!visible.clusters && map.hasLayer(clusterLayer)) map.removeLayer(clusterLayer);
  }
}

function renderClusterList(clustersGeoJSON) {
  const list = document.getElementById("cluster-list");
  list.innerHTML = "";
  const features = [...clustersGeoJSON.features].sort(
    (a, b) => b.properties.severity_score - a.properties.severity_score
  );
  for (const f of features) {
    const p = f.properties;
    const li = document.createElement("li");
    li.className = "cluster-item";
    li.style.borderLeftColor = severityColor(p.severity_score);
    li.innerHTML = `
      <div class="row1">
        <span>Cluster #${p.cluster_id}</span>
        <span class="severity-badge">${p.severity_score.toFixed(2)}</span>
      </div>
      <div class="tier">${p.intervention_tier} &middot; +${p.suggested_bonus_pct}% &middot; ${p.hex_count} hexes</div>
    `;
    li.addEventListener("click", () => {
      const [lng, lat] = p.centroid;
      map.setView([lat, lng], 12);
    });
    list.appendChild(li);
  }
}

async function loadBoundary() {
  if (boundaryLayer) map.removeLayer(boundaryLayer);
  const boundaryGeoJSON = await fetchJSON(`/api/boundary?metro=${currentMetro}`);
  boundaryLayer = L.geoJSON(boundaryGeoJSON, {
    style: {
      fill: false,
      color: "#1e3a8a",
      weight: 2.5,
    },
    interactive: false,
  }).addTo(map);
}

async function loadAll() {
  const [hexesGeoJSON, clustersGeoJSON, stats] = await Promise.all([
    fetchJSON(`/api/hexes?metro=${currentMetro}`),
    fetchJSON(`/api/clusters?metro=${currentMetro}`),
    fetchJSON(`/api/stats?metro=${currentMetro}`),
  ]);

  if (hexLayer) map.removeLayer(hexLayer);
  if (clusterLayer) map.removeLayer(clusterLayer);

  hexLayer = L.geoJSON(hexesGeoJSON, {
    style: styleHex,
    onEachFeature: (feature, layer) => layer.bindPopup(hexPopup(feature.properties)),
  });

  clusterLayer = L.geoJSON(clustersGeoJSON, {
    style: styleCluster,
    onEachFeature: (feature, layer) => layer.bindPopup(clusterPopup(feature.properties)),
  });

  applyLayerVisibility();
  if (boundaryLayer) boundaryLayer.bringToFront();
  renderClusterList(clustersGeoJSON);

  document.getElementById("stats-readout").textContent =
    `${stats.total_orders.toLocaleString()} orders · ${stats.hex_count.toLocaleString()} hexes · ` +
    `${stats.cluster_count} clusters · avg friction ${stats.mean_friction_score.toFixed(3)}`;
}

document.querySelectorAll(".seg-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const layerName = btn.dataset.layer;
    visible[layerName] = !visible[layerName];
    btn.classList.toggle("active", visible[layerName]);
    applyLayerVisibility();
  });
});

document.getElementById("reshuffle-btn").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Reshuffling...";
  try {
    await fetchJSON(`/api/regenerate?metro=${currentMetro}`, { method: "POST" });
    await loadAll();
  } finally {
    btn.disabled = false;
    btn.textContent = "Reshuffle Data";
  }
});

async function switchMetro(metro) {
  if (metro.id === currentMetro) return;
  currentMetro = metro.id;
  document.querySelectorAll(".metro-btn").forEach((b) => b.classList.toggle("active", b.dataset.metroId === metro.id));
  map.setView(metro.center, metro.zoom);
  await Promise.all([loadBoundary(), loadAll()]);
}

async function initMetroToggle() {
  const { metros } = await fetchJSON("/api/metros");
  const container = document.getElementById("metro-toggle");
  container.innerHTML = "";
  metros.forEach((metro, i) => {
    const btn = document.createElement("button");
    btn.className = "seg-btn metro-btn" + (i === 0 ? " active" : "");
    btn.dataset.metroId = metro.id;
    btn.textContent = metro.name;
    btn.addEventListener("click", () => switchMetro(metro));
    container.appendChild(btn);
  });

  const initial = metros[0];
  currentMetro = initial.id;
  map.setView(initial.center, initial.zoom);
}

async function init() {
  await initMetroToggle();
  await Promise.all([loadBoundary(), loadAll()]);
}

init().catch((err) => {
  console.error(err);
  document.getElementById("stats-readout").textContent = "Failed to load data — see console.";
});
