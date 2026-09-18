/*
 * Elevation profile chart — a single line dataset (distance_km on X,
 * elevation_m on Y) below the ride-stats row, on posts that have a route
 * with elevation data (docs/dev/elevation_profile_chart.md Tier 1),
 * incline-colored per segment with a tight X-axis and start/end markers
 * (Tier 3), and a chart→map hover sync (Tier 2).
 *
 * Same conventions as static/js/post-map.js: plain script tag, no bundler
 * (AGENTS.md), data injected via a small inline <script> block in
 * post.html, theme-awareness via the "bulliexplorer:themechange" event
 * base.html's toggle dispatches — reuses post-map.js's exact route-line
 * color for the line itself (#b85c00 light / #f0954a dark) except where
 * a segment is colored by incline instead.
 */
(function () {
  "use strict";

  const DATA = window.BULLIEXPLORER_ELEVATION_DATA || {};
  const ELEVATION_PROFILE = DATA.elevationProfile;
  const DISTANCE_KM = DATA.distanceKm;

  const canvas = document.getElementById("elevation-chart");
  if (!canvas || !ELEVATION_PROFILE || !ELEVATION_PROFILE.length) return;

  // ── Incline color-coding (elevation_profile_chart.md Tier 3) ────────
  //
  // Cutoffs tuned against this project's own real routes, not guessed
  // once and shipped: at these exact percentages, Feldberg Summit
  // Loop's real climb (checked directly against its synced DB row
  // during development) gives roughly a 39/36/25% green/amber/red
  // split, and a long flat-ish touring route (NC4200) comes out
  // entirely green — "mostly green/amber, red reserved for genuinely
  // steep" per the request, not the inverse.
  var INCLINE_GREEN_MAX = 5; // |gradient%| below this → gentle (green)
  var INCLINE_AMBER_MAX = 10; // below this → moderate (amber); at/above → steep (red)

  var INCLINE_COLORS = { green: "#3a9a4a", amber: "#d99a1f", red: "#c0392b" };

  // hex -> "rgba(r, g, b, alpha)" for the translucent fill — kept as a
  // tiny standalone helper rather than a second alpha-aware color table,
  // so the red/amber/green hex values above stay the single source of
  // truth for both the line and the fill under it.
  function withAlpha(hexColor, alpha) {
    var r = parseInt(hexColor.slice(1, 3), 16);
    var g = parseInt(hexColor.slice(3, 5), 16);
    var b = parseInt(hexColor.slice(5, 7), 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
  }

  // Raw point-to-point gradient on a GPS/barometric-elevation track is
  // noisy — consecutive downsampled segments zigzag between +8% and
  // -3% on ground that's actually a steady climb, which would
  // color-code as a messy flicker instead of Komoot's clean "green
  // approach, red final push" look. A centered moving-average window
  // over the elevation values (checked directly against Feldberg's
  // real profile during development — window=9 smooths out exactly
  // this noise without eroding the real climb/descent shape) computes
  // the gradient from smoothed elevation, not raw.
  function smoothElevations(profile, window) {
    var half = Math.floor(window / 2);
    var n = profile.length;
    var out = new Array(n);
    for (var i = 0; i < n; i++) {
      var lo = Math.max(0, i - half);
      var hi = Math.min(n, i + half + 1);
      var sum = 0;
      for (var j = lo; j < hi; j++) sum += profile[j][1];
      out[i] = sum / (hi - lo);
    }
    return out;
  }

  // alpha is optional: omitted (or null) returns the solid hex used for
  // the line itself; a 0–1 value returns the same color as a
  // translucent rgba() for the fill underneath it (Komoot's "solid line,
  // soft-tinted fill" look, not a solid block of color).
  function inclineColorForGradient(gradientPercent, alpha) {
    var abs = Math.abs(gradientPercent);
    var hex = abs < INCLINE_GREEN_MAX ? INCLINE_COLORS.green : abs < INCLINE_AMBER_MAX ? INCLINE_COLORS.amber : INCLINE_COLORS.red;
    return alpha == null ? hex : withAlpha(hex, alpha);
  }

  // Per-segment gradient (%) between two adjacent source points, using
  // the smoothed elevation at each index rather than the segment's own
  // raw endpoints. Exposed as its own function (not inlined in the
  // segment.borderColor callback below) so it's independently testable
  // — see the source-assertion tests in tests/unit/test_templates.py.
  function gradientPercentAt(profile, smoothedElevations, index) {
    if (index < 0 || index >= profile.length - 1) return 0;
    var distanceDeltaM = (profile[index + 1][0] - profile[index][0]) * 1000;
    if (distanceDeltaM <= 0) return 0;
    var elevationDelta = smoothedElevations[index + 1] - smoothedElevations[index];
    return (elevationDelta / distanceDeltaM) * 100;
  }

  var smoothedElevations = smoothElevations(ELEVATION_PROFILE, 9);

  // Same route-line color as post-map.js's routeLineColor(flavor) — kept
  // as a literal copy here rather than a shared import, since this
  // project has no bundler/module system to share a small helper between
  // two independently-loaded <script> tags without a global. Used as
  // the marker/fallback color; the line itself is incline-colored
  // per-segment instead of this flat color.
  function routeLineColor(flavor) {
    return flavor === "dark" ? "#f0954a" : "#b85c00";
  }

  function currentFlavor() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  // Chart.js needs literal color strings in its config object, not CSS
  // custom properties — read via getComputedStyle at chart-init/theme-
  // change time, same reasoning noted in the Tier 1 plan doc.
  function themeColors() {
    var styles = getComputedStyle(document.documentElement);
    return {
      line: routeLineColor(currentFlavor()),
      text: styles.getPropertyValue("--color-text-muted").trim() || "#5c564d",
      grid: styles.getPropertyValue("--color-border").trim() || "#e4ddd2",
    };
  }

  var colors = themeColors();

  // Tight X-axis (Tier 3): the chart's max must equal the route's
  // actual total distance exactly, not Chart.js's default
  // auto-padding, so the line reaches the right edge with no trailing
  // empty space. Falls back to the profile's own last distance value
  // if distance_km wasn't passed (defensive only — post.html always
  // passes route.distance_km alongside elevation_profile today).
  var totalDistanceKm = DISTANCE_KM != null ? DISTANCE_KM : ELEVATION_PROFILE[ELEVATION_PROFILE.length - 1][0];

  var chart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [
        {
          data: ELEVATION_PROFILE.map(function (point) {
            return { x: point[0], y: point[1] };
          }),
          borderColor: colors.line,
          backgroundColor: colors.line,
          borderWidth: 2,
          pointRadius: 0,
          // fill: 'origin' (not false) — without this the area under the
          // line never renders at all, which is why a first cut of this
          // looked like "just a thin line, mostly green" even on a route
          // with real climbing: the segment.borderColor callback below
          // was correctly coloring the line, but there was no fill to
          // color in the first place.
          fill: "origin",
          tension: 0.15,
          // Per-segment incline color-coding — Chart.js's native
          // `segment` scriptable option, no plugin needed beyond what
          // Tier 1 already vendors. ctx.p0DataIndex is the index of the
          // segment's first point in the dataset, which lines up
          // directly with ELEVATION_PROFILE's own indices. Both
          // borderColor (the line) and backgroundColor (the fill under
          // it, at 0.3 alpha for the translucent look) must be set —
          // Chart.js doesn't derive one from the other.
          segment: {
            borderColor: function (ctx) {
              var gradient = gradientPercentAt(ELEVATION_PROFILE, smoothedElevations, ctx.p0DataIndex);
              return inclineColorForGradient(gradient);
            },
            backgroundColor: function (ctx) {
              var gradient = gradientPercentAt(ELEVATION_PROFILE, smoothedElevations, ctx.p0DataIndex);
              return inclineColorForGradient(gradient, 0.3);
            },
          },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: function (items) {
              return items[0].parsed.x.toFixed(1) + " km";
            },
            // Hover tooltip (Tier 3): distance (title above), elevation,
            // cumulative gain to that point, and local incline % — all
            // computable from the same profile data already loaded.
            // Deliberately no surface/way-type line here — that data
            // isn't reliably present in this project's tile data
            // (gis_cycling_upgrade.md Phase 0), out of scope per the
            // Tier 3 plan's explicit callout.
            label: function (item) {
              var index = item.dataIndex;
              var elevationM = Math.round(item.parsed.y);
              var gainToHereM = 0;
              for (var i = 1; i <= index; i++) {
                var delta = ELEVATION_PROFILE[i][1] - ELEVATION_PROFILE[i - 1][1];
                if (delta > 0) gainToHereM += delta;
              }
              var gradient = gradientPercentAt(ELEVATION_PROFILE, smoothedElevations, Math.min(index, ELEVATION_PROFILE.length - 2));
              var lines = [elevationM + " m", "+" + Math.round(gainToHereM) + " m climbed so far"];
              lines.push((gradient >= 0 ? "+" : "") + gradient.toFixed(1) + "% grade");
              return lines;
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: totalDistanceKm,
          // Tight X-axis: no auto-padding beyond the route's actual
          // total distance — the line reaches the right edge exactly.
          grace: 0,
          title: { display: true, text: "km", color: colors.text },
          ticks: { color: colors.text },
          grid: { color: colors.grid },
        },
        y: {
          title: { display: true, text: "m", color: colors.text },
          ticks: { color: colors.text },
          grid: { color: colors.grid },
        },
      },
    },
    // Start/end marker dots ("A"/"B", Tier 3) — a small plugin drawing
    // two labeled circles at the first/last data point, after Chart.js's
    // own draw pass. Cosmetic, pairs naturally with Tier 2's map-hover
    // marker but doesn't depend on it (Tier 2 can be entirely absent and
    // these still render).
    plugins: [
      {
        id: "elevationStartEndMarkers",
        afterDraw: function (chartInstance) {
          var meta = chartInstance.getDatasetMeta(0);
          var points = meta.data;
          if (!points || points.length < 2) return;
          var ctx = chartInstance.ctx;
          var labels = ["A", "B"];
          [points[0], points[points.length - 1]].forEach(function (point, i) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(point.x, point.y, 7, 0, 2 * Math.PI);
            ctx.fillStyle = colors.line;
            ctx.fill();
            ctx.lineWidth = 2;
            ctx.strokeStyle = "#fff";
            ctx.stroke();
            ctx.fillStyle = "#fff";
            ctx.font = "bold 9px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(labels[i], point.x, point.y);
            ctx.restore();
          });
        },
      },
    ],
  });

  // Hover → map sync (elevation_profile_chart.md Tier 2). Chart.js's
  // "index" interaction mode (set in options above) already tells us the
  // exact nearest-point index per pointer move; onHover reads the same
  // x value canvas.js's own tooltip uses, so "where the tooltip points"
  // and "where the map marker lands" always agree. Dispatched as a
  // CustomEvent on the document rather than calling into post-map.js's
  // internals directly — the two files are independently loaded <script>
  // tags with no shared module system (AGENTS.md: no build step), same
  // reasoning as duplicating routeLineColor() here instead of exporting
  // it. post-map.js interpolates the distance-km back to a lng/lat along
  // ROUTE_GEOJSON and shows/hides the marker; this file has no map
  // knowledge at all, matching its existing "only cares about elevation
  // data" scope. Map → chart hover sync is explicitly out of scope
  // (docs/dev/elevation_profile_chart.md Tier 2's scope notes) — this is
  // a one-way, chart-leads dispatch only.
  chart.options.onHover = function (_event, activeElements) {
    if (!activeElements || !activeElements.length) {
      document.dispatchEvent(new CustomEvent("bulliexplorer:elevationhoverend"));
      return;
    }
    var distanceKm = chart.data.datasets[0].data[activeElements[0].index].x;
    document.dispatchEvent(
      new CustomEvent("bulliexplorer:elevationhover", { detail: { distanceKm: distanceKm } }),
    );
  };
  canvas.addEventListener("mouseleave", function () {
    document.dispatchEvent(new CustomEvent("bulliexplorer:elevationhoverend"));
  });

  // Live theme swap — update in place (chart.update()), not a
  // destroy-and-recreate, same "no reload required" bar post-map.js's
  // basemap/route-line re-theming already meets. Segment incline colors
  // are theme-independent (green/amber/red read the same in both
  // flavors), so only the marker/text/grid colors need updating here.
  document.addEventListener("bulliexplorer:themechange", function () {
    var next = themeColors();
    colors = next;
    var dataset = chart.data.datasets[0];
    dataset.borderColor = next.line;
    dataset.backgroundColor = next.line;
    chart.options.scales.x.ticks.color = next.text;
    chart.options.scales.x.title.color = next.text;
    chart.options.scales.x.grid.color = next.grid;
    chart.options.scales.y.ticks.color = next.text;
    chart.options.scales.y.title.color = next.text;
    chart.options.scales.y.grid.color = next.grid;
    chart.update();
  });
})();
