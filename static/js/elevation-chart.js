/*
 * Elevation profile chart — a single line dataset (distance_km on X,
 * elevation_m on Y) below the ride-stats row, on posts that have a route
 * with elevation data (docs/dev/elevation_profile_chart.md Tier 1).
 *
 * Same conventions as static/js/post-map.js: plain script tag, no bundler
 * (AGENTS.md), data injected via a small inline <script> block in
 * post.html, theme-awareness via the "bulliexplorer:themechange" event
 * base.html's toggle dispatches — reuses post-map.js's exact route-line
 * colors (#b85c00 light / #f0954a dark) rather than a second palette, so
 * the chart's line reads as the same brand color as the map's route.
 */
(function () {
  "use strict";

  const DATA = window.BULLIEXPLORER_ELEVATION_DATA || {};
  const ELEVATION_PROFILE = DATA.elevationProfile;

  const canvas = document.getElementById("elevation-chart");
  if (!canvas || !ELEVATION_PROFILE || !ELEVATION_PROFILE.length) return;

  // Same route-line colors as post-map.js's routeLineColor(flavor) — kept
  // as a literal copy here rather than a shared import, since this
  // project has no bundler/module system to share a small helper between
  // two independently-loaded <script> tags without a global.
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
          fill: false,
          tension: 0.15,
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
            label: function (item) {
              return Math.round(item.parsed.y) + " m";
            },
          },
        },
      },
      scales: {
        x: {
          type: "linear",
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
  });

  // Live theme swap — update in place (chart.update()), not a
  // destroy-and-recreate, same "no reload required" bar post-map.js's
  // basemap/route-line re-theming already meets.
  document.addEventListener("bulliexplorer:themechange", function () {
    var next = themeColors();
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
