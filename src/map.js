/*
 * MediaMap — tiny schematic map renderer for the design comps and the final workbench.
 * Draws a real-coordinate projection of the selected anchor's 1/3km candidates.
 * No tiles, no network, no dependencies.
 */
(function (root) {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  function project(lng, lat, b, w, h, pad) {
    var x = pad + ((lng - b.minLng) / (b.maxLng - b.minLng)) * (w - pad * 2);
    var y = h - pad - ((lat - b.minLat) / (b.maxLat - b.minLat)) * (h - pad * 2);
    return { x: x, y: y };
  }

  function boundsOf(sample) {
    var c = sample.center || { lng: 121.4, lat: 31.2 };
    var r = sample.radius || 3000;
    var dLat = r / 111000;
    var dLng = r / (111000 * Math.max(0.2, Math.cos(c.lat * Math.PI / 180)));
    var b = { minLng: c.lng - dLng, maxLng: c.lng + dLng, minLat: c.lat - dLat, maxLat: c.lat + dLat };
    var pts = [].concat(sample.points.bus || [], sample.points.metro || []);
    pts.forEach(function (p) {
      if (p.lng == null || p.lat == null) return;
      b.minLng = Math.min(b.minLng, p.lng);
      b.maxLng = Math.max(b.maxLng, p.lng);
      b.minLat = Math.min(b.minLat, p.lat);
      b.maxLat = Math.max(b.maxLat, p.lat);
    });
    b.minLng -= dLng * 0.08; b.maxLng += dLng * 0.08;
    b.minLat -= dLat * 0.08; b.maxLat += dLat * 0.08;
    return b;
  }

  function render(svg, sample, opts) {
    opts = opts || {};
    var w = opts.width || 680, h = opts.height || 420, pad = opts.pad || 26;
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    var b = boundsOf(sample);
    var c = project(sample.center.lng, sample.center.lat, b, w, h, pad);

    if (opts.background) svg.appendChild(el("rect", { x: 0, y: 0, width: w, height: h, fill: opts.background }));

    if (opts.grid !== false) {
      var g = el("g", { stroke: opts.gridColor || "#2A343B", "stroke-opacity": opts.gridOpacity || 0.55, "stroke-width": 1 });
      for (var i = 1; i < 10; i++) g.appendChild(el("line", { x1: (w / 10) * i, y1: 0, x2: (w / 10) * i, y2: h }));
      for (var j = 1; j < 7; j++) g.appendChild(el("line", { x1: 0, y1: (h / 7) * j, x2: w, y2: (h / 7) * j }));
      svg.appendChild(g);
    }

    // coverage rings (ellipse because lng/lat scale differs)
    if (opts.rings !== false) {
      var radii = [sample.radius || 3000, 3000, 1000]
        .filter(function (v, i, a) { return a.indexOf(v) === i && v <= (sample.radius || 3000); })
        .sort(function (a, b) { return b - a; });
      radii.forEach(function (r, idx) {
        var dLat = r / 111000;
        var dLng = r / (111000 * Math.cos(sample.center.lat * Math.PI / 180));
        var p2 = project(sample.center.lng + dLng, sample.center.lat + dLat, b, w, h, pad);
        var rx = Math.abs(p2.x - c.x), ry = Math.abs(p2.y - c.y);
        var ring = el("ellipse", {
          cx: c.x, cy: c.y, rx: rx, ry: ry,
          fill: idx === 0 ? (opts.ringFill || "none") : "none",
          stroke: opts.ringColor || "#FFB27A",
          "stroke-opacity": idx === 0 ? (opts.ringOpacity || 0.45) : 0.32,
          "stroke-width": idx === 0 ? 1.2 : 1,
          "stroke-dasharray": idx === 0 ? (opts.ringDash || "5 7") : "2 5"
        });
        ring.setAttribute("class", "map-ring");
        svg.appendChild(ring);
      });
    }

    var selected = [];
    var buses = (sample.points.bus || []).slice();
    var metros = (sample.points.metro || []).slice();

    buses.forEach(function (p) {
      if (p.lng == null) return;
      var pt = project(p.lng, p.lat, b, w, h, pad);
      if (p.selected) {
        selected.push({ kind: "bus", p: p, x: pt.x, y: pt.y });
      } else {
        svg.appendChild(el("circle", {
          cx: pt.x, cy: pt.y, r: opts.candidateSize || 2.4,
          fill: opts.candidateColor || "#6B7A82", "fill-opacity": 0.55
        }));
      }
    });
    metros.forEach(function (p) {
      if (p.lng == null) return;
      var pt = project(p.lng, p.lat, b, w, h, pad);
      if (p.selected) {
        selected.push({ kind: "metro", p: p, x: pt.x, y: pt.y });
      } else {
        svg.appendChild(el("rect", {
          x: pt.x - 2.2, y: pt.y - 2.2, width: 4.4, height: 4.4,
          fill: "none", stroke: opts.candidateColor || "#6B7A82", "stroke-opacity": 0.6
        }));
      }
    });

    // lines from anchor to selected bus stops
    if (opts.lines !== false) {
      selected.filter(function (s) { return s.kind === "bus"; }).forEach(function (s) {
        svg.appendChild(el("line", {
          x1: c.x, y1: c.y, x2: s.x, y2: s.y,
          stroke: opts.lineColor || "#FF5A3C", "stroke-opacity": opts.lineOpacity || 0.5,
          "stroke-width": opts.lineWidth || 1, "stroke-dasharray": opts.lineDash || "3 4"
        }));
      });
    }

    // selected points
    var busLabelCount = 0;
    selected.forEach(function (s, i) {
      var showLabel = opts.labels !== false && (s.kind === "metro" || busLabelCount < (opts.maxBusLabels == null ? 8 : opts.maxBusLabels));
      if (s.kind === "bus") busLabelCount += 1;
      if (s.kind === "metro") {
        svg.appendChild(el("circle", {
          cx: s.x, cy: s.y, r: opts.metroSize || 6.5,
          fill: "none", stroke: opts.selectedColor || "#FF5A3C", "stroke-width": 2
        }));
        svg.appendChild(el("circle", {
          cx: s.x, cy: s.y, r: 2.2, fill: opts.selectedColor || "#FF5A3C"
        }));
      } else {
        svg.appendChild(el("circle", {
          cx: s.x, cy: s.y, r: opts.selectedSize || 4.2,
          fill: opts.selectedColor || "#FF5A3C"
        }));
      }
      if (showLabel) {
        var label = s.kind === "metro" ? s.p.station : s.p.name;
        var tx = s.x + 7, ty = s.y - 5 - (i % 3) * 1.5;
        if (tx > w - 70) tx = s.x - 8 - Math.min(64, label.length * 6);
        var t = el("text", {
          x: tx, y: ty,
          fill: opts.labelColor || "#E8E6E0",
          "font-size": opts.labelSize || 9,
          "font-family": opts.labelFont || "Consolas, monospace",
          "letter-spacing": "0.02em"
        });
        t.textContent = (opts.numbered ? String(i + 1).padStart(2, "0") + " " : "") + label;
        svg.appendChild(t);
      }
    });

    // center marker
    svg.appendChild(el("circle", { cx: c.x, cy: c.y, r: opts.centerHalo || 13, fill: opts.selectedColor || "#FF5A3C", "fill-opacity": 0.12 }));
    svg.appendChild(el("circle", { cx: c.x, cy: c.y, r: opts.centerSize || 5, fill: opts.selectedColor || "#FF5A3C", stroke: opts.background || "#0B0D14", "stroke-width": 2 }));
    if (opts.centerLabel !== false) {
      var ct = el("text", {
        x: c.x + 10, y: c.y + 4,
        fill: opts.labelColor || "#E8E6E0",
        "font-size": opts.centerLabelSize || 11,
        "font-weight": "700",
        "font-family": opts.labelFont || "Consolas, monospace"
      });
      ct.textContent = sample.activeAnchor.replace("上海", "").replace("妇儿医院", "妇儿");
      svg.appendChild(ct);
    }
  }

  root.MediaMap = { render: render };
})(typeof globalThis !== "undefined" ? globalThis : this);
