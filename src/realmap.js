/*
 * RealMap — draws a real OSM basemap crop + projected inventory points.
 * Expects window.MAP_ASSETS[anchor][radius] from src/map-assets.js.
 * No network at runtime; the PNG is local.
 */
(function (root) {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";

  function el(name, attrs) {
    var n = document.createElementNS(NS, name);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function mx(lng) { return (lng + 180) / 360; }
  function my(lat) {
    var s = Math.sin(lat * Math.PI / 180);
    return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
  }

  function render(svg, sample, meta, opts) {
    opts = opts || {};
    if (!meta) return false;
    var w = meta.width, h = meta.height;
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    // real basemap
    svg.appendChild(el("image", {
      href: meta.file,
      x: 0, y: 0, width: w, height: h,
      preserveAspectRatio: "none",
      style: "filter:grayscale(1) contrast(1.18) brightness(1.02);opacity:1"
    }));

    // very light paper wash: keep OSM labels readable, remove the pastel cast
    svg.appendChild(el("rect", { x: 0, y: 0, width: w, height: h, fill: "#FAF8F2", "fill-opacity": 0.03 }));

    var left = mx(meta.minLng), right = mx(meta.maxLng);
    var top = my(meta.maxLat), bottom = my(meta.minLat);
    function project(lng, lat) {
      return {
        x: (mx(lng) - left) / (right - left) * w,
        y: (my(lat) - top) / (bottom - top) * h
      };
    }

    var anchors = (sample.anchors && sample.anchors.length) ? sample.anchors : [{ lng: sample.center.lng, lat: sample.center.lat, radius: sample.radius, label: sample.anchorLabel }];
    anchors.forEach(function (a, ai) {
      var c = project(a.lng, a.lat);
      var baseRadius = a.radius || sample.radius || 3000;
      // coverage rings, 5/3/1 km depending on this node's radius
      var radii = [5000, 3000, 1000].filter(function (r) { return r <= baseRadius; });
      radii.forEach(function (r, idx) {
        var dLat = r / 111000;
        var dLng = r / (111000 * Math.cos(a.lat * Math.PI / 180));
        var p2 = project(a.lng + dLng, a.lat + dLat);
        var rx = Math.abs(p2.x - c.x), ry = Math.abs(p2.y - c.y);
        svg.appendChild(el("ellipse", {
          cx: c.x, cy: c.y, rx: rx, ry: ry,
          fill: "none",
          stroke: opts.ringColor || "#C8443A",
          "stroke-opacity": idx === 0 ? 0.72 : 0.38,
          "stroke-width": idx === 0 ? 1.7 : 1.1,
          "stroke-dasharray": idx === 0 ? "6 7" : "2 5"
        }));
        var label = el("text", {
          x: c.x + 4, y: c.y - ry - 4,
          fill: opts.ringColor || "#C8443A",
          "font-size": 9, "font-family": "Consolas, monospace",
          "paint-order": "stroke", stroke: opts.haloColor || "#FAF8F2", "stroke-width": 3
        });
        label.textContent = (r / 1000) + "km";
        svg.appendChild(label);
      });
    });

    var selected = [];
    // Bus = route polylines (platform geometry, WGS84). Candidates faint, selected bold.
    // Never drawn as dots; no anchor→stop connector lines.
    function pathD(path) {
      return path.map(function (q, i) {
        var pt = project(q[0], q[1]);
        return (i ? "L" : "M") + pt.x.toFixed(1) + " " + pt.y.toFixed(1);
      }).join("");
    }
    var lines = sample.lines || [];
    lines.filter(function (l) { return !l.selected; }).forEach(function (l) {
      svg.appendChild(el("path", {
        d: pathD(l.path), fill: "none",
        stroke: opts.candidateColor || "#2F5FD0", "stroke-opacity": 0.3, "stroke-width": 1
      }));
    });
    lines.filter(function (l) { return l.selected; }).forEach(function (l) {
      svg.appendChild(el("path", {
        d: pathD(l.path), fill: "none",
        stroke: opts.haloColor || "#FAF8F2", "stroke-opacity": 0.95, "stroke-width": 7,
        "stroke-linejoin": "round", "stroke-linecap": "round"
      }));
      var busColor = opts.busSelectedColor || opts.lineColor || "#FF4D00";
      svg.appendChild(el("path", {
        d: pathD(l.path), fill: "none",
        stroke: busColor, "stroke-opacity": 0.98, "stroke-width": 4.2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        "data-key": "bus:" + l.line,
        style: "filter:drop-shadow(0 0 3px " + busColor + ")"
      }));
      if (l.tick) {
        var tp = project(l.tick[0], l.tick[1]);
        selected.push({ kind: "bus", p: { name: l.name + " · 经" + (l.pointName || "—"), lng: l.tick[0], lat: l.tick[1] }, x: tp.x, y: tp.y });
      }
    });
    (sample.points.metro || []).forEach(function (p) {
      if (p.lng == null || p.lat == null) return;
      var pt = project(p.lng, p.lat);
      if (p.selected) {
        selected.push({ kind: "metro", p: p, x: pt.x, y: pt.y });
      } else {
        svg.appendChild(el("rect", {
          x: pt.x - 3, y: pt.y - 3, width: 6, height: 6,
          fill: "none", stroke: opts.candidateColor || "#2F5FD0", "stroke-width": 1.4, "stroke-opacity": 0.8
        }));
      }
    });

    var busLabelCount = 0;
    selected.forEach(function (s, i) {
      var showLabel = s.kind === "metro" || busLabelCount < (opts.maxBusLabels == null ? 7 : opts.maxBusLabels);
      if (s.kind === "bus") busLabelCount += 1;
      if (s.kind === "metro") {
        var metroColor = opts.selectedColor || "#0B63FF";
        var mkey = s.p.selectedIds && s.p.selectedIds[0] ? "metro:" + s.p.selectedIds[0] : "";
        var ring = el("circle", {
          cx: s.x, cy: s.y, r: 9, fill: "none",
          stroke: metroColor, "stroke-width": 3,
          style: "filter:drop-shadow(0 0 3px " + metroColor + ")"
        });
        if (mkey) ring.setAttribute("data-key", mkey);
        svg.appendChild(ring);
        svg.appendChild(el("circle", { cx: s.x, cy: s.y, r: 3.4, fill: metroColor }));
      } else {
        // tiny tick where the route passes closest to the anchor (not a "point" media)
        svg.appendChild(el("circle", {
          cx: s.x, cy: s.y, r: 2.2, fill: opts.busSelectedColor || opts.selectedColor || "#C8443A",
          stroke: opts.haloColor || "#FAF8F2", "stroke-width": 1
        }));
      }
      if (!showLabel) return;
      var label = s.kind === "metro" ? (s.p.label || s.p.station) : s.p.name;
      var tx = s.x + 7, ty = s.y - 5 - (i % 3) * 2;
      if (tx > w - 80) tx = s.x - 8 - Math.min(70, label.length * 7);
      var t = el("text", {
        x: tx, y: ty,
        fill: opts.labelColor || "#151515",
        "font-size": opts.labelSize || 10,
        "font-weight": 600,
        "font-family": opts.labelFont || "Consolas, monospace",
        "paint-order": "stroke",
        stroke: opts.haloColor || "#FAF8F2", "stroke-width": 3.6,
        "stroke-linejoin": "round"
      });
      t.textContent = (opts.numbered ? String(i + 1).padStart(2, "0") + " " : "") + label;
      svg.appendChild(t);
    });

    // anchor markers (one per branch/store in network mode)
    anchors.forEach(function (a, ai) {
      var c = project(a.lng, a.lat);
      svg.appendChild(el("circle", {
        cx: c.x, cy: c.y, r: 12,
        fill: opts.anchorColor || opts.selectedColor || "#C8443A", "fill-opacity": 0.14
      }));
      svg.appendChild(el("circle", {
        cx: c.x, cy: c.y, r: 4.5,
        fill: opts.anchorColor || opts.selectedColor || "#C8443A", stroke: opts.haloColor || "#FAF8F2", "stroke-width": 2
      }));
      var shortLabel = String(a.label || sample.anchorLabel || (sample.activeAnchor || "").replace("上海", "").replace("妇儿医院", "妇儿")).replace(/（[^）]*）/g, "");
      var dx = anchors.length > 1 ? [8, -8, 9][ai % 3] : 9;
      var dy = anchors.length > 1 ? [-8, 18, 14][ai % 3] : 4;
      var ct = el("text", {
        x: c.x + dx, y: c.y + dy,
        "text-anchor": anchors.length > 1 && ai % 3 === 1 ? "end" : "start",
        fill: opts.labelColor || "#151515",
        "font-size": 11, "font-weight": 700,
        "font-family": opts.labelFont || "Consolas, monospace",
        "paint-order": "stroke", stroke: opts.haloColor || "#FAF8F2", "stroke-width": 3
      });
      ct.textContent = shortLabel;
      svg.appendChild(ct);
    });

    if (sample.geoNote) {
      var gn = el("text", {
        x: 10, y: 22, fill: opts.labelColor || "#151515",
        "font-size": 13, "font-weight": 600, "font-family": opts.labelFont || "Consolas, monospace",
        "paint-order": "stroke", stroke: opts.haloColor || "#FAF8F2", "stroke-width": 4
      });
      gn.textContent = sample.geoNote;
      svg.appendChild(gn);
    }

    // attribution
    var at = el("text", {
      x: w - 8, y: h - 8, "text-anchor": "end",
      fill: "#6E6A62", "font-size": 8, "font-family": "Consolas, monospace",
      "paint-order": "stroke", stroke: opts.haloColor || "#FAF8F2", "stroke-width": 3
    });
    at.textContent = "© OpenStreetMap contributors";
    svg.appendChild(at);
    return true;
  }

  root.RealMap = { render: render };
})(typeof globalThis !== "undefined" ? globalThis : this);
