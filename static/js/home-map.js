/*
 * Homepage aggregate map — Phase 2b, final piece
 * (docs/dev/bulliexplorer_experience_2027.md). Deliberately a small,
 * standalone script, not an extension of post-map.js: this phase's own
 * explicit non-goals rule out marker clustering, vector-tile
 * infrastructure, and anything post-map.js's much larger feature set
 * (amenity overlay, CyclOSM toggle, elevation-chart sync) would pull in
 * — "a plain FeatureCollection... is more than sufficient" at this post
 * count.
 *
 * Only ever loaded by the deferred-injection script in home.html, itself
 * only triggered once #explore-map scrolls near the viewport — this
 * file, maplibre-gl.js, pmtiles.js, and basemaps.js are all absent from
 * the page entirely until then (Phase 2b's performance-spike PASS
 * result this depends on). window.maplibregl/pmtiles/basemaps are
 * therefore guaranteed present by the time this runs — home.html's own
 * onload chain loads them in that exact order first.
 *
 * Data comes from GET /trips.geojson (Phase 2b, Step 3) — fetched here,
 * not inlined into the page, since it's fetched only after this script
 * itself is already deferred behind the same intersection gate.
 */
(function () {
  "use strict";

  var container = document.getElementById("explore-map");
  if (!container) return;

  function currentFlavor() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  // Same WCAG-checked route line colours as static/js/post-map.js
  // (fix_amenity_overlay_ux.md / the contrast fix referenced there) —
  // kept in sync manually since this is a separate, smaller file by
  // design; not worth a shared-constants module for two colour pairs.
  function routeLineColor(flavor) {
    return flavor === "dark" ? "#f0954a" : "#b85c00";
  }

  function poiPointColor(flavor) {
    return flavor === "dark" ? "#4dd0e1" : "#00838f";
  }

  // Same slug shape every real slug in this project actually has
  // (lowercase letters/digits/hyphens, generated server-side — see
  // app/models/post.py). properties.slug always comes from our own
  // GET /trips.geojson response (server-controlled, sourced from the
  // Post.slug DB column), but validating it explicitly before building
  // a navigation URL removes any ambiguity rather than relying on that
  // trust chain alone.
  var SAFE_SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

  function navigateToPost(slug) {
    if (typeof slug !== "string" || !SAFE_SLUG_PATTERN.test(slug)) return;
    // Always a same-origin, relative, root-anchored path built from an
    // already-regex-validated slug — encodeURIComponent() is redundant
    // given that validation (the pattern has no encodable characters)
    // but is a defensible, cheap extra layer, not load-bearing on its own.
    window.location.assign("/posts/" + encodeURIComponent(slug));
  }

  var flavor = currentFlavor();

  var protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  var map = new maplibregl.Map({
    container: "explore-map",
    style: {
      version: 8,
      glyphs: "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
      sprite: "https://protomaps.github.io/basemaps-assets/sprites/v4/" + flavor,
      sources: {
        protomaps: {
          type: "vector",
          url: container.dataset.tilesUrl,
          attribution:
            '<a href="https://protomaps.com">Protomaps</a> \u00a9 ' +
            '<a href="https://openstreetmap.org">OpenStreetMap</a>',
        },
      },
      layers: basemaps.layers("protomaps", basemaps.namedFlavor(flavor), { lang: "de" }),
    },
    // Rough Central-Europe default — overridden once trips load and the
    // map fits their combined bounds. Only matters for the brief moment
    // before that fetch resolves, or if it returns zero features.
    center: [8.0, 48.5],
    zoom: 5,
    attributionControl: false,
  });

  map.addControl(new maplibregl.AttributionControl({ compact: true }));
  map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }));

  map.on("load", function () {
    fetch("/trips.geojson")
      .then(function (response) {
        return response.json();
      })
      .then(function (geojson) {
        var features = (geojson && geojson.features) || [];
        if (features.length === 0) {
          // Empty site / every published post lacks both a route and a
          // POI — GET /trips.geojson's own documented, valid empty
          // state. The section (heading + map) hides entirely rather
          // than showing an empty grey box; matches home.html's
          // existing "No posts yet" philosophy for the rest of the page.
          var section = container.closest(".explore-map-section");
          if (section) section.hidden = true;
          return;
        }

        map.addSource("trips", { type: "geojson", data: geojson });

        map.addLayer({
          id: "trips-routes",
          type: "line",
          source: "trips",
          filter: ["==", ["get", "tier"], "route"],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": routeLineColor(flavor), "line-width": 2.5 },
        });

        map.addLayer({
          id: "trips-poi-only",
          type: "circle",
          source: "trips",
          filter: ["==", ["get", "tier"], "poi_only"],
          paint: {
            "circle-radius": 6,
            "circle-color": poiPointColor(flavor),
            "circle-stroke-width": 2,
            "circle-stroke-color": "#fff",
          },
        });

        // Click behaviour (decided, per the doc's Phase 2b product
        // decisions): navigate straight to the post, no inline popup.
        ["trips-routes", "trips-poi-only"].forEach(function (layerId) {
          map.on("click", layerId, function (e) {
            navigateToPost(e.features[0].properties.slug);
          });
          map.on("mouseenter", layerId, function () {
            map.getCanvas().style.cursor = "pointer";
          });
          map.on("mouseleave", layerId, function () {
            map.getCanvas().style.cursor = "";
          });
        });

        // Fit the viewport to every feature's own coordinates — a
        // LineString's coordinate array or a Point's single [lng, lat]
        // pair, handled the same way (extend() takes either).
        var bounds;
        features.forEach(function (feature) {
          var geom = feature.geometry;
          var coordsList = geom.type === "Point" ? [geom.coordinates] : geom.coordinates;
          coordsList.forEach(function (c) {
            bounds = bounds ? bounds.extend(c) : new maplibregl.LngLatBounds(c, c);
          });
        });
        if (bounds) map.fitBounds(bounds, { padding: 32, maxZoom: 10 });
      })
      .catch(function () {
        // A failed fetch (network blip, etc.) leaves the base map
        // visible with no trip overlay — degrades gracefully rather
        // than throwing, consistent with post-map.js's own amenities-
        // fetch error handling.
      });
  });
})();
