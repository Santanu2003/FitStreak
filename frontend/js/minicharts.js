/* MiniChart - FitStreak's own interactive chart renderer (no libraries, no internet needed).
 *
 * Every chart in the app goes through this file. Charts are SVG that animate in and react to
 * the mouse / finger: hovering a bar or a point lights up that category and shows a tooltip
 * with every series, line charts get a guide line and enlarged points, doughnut slices pop out
 * with the value shown in the centre, clicking a legend entry shows / hides that series, and
 * charts re-fit themselves when the window is resized. Animations are skipped for people who
 * ask their OS for reduced motion.
 *
 * Supported subset of the Chart.js-style config that app.js hands in:
 *   type: "line" | "bar" | "doughnut"
 *   data.labels, data.shortLabels (optional, used on the axis; tooltips use the full label)
 *   data.datasets[{ label, data, backgroundColor, borderColor, legendColor, fill, tension, borderDash,
 *                   yAxisID ("y" | "y1"), type ("line" | "bar" - lets a bar chart carry a line),
 *                   unit (" kcal"), decimals }]
 *   options.indexAxis: "y"                    horizontal bars
 *   options.scales.{x,y,y1}.title.text        axis titles ("y1" = right-hand axis)
 *   options.scales.y.beginAtZero              start the axis at zero
 *   options.plugins.legend.display === false  hide the legend
 *   options.unit                              default tooltip unit, e.g. " kcal"
 *   options.tooltipExtra(index) -> [strings]  extra tooltip lines for a category
 *   options.onClick(index)                    make bars / points clickable
 *   options.centerLabel                       doughnut centre caption (default "Total")
 *   options.highlightIndex                    category kept highlighted (e.g. the selected day)
 */
