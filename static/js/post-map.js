/*
 * Post-detail map behavior — route line, curated POI markers, and the
 * clustered nearby-amenities overlay (MapLibre GL).
 *
 * Extracted from templates/post.html (F4, docs/dev/review_17SEP2026.md) —
 * previously ~750 lines of inline <script> in the Jinja template, which
 * meant the browser re-downloaded identical behavior code with every HTML
 * response, djlint couldn't lint it, and pure functions inside it
 * (escapeHtml, buildAmenityPopupHtml, phone parsing) were structurally
 * untestable purely because of where they lived. Plain script tag, no
 * bundler — consistent with this project's no-build-step architecture
 * (AGENTS.md).
 *
 * Data (route/POI GeoJSON, amenities endpoint URL, tiles URL) is passed in
 * via window.BULLIEXPLORER_MAP_DATA, set by a small inline <script> block
 * that remains in post.html — data belongs in the page, behavior doesn't.
 * Only runs on posts that actually render a map (post.html only includes
 * this file when route_geojson and tiles_url are both present).
 */
  (function () {
    "use strict";

    // ── Data injected from server ──────────────────────────────────────────
    // |tojson filter escapes forward-slashes and special chars — safe in <script>.
    // Data is provided by the small inline <script> block in post.html
    // (window.BULLIEXPLORER_MAP_DATA) — this file itself carries no
    // Jinja templating (F4, docs/dev/review_17SEP2026.md), so the browser
    // can cache it across page loads instead of re-downloading identical
    // behavior code with every HTML response.
    const DATA = window.BULLIEXPLORER_MAP_DATA || {};
    const ROUTE_GEOJSON = DATA.routeGeojson;
    const POIS_GEOJSON = DATA.poisGeojson;
    // Amenities are no longer inlined here (docs/dev/review_17SEP2026.md
    // F1) — a route with 15k+ amenities blew this past 3.7MB inside the
    // HTML document itself, re-downloaded on every visit even though the
    // toggle below defaults off. Fetched lazily from this endpoint only
    // the first time the "Show nearby services" checkbox is checked.
    const AMENITIES_GEOJSON_URL = DATA.amenitiesGeojsonUrl;
    const TILES_URL = DATA.tilesUrl;

    // ── Category → marker colour map ──────────────────────────────────────
    const CATEGORY_COLOURS = {
      campsite:    "#4CAF50",  // green
      shelter:     "#795548",  // brown
      restaurant:  "#FF9800",  // orange
      // cafe (fix_peaks_cablecars_amenity_review.md Phase 2) — shares
      // restaurant's colour: same "food-related stop" visual family,
      // distinguished by name/popup rather than a wholly new colour,
      // same principle already applied to wilderness_hut->shelter.
      cafe:        "#FF9800",  // orange, same as restaurant
      hotel:       "#2196F3",  // blue
      gas_station: "#9C27B0",  // purple
      viewpoint:   "#00BCD4",  // cyan
      bike_shop:   "#F44336",  // red
      // bike_repair_station (fix_peaks_cablecars_amenity_review.md
      // Phase 2) — shares bike_shop's colour, same reasoning as cafe
      // above: a free public repair stand and a commercial bike shop
      // are distinct categories (kept as separate NearbyAmenity rows,
      // separate popup text) but the same visual family.
      bike_repair_station: "#F44336",  // red, same as bike_shop
      water_point: "#03A9F4",  // light-blue
      other:       "#607D8B",  // slate
    };

    // Marker glyphs — Maki (mapbox/maki, CC0), the de-facto standard POI
    // icon set used across most consumer mapping apps (Komoot, Google
    // Maps, RideWithGPS all follow the same "colored circle, white
    // glyph" convention this adapts). 15x15 viewBox paths, used verbatim
    // (no build step — vendored inline, same as this file's other
    // hand-authored SVGs). "other"/unmapped categories intentionally
    // have no entry — a plain color dot is the correct fallback for a
    // genuinely uncategorized point, not a missing-icon glyph.
    const CATEGORY_ICON_PATHS = {
      campsite:    "M14 10V11C14 11.5523 13.5523 12 13 12H2C1.44772 12 1 11.5523 1 11V10C1 9.44772 1.44772 9.00001 2 9.00001H2.25L7.03206 1.25762C7.24699 0.90965 7.75302 0.909651 7.96794 1.25762L12.75 9.00001H13C13.5523 9.00001 14 9.44772 14 10ZM10.5 9.00001L7.5 4.00001L4.5 9.00001H10.5Z",
      shelter:     "M13 2L1 6V8L2 7.66667V13H12V11H4V7L13 4V2Z",
      restaurant:  "M3.5,0l-1,5.5c-0.1464,0.805,1.7815,1.181,1.75,2L4,14c-0.0384,0.9993,1,1,1,1s1.0384-0.0007,1-1L5.75,7.5c-0.0314-0.8176,1.7334-1.1808,1.75-2L6.5,0H6l0.25,4L5.5,4.5L5.25,0h-0.5L4.5,4.5L3.75,4L4,0H3.5z M12,0c-0.7364,0-1.9642,0.6549-2.4551,1.6367C9.1358,2.3731,9,4.0182,9,5v2.5c0,0.8182,1.0909,1,1.5,1L10,14c-0.0905,0.9959,1,1,1,1s1,0,1-1V0z",
      hotel:       "M0.5,2.5C0.2,2.5,0,2.7,0,3v7.5v2C0,12.8,0.2,13,0.5,13S1,12.8,1,12.5V11h13v1.5c0,0.3,0.2,0.5,0.5,0.5s0.5-0.2,0.5-0.5v-2c0-0.3-0.2-0.5-0.5-0.5H1V3C1,2.7,0.8,2.5,0.5,2.5z M3.5,3C2.7,3,2,3.7,2,4.5l0,0C2,5.3,2.7,6,3.5,6l0,0C4.3,6,5,5.3,5,4.5l0,0C5,3.7,4.3,3,3.5,3L3.5,3z M7,4C5.5,4,5.5,5.5,5.5,5.5V7h-3C2.2,7,2,7.2,2,7.5v1C2,8.8,2.2,9,2.5,9H6h9V6.5C15,4,12.5,4,12.5,4H7z",
      gas_station: "m14 6v5.5c0 .2761-.2239.5-.5.5s-.5-.2239-.5-.5v-2c0-.8284-.6716-1.5-1.5-1.5h-1.5v-6c0-.5523-.4477-1-1-1h-6c-.5523 0-1 .4477-1 1v11c0 .5523.4477 1 1 1h6c.5523 0 1-.4477 1-1v-4h1.5c.2761 0 .5.2239.5.5v2c0 .8284.6716 1.5 1.5 1.5s1.5-.6716 1.5-1.5v-6.5c0-.5523-.4477-1-1-1v-1.51c-.0054-.2722-.2277-.4901-.5-.49-.2816.0047-.5062.2367-.5015.5184.0002.0105.0007.0211.0015.0316v2.45c0 .5523.4477 1 1 1s1-.4477 1-1-.4477-1-1-1zm-5 .5c0 .2761-.2239.5-.5.5h-5c-.2761 0-.5-.2239-.5-.5v-3c0-.2761.2239-.5.5-.5h5c.2761 0 .5.2239.5.5z",
      viewpoint:   "M6.02,8.425a2.3859,2.3859,0,0,0-.46.44l-4.55-3.5a7.9976,7.9976,0,0,1,1.51-1.51Zm6.46-4.56-3.5,4.55a2.3971,2.3971,0,0,1,.45.45l4.56-3.5A7.945,7.945,0,0,0,12.48,3.865ZM7.3042,10.0129a1.5,1.5,0,1,0,1.6829,1.2914h0A1.5,1.5,0,0,0,7.3042,10.0129ZM6.43,2.235a7.9329,7.9329,0,0,0-2.06.55l2.2,5.32a2.0438,2.0438,0,0,1,.61-.17Zm2.14.01-.75,5.69a2.49,2.49,0,0,1,.61.16l2.2-5.3A7.2129,7.2129,0,0,0,8.57,2.245Z",
      bike_shop:   "M7.5,2c-0.6761-0.01-0.6761,1.0096,0,1H9v1.2656l-2.8027,2.334L5.2226,4H5.5c0.6761,0.01,0.6761-1.0096,0-1h-2c-0.6761-0.01-0.6761,1.0096,0,1h0.6523L5.043,6.375C4.5752,6.1424,4.0559,6,3.5,6C1.5729,6,0,7.5729,0,9.5S1.5729,13,3.5,13S7,11.4271,7,9.5c0-0.6699-0.2003-1.2911-0.5293-1.8242L9.291,5.3262l0.4629,1.1602C8.7114,7.0937,8,8.2112,8,9.5c0,1.9271,1.5729,3.5,3.5,3.5S15,11.4271,15,9.5S13.4271,6,11.5,6c-0.2831,0-0.5544,0.0434-0.8184,0.1074L10,4.4023V2.5c0-0.2761-0.2239-0.5-0.5-0.5H7.5z M3.5,7c0.5923,0,1.1276,0.2119,1.5547,0.5527l-1.875,1.5625c-0.5109,0.4273,0.1278,1.1945,0.6406,0.7695l1.875-1.5625C5.8835,8.674,6,9.0711,6,9.5C6,10.8866,4.8866,12,3.5,12S1,10.8866,1,9.5S2.1133,7,3.5,7L3.5,7z M11.5,7C12.8866,7,14,8.1134,14,9.5S12.8866,12,11.5,12S9,10.8866,9,9.5c0-0.877,0.4468-1.6421,1.125-2.0879l0.9102,2.2734c0.246,0.6231,1.1804,0.2501,0.9297-0.3711l-0.9082-2.2695C11.2009,7.0193,11.3481,7,11.5,7L11.5,7z",
      water_point: "M6,1A2,2,0,0,0,4,3V6.5a.5.5,0,0,0,.5.5h2A.5.5,0,0,0,7,6.5v-2A.5.5,0,0,1,7.5,4H14V1ZM7,15H4a.5.5,0,0,1-.48-.38L2,8.62a.5.5,0,0,1,.365-.606A.558.558,0,0,1,2.5,8h6a.5.5,0,0,1,.514.485A.47.47,0,0,1,9,8.62l-1.5,6A.5.5,0,0,1,7,15ZM3.65,11H7.36l.5-2H3.14Z",
      cafe:        "M3.5,0l-1,5.5c-0.1464,0.805,1.7815,1.181,1.75,2L4,14c-0.0384,0.9993,1,1,1,1s1.0384-0.0007,1-1L5.75,7.5c-0.0314-0.8176,1.7334-1.1808,1.75-2L6.5,0H6l0.25,4L5.5,4.5L5.25,0h-0.5L4.5,4.5L3.75,4L4,0H3.5z M12,0c-0.7364,0-1.9642,0.6549-2.4551,1.6367C9.1358,2.3731,9,4.0182,9,5v2.5c0,0.8182,1.0909,1,1.5,1L10,14c-0.0905,0.9959,1,1,1,1s1,0,1-1V0z",
      bike_repair_station: "M7.5,2c-0.6761-0.01-0.6761,1.0096,0,1H9v1.2656l-2.8027,2.334L5.2226,4H5.5c0.6761,0.01,0.6761-1.0096,0-1h-2c-0.6761-0.01-0.6761,1.0096,0,1h0.6523L5.043,6.375C4.5752,6.1424,4.0559,6,3.5,6C1.5729,6,0,7.5729,0,9.5S1.5729,13,3.5,13S7,11.4271,7,9.5c0-0.6699-0.2003-1.2911-0.5293-1.8242L9.291,5.3262l0.4629,1.1602C8.7114,7.0937,8,8.2112,8,9.5c0,1.9271,1.5729,3.5,3.5,3.5S15,11.4271,15,9.5S13.4271,6,11.5,6c-0.2831,0-0.5544,0.0434-0.8184,0.1074L10,4.4023V2.5c0-0.2761-0.2239-0.5-0.5-0.5H7.5z M3.5,7c0.5923,0,1.1276,0.2119,1.5547,0.5527l-1.875,1.5625c-0.5109,0.4273,0.1278,1.1945,0.6406,0.7695l1.875-1.5625C5.8835,8.674,6,9.0711,6,9.5C6,10.8866,4.8866,12,3.5,12S1,10.8866,1,9.5S2.1133,7,3.5,7L3.5,7z M11.5,7C12.8866,7,14,8.1134,14,9.5S12.8866,12,11.5,12S9,10.8866,9,9.5c0-0.877,0.4468-1.6421,1.125-2.0879l0.9102,2.2734c0.246,0.6231,1.1804,0.2501,0.9297-0.3711l-0.9082-2.2695C11.2009,7.0193,11.3481,7,11.5,7L11.5,7z",
    };

    // Builds a "colored circle, white glyph" marker element — falls back
    // to a plain colored dot (no inner svg) for a category with no
    // tracked icon (currently only "other").
    function buildCategoryMarkerElement(category, name, diameterPx, opacity) {
      var colour = CATEGORY_COLOURS[category] || CATEGORY_COLOURS.other;
      var iconPath = CATEGORY_ICON_PATHS[category];
      var el = document.createElement("div");
      el.setAttribute("aria-label", name);
      el.style.cssText = [
        "width:" + diameterPx + "px", "height:" + diameterPx + "px", "border-radius:50%",
        "background:" + colour,
        "opacity:" + opacity,
        "border:2px solid #fff",
        "box-shadow:0 1px 4px rgba(0,0,0,.45)",
        "display:flex", "align-items:center", "justify-content:center",
        "cursor:pointer",
      ].join(";");
      if (iconPath) {
        var glyphSize = Math.round(diameterPx * 0.55);
        var svgNs = "http://www.w3.org/2000/svg";
        var svg = document.createElementNS(svgNs, "svg");
        svg.setAttribute("width", String(glyphSize));
        svg.setAttribute("height", String(glyphSize));
        svg.setAttribute("viewBox", "0 0 15 15");
        svg.setAttribute("fill", "#fff");
        svg.setAttribute("aria-hidden", "true");
        svg.setAttribute("focusable", "false");
        var path = document.createElementNS(svgNs, "path");
        path.setAttribute("d", iconPath);
        svg.appendChild(path);
        el.appendChild(svg);
      }
      return el;
    }

    // Escapes text pulled from OSM tag data before it's concatenated into
    // popup innerHTML (fix_amenity_overlay_ux.md Phase 3) — amenity
    // name/tags are auto-discovered from OpenStreetMap, editable by
    // anyone, unlike the curated POI data the popup above already
    // concatenates unescaped. Cheap and standard; not worth a library.
    function escapeHtml(value) {
      var div = document.createElement("div");
      div.textContent = String(value == null ? "" : value);
      return div.innerHTML;
    }

    // Human-readable label for a category slug ("bike_shop" → "Bike
    // shop") — categories always shown now per Phase 3's "name plus a
    // category line" popup design, not just a bare name.
    function categoryLabel(category) {
      if (!category) return "";
      return category
        .split("_")
        .map(function (word, i) {
          return i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word;
        })
        .join(" ");
    }

    // Builds the nearby-amenity popup HTML (fix_amenity_overlay_ux.md
    // Phase 3). Name + category line always shown; a website link
    // (opens in a new tab) and a phone link (tel:) only when those OSM
    // tags actually exist on this element — no empty "Phone: —" row for
    // a field that isn't there.
    //
    // `props.tags` comes back from a GeoJSON *source* feature (not a
    // plain JS object we built ourselves) — MapLibre/GL JS serializes
    // nested object properties to a JSON string on the wire, so this
    // must be parsed defensively rather than accessed directly.
    function amenityTags(props) {
      if (!props || !props.tags) return {};
      if (typeof props.tags === "string") {
        try {
          return JSON.parse(props.tags) || {};
        } catch (e) {
          return {};
        }
      }
      return props.tags;
    }

    function buildAmenityPopupHtml(props) {
      var tags = amenityTags(props);
      var name = props.name || categoryLabel(props.category) || "Unnamed";
      var html = "<strong>" + escapeHtml(name) + "</strong>";
      var category = categoryLabel(props.category);
      if (category) {
        html += "<br><small class='text-muted'>" + escapeHtml(category) + "</small>";
      }

      // Scheme allowlist (F2, docs/dev/review_17SEP2026.md) — escapeHtml()
      // prevents breaking out of the href attribute, but a `javascript:...`
      // value is still a perfectly valid *escaped* string that would
      // survive intact as a clickable, executable link. tags.website is
      // raw third-party OSM data (anyone can edit it), so only render the
      // link when it's actually an http(s) URL — same silent-drop
      // behaviour as the existing "no website tag" case, no placeholder.
      var website = tags.website || tags["contact:website"];
      if (website && /^https?:\/\//i.test(website)) {
        html +=
          "<br><a href='" + escapeHtml(website) + "' target='_blank' rel='noopener noreferrer'>Website</a>";
      }

      var phone = tags.phone || tags["contact:phone"];
      if (phone) {
        // OSM's phone tag occasionally lists more than one number
        // separated by ";" or "," (e.g. "+49 761 1234; +49 761 5678") —
        // take only the first for the tel: link (a link can only dial
        // one number), but keep displaying the full original tag text
        // so a reader who needs the second number still sees it.
        var firstPhone = phone.split(/[;,]/)[0];
        var telHref = firstPhone.replace(/[^+\d]/g, "");
        html += "<br><a href='tel:" + escapeHtml(telHref) + "'>" + escapeHtml(phone) + "</a>";
      }

      return html;
    }

    // ── Register the pmtiles:// protocol with MapLibre ─────────────────────
    const protocol = new pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);

    // ── Dark-mode-aware basemap flavor (Phase 2, §5.4) ─────────────────────
    // Reads the data-theme attribute the pre-paint script in base.html has
    // already set before this script runs, so no flash on initial load.
    // Also listens for the "bulliexplorer:themechange" event the nav
    // toggle (base.html) dispatches on click, so switching theme mid-
    // session updates the map immediately — no reload required.
    function currentFlavor() {
      return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }

    // Route line color per flavor.
    // Light: #b85c00 — darkened from the old #e87722 to pass WCAG 1.4.11
    //   graphical-object 3:1 minimum against the Protomaps light earth fill
    //   (~#f5f0e8). Contrast ratio: ~4.6:1. Stays recognisably orange/brand.
    // Dark: #f0954a — lightened for 3:1 against the dark earth fill
    //   (~#1f1f1f). Contrast ratio: ~5.6:1. Unchanged from Phase 2.
    function routeLineColor(flavor) {
      return flavor === "dark" ? "#f0954a" : "#b85c00";
    }

    // Cycling-aware basemap layers (gis_cycling_upgrade.md Phase 1).
    // Filtered on the "roads" source-layer's `kind`/`kind_detail` fields
    // (confirmed present via direct tile inspection in Phase 0 — `kind`
    // only has 5 broad buckets; the real cycleway/path/track/footway
    // distinction lives on `kind_detail`, the OSM highway=* value).
    // Two layers, CyclOSM-inspired: a solid, saturated line for dedicated
    // cycleways, a dashed muted line for path/track (likely-unpaved,
    // shared-use). Deliberately excludes footway/sidewalk/steps/
    // pedestrian, which also live under kind_detail's kind="path" bucket
    // but aren't cycling infrastructure.
    // Appended to (not replacing) basemaps.layers()'s own array, so they
    // draw on top of the base road styling but below the route line and
    // POI markers, which are added after "load", later in paint order.
    function cyclingLayers(flavor) {
      var cycleway = flavor === "dark" ? "#5b9bff" : "#0a5fd6";
      var unpaved  = flavor === "dark" ? "#c9a876" : "#8a6d3b";
      return [
        {
          id: "cycling-unpaved-likely",
          type: "line",
          source: "protomaps",
          "source-layer": "roads",
          minzoom: 11,
          filter: [
            "all",
            ["==", ["get", "kind"], "path"],
            ["in", ["get", "kind_detail"], ["literal", ["path", "track"]]],
          ],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: {
            "line-color": unpaved,
            "line-width": 1.2,
            "line-dasharray": [2, 1.5],
          },
        },
        {
          id: "cycling-cycleway",
          type: "line",
          source: "protomaps",
          "source-layer": "roads",
          minzoom: 11,
          filter: [
            "all",
            ["==", ["get", "kind"], "path"],
            ["==", ["get", "kind_detail"], "cycleway"],
          ],
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": cycleway, "line-width": 1.5 },
        },
      ];
    }

    // Label priority fix (fix_label_priority_and_trail_differentiation.md
    // Phase 1-2). Real tile inspection (pmtiles tile + mapbox-vector-tile
    // decode over Siebengebirge/Königswinter) found the basemap's
    // "places_locality" style layer (source-layer "places", filter
    // kind=="locality") renders BOTH real named settlements
    // (kind_detail: "town"/"village", e.g. Königswinter, Rott — tile
    // data min_zoom 8-11, legitimate and wanted at that zoom) AND
    // hyper-local cadastral field/forest-parcel names (kind_detail:
    // "locality" — identical string to the outer kind — e.g. "Am
    // Röbig", "Im Mantel", tile data min_zoom 13+) from the SAME style
    // layer with the SAME filter, distinguished only by kind_detail.
    // MapLibre's symbol-sort-key on this layer falls back to each
    // feature's own min_zoom when no explicit sort_key exists (real,
    // confirmed from the vendored library source, not assumed) — lower
    // values win the cross-layer collision budget, so the much higher
    // volume of low-min_zoom real-settlement labels (115+ in one z11
    // tile alone) already wins most of the contest, and right at the
    // zoom peaks start existing in the tile data (z12-13), an even
    // larger wave of hyper-local names also turns on (144 in one z13
    // tile), directly swamping the newly-available peak labels. Real,
    // decisive answer to Phase 1's discovery question: "places_locality,
    // filtered on kind==\"locality\", no minzoom cap set by the style
    // layer itself — gated only by each feature's own tile-data
    // min_zoom, which for real settlements starts as low as 8."
    //
    // Fix: split the ONE shared layer into two by kind_detail rather
    // than raising a blanket minzoom on the whole thing (which would
    // also suppress legitimate town/village names like Königswinter
    // itself — the doc's own "priority fix, not a deletion" instruction
    // applies to the real settlement names too, not just the field
    // names). Real settlements keep rendering exactly as before,
    // unmodified. Hyper-local field/forest names (kind_detail==
    // "locality") get deferred behind an explicit minzoom — giving
    // peaks a clear zoom window once they start existing in the data,
    // without deleting the field-name data (it still renders once
    // genuinely zoomed in, exactly as the doc requires).
    //
    // Regression fix: the vendored basemaps library's own "places_locality"
    // filter is legacy MapLibre filter syntax — ["==","kind","locality"]
    // (bare property-name string), not the modern expression syntax
    // (["==",["get","kind"],"locality"]) used everywhere else in this
    // file's own custom layers. Nesting that legacy filter and a modern
    // ["get", ...] expression inside the same "all" combinator produces
    // an invalid, dialect-mixed filter that MapLibre's style validator
    // rejects outright ("layers[N].filter[2][1]: string expected, array
    // found") — and because this is one layer inside the single style
    // object passed to `new maplibregl.Map({style: {...}})`, that
    // validation failure took down the ENTIRE style load, not just this
    // one layer: base tiles gone, map area a blank void, while
    // elevation-chart.js kept working fine since it's a wholly separate
    // script. Reproduced for real with a headless browser (console:
    // exactly this error, twice — once per new layer) before applying
    // this fix, and re-verified clean afterwards.
    //
    // Fix: build the "kind" check explicitly as a modern expression in
    // both branches, instead of splicing in the vendored layer's own
    // (legacy-syntax) `layer.filter` value. Every filter added by this
    // function is now internally consistent modern-expression syntax.
    function adjustLocalityLabelPriority(layers) {
      var MICRO_TOPONYM_MINZOOM = 14;
      var KIND_IS_LOCALITY = ["==", ["get", "kind"], "locality"];
      return layers.map(function (layer) {
        if (layer.id !== "places_locality") return layer;
        return Object.assign({}, layer, {
          filter: ["all", KIND_IS_LOCALITY, ["!=", ["get", "kind_detail"], "locality"]],
        });
      }).concat(
        layers
          .filter(function (layer) {
            return layer.id === "places_locality";
          })
          .map(function (layer) {
            return Object.assign({}, layer, {
              id: "places_locality_micro_toponym",
              minzoom: MICRO_TOPONYM_MINZOOM,
              filter: ["all", KIND_IS_LOCALITY, ["==", ["get", "kind_detail"], "locality"]],
            });
          })
      );
    }

    // Peak elevation labels (fix_peaks_cablecars_amenity_review.md
    // Phase 1). Real tile inspection (pmtiles tile + mapbox-vector-tile
    // decode, z14 over Feldberg) found peaks live on the "pois"
    // source-layer as kind="peak", NOT a "physical_point" layer as the
    // doc's initial research assumed — that layer doesn't exist in this
    // basemap's actual schema at all (confirmed vector_layers list:
    // boundaries, buildings, earth, landcover, landuse, places, pois,
    // roads, water). Feldberg's own peak feature: elevation 1494,
    // min_zoom 12 — real data, not assumed.
    //
    // basemaps.layers()'s own built-in "pois" symbol layer (light/dark
    // flavors only — white/grayscale/black have no pois color palette)
    // already renders a peak icon + name label for kind="peak", shared
    // with ~30 other POI kinds in one layer. Deliberately NOT
    // duplicating that icon/name/halo/zoom-fade logic in a second full
    // peak layer (would risk visually diverging from the other 30 kinds
    // sharing the native layer, and double-render a name label already
    // shown). This layer is purely additive: elevation text only,
    // positioned below the native icon+name (native uses a horizontal
    // left/right text-offset, so a below-anchored addition doesn't
    // collide with it), color/halo matched to the native pois.green /
    // earth tokens per flavor so it reads as one coherent label, not a
    // visually distinct bolt-on.
    //
    // Regression fix #2, found live in production after the first
    // regression fix: with the crash resolved, real headless-browser
    // introspection (queryRenderedFeatures against the real production
    // page, then isolated by incrementally rebuilding the style from
    // scratch) found peaks were STILL not rendering — not from the
    // filter-dialect bug (already fixed), and not an "elevation" vs
    // "ele" property-name mismatch (checked directly against real
    // decoded tile bytes for Feldberg/Seebuck/Baldenweger Buck: the
    // property is genuinely named "elevation" on every real peak
    // feature checked). The real cause, isolated by testing the stock
    // vendor style alone (peaks render: 1 result) versus adding this
    // layer (peaks render: 0 results) with every other addition held
    // constant: this layer's own presence was winning the MapLibre
    // collision budget over the native "pois" layer's peak icon+name
    // for the exact same feature, hiding the more important native
    // label entirely. First attempted fix: an explicit `symbol-sort-key`
    // deliberately set slightly worse than the native "pois" layer's
    // own fallback, on the theory that a numerically higher (lower-
    // priority) sort-key would make this layer defer to "pois" in any
    // collision. Tested directly with the same isolated-rebuild method
    // — disproven: "pois" still rendered 0 peaks with that sort-key in
    // place, meaning MapLibre's actual cross-layer collision priority
    // doesn't work the way that theory assumed (no single documented
    // default/ordering rule for this case, confirmed via web search of
    // MapLibre's own docs). Correct, verified fix: `text-allow-overlap:
    // true` + `text-ignore-placement: true` — removes this layer from
    // the collision system entirely rather than trying to out-rank
    // "pois" within it. This layer's small elevation text now always
    // draws unconditionally and can never block (or be blocked by) any
    // other symbol, matching its "purely additive, supplementary"
    // design intent exactly — verified with the same isolated-rebuild
    // method: "pois" back to rendering its peak (1 result, matching the
    // stock-style baseline), this layer still rendering its own
    // elevation text (10 results) at the same time.
    function peakElevationLayer(flavor) {
      var textColor = flavor === "dark" ? "#30C573" : "#20834D";
      var haloColor = flavor === "dark" ? "#1f1f1f" : "#e2dfda";
      return {
        id: "peak-elevation-labels",
        type: "symbol",
        source: "protomaps",
        "source-layer": "pois",
        minzoom: 11,
        filter: ["all", ["==", ["get", "kind"], "peak"], ["has", "elevation"]],
        layout: {
          "text-field": ["concat", ["get", "elevation"], " m"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-anchor": "top",
          "text-offset": [0, 0.9],
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": textColor,
          "text-halo-color": haloColor,
          "text-halo-width": 1,
        },
      };
    }

    const flavor = currentFlavor();
    const ROUTE_LINE_COLOR = routeLineColor(flavor);

    // ── Initialise map ──────────────────────────────────────────────────────
    const map = new maplibregl.Map({
      container: "post-map",
      style: {
        version: 8,
        glyphs:  "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
        sprite:  "https://protomaps.github.io/basemaps-assets/sprites/v4/" + flavor,
        sources: {
          protomaps: {
            type: "vector",
            url:  TILES_URL,
            attribution:
              '<a href="https://protomaps.com">Protomaps</a> © ' +
              '<a href="https://openstreetmap.org">OpenStreetMap</a>',
          },
        },
        layers: adjustLocalityLabelPriority(
          basemaps.layers("protomaps", basemaps.namedFlavor(flavor), { lang: "de" })
        )
          .concat(cyclingLayers(flavor))
          .concat([peakElevationLayer(flavor)]),
      },
      // Rough centre — overridden once the map loads and fits to the route.
      center: [8.1, 48.1],
      zoom: 10,
      attributionControl: false,
    });

    map.addControl(new maplibregl.AttributionControl({ compact: true }));
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }));
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));

    // ── Nearby-amenity overlay: clustered GeoJSON source + GL layers ──────
    // (fix_amenity_overlay_performance.md) Scoped to color-coded circles,
    // not per-category icons — MapLibre's native icon-image layers need a
    // sprite sheet, new asset-generation infra this fix doesn't need to
    // solve the actual problem (performance). A cluster of 50 mixed
    // amenities needs a count bubble, not 50 different glyphs anyway.
    // Curated POI markers (buildCategoryMarkerElement, above) are
    // untouched — single digits to low dozens per post, genuinely fine as
    // DOM markers at that scale.
    var AMENITIES_SOURCE_ID = "amenities";
    var AMENITIES_LAYER_IDS = ["amenities-clusters", "amenities-cluster-count", "amenities-unclustered"];

    // Runtime-generated icons for unclustered amenity points
    // (fix_amenity_overlay_ux.md Phase 2). map.addImage() accepts any
    // canvas/ImageData at runtime — no sprite sheet file needed, despite
    // the original performance-fix doc assuming one was required. Reuses
    // CATEGORY_ICON_PATHS/CATEGORY_COLOURS (already vendored for the
    // curated-POI DOM markers above) rather than any new asset: same
    // "colored circle, white glyph" visual recipe, just rasterized once
    // per category onto an offscreen canvas instead of built as DOM
    // nodes per feature.
    function categoryImageId(category) {
      return "amenity-icon-" + category;
    }

    function drawCategoryIcon(category) {
      var size = 32;
      var canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      var ctx = canvas.getContext("2d");
      var colour = CATEGORY_COLOURS[category] || CATEGORY_COLOURS.other;

      ctx.beginPath();
      ctx.arc(size / 2, size / 2, size / 2 - 1.5, 0, 2 * Math.PI);
      ctx.fillStyle = colour;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();

      var iconPath = CATEGORY_ICON_PATHS[category];
      if (iconPath) {
        var glyphSize = size * 0.55;
        var scale = glyphSize / 15; // paths are authored in a 15x15 viewBox
        var offset = (size - glyphSize) / 2;
        ctx.save();
        ctx.translate(offset, offset);
        ctx.scale(scale, scale);
        ctx.fillStyle = "#fff";
        var path2d = new Path2D(iconPath);
        ctx.fill(path2d);
        ctx.restore();
      }
      return ctx.getImageData(0, 0, size, size);
    }

    // Registers one runtime image per known category (plus "other" as the
    // fallback for anything unmapped). Must be called again after every
    // setStyle() — map.addImage() doesn't survive a style swap any more
    // than layers/sources do, and the unclustered symbol layer's
    // icon-image expression below references these ids by name.
    function registerCategoryImages(mapInstance) {
      var categories = Object.keys(CATEGORY_COLOURS);
      categories.forEach(function (category) {
        var id = categoryImageId(category);
        if (mapInstance.hasImage(id)) return; // idempotent, same reasoning as addAmenitiesSourceAndLayers
        mapInstance.addImage(id, drawCategoryIcon(category));
      });
    }

    // Adds the amenities source + its three layers (idempotent — a no-op
    // if the source already exists, since this is also called after a
    // theme-swap setStyle() where addSource() would otherwise throw on
    // an id that's already present from transformStyle's carry-over).
    function addAmenitiesSourceAndLayers(mapInstance, amenitiesGeojson) {
      if (mapInstance.getSource(AMENITIES_SOURCE_ID)) return;

      mapInstance.addSource(AMENITIES_SOURCE_ID, {
        type: "geojson",
        data: amenitiesGeojson,
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 50,
      });

      mapInstance.addLayer({
        id: "amenities-clusters",
        type: "circle",
        source: AMENITIES_SOURCE_ID,
        filter: ["has", "point_count"],
        layout: { visibility: "none" },
        paint: {
          "circle-color": "#607D8B",
          "circle-opacity": 0.85,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
          // Radius scales with cluster size — small clusters stay compact,
          // large ones (Rhineland-density corridors) read as clearly bigger.
          "circle-radius": ["step", ["get", "point_count"], 14, 25, 18, 100, 24, 750, 30],
        },
      });
      mapInstance.addLayer({
        id: "amenities-cluster-count",
        type: "symbol",
        source: AMENITIES_SOURCE_ID,
        filter: ["has", "point_count"],
        layout: {
          visibility: "none",
          "text-field": "{point_count_abbreviated}",
          "text-font": ["Noto Sans Regular"],
          "text-size": 12,
        },
        paint: { "text-color": "#fff" },
      });
      // symbol + icon-image, not circle: unclustered points get real
      // per-category icons now (Phase 2). Clusters keep the count-bubble
      // circle styling above unchanged — a cluster of dozens of mixed
      // categories has nowhere useful to put one icon.
      mapInstance.addLayer({
        id: "amenities-unclustered",
        type: "symbol",
        source: AMENITIES_SOURCE_ID,
        filter: ["!", ["has", "point_count"]],
        layout: {
          visibility: "none",
          "icon-image": ["concat", "amenity-icon-", ["get", "category"]],
          "icon-size": 0.75,
          "icon-allow-overlap": true,
        },
      });
    }

    function setAmenitiesVisibility(mapInstance, visible) {
      var value = visible ? "visible" : "none";
      AMENITIES_LAYER_IDS.forEach(function (layerId) {
        if (mapInstance.getLayer(layerId)) {
          mapInstance.setLayoutProperty(layerId, "visibility", value);
        }
      });
    }

    let routeLoaded = false;
    let amenitiesVisible = false;

    // ── Chart → map hover sync (elevation_profile_chart.md Tier 2) ──────
    // Given a target distance-km, walks ROUTE_GEOJSON's coordinates
    // accumulating 2D segment lengths (same planar-degrees approximation
    // used in geo_sync.py's _downsample_elevation_profile, adequate at
    // ride-track scale — this positions a hover marker, it's not a survey)
    // until the target is reached, then linearly interpolates between the
    // two bracketing points. Hand-written, not Turf.js — one ~20-line
    // function doesn't justify vendoring a whole geometry library,
    // consistent with this file's existing Maki-icon canvas rendering
    // taking the same "small hand-rolled helper" approach over a
    // dependency.
    function interpolateAlongRoute(coordinates, targetDistanceKm) {
      if (!coordinates || coordinates.length < 2) return null;
      if (targetDistanceKm <= 0) return coordinates[0];

      var cumulativeKm = 0;
      for (var i = 0; i < coordinates.length - 1; i++) {
        var lon1 = coordinates[i][0], lat1 = coordinates[i][1];
        var lon2 = coordinates[i + 1][0], lat2 = coordinates[i + 1][1];
        var meanLatRad = ((lat1 + lat2) / 2) * (Math.PI / 180);
        var dxKm = (lon2 - lon1) * 111.320 * Math.cos(meanLatRad);
        var dyKm = (lat2 - lat1) * 110.574;
        var segmentKm = Math.sqrt(dxKm * dxKm + dyKm * dyKm);

        if (cumulativeKm + segmentKm >= targetDistanceKm || i === coordinates.length - 2) {
          var remainingKm = targetDistanceKm - cumulativeKm;
          var fraction = segmentKm > 0 ? Math.min(Math.max(remainingKm / segmentKm, 0), 1) : 0;
          return [lon1 + (lon2 - lon1) * fraction, lat1 + (lat2 - lat1) * fraction];
        }
        cumulativeKm += segmentKm;
      }
      return coordinates[coordinates.length - 1];
    }

    var hoverMarkerEl = null;
    var hoverMarker = null;

    function showHoverMarker(lngLat) {
      if (!hoverMarker) {
        hoverMarkerEl = document.createElement("div");
        hoverMarkerEl.className = "elevation-hover-marker";
        hoverMarker = new maplibregl.Marker({ element: hoverMarkerEl }).setLngLat(lngLat).addTo(map);
      } else {
        hoverMarker.setLngLat(lngLat);
      }
      hoverMarkerEl.style.display = "block";
    }

    function hideHoverMarker() {
      if (hoverMarkerEl) hoverMarkerEl.style.display = "none";
    }

    // elevation-chart.js dispatches these on the document (no shared
    // module system between the two independently-loaded <script> tags
    // in this project — same reasoning as duplicating routeLineColor()
    // there rather than sharing a helper). Only wired up once the route
    // is actually loaded — ROUTE_GEOJSON's coordinates aren't available
    // before then.
    document.addEventListener("bulliexplorer:elevationhover", function (event) {
      if (!routeLoaded || !ROUTE_GEOJSON) return;
      var point = interpolateAlongRoute(ROUTE_GEOJSON.geometry.coordinates, event.detail.distanceKm);
      if (point) showHoverMarker(point);
    });
    document.addEventListener("bulliexplorer:elevationhoverend", function () {
      hideHoverMarker();
    });

    map.on("load", function () {
      routeLoaded = true;

      // ── Route line ─────────────────────────────────────────────
      map.addSource("route", { type: "geojson", data: ROUTE_GEOJSON });

      // Subtle casing shadow so the line reads on both light and dark tiles.
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#fff", "line-width": 6, "line-opacity": 0.5 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": ROUTE_LINE_COLOR, "line-width": 3.5 },
      });

      // ── Fit viewport to the route ─────────────────────────────────────
      var coords = ROUTE_GEOJSON.geometry.coordinates;
      var bounds = coords.reduce(function (b, c) {
        return b.extend(c);
      }, new maplibregl.LngLatBounds(coords[0], coords[0]));
      map.fitBounds(bounds, { padding: 48, maxZoom: 14 });

      // ── POI markers ──────────────────────────────────────────
      var features = (POIS_GEOJSON && POIS_GEOJSON.features) || [];
      features.forEach(function (feature) {
        var props = feature.properties;
        var el = buildCategoryMarkerElement(props.category, props.name, 28, 1);

        // escapeHtml() used here too now (tech-debt register,
        // review_17SEP2026.md) — name/notes are author-curated content,
        // so not third-party-exploitable, but escapeHtml() already
        // exists a hundred-plus lines below for the amenity popup;
        // using it consistently here removes the only asymmetry between
        // the two popup builders.
        var popupHtml = "<strong>" + escapeHtml(props.name) + "</strong>";
        if (props.notes) {
          popupHtml += "<br><small class='text-muted'>" + escapeHtml(props.notes) + "</small>";
        }

        new maplibregl.Marker({ element: el })
          .setLngLat(feature.geometry.coordinates)
          .setPopup(new maplibregl.Popup({ offset: 16 }).setHTML(popupHtml))
          .addTo(map);
      });

      // ── Nearby-amenity overlay (fix_amenity_overlay_performance.md) ────
      // Auto-discovered, not curated — a clustered GeoJSON source + GL
      // layers, NOT individual maplibregl.Marker DOM elements. Dream of
      // North alone has 15,686 amenities; one DOM element + one Marker
      // object per point is a well-documented MapLibre/Mapbox performance
      // cliff well before that scale (fine for dozens, degrades sharply
      // in the low thousands). GPU-rendered via the same pipeline already
      // drawing the whole basemap — genuinely handles tens of thousands of
      // points with no perceptible lag. Clustering (cluster: true) isn't a
      // separate feature bolted on here — even instant rendering of 15,686
      // individual points at a wide zoom would still be an unreadable
      // solid mass; grouping into count bubbles that split apart on zoom
      // is what actually fixes both performance AND readability together.
      // Source starts empty — the real data is fetched lazily (below),
      // only on first toggle check, not on page load (F1,
      // review_17SEP2026.md). An empty FeatureCollection is a valid,
      // cheap placeholder; setData() swaps in the real one once fetched.
      registerCategoryImages(map); // must run before addAmenitiesSourceAndLayers references these image ids
      addAmenitiesSourceAndLayers(map, { type: "FeatureCollection", features: [] });
      setAmenitiesVisibility(map, amenitiesVisible); // off by default, same as before

      var amenityToggle = document.getElementById("amenity-toggle-input");
      var amenitiesLoaded = false;
      var amenitiesLoading = false;
      if (amenityToggle && AMENITIES_GEOJSON_URL) {
        amenityToggle.addEventListener("change", function () {
          amenitiesVisible = amenityToggle.checked;
          setAmenitiesVisibility(map, amenitiesVisible);

          // Fetch once, lazily, on the first time the toggle is checked
          // — not on page load, not re-fetched on subsequent toggles.
          if (amenitiesVisible && !amenitiesLoaded && !amenitiesLoading) {
            amenitiesLoading = true;
            fetch(AMENITIES_GEOJSON_URL)
              .then(function (resp) {
                if (!resp.ok) throw new Error("amenities fetch failed: " + resp.status);
                return resp.json();
              })
              .then(function (geojson) {
                amenitiesLoaded = true;
                var source = map.getSource(AMENITIES_SOURCE_ID);
                if (source) source.setData(geojson);
              })
              .catch(function (err) {
                // Graceful degradation, same philosophy as the rest of
                // this project (amenities/geocoding/tiles all fail
                // toward "less enrichment", never toward a broken page)
                // — a failed fetch just leaves the overlay empty, the
                // rest of the map is unaffected.
                console.error("Failed to load nearby amenities:", err);
              })
              .finally(function () {
                amenitiesLoading = false;
              });
          }
        });
      }

      // Cluster click-to-expand (fix_amenity_overlay_ux.md Phase 1) —
      // MapLibre's own canonical, documented pattern for clustered
      // sources: getClusterExpansionZoom(clusterId) returns the zoom
      // level at which this specific cluster starts splitting apart,
      // then easeTo() smoothly gets there. Without this, a reader has to
      // manually scroll-zoom repeatedly to make a cluster break apart.
      map.on("click", "amenities-clusters", function (e) {
        var features = map.queryRenderedFeatures(e.point, { layers: ["amenities-clusters"] });
        var clusterId = features[0] && features[0].properties && features[0].properties.cluster_id;
        if (clusterId === undefined) return;
        map.getSource(AMENITIES_SOURCE_ID).getClusterExpansionZoom(clusterId, function (err, zoom) {
          if (err) return;
          map.easeTo({ center: features[0].geometry.coordinates, zoom: zoom });
        });
      });
      map.on("mouseenter", "amenities-clusters", function () {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "amenities-clusters", function () {
        map.getCanvas().style.cursor = "";
      });

      // Richer popups (fix_amenity_overlay_ux.md Phase 3) — name and
      // category always shown (closer to a Google-Maps-style "name plus a
      // category line", not just a bare name); a website link (new tab)
      // and a phone link (tel:) added only when those OSM tags actually
      // exist on this element — no empty placeholder rows for fields
      // that aren't there.
      map.on("click", "amenities-unclustered", function (e) {
        var feature = e.features && e.features[0];
        if (!feature) return;
        var props = feature.properties;
        new maplibregl.Popup({ offset: 12 })
          .setLngLat(feature.geometry.coordinates)
          .setHTML(buildAmenityPopupHtml(props))
          .addTo(map);
      });
      map.on("mouseenter", "amenities-unclustered", function () {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "amenities-unclustered", function () {
        map.getCanvas().style.cursor = "";
      });
    });

    // ── Live theme swap: react to the nav toggle without a page reload ────
    // map.setStyle() tears down and rebuilds every source/layer, so the
    // route line + casing AND the amenities source/layers (both added in
    // the "load" handler above) have to be carried over via transformStyle
    // below once the new style finishes loading. Curated POI markers are
    // the one exception — plain DOM elements attached via maplibregl.
    // Marker, not style layers, so they survive a setStyle() call
    // untouched, no carry-over needed.
    document.addEventListener("bulliexplorer:themechange", function (event) {
      if (!routeLoaded) return; // still mid-initial-load; nothing to swap yet
      var nextFlavor = event.detail.theme === "dark" ? "dark" : "light";
      var nextRouteColor = routeLineColor(nextFlavor);

      // map.addImage() doesn't survive setStyle() any more than
      // layers/sources do (fix_amenity_overlay_ux.md Phase 2) — the
      // carried-over amenities-unclustered layer references these image
      // ids via icon-image, so they must exist again before that layer
      // is actually asked to render. "styledata" fires once the new
      // style (including transformStyle's carried-over layers) has been
      // applied — the earliest point at which addImage calls stick to
      // the new style rather than the outgoing one.
      map.once("styledata", function () {
        registerCategoryImages(map);
      });

      map.setStyle(
        {
          version: 8,
          glyphs:  "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
          sprite:  "https://protomaps.github.io/basemaps-assets/sprites/v4/" + nextFlavor,
          sources: {
            protomaps: {
              type: "vector",
              url:  TILES_URL,
              attribution:
                '<a href="https://protomaps.com">Protomaps</a> © ' +
                '<a href="https://openstreetmap.org">OpenStreetMap</a>',
            },
          },
          layers: adjustLocalityLabelPriority(
            basemaps.layers("protomaps", basemaps.namedFlavor(nextFlavor), { lang: "de" })
          )
            .concat(cyclingLayers(nextFlavor))
            .concat([peakElevationLayer(nextFlavor)]),
        },
        {
          // transformStyle carries the route source/layers over from the
          // outgoing style into the new one, so they don't need to be
          // torn down and manually re-added — the MapLibre-recommended
          // pattern for a setStyle() that must preserve custom content
          // (see maplibre-gl-js discussion #7240/#7346 on style.load /
          // styledata firing before a style is actually ready to mutate).
          // Amenities (fix_amenity_overlay_performance.md) are style
          // layers now, not plain DOM markers like the POI pins above —
          // setStyle() tears down every source/layer, so the amenities
          // source + its three layer ids need the exact same carry-over
          // treatment already proven for route/route-line/route-casing.
          transformStyle: function (previousStyle, nextStyle) {
            var carried = (previousStyle && previousStyle.sources && previousStyle.sources.route)
              ? { route: previousStyle.sources.route }
              : {};
            if (previousStyle && previousStyle.sources && previousStyle.sources[AMENITIES_SOURCE_ID]) {
              carried[AMENITIES_SOURCE_ID] = previousStyle.sources[AMENITIES_SOURCE_ID];
            }
            var carriedLayerIds = ["route-casing", "route-line"].concat(AMENITIES_LAYER_IDS);
            var carriedLayers = (previousStyle && previousStyle.layers)
              ? previousStyle.layers.filter(function (l) {
                  return carriedLayerIds.includes(l.id);
                })
              : [];
            return Object.assign({}, nextStyle, {
              sources: Object.assign({}, nextStyle.sources, carried),
              layers: nextStyle.layers.concat(
                carriedLayers.map(function (l) {
                  if (l.id !== "route-line") return l;
                  return Object.assign({}, l, {
                    paint: Object.assign({}, l.paint, { "line-color": nextRouteColor }),
                  });
                }),
              ),
            });
          },
        },
      );
    });

    // ── Full-screen map toggle (Phase 2, gis_cycling_upgrade.md) ──────────
    // Reuses the SAME map instance — never re-initialised — by toggling a
    // `position: fixed` class on the wrapper and calling map.resize(), the
    // documented MapLibre pattern for a container whose pixel size changed
    // outside its own control (https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#resize).
    const mapWrap  = document.getElementById("map-wrap");
    const toggleBtn = document.getElementById("map-fullscreen-toggle");

    if (mapWrap && toggleBtn) {
      function getFocusable(container) {
        return Array.prototype.slice
          .call(
            container.querySelectorAll(
              'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
            ),
          )
          .filter(function (el) {
            return !el.disabled && el.offsetParent !== null;
          });
      }

      function openFullscreen() {
        mapWrap.classList.add("is-fullscreen");
        mapWrap.setAttribute("role", "dialog");
        mapWrap.setAttribute("aria-modal", "true");
        mapWrap.setAttribute("aria-label", "Full screen map");
        document.body.classList.add("map-fullscreen-active");
        toggleBtn.setAttribute("aria-pressed", "true");
        toggleBtn.setAttribute("aria-label", "Exit full screen map");
        // Wait one frame so the layout change above has actually taken
        // effect before asking MapLibre to re-measure its container —
        // resize() reads the container's current pixel size synchronously.
        requestAnimationFrame(function () {
          map.resize();
        });
      }

      function closeFullscreen() {
        mapWrap.classList.remove("is-fullscreen");
        mapWrap.removeAttribute("role");
        mapWrap.removeAttribute("aria-modal");
        mapWrap.removeAttribute("aria-label");
        document.body.classList.remove("map-fullscreen-active");
        toggleBtn.setAttribute("aria-pressed", "false");
        toggleBtn.setAttribute("aria-label", "View map full screen");
        requestAnimationFrame(function () {
          map.resize();
        });
      }

      toggleBtn.addEventListener("click", function () {
        if (mapWrap.classList.contains("is-fullscreen")) {
          closeFullscreen();
          toggleBtn.focus();
        } else {
          openFullscreen();
        }
      });

      // Escape closes; Tab is trapped within the wrap's own focusable
      // elements (the toggle/close button plus MapLibre's own nav/
      // attribution controls) while open — only intercepts Tab, so a
      // screen reader's own virtual-cursor/quick-nav browsing (which
      // doesn't use Tab) is never trapped, satisfying this phase's
      // "doesn't trap a screen-reader user who can't find/use Escape"
      // requirement.
      document.addEventListener("keydown", function (e) {
        if (!mapWrap.classList.contains("is-fullscreen")) return;

        if (e.key === "Escape") {
          closeFullscreen();
          toggleBtn.focus();
          return;
        }

        if (e.key === "Tab") {
          const focusable = getFocusable(mapWrap);
          if (focusable.length === 0) return;
          const first = focusable[0];
          const last = focusable[focusable.length - 1];
          if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
          } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      });
    }
  }());