(function (root) {
  "use strict";

  var PALETTE = ["#3F5A34", "#C9DE3B", "#14201A", "#3E7CA6", "#E4573F", "#9AAE20"];
  var INK = "#14201A", MUTED = "#6E7266", GRID = "#E4E3D4";
  var uid = 0;

  // ------------------------------------------------------------- helpers ----
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }
  function has(v) { return v !== null && v !== undefined && v !== "" && isFinite(Number(v)); }
  function r1(v) { return Math.round(v * 10) / 10; }
  function r2(v) { return Math.round(v * 100) / 100; }

  function fmt(v) {
    var a = Math.abs(v);
    if (a >= 10000) return Math.round(v / 1000) + "k";
    if (a >= 1000) return r1(v / 1000) + "k";
    return String(r1(v));
  }
  function fmtVal(v, d, cfg) {
    var dec = d && d.decimals !== undefined ? d.decimals : null;
    var s = dec !== null ? Number(v).toFixed(dec) : String(Math.round(v * 100) / 100);
    var parts = s.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    var unit = (d && d.unit !== undefined) ? d.unit : ((cfg.options && cfg.options.unit) || "");
    return parts.join(".") + unit;
  }

  function niceScale(min, max, count) {
    if (max === min) { max = min + 1; }
    var span = max - min;
    var raw = span / (count || 4);
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var f = raw / mag;
    var step = (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag;
    var lo = Math.floor(min / step) * step;
    var hi = Math.ceil(max / step) * step;
    var ticks = [];
    for (var t = lo; t <= hi + step / 1000; t += step) ticks.push(r1(t * 1000) / 1000);
    return { min: lo, max: hi, ticks: ticks };
  }

  function pick(c, i, fallback) {
    if (Array.isArray(c)) return c[i % c.length] || fallback;
    return c || fallback;
  }
  // Darkens a #rrggbb color for the hovered-bar state; non-hex colors pass through unchanged.
  function shade(hex, amt) {
    if (typeof hex !== "string" || hex.charAt(0) !== "#" || (hex.length !== 7 && hex.length !== 4)) return hex;
    var h = hex.length === 4 ? "#" + hex[1] + hex[1] + hex[2] + hex[2] + hex[3] + hex[3] : hex;
    var n = parseInt(h.slice(1), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    r = Math.max(0, Math.min(255, Math.round(r * (1 + amt))));
    g = Math.max(0, Math.min(255, Math.round(g * (1 + amt))));
    b = Math.max(0, Math.min(255, Math.round(b * (1 + amt))));
    return "#" + (1 << 24 | r << 16 | g << 8 | b).toString(16).slice(1);
  }
  function axisOf(ds) { return ds.yAxisID === "y1" ? "y1" : "y"; }
  function axisTitle(cfg, key) {
    var s = cfg.options && cfg.options.scales && cfg.options.scales[key];
    return s && s.title && s.title.display !== false && s.title.text ? String(s.title.text) : "";
  }
  function legendOn(cfg, count) {
    var l = cfg.options && cfg.options.plugins && cfg.options.plugins.legend;
    if (l && l.display === false) return false;
    return count > 1 || cfg.type === "doughnut";
  }

  function legendSvg(items, W, y) {
    var widths = items.map(function (it) { return 26 + String(it.label).length * 6.4; });
    var total = widths.reduce(function (a, b) { return a + b; }, 0);
    var x = Math.max(8, (W - total) / 2), out = "";
    items.forEach(function (it, i) {
      out += '<g class="mc-legend-item' + (it.off ? " mc-off" : "") + '" data-key="' + it.key + '">' +
        '<rect x="' + r1(x - 4) + '" y="' + (y - 14) + '" width="' + r1(widths[i] - 2) + '" height="20" rx="5" fill="transparent"/>' +
        '<rect x="' + r1(x) + '" y="' + (y - 8) + '" width="10" height="10" rx="2.5" fill="' + esc(it.color) + '"/>' +
        '<text x="' + r1(x + 15) + '" y="' + y + '" font-size="11.5" fill="' + INK + '">' + esc(it.label) + "</text></g>";
      x += widths[i];
    });
    return out;
  }

  function emptySvg(W, H, msg) {
    return '<svg viewBox="0 0 ' + W + " " + H + '" xmlns="http://www.w3.org/2000/svg" role="img">' +
      '<text x="' + W / 2 + '" y="' + H / 2 + '" text-anchor="middle" font-size="13" fill="' + MUTED + '">' + esc(msg) + "</text></svg>";
  }

  function tipHtml(title, rows, extra) {
    var h = '<div class="mc-tip-title">' + esc(title) + "</div>";
    rows.forEach(function (r) {
      h += '<div class="mc-tip-row"><i style="background:' + esc(r.color) + '"></i><span>' + esc(r.label) +
           "</span><b>" + esc(r.value) + "</b></div>";
    });
    (extra || []).forEach(function (t) { h += '<div class="mc-tip-extra">' + esc(t) + "</div>"; });
    return h;
  }

  // Smooth path through points (monotone-ish cardinal spline, no overshoot).
  function smoothPath(pts, tension) {
    if (pts.length < 3 || !tension) {
      return pts.map(function (p, i) { return (i ? "L" : "M") + r1(p[0]) + " " + r1(p[1]); }).join(" ");
    }
    var t = Math.min(0.5, tension) * 0.9, d = "M" + r1(pts[0][0]) + " " + r1(pts[0][1]);
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      var c1x = p1[0] + (p2[0] - p0[0]) * t / 1.5, c1y = p1[1] + (p2[1] - p0[1]) * t / 1.5;
      var c2x = p2[0] - (p3[0] - p1[0]) * t / 1.5, c2y = p2[1] - (p3[1] - p1[1]) * t / 1.5;
      var lo = Math.min(p1[1], p2[1]), hi = Math.max(p1[1], p2[1]);
      c1y = Math.max(lo, Math.min(hi, c1y)); c2y = Math.max(lo, Math.min(hi, c2y));
      d += " C" + r1(c1x) + " " + r1(c1y) + " " + r1(c2x) + " " + r1(c2y) + " " + r1(p2[0]) + " " + r1(p2[1]);
    }
    return d;
  }

  // -------------------------------------------------------------- doughnut ----
  function doughnutBuild(cfg, W, H, st) {
    var ds = cfg.data.datasets[0] || { data: [] };
    var labels = cfg.data.labels || [];
    var raw = (ds.data || []).map(function (v) { return Math.max(0, num(v)); });
    var hidden = st.hidden || {};
    var values = raw.map(function (v, i) { return hidden["s" + i] ? 0 : v; });
    var total = values.reduce(function (a, b) { return a + b; }, 0);
    var items = raw.map(function (v, i) {
      return { key: "s" + i, label: labels[i] !== undefined ? labels[i] : "Item " + (i + 1),
               color: pick(ds.backgroundColor, i, PALETTE[i % PALETTE.length]), off: !!hidden["s" + i] };
    });
    if (!raw.some(function (v) { return v > 0; })) return { svg: emptySvg(W, H, "No data yet"), model: null };

    var legendH = 30;
    var cx = W / 2, cy = (H - legendH) / 2, R = Math.min(W, H - legendH) / 2 - 12, r = R * 0.6;
    var svg = "", angle = -Math.PI / 2, slices = [];

    values.forEach(function (v, i) {
      if (!v) return;
      var color = items[i].color, label = items[i].label;
      var pct = total ? Math.round((v / total) * 1000) / 10 : 0;
      var a2 = angle + (v / total) * Math.PI * 2, mid = (angle + a2) / 2, d;
      if (v >= total - 1e-9) {
        d = "M" + (cx - R) + " " + cy + " a" + R + " " + R + " 0 1 0 " + 2 * R + " 0 a" + R + " " + R + " 0 1 0 " + (-2 * R) + " 0 Z M" +
            (cx - r) + " " + cy + " a" + r + " " + r + " 0 1 1 " + 2 * r + " 0 a" + r + " " + r + " 0 1 1 " + (-2 * r) + " 0 Z";
      } else {
        var large = a2 - angle > Math.PI ? 1 : 0;
        var x1 = cx + R * Math.cos(angle), y1 = cy + R * Math.sin(angle);
        var x2 = cx + R * Math.cos(a2), y2 = cy + R * Math.sin(a2);
        var x3 = cx + r * Math.cos(a2), y3 = cy + r * Math.sin(a2);
        var x4 = cx + r * Math.cos(angle), y4 = cy + r * Math.sin(angle);
        d = "M" + r1(x1) + " " + r1(y1) + " A" + R + " " + R + " 0 " + large + " 1 " + r1(x2) + " " + r1(y2) +
            " L" + r1(x3) + " " + r1(y3) + " A" + r + " " + r + " 0 " + large + " 0 " + r1(x4) + " " + r1(y4) + " Z";
      }
      slices.push({ i: i, label: label, value: v, pct: pct, color: color });
      svg += '<g class="mc-slice-g' + (st.animate ? " mc-anim" : "") + '" style="transform-origin:' + cx + "px " + cy + "px;animation-delay:" + slices.length * 90 + 'ms">' +
        '<path class="mc-slice" data-i="' + i + '" fill="' + esc(color) + '" stroke="#fff" stroke-width="1.5" ' +
        'style="--dx:' + r1(Math.cos(mid) * 7) + "px;--dy:" + r1(Math.sin(mid) * 7) + 'px" d="' + d + '">' +
        "<title>" + esc(label) + ": " + esc(fmtVal(v, ds, cfg)) + " (" + pct + "%)</title></path></g>";
      angle = a2;
    });

    var totalTxt = fmtVal(total, ds, cfg);
    svg += '<g class="mc-center" pointer-events="none" text-anchor="middle">' +
      '<text class="mc-c1" x="' + cx + '" y="' + r1(cy - 2) + '" font-size="' + r1(Math.max(15, r * 0.36)) + '" font-weight="700" fill="' + INK + '">' + esc(totalTxt) + "</text>" +
      '<text class="mc-c2" x="' + cx + '" y="' + r1(cy + Math.max(15, r * 0.3)) + '" font-size="11.5" fill="' + MUTED + '">' + esc((cfg.options && cfg.options.centerLabel) || "Total") + "</text></g>";
    svg += legendSvg(items, W, H - 8);
    return {
      svg: '<svg viewBox="0 0 ' + W + " " + H + '" xmlns="http://www.w3.org/2000/svg" role="img">' + svg + "</svg>",
      model: { kind: "doughnut", slices: slices, centerDefault: [totalTxt, (cfg.options && cfg.options.centerLabel) || "Total"],
               unitDs: ds, items: items }
    };
  }

  // --------------------------------------------------------- line / bar chart --
  function cartesianBuild(cfg, W, H, st) {
    var labels = cfg.data.labels || [];
    var shortLabels = cfg.data.shortLabels || labels;
    var all = (cfg.data.datasets || []).map(function (d, i) { return { d: d, i: i }; })
      .filter(function (x) { return x.d && x.d.data && x.d.data.length; });
    if (!labels.length || !all.length) return { svg: emptySvg(W, H, "No data yet"), model: null };

    var hidden = st.hidden || {};
    var datasets = all.filter(function (x) { return !hidden["d" + x.i]; });
    var horizontal = cfg.type === "bar" && cfg.options && cfg.options.indexAxis === "y";
    var n = labels.length, id = "mc" + (++uid);
    var kindOf = function (d) { return horizontal ? "bar" : (d.type || cfg.type); };
    var showLegend = legendOn(cfg, all.length);
    var hasRight = !horizontal && datasets.some(function (x) { return axisOf(x.d) === "y1"; });

    var titleL = horizontal ? "" : axisTitle(cfg, "y");
    var titleR = hasRight ? axisTitle(cfg, "y1") : "";
    var titleB = horizontal ? axisTitle(cfg, "x") : axisTitle(cfg, "x");
    var maxLabelLen = shortLabels.reduce(function (m, l) { return Math.max(m, String(l).length); }, 0);
    var padL = horizontal ? Math.min(150, 14 + maxLabelLen * 6.2) : 44 + (titleL ? 14 : 0);
    var padR = hasRight ? 44 + (titleR ? 14 : 0) : 16;
    var padT = showLegend ? 38 : 16;
    var padB = 26 + (titleB ? 16 : 0);
    var plotW = W - padL - padR, plotH = H - padT - padB;
    if (plotW < 40 || plotH < 40) return { svg: emptySvg(W, H, "Chart too small"), model: null };

    // ---- value axes ----
    var scales = {};
    ["y", "y1"].forEach(function (key) {
      var ds = datasets.filter(function (x) { return (horizontal ? "y" : axisOf(x.d)) === key; });
      if (!ds.length) return;
      var vals = [];
      ds.forEach(function (x) { x.d.data.forEach(function (v) { if (has(v)) vals.push(num(v)); }); });
      if (!vals.length) vals = [0, 1];
      var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
      var opt = cfg.options && cfg.options.scales && cfg.options.scales[key];
      var hasBar = ds.some(function (x) { return kindOf(x.d) === "bar"; });
      var zero = hasBar || (opt && opt.beginAtZero) || (lo >= 0 && lo < hi * 0.5);
      if (zero) lo = Math.min(0, lo);
      else { var pad = (hi - lo) * 0.15 || 1; lo -= pad; hi += pad; if (lo < 0 && Math.min.apply(null, vals) >= 0) lo = 0; }
      scales[key] = niceScale(lo, hi, 4);
    });
    if (!scales.y) scales.y = niceScale(0, 1, 4);

    var svg = "";
    function vPos(key, v) {
      var s = scales[key] || scales.y;
      var t = (v - s.min) / (s.max - s.min || 1);
      return horizontal ? padL + t * plotW : padT + plotH - t * plotH;
    }

    // ---- gradient defs for line areas ----
    var defs = "";
    datasets.forEach(function (x) {
      if (kindOf(x.d) === "line" && x.d.fill) {
        var c = pick(x.d.borderColor, x.i, PALETTE[x.i % PALETTE.length]);
        defs += '<linearGradient id="' + id + "g" + x.i + '" x1="0" y1="0" x2="0" y2="1">' +
                '<stop offset="0" stop-color="' + esc(c) + '" stop-opacity="0.34"/><stop offset="1" stop-color="' + esc(c) + '" stop-opacity="0.02"/></linearGradient>';
      }
    });
    if (defs) svg += "<defs>" + defs + "</defs>";

    // ---- gridlines + ticks ----
    scales.y.ticks.forEach(function (t) {
      var p = vPos("y", t);
      if (horizontal) {
        svg += '<line x1="' + r1(p) + '" y1="' + padT + '" x2="' + r1(p) + '" y2="' + (padT + plotH) + '" stroke="' + GRID + '"/>' +
               '<text x="' + r1(p) + '" y="' + (padT + plotH + 14) + '" text-anchor="middle" font-size="10.5" fill="' + MUTED + '">' + fmt(t) + "</text>";
      } else {
        svg += '<line x1="' + padL + '" y1="' + r1(p) + '" x2="' + (padL + plotW) + '" y2="' + r1(p) + '" stroke="' + GRID + '"/>' +
               '<text x="' + (padL - 6) + '" y="' + r1(p + 3.5) + '" text-anchor="end" font-size="10.5" fill="' + MUTED + '">' + fmt(t) + "</text>";
      }
    });
    if (scales.y1 && hasRight) {
      scales.y1.ticks.forEach(function (t) {
        svg += '<text x="' + (padL + plotW + 6) + '" y="' + r1(vPos("y1", t) + 3.5) + '" font-size="10.5" fill="' + MUTED + '">' + fmt(t) + "</text>";
      });
    }

    // ---- category labels ----
    var band = (horizontal ? plotH : plotW) / n;
    if (horizontal) {
      labels.forEach(function (l, i) {
        svg += '<text x="' + (padL - 6) + '" y="' + r1(padT + band * i + band / 2 + 3.5) + '" text-anchor="end" font-size="11.5" fill="' + INK + '">' + esc(shortLabels[i]) + "</text>";
      });
    } else {
      var maxShown = Math.max(2, Math.floor(plotW / (maxLabelLen * 6 + 10)));
      var every = Math.ceil(n / maxShown);
      shortLabels.forEach(function (l, i) {
        if (i % every !== 0) return;
        svg += '<text x="' + r1(padL + band * i + band / 2) + '" y="' + (padT + plotH + 15) + '" text-anchor="middle" font-size="10.5" fill="' + INK + '">' + esc(l) + "</text>";
      });
    }

    // ---- hover helpers drawn under the data ----
    // The soft full-column band is only useful when a line shares the chart (to anchor its
    // guide line); a bar-only chart instead highlights the hovered bar itself (see mc-hot below).
    var hasLine = datasets.some(function (x) { return kindOf(x.d) === "line"; });
    if (hasLine) {
      svg += horizontal
        ? '<rect class="mc-band" x="' + padL + '" y="' + padT + '" width="' + plotW + '" height="' + r1(band) + '" rx="4"/>'
        : '<rect class="mc-band" x="' + padL + '" y="' + padT + '" width="' + r1(band) + '" height="' + plotH + '" rx="4"/>';
    }

    var hi = cfg.options && cfg.options.highlightIndex;
    if (has(hi) && hi >= 0 && hi < n) {
      svg += horizontal
        ? '<rect class="mc-select" x="' + padL + '" y="' + r1(padT + band * hi) + '" width="' + plotW + '" height="' + r1(band) + '" rx="4"/>'
        : '<rect class="mc-select" x="' + r1(padL + band * hi) + '" y="' + padT + '" width="' + r1(band) + '" height="' + plotH + '" rx="4"/>';
    }

    // ---- data ----
    var bars = datasets.filter(function (x) { return kindOf(x.d) === "bar"; });
    var groupW = band * (bars.length > 1 ? 0.78 : 0.62), barW = bars.length ? groupW / bars.length : 0;
    var lineGeo = [];      // for the model: point centres per dataset
    var animate = st.animate;

    bars.forEach(function (x, bi) {
      var d = x.d, key = horizontal ? "y" : axisOf(d);
      var base = vPos(key, Math.max(scales[key].min, 0));
      d.data.forEach(function (raw, i) {
        if (!has(raw)) return;
        var v = num(raw), p = vPos(key, v);
        var color = pick(d.backgroundColor, i, PALETTE[x.i % PALETTE.length]);
        var hot = shade(color, -0.22);
        var delay = "animation-delay:" + (i * 40 + bi * 60) + "ms;";
        var cls = "mc-bar " + (horizontal ? "mc-bar-h" : "mc-bar-v") + (animate ? " mc-anim " + (horizontal ? "mc-grow-h" : "mc-grow-v") : "");
        var vars = "--c:" + esc(color) + ";--ch:" + esc(hot) + ";";
        if (horizontal) {
          var y = padT + band * i + (band - groupW) / 2 + barW * bi;
          svg += '<rect class="' + cls + '" data-i="' + i + '" data-key="d' + x.i + '" style="' + vars + "transform-origin:" + r1(base) + "px " + r1(y + (barW - 2) / 2) + "px;" + delay + '" x="' + r1(Math.min(base, p)) + '" y="' + r1(y + 1) + '" width="' + r1(Math.abs(p - base)) + '" height="' + r1(Math.max(1, barW - 2)) + '" rx="3" fill="' + esc(color) + '"/>';
        } else {
          var bx = padL + band * i + (band - groupW) / 2 + barW * bi;
          svg += '<rect class="' + cls + '" data-i="' + i + '" data-key="d' + x.i + '" style="' + vars + "transform-origin:" + r1(bx + (barW - 2) / 2) + "px " + r1(base) + "px;" + delay + '" x="' + r1(bx + 1) + '" y="' + r1(Math.min(base, p)) + '" width="' + r1(Math.max(1, barW - 2)) + '" height="' + r1(Math.max(1, Math.abs(base - p))) + '" rx="3" fill="' + esc(color) + '"/>';
        }
      });
    });

    datasets.forEach(function (x) {
      var d = x.d;
      if (kindOf(d) !== "line") return;
      var key = axisOf(d);
      var color = pick(d.borderColor, x.i, PALETTE[x.i % PALETTE.length]);
      var pts = [];
      d.data.forEach(function (raw, i) {
        if (has(raw)) pts.push([padL + band * i + band / 2, vPos(key, num(raw)), num(raw), i]);
      });
      lineGeo.push({ key: "d" + x.i, pts: pts });
      if (!pts.length) return;
      var path = smoothPath(pts, d.tension || 0);
      var dashed = !!d.borderDash;
      if (d.fill && pts.length > 1) {
        var baseY = vPos(key, Math.max(scales[key].min, 0));
        svg += '<path class="mc-area' + (animate ? " mc-anim mc-fade" : "") + '" data-key="d' + x.i + '" d="' + path + " L" + r1(pts[pts.length - 1][0]) + " " + r1(baseY) + " L" + r1(pts[0][0]) + " " + r1(baseY) + ' Z" fill="url(#' + id + "g" + x.i + ')"/>';
      }
      svg += '<path class="mc-line' + (animate ? " mc-anim " + (dashed ? "mc-fade" : "mc-draw") : "") + '" data-key="d' + x.i + '" pathLength="1" d="' + path + '" fill="none" stroke="' + esc(color) + '" stroke-width="' + (d.borderWidth || 2.5) + '"' +
             (dashed ? ' stroke-dasharray="' + esc(d.borderDash.join(" ")) + '"' : "") + ' stroke-linejoin="round" stroke-linecap="round"/>';
      pts.forEach(function (p, k) {
        if (d.pointRadius === 0) return;
        svg += '<circle class="mc-pt' + (animate ? " mc-anim mc-pop" : "") + '" data-i="' + p[3] + '" data-key="d' + x.i + '" style="animation-delay:' + (500 + k * 25) + 'ms" cx="' + r1(p[0]) + '" cy="' + r1(p[1]) + '" r="' + (d.pointRadius || 3.5) + '" fill="' + esc(color) + '" stroke="#fff" stroke-width="1.5"/>';
      });
    });

    // guide line (line charts hover) - above the data, below the overlay
    svg += horizontal ? "" : '<line class="mc-guide" x1="0" x2="0" y1="' + padT + '" y2="' + (padT + plotH) + '"/>';

    // ---- axis titles + legend ----
    if (titleL) svg += '<text transform="translate(12 ' + r1(padT + plotH / 2) + ') rotate(-90)" text-anchor="middle" font-size="11.5" fill="' + MUTED + '">' + esc(titleL) + "</text>";
    if (titleR) svg += '<text transform="translate(' + (W - 8) + " " + r1(padT + plotH / 2) + ') rotate(90)" text-anchor="middle" font-size="11.5" fill="' + MUTED + '">' + esc(titleR) + "</text>";
    if (titleB) svg += '<text x="' + r1(padL + plotW / 2) + '" y="' + (H - 4) + '" text-anchor="middle" font-size="11.5" fill="' + MUTED + '">' + esc(titleB) + "</text>";
    if (showLegend) {
      svg += legendSvg(all.map(function (x) {
        var isBar = kindOf(x.d) === "bar";
        return { key: "d" + x.i, label: x.d.label || "Series " + (x.i + 1), off: !!hidden["d" + x.i],
                 color: x.d.legendColor || (isBar ? pick(x.d.backgroundColor, x.i, PALETTE[x.i % PALETTE.length]) : pick(x.d.borderColor, x.i, PALETTE[x.i % PALETTE.length])) };
      }), W, 18);
    }

    // ---- overlay that catches the pointer (clickable when options.onClick is given) ----
    var clickable = !!(cfg.options && cfg.options.onClick);
    svg += '<rect class="mc-overlay' + (clickable ? " mc-clickable" : "") + '" x="' + padL + '" y="' + padT + '" width="' + plotW + '" height="' + plotH + '" fill="transparent"/>';

    // ---- tooltip contents per category ----
    var tips = labels.map(function (label, i) {
      var rows = [];
      datasets.forEach(function (x) {
        var v = x.d.data[i];
        if (!has(v)) return;
        var isBar = kindOf(x.d) === "bar";
        rows.push({ color: isBar ? pick(x.d.backgroundColor, i, PALETTE[x.i % PALETTE.length]) : pick(x.d.borderColor, x.i, PALETTE[x.i % PALETTE.length]),
                    label: x.d.label || "", value: fmtVal(num(v), x.d, cfg) });
      });
      var extra = cfg.options && typeof cfg.options.tooltipExtra === "function" ? cfg.options.tooltipExtra(i) : [];
      return tipHtml(label, rows, extra);
    });

    return {
      svg: '<svg viewBox="0 0 ' + W + " " + H + '" xmlns="http://www.w3.org/2000/svg" role="img">' + svg + "</svg>",
      model: { kind: horizontal ? "hbar" : "cartesian", n: n, band: band, padL: padL, padT: padT, plotW: plotW, plotH: plotH,
               W: W, H: H, tips: tips, lines: lineGeo, clickable: clickable, labels: labels }
    };
  }

  // ------------------------------------------------------------- public API --
  function build(cfg, W, H, st) {
    if (!cfg || !cfg.data) return { svg: emptySvg(W, H, "No data yet"), model: null };
    return cfg.type === "doughnut" ? doughnutBuild(cfg, W, H, st) : cartesianBuild(cfg, W, H, st);
  }

  // Pure string version (used by tests/minicharts_check.js and anywhere without a DOM).
  function toSvg(cfg, opts) {
    opts = opts || {};
    return build(cfg, opts.width || 600, opts.height || 240, { hidden: {}, animate: false }).svg;
  }

  var STYLE_ID = "minichart-styles";
  var CSS = [
    ".mini-chart{position:relative;line-height:1.2}",
    ".mini-chart svg{width:100%;height:auto;display:block;overflow:visible;font-family:inherit;user-select:none;-webkit-tap-highlight-color:transparent}",
    ".mc-bar,.mc-slice,.mc-pt,.mc-line,.mc-area{transition:opacity .18s ease,fill .18s ease,filter .18s ease,transform .18s cubic-bezier(.2,.9,.3,1.3)}",
    ".mc-bar{cursor:default;fill:var(--c)}",
    ".mc-dim{opacity:.42}",
    ".mc-bar.mc-hot{fill:var(--ch);filter:drop-shadow(0 4px 8px rgba(20,32,26,.3));stroke:rgba(255,255,255,.85);stroke-width:1.5}",
    ".mc-bar-v.mc-hot{transform:translateY(-4px)}",
    ".mc-bar-h.mc-hot{transform:translateX(4px)}",
    ".mc-pt{transform-box:fill-box;transform-origin:center}",
    ".mc-pt.mc-hot{transform:scale(1.9);filter:drop-shadow(0 0 4px rgba(20,32,26,.45))}",
    ".mc-band{fill:rgba(63,90,52,.09);opacity:0;transition:opacity .15s ease,x .12s ease-out,y .12s ease-out;pointer-events:none}",
    ".mc-band.mc-on{opacity:1}",
    ".mc-select{fill:rgba(201,222,59,.32);stroke:rgba(154,174,32,.7);stroke-dasharray:4 3;pointer-events:none}",
    ".mc-guide{stroke:#14201A;stroke-width:1;stroke-dasharray:3 3;opacity:0;transition:opacity .15s ease;pointer-events:none}",
    ".mc-guide.mc-on{opacity:.5}",
    ".mc-overlay.mc-clickable{cursor:pointer}",
    ".mc-slice{cursor:pointer}",
    ".mc-slice.mc-hot{transform:translate(var(--dx),var(--dy));filter:drop-shadow(0 4px 8px rgba(20,32,26,.3))}",
    ".mc-center text{transition:opacity .15s ease}",
    ".mc-legend-item{cursor:pointer;transition:opacity .15s ease}",
    ".mc-legend-item:hover text{text-decoration:underline}",
    ".mc-legend-item.mc-off{opacity:.38}",
    ".mc-legend-item.mc-off text{text-decoration:line-through}",
    ".mc-tip{position:absolute;z-index:30;pointer-events:none;background:#14201A;color:#fff;border-radius:8px;padding:9px 12px;font-size:12px;min-width:120px;max-width:280px;box-shadow:0 10px 26px rgba(20,32,26,.35);opacity:0;transform:translateY(4px);transition:opacity .12s ease,transform .12s ease}",
    ".mc-tip.mc-on{opacity:1;transform:none}",
    ".mc-tip-title{font-weight:700;color:#C9DE3B;margin-bottom:5px;letter-spacing:.01em}",
    ".mc-tip-row{display:flex;align-items:center;gap:7px;padding:1.5px 0}",
    ".mc-tip-row i{width:9px;height:9px;border-radius:3px;flex-shrink:0;box-shadow:0 0 0 1.5px rgba(255,255,255,.55)}",
    ".mc-tip-row span{flex:1;color:#DCE3D2}",
    ".mc-tip-row b{font-family:'IBM Plex Mono',Consolas,monospace;font-weight:500;padding-left:10px}",
    ".mc-tip-extra{margin-top:5px;padding-top:5px;border-top:1px solid rgba(255,255,255,.18);color:#C9D4C0}",
    "@keyframes mc-grow-v{from{transform:scaleY(0)}to{transform:scaleY(1)}}",
    "@keyframes mc-grow-h{from{transform:scaleX(0)}to{transform:scaleX(1)}}",
    "@keyframes mc-draw{from{stroke-dasharray:1;stroke-dashoffset:1}to{stroke-dasharray:1;stroke-dashoffset:0}}",
    "@keyframes mc-fade{from{opacity:0}to{opacity:1}}",
    "@keyframes mc-pop{from{opacity:0;transform:scale(0)}to{opacity:1;transform:scale(1)}}",
    "@keyframes mc-slice-in{from{opacity:0;transform:scale(.86) rotate(-14deg)}to{opacity:1;transform:none}}",
    ".mc-anim{animation-fill-mode:backwards}",
    ".mc-grow-v{animation:mc-grow-v .75s cubic-bezier(.2,.8,.2,1)}",
    ".mc-grow-h{animation:mc-grow-h .75s cubic-bezier(.2,.8,.2,1)}",
    ".mc-draw{animation:mc-draw 1.1s ease}",
    ".mc-fade{animation:mc-fade .9s ease .2s}",
    ".mc-pop{animation:mc-pop .4s cubic-bezier(.2,1.6,.4,1)}",
    ".mc-slice-g.mc-anim{animation:mc-slice-in .7s cubic-bezier(.2,.9,.3,1)}",
    "@media (prefers-reduced-motion:reduce){.mc-anim{animation:none!important}.mc-tip,.mc-band,.mc-guide{transition:none}}"
  ].join("\n");

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement("style");
    s.id = STYLE_ID; s.textContent = CSS;
    document.head.appendChild(s);
  }

  // Draws into a <div class="mini-chart"> placed after `canvas` and hides the canvas.
  function render(canvas, cfg) {
    ensureStyles();
    var parent = canvas.parentElement;
    var box = document.createElement("div");
    box.className = "mini-chart";
    var tip = document.createElement("div");
    tip.className = "mc-tip";
    canvas.classList.add("hidden");
    canvas.insertAdjacentElement("afterend", box);

    var state = { hidden: {}, animate: true };
    var lastW = 0, model = null, svgEl = null, raf = 0, ro = null, dead = false;
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) state.animate = false;

    function measure() {
      var W = 480;
      if (parent && parent.clientWidth) {
        var cs = window.getComputedStyle(parent);
        W = parent.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
      }
      return Math.max(300, Math.min(1200, Math.round(W)));
    }
    function heightFor(W) {
      var H = Math.max(180, (Number(canvas.getAttribute("height")) || 220) + 20);
      if (cfg && cfg.type === "bar" && cfg.options && cfg.options.indexAxis === "y" && cfg.data && cfg.data.labels) {
        H = Math.max(H, cfg.data.labels.length * 30 + 70);
      }
      return H;
    }

    function draw() {
      if (dead) return;
      var W = measure(), H = heightFor(W);
      lastW = W;
      var out = build(cfg, W, H, state);
      model = out.model;
      box.innerHTML = out.svg;
      box.appendChild(tip);
      tip.classList.remove("mc-on");
      svgEl = box.querySelector("svg");
      state.animate = false;               // animate only the first paint
      bind();
    }

    function q(sel) { return Array.prototype.slice.call(box.querySelectorAll(sel)); }
    function showTip(html, cx, cy) {
      tip.innerHTML = html;
      var b = box.getBoundingClientRect();
      var x = cx - b.left + 16, y = cy - b.top - tip.offsetHeight - 12;
      if (x + tip.offsetWidth > b.width) x = cx - b.left - tip.offsetWidth - 16;
      if (x < 0) x = 4;
      if (y < 0) y = cy - b.top + 18;
      tip.style.left = Math.round(x) + "px";
      tip.style.top = Math.round(y) + "px";
      tip.classList.add("mc-on");
    }
    function hideTip() { tip.classList.remove("mc-on"); }

    function bind() {
      // legend: hover highlights a series, click shows / hides it
      q(".mc-legend-item").forEach(function (g) {
        var key = g.getAttribute("data-key");
        g.addEventListener("click", function () {
          var visibleCount = q(".mc-legend-item:not(.mc-off)").length;
          if (!state.hidden[key] && visibleCount <= 1) return;   // always keep one series
          state.hidden[key] = !state.hidden[key];
          draw();
        });
        g.addEventListener("pointerenter", function () {
          if (state.hidden[key]) return;
          q("[data-key]").forEach(function (el) {
            if (el.classList.contains("mc-legend-item")) return;
            el.classList.toggle("mc-dim", el.getAttribute("data-key") !== key);
          });
          q(".mc-slice").forEach(function (el) {
            var on = "s" + el.getAttribute("data-i") === key;
            el.classList.toggle("mc-hot", on); el.classList.toggle("mc-dim", !on);
          });
        });
        g.addEventListener("pointerleave", function () {
          q(".mc-dim").forEach(function (el) { el.classList.remove("mc-dim"); });
          q(".mc-slice.mc-hot").forEach(function (el) { el.classList.remove("mc-hot"); });
        });
      });
      if (!model) return;
      if (model.kind === "doughnut") bindDoughnut(); else bindCartesian();
    }

    function bindDoughnut() {
      var c1 = box.querySelector(".mc-c1"), c2 = box.querySelector(".mc-c2");
      function reset() {
        q(".mc-slice").forEach(function (el) { el.classList.remove("mc-hot", "mc-dim"); });
        c1.textContent = model.centerDefault[0]; c2.textContent = model.centerDefault[1];
        hideTip();
      }
      q(".mc-slice").forEach(function (el) {
        var i = Number(el.getAttribute("data-i"));
        var s = model.slices.filter(function (x) { return x.i === i; })[0];
        function on(e) {
          q(".mc-slice").forEach(function (o) { o.classList.toggle("mc-hot", o === el); o.classList.toggle("mc-dim", o !== el); });
          c1.textContent = fmtVal(s.value, model.unitDs, cfg); c2.textContent = s.label + " \u00b7 " + s.pct + "%";
          showTip(tipHtml(s.label, [{ color: s.color, label: s.pct + "% of total", value: fmtVal(s.value, model.unitDs, cfg) }]), e.clientX, e.clientY);
        }
        el.addEventListener("pointerenter", on);
        el.addEventListener("pointermove", on);
        el.addEventListener("pointerleave", reset);
        if (cfg.options && cfg.options.onClick) el.addEventListener("click", function () { cfg.options.onClick(i); });
      });
    }

    function bindCartesian() {
      var overlay = box.querySelector(".mc-overlay");
      var bandEl = box.querySelector(".mc-band"), guide = box.querySelector(".mc-guide");
      var horizontal = model.kind === "hbar", current = -1;

      function indexAt(e) {
        var r = svgEl.getBoundingClientRect(), k = model.W / r.width;
        var pos = horizontal ? (e.clientY - r.top) * k - model.padT : (e.clientX - r.left) * k - model.padL;
        var i = Math.floor(pos / model.band);
        return Math.max(0, Math.min(model.n - 1, i));
      }
      function activate(i, e) {
        if (i !== current) {
          current = i;
          q(".mc-hot").forEach(function (el) { el.classList.remove("mc-hot"); });
          q(".mc-bar").forEach(function (el) {
            var on = Number(el.getAttribute("data-i")) === i;
            el.classList.toggle("mc-hot", on); el.classList.toggle("mc-dim", !on);
          });
          q(".mc-pt").forEach(function (el) { el.classList.toggle("mc-hot", Number(el.getAttribute("data-i")) === i); });
          if (bandEl) {
            if (horizontal) bandEl.setAttribute("y", model.padT + model.band * i);
            else {
              bandEl.setAttribute("x", model.padL + model.band * i);
            }
            bandEl.classList.add("mc-on");
          }
          if (guide && model.lines.length) {
            var gx = model.padL + model.band * i + model.band / 2;
            guide.setAttribute("x1", gx); guide.setAttribute("x2", gx);
            guide.classList.add("mc-on");
          }
        }
        showTip(model.tips[i], e.clientX, e.clientY);
      }
      function leave() {
        current = -1;
        q(".mc-hot").forEach(function (el) { el.classList.remove("mc-hot"); });
        q(".mc-bar.mc-dim").forEach(function (el) { el.classList.remove("mc-dim"); });
        if (bandEl) bandEl.classList.remove("mc-on");
        if (guide) guide.classList.remove("mc-on");
        hideTip();
      }
      overlay.addEventListener("pointermove", function (e) { activate(indexAt(e), e); });
      overlay.addEventListener("pointerdown", function (e) { activate(indexAt(e), e); });
      overlay.addEventListener("pointerleave", leave);
      if (model.clickable) overlay.addEventListener("click", function (e) { cfg.options.onClick(indexAt(e)); });
    }

    draw();

    if (typeof ResizeObserver !== "undefined" && parent) {
      ro = new ResizeObserver(function () {
        if (dead || raf) return;
        raf = requestAnimationFrame(function () {
          raf = 0;
          if (!dead && Math.abs(measure() - lastW) > 8) draw();
        });
      });
      ro.observe(parent);
    }

    return {
      destroy: function () {
        dead = true;
        if (ro) ro.disconnect();
        if (raf) cancelAnimationFrame(raf);
        box.remove();
        canvas.classList.remove("hidden");
      }
    };
  }

  var api = { toSvg: toSvg, render: render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MiniChart = api;
})(typeof window !== "undefined" ? window : this);
