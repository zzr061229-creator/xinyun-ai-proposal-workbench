/*
 * Engine — deterministic media plan selection & pricing.
 * Pure functions, no DOM, no network. Runs in browser (window.Engine) and Node (module.exports).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.Engine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var PRICING = {
    bus: { S: 58000, "A++": 48000, "A+": 38000, AA: 48000 },
    metro: { "A++": 300000, "A+": 200000 },
    busDefault: 48000,
    metroDefault: 200000,
    production: { bus: 5000, metro: 2000 },
    discount: 1.0,        // 默认刊例；0.92 只是可切换示例，由 brief.discount 传入
    discountOptions: [1.0, 0.92],
    floor: 0.88,          // 仅销售视图底线
    monitoringRate: 0,
    weeksPerMonth: 52 / 12
  };

  var GRADE_SCORE = { S: 1, "A++": 0.8, "A+": 0.6, AA: 0.5 };
  var MAX_BUS_LINES = 14;
  var MAX_QTY_PER_LINE = 6;
  var MAX_EXITS_PER_STATION = 2;
  var BUS_DAILY_REACH = 98000; // 9.8万/辆/天, 05 样本均值（无平台数据时的兜底）
  var configuredFrom = null;

  // Prices come from data/config/pricing.json via APP_DATA.pricing when present.
  function configurePricing(data) {
    var pr = data && data.pricing;
    if (!pr || configuredFrom === pr) return;
    configuredFrom = pr;
    ["S", "A++", "A+"].forEach(function (g) {
      if (pr.bus && pr.bus[g]) PRICING.bus[g] = Number(pr.bus[g]);
      if (pr.metro && pr.metro[g]) PRICING.metro[g] = Number(pr.metro[g]);
    });
    if (pr.production) {
      if (pr.production.bus != null) PRICING.production.bus = Number(pr.production.bus);
      if (pr.production.metro != null) PRICING.production.metro = Number(pr.production.metro);
    }
    if (pr.discount) {
      if (pr.discount["default"] != null) PRICING.discount = Number(pr.discount["default"]);
      if (pr.discount.floor != null) PRICING.floor = Number(pr.discount.floor);
      if (pr.discount.options) PRICING.discountOptions = [PRICING.discount].concat(pr.discount.options.map(Number));
    }
    if (pr.monitoringRate != null) PRICING.monitoringRate = Number(pr.monitoringRate);
    if (pr.weeksPerMonth) PRICING.weeksPerMonth = Number(pr.weeksPerMonth);
  }

  function footfallOf(data, anchor) { return ((data && data.footfall) || {})[anchor] || null; }
  function sampleBusReach(data, grade) {
    var t = (data && data.sampleReach && data.sampleReach.busPerVehicleByGrade) || {};
    return t[grade] || t.all || BUS_DAILY_REACH;
  }
  var DAY_MS = 86400000;

  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
  function meters(lng1, lat1, lng2, lat2) {
    var R = 6371000, rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad, dLng = (lng2 - lng1) * rad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  function priceOf(media, grade) {
    var table = media === "metro" ? PRICING.metro : PRICING.bus;
    var fallback = media === "metro" ? PRICING.metroDefault : PRICING.busDefault;
    return table[grade] || fallback;
  }
  function gradeScore(grade) { return GRADE_SCORE[grade] == null ? 0.5 : GRADE_SCORE[grade]; }
  function monthsOf(weeks) { return weeks / PRICING.weeksPerMonth; }
  function unitMedia(media, grade, weeks) { return priceOf(media, grade) * monthsOf(weeks); }
  function unitProd(media) { return PRICING.production[media] || 0; }
  function unitNet(media, grade, weeks, discount) {
    return Math.round((unitMedia(media, grade, weeks) + unitProd(media)) * discount);
  }
  function round2(x) { return Math.round(x * 100) / 100; }
  function uniq(arr) { return Array.from(new Set(arr)); }

  function shortAnchor(data, name) {
    var a = (data.anchors || []).find(function (x) { return x.name === name; });
    return a ? a.short : name;
  }

  function metroShare(budgetYuan) {
    var wan = budgetYuan / 10000;
    if (wan <= 200) return 0.60;
    if (wan >= 500) return 0.47;
    return 0.60 - 0.13 * (wan - 200) / 300;
  }

  function addDays(dateStr, days) {
    var parts = String(dateStr || "2027-04-01").split("-").map(Number);
    var dt = new Date(Date.UTC(parts[0], (parts[1] || 1) - 1, (parts[2] || 1) + days));
    return dt.toISOString().slice(0, 10);
  }

  function buildSchedule(startDate) {
    return [
      { key: "brief", label: "需求/锚点确认", date: addDays(startDate, -18), note: "T-18" },
      { key: "design", label: "设计/内容审批", date: addDays(startDate, -14), note: "T-14" },
      { key: "production", label: "制作", date: addDays(startDate, -10), note: "T-10" },
      { key: "install", label: "分批夜间安装", date: addDays(startDate, -7), end: addDays(startDate, -2), note: "T-7～T-2" },
      { key: "launch", label: "上刊", date: startDate, note: "T0" },
      { key: "proof", label: "上刊证明", date: addDays(startDate, 1), note: "T+1" },
      { key: "monitor", label: "上刊监测", date: addDays(startDate, 5), note: "T+5" },
      { key: "monthly", label: "月监测", date: addDays(startDate, 30), note: "T+30" }
    ];
  }

  /**
   * Resolve the anchor set for this brief.
   * - explicit brief.anchors wins (tests / deep links)
   * - industry.anchorBundle (multi-branch / multi-store network) next
   * - otherwise the historical single anchor
   */
  function anchorsOf(data, brief) {
    if (brief.anchors && brief.anchors.length) {
      return brief.anchors.map(function (m) {
        return {
          anchor: m.anchor || m.anchorId || brief.anchor,
          radius: Number(m.radius || brief.radius || 3000),
          weight: Number(m.weight || 1),
          label: m.label || ""
        };
      });
    }
    var ind = (data.industries || []).find(function (x) { return x.id === brief.industryId; });
    var b = ind && ind.anchorBundle;
    if (b && b.members && b.members.length > 1) {
      return b.members.map(function (m) {
        return {
          anchor: m.anchor,
          radius: Number(m.radius || brief.radius || 1000),
          weight: Number(m.weight || 1),
          label: m.label || ""
        };
      });
    }
    return [{ anchor: brief.anchor, radius: Number(brief.radius || 3000), weight: 1, label: "" }];
  }

  /**
   * Build deduped candidates for one anchor or a bundle of anchors.
   * bus: one candidate per line (best media form, max freeCount)
   * metro: one candidate per exit (max 2 per station enforced at selection)
   * A line/exit covered by several nodes is kept once; the nearest node wins
   * for distance/reach attribution.
   */
  function buildCandidates(data, brief) {
    var warnings = [];
    var members = anchorsOf(data, brief);
    var anchor = members[0].anchor;
    var radiusKey = String(members[0].radius || 3000);

    var busByLine = Object.create(null);
    (data.bus || []).forEach(function (b) {
      if (!busByLine[b.line]) busByLine[b.line] = [];
      busByLine[b.line].push(b);
    });

    var busMap = new Map();
    var metroMap = new Map();
    var orphanBus = new Set();
    var orphanStations = new Set();
    var coverageBusNames = new Set();
    var coverageStationNames = new Set();
    var coverageBusRows = 0;
    var coverageMetroRows = 0;
    var coverageTotal = 0;
    var citywideMetroExits = 0;
    var citywideStationNames = new Set();

    function mergeAnchor(list, name) {
      if (list.indexOf(name) < 0) list.push(name);
      return list;
    }

    members.forEach(function (m) {
      var all = (data.coverage || {})[m.anchor];
      if (!all) {
        warnings.push("锚点「" + m.anchor + "」没有覆盖数据。");
        return;
      }
      var key = String(m.radius || brief.radius || 3000);
      var cov = all[key];
      if (!cov) {
        var keys = Object.keys(all).sort(function (a, b) { return Number(a) - Number(b); });
        warnings.push("锚点「" + m.anchor + "」没有 " + key + "m 覆盖，改用 " + (keys[0] || "-") + "m。");
        key = keys[0];
        cov = all[key];
      }
      if (!cov) {
        warnings.push("锚点「" + m.anchor + "」覆盖数据为空。");
        return;
      }
      m._cov = cov;
      m._radius = Number(key);
      coverageTotal += cov.list.length;
      var label = m.label || shortAnchor(data, m.anchor);

      cov.list.forEach(function (r) {
        if (r.mediaType === "bus") {
          coverageBusRows += 1;
          coverageBusNames.add(r.lineName);
          var alias = (data.aliases || {})[r.lineName];
          if (!alias || !alias.matched || !alias.inventoryName) { orphanBus.add(r.lineName); return; }
          var rows = busByLine[alias.inventoryName] || [];
          if (!rows.length) { orphanBus.add(r.lineName); return; }
          var best = rows.slice().sort(function (a, b) {
            if (b.free !== a.free) return b.free - a.free;
            if (gradeScore(b.grade) !== gradeScore(a.grade)) return gradeScore(b.grade) - gradeScore(a.grade);
            return priceOf("bus", a.grade) - priceOf("bus", b.grade);
          })[0];
          var line = alias.inventoryName;
          var prev = busMap.get(line);
          if (prev) {
            mergeAnchor(prev.anchors, m.anchor);
            if (r.minDistance < prev.distance) {
              prev.distance = r.minDistance;
              prev.pointName = r.pointName || prev.pointName;
              prev.pointLng = r.pointLng;
              prev.pointLat = r.pointLat;
              prev.pointDistance = r.pointDistance;
              prev.reachAnchor = m.anchor;
              prev.anchorLabel = label;
              prev.localRadius = m._radius;
            }
            return;
          }
          busMap.set(line, {
            media: "bus",
            id: line + "|" + best.media,
            line: line,
            name: line + (best.media ? " · " + best.media : ""),
            subName: best.media || "",
            company: best.company || "",
            grade: best.grade,
            free: best.free,
            total: best.total,
            contract: best.contract,
            reserved: best.reserved,
            maintenance: best.maintenance,
            distance: r.minDistance,
            pointName: r.pointName || "",
            pointLng: r.pointLng,
            pointLat: r.pointLat,
            pointDistance: r.pointDistance,
            anchors: [m.anchor],
            anchorLabel: label,
            reachAnchor: m.anchor,
            localRadius: m._radius,
            weight: m.weight,
            coverageName: r.lineName
          });
        } else if (r.mediaType === "metro") {
          coverageMetroRows += 1;
          var station = r.pointName;
          coverageStationNames.add(station);
          var st = (data.stations || {})[station];
          if (!st || !st.inInventory) { orphanStations.add(station); return; }
          (st.exits || []).forEach(function (e) {
            if (!(e.free >= 1) || !e.grade) return;
            var prevM = metroMap.get(e.id);
            if (prevM) {
              mergeAnchor(prevM.anchors, m.anchor);
              if (r.lineName && prevM.stationLines.indexOf(r.lineName) < 0) prevM.stationLines.push(r.lineName);
              if (r.minDistance < prevM.distance) {
                prevM.distance = r.minDistance;
                prevM.pointLng = r.pointLng;
                prevM.pointLat = r.pointLat;
                prevM.pointDistance = r.pointDistance;
                prevM.reachAnchor = m.anchor;
                prevM.anchorLabel = label;
                prevM.localRadius = m._radius;
              }
              return;
            }
            metroMap.set(e.id, {
              media: "metro",
              id: e.id,
              station: station,
              exit: e.exit,
              name: station + " " + e.exit,
              subName: e.exit,
              grade: e.grade,
              free: e.free,
              total: e.total,
              contract: e.contract,
              reserved: e.reserved,
              area: e.area || "",
              district: e.district || "",
              distance: r.minDistance,
              pointName: station,
              pointLng: r.pointLng,
              pointLat: r.pointLat,
              pointDistance: r.pointDistance,
              anchors: [m.anchor],
              anchorLabel: label,
              reachAnchor: m.anchor,
              localRadius: m._radius,
              weight: m.weight,
              stationLines: r.lineName ? [r.lineName] : []
            });
          });
        }
      });
    });

    // 全城铺送：地铁候选不只看 4 个枢纽覆盖内的站，而是把红豆在库的
    // 24 个站全部放进池子；每个口按最近枢纽取人流文件，没有平台数据的
    // 口保持 null（显示“—”），不估算。公交仍由 4 个枢纽的覆盖决定。
    var ind = (data.industries || []).find(function (x) { return x.id === brief.industryId; });
    var bundle = ind && ind.anchorBundle;
    if (bundle && bundle.citywide) {
      var hubs = members.filter(function (m) { return !!m._cov; }).map(function (m) {
        return {
          anchor: m.anchor,
          label: m.label || shortAnchor(data, m.anchor),
          weight: m.weight,
          lng: Number(m._cov.center.lng),
          lat: Number(m._cov.center.lat)
        };
      }).filter(function (h) { return isFinite(h.lng) && isFinite(h.lat); });
      var exitGeo = {};
      Object.keys(data.geo || {}).forEach(function (a) {
        var g = data.geo[a] || {};
        Object.keys(g.exits || {}).forEach(function (id) {
          if (!exitGeo[id]) exitGeo[id] = g.exits[id];
        });
      });
      Object.keys(data.stations || {}).forEach(function (name) {
        var st = data.stations[name];
        if (!st || !st.inInventory || !st.coord) return;
        var best = null, bestD = Infinity;
        hubs.forEach(function (h) {
          var d = meters(st.coord.lng, st.coord.lat, h.lng, h.lat);
          if (d < bestD) { bestD = d; best = h; }
        });
        if (!best) return;
        (st.exits || []).forEach(function (e) {
          if (!(e.free >= 1) || !e.grade) return;
          if (metroMap.has(e.id)) return;
          var gp = exitGeo[e.id] || st.coord;
          metroMap.set(e.id, {
            media: "metro",
            id: e.id,
            station: name,
            exit: e.exit,
            name: name + " " + e.exit,
            subName: e.exit,
            grade: e.grade,
            free: e.free,
            total: e.total,
            contract: e.contract,
            reserved: e.reserved,
            area: e.area || "",
            district: e.district || "",
            distance: Math.round(bestD),
            pointName: name,
            pointLng: gp.lng,
            pointLat: gp.lat,
            pointDistance: Math.round(bestD),
            anchors: [best.anchor],
            anchorLabel: best.label,
            reachAnchor: best.anchor,
            localRadius: Math.max(3000, Math.round(bestD)),
            weight: best.weight,
            citywide: true,
            stationLines: []
          });
          citywideMetroExits += 1;
          citywideStationNames.add(name);
        });
      });
    }

    var bus = Array.from(busMap.values());
    var metro = Array.from(metroMap.values());
    attachReach(data, members, bus, metro, !!(bundle && bundle.citywide));
    // 行业权重里的“触达”维度：在本次候选内做 0–1 归一化。
    var reachMax = 0;
    bus.concat(metro).forEach(function (c) {
      var v = c.dailyReach != null ? c.dailyReach : (c.reachEst || 0);
      if (v > reachMax) reachMax = v;
    });
    bus.concat(metro).forEach(function (c) {
      var v = c.dailyReach != null ? c.dailyReach : (c.reachEst || 0);
      c.reachScore = reachMax > 0 ? v / reachMax : 0;
    });

    var validMembers = members.filter(function (m) { return !!m._cov; });
    var stats = {
      anchor: anchor,
      radius: Number(radiusKey),
      anchors: validMembers.map(function (m) { return m.anchor; }),
      anchorLabels: validMembers.map(function (m) { return m.label || shortAnchor(data, m.anchor); }),
      anchorCount: validMembers.length,
      coverageTotal: coverageTotal,
      coverageBusRows: coverageBusRows,
      coverageMetroRows: coverageMetroRows,
      coverageBusLines: coverageBusNames.size,
      coverageStations: coverageStationNames.size,
      citywide: !!(bundle && bundle.citywide),
      citywideMetroExits: citywideMetroExits,
      citywideStations: uniq(metro.map(function (m) { return m.station; })).length,
      citywideDistricts: uniq(metro.filter(function (m) { return m.district; }).map(function (m) { return m.district; })).length,
      busLines: bus.length,
      metroExits: metro.length,
      metroStations: uniq(metro.map(function (m) { return m.station; })).length,
      orphanBus: Array.from(orphanBus),
      orphanStations: Array.from(orphanStations),
      availableBusFree: bus.reduce(function (s, b) { return s + b.free; }, 0),
      availableMetroFree: metro.reduce(function (s, m) { return s + m.free; }, 0)
    };
    if (orphanBus.size && !(bundle && bundle.citywide)) {
      warnings.push("覆盖里有 " + orphanBus.size + " 条公交线路不在红豆可售库：" + Array.from(orphanBus).slice(0, 4).join("、"));
    }
    if (orphanStations.size) {
      var orphanNames = Array.from(orphanStations).slice(0, 4).join("、");
      warnings.push(bundle && bundle.citywide
        ? "覆盖范围内 " + orphanStations.size + " 个站不在红豆库（" + orphanNames + "）；全城模式已改用 24 个在库站。"
        : "覆盖里有 " + orphanStations.size + " 个地铁站不在红豆可售库：" + orphanNames);
    }
    if (Number(radiusKey) === 1000 && metro.length === 0) warnings.push("1km 内没有可售地铁口，建议切 3km。");
    return {
      bus: bus, metro: metro, stats: stats, warnings: warnings,
      anchor: anchor, radius: radiusKey,
      anchors: stats.anchors, anchorLabels: stats.anchorLabels, anchorCount: stats.anchorCount
    };
  }

  // dailyReach = 平台 2023-05「触达人群-日均人次」（公交按线路、地铁按出入口）。
  // 无平台标签 → null（显示“无数据”），绝不写 0。
  // 锚点没有平台人流文件 → reachSource = "sample"：公交按 05 样本级别均值估算
  // （reachEst，元/辆/天口径），地铁 null。
  // 网点模式：每个候选按它最近的网点（reachAnchor）取对应人流文件，不混用别的网点。
  function attachReach(data, members, bus, metro, citywide) {
    var ffBy = {};
    members.forEach(function (m) { ffBy[m.anchor] = footfallOf(data, m.anchor); });
    function ffOf(c) { return ffBy[c.reachAnchor] || null; }
    // 站点级 aggregateReach 不依赖“最近枢纽”：同一个站在任何一个人流文件里
    // 都有同口径的站点合计，全城模式可以在缺出口数据时用它，避免把有数据的
    // 站误标成“无数据”。
    var stationAgg = {};
    Object.keys(data.footfall || {}).forEach(function (a) {
      var ff = data.footfall[a] || {};
      Object.keys(ff.stations || {}).forEach(function (st) {
        var v = (ff.stations[st] || {}).aggregateReach;
        if (stationAgg[st] == null && v != null) stationAgg[st] = v;
      });
    });
    // 候选池里这个站有没有任何一个“可售口”带出口级数据；有的话就保留
    // 出口口径，不能拿整站合计去抬另一个无数据口。
    var candHasData = {};
    metro.forEach(function (c) {
      var ff = ffOf(c);
      var e = ff && (ff.exits || {})[c.id];
      if (e && e.dailyReach != null) candHasData[c.station] = true;
    });
    bus.forEach(function (c) {
      var ff = ffOf(c);
      if (ff) {
        var r = (ff.bus || {})[c.line];
        c.dailyReach = r && r.dailyReach != null ? r.dailyReach : null;
        c.reachSource = c.dailyReach != null ? "platform" : "none";
        c.reachEst = null;
      } else {
        c.dailyReach = null;
        c.reachSource = "sample";
        c.reachEst = sampleBusReach(data, c.grade);
      }
    });
    metro.forEach(function (c) {
      if (ffOf(c)) {
        var ff = ffOf(c);
        var e = (ff.exits || {})[c.id];
        if (e && e.dailyReach != null) {
          c.dailyReach = e.dailyReach;
          c.reachSource = "platform";
          c.reachScope = "exit";
        } else if (citywide && !candHasData[c.station]) {
          // 只给“候选口全都没有出口级数据”的站退回站点 aggregateReach；
          // 像人民广场这种已有出口数据的站，不能用整站合计去抬某个无数据口。
          var agg = stationAgg[c.station];
          c.dailyReach = agg == null ? null : agg;
          c.reachSource = agg == null ? "none" : "platform";
          c.reachScope = agg == null ? "none" : "station";
        } else {
          c.dailyReach = null;
          c.reachSource = "none";
          c.reachScope = "none";
        }
      } else {
        c.dailyReach = null;
        c.reachSource = "sample";
        c.reachScope = "none";
      }
      c.reachEst = null;
    });
  }

  // 方案级触达（日均人次）。地铁同站多口不相加：单口用该口 dailyReach；
  // 同站 >=2 口用站点 aggregateReach（平台合并去重），且不低于其中最大单口
  // （去重并集不可能小于任一组成口）。公交 = 车辆数 × 线路日均触达（footfall.json 公式）。
  // 网点模式按 reachAnchor 分组，各用各的人流文件；网点之间未去重。
  function reachOf(data, anchors, items, days) {
    var members = Array.isArray(anchors) ? anchors : [anchors];
    var ffBy = {};
    var platformAnchors = [];
    members.forEach(function (a) {
      var ff = footfallOf(data, a);
      if (ff) { ffBy[a] = ff; platformAnchors.push(a); }
    });
    var missing = [];
    var busDaily = 0, metroDaily = 0;
    var stationRows = [];
    var sampleBus = 0, sampleAnchors = [];
    var seenSample = {};

    function anchorOf(it) {
      var a = it.reachAnchor || (it.anchors && it.anchors[0]) || "";
      return ffBy[a] ? a : "";
    }

    if (platformAnchors.length) {
      var byStation = {};
      items.forEach(function (it) {
        var a = anchorOf(it);
        if (!a) {
          if (it.media === "bus" && it.reachEst != null) {
            sampleBus += it.qty * it.reachEst;
            if (!seenSample[it.reachAnchor]) { seenSample[it.reachAnchor] = 1; sampleAnchors.push(it.reachAnchor); }
          }
          return;
        }
        if (it.media === "bus") {
          if (it.dailyReach == null) { missing.push(it.name); return; }
          busDaily += it.qty * it.dailyReach;
          return;
        }
        var key = a + "|" + it.station;
        (byStation[key] = byStation[key] || []).push(it);
      });
      Object.keys(byStation).forEach(function (key) {
        var list = byStation[key];
        var a = key.split("|")[0];
        var st = key.slice(a.length + 1);
        var ff = ffBy[a];
        var known = list.filter(function (x) { return x.dailyReach != null; });
        list.forEach(function (x) { if (x.dailyReach == null) missing.push(x.station + " " + x.exit); });
        if (!known.length) return;
        var maxOne = Math.max.apply(null, known.map(function (x) { return x.dailyReach; }));
        var v = maxOne, method = list.some(function (x) { return x.reachScope === "station"; }) ? "站点口径" : "单口";
        if (list.length >= 2) {
          var agg = ((ff.stations || {})[st] || {}).aggregateReach;
          v = agg != null ? Math.max(agg, maxOne) : maxOne;
          method = agg != null ? "同站合并去重" : "同站取最大单口";
        }
        metroDaily += v;
        stationRows.push({ anchor: a, station: st, exits: list.length, daily: v, method: method });
      });
      var firstFf = ffBy[platformAnchors[0]];
      var mixed = sampleBus > 0;
      return {
        source: mixed ? "mixed" : "platform",
        label: "平台 " + (firstFf.month || "2023-05") + (platformAnchors.length > 1 ? "（" + platformAnchors.length + " 点）" : ""),
        daily: busDaily + metroDaily + sampleBus,
        busDaily: busDaily,
        metroDaily: metroDaily,
        sampleBusDaily: sampleBus,
        anchors: platformAnchors,
        sampleAnchors: sampleAnchors,
        total: (busDaily + metroDaily + sampleBus) * days,
        stations: stationRows,
        missing: missing,
        note: "2023-05 平台触达人群-日均人次；地铁同站多口按合并去重、不相加；公交与地铁之间未去重；多个点位之间未去重；仅作相对权重。"
      };
    }
    items.forEach(function (it) {
      if (it.media === "bus") busDaily += it.qty * (it.reachEst || sampleBusReach(data, it.grade));
    });
    return {
      source: "sample",
      label: "样本估算",
      daily: busDaily,
      busDaily: busDaily,
      metroDaily: null,
      total: busDaily * days,
      stations: [],
      missing: [],
      anchors: [],
      note: "该锚点暂无平台人流：公交按 05 历史提案样本级别均值估算（车辆数 × 日均触达），地铁不计；仅作相对权重。"
    };
  }

  function emptyStats() {
    return {
      coverageTotal: 0, coverageBusRows: 0, coverageMetroRows: 0,
      coverageBusLines: 0, coverageStations: 0,
      busLines: 0, metroExits: 0, metroStations: 0,
      orphanBus: [], orphanStations: [],
      availableBusFree: 0, availableMetroFree: 0
    };
  }

  function maxEfficiency(media, grade, weeks, discount) {
    return 1 / Math.max(1, unitNet(media, grade, weeks, discount));
  }

  var DEFAULT_WEIGHTS = {
    distance: 0.45, grade: 0.25, availability: 0.20, efficiency: 0.10, reach: 0,
    metroMultiplier: 1.2
  };

  function weightsFor(data, brief) {
    var ind = (data.industries || []).find(function (x) { return x.id === brief.industryId; });
    var w = (ind && ind.scoringWeights) || {};
    var out = Object.assign({}, DEFAULT_WEIGHTS, w);
    ["distance", "grade", "availability", "efficiency", "reach"].forEach(function (k) {
      out[k] = Number(out[k] == null ? DEFAULT_WEIGHTS[k] : out[k]);
    });
    out.metroMultiplier = Number(out.metroMultiplier == null ? DEFAULT_WEIGHTS.metroMultiplier : out.metroMultiplier);
    return out;
  }

  function scoreOf(c, radius, maxEff, weeks, discount, W) {
    var p = unitNet(c.media, c.grade, weeks, discount);
    var local = Number(c.localRadius || radius || 3000);
    var ds = clamp(1 - c.distance / Math.max(1, local), 0, 1);
    var gs = gradeScore(c.grade);
    var av = c.free / Math.max(1, c.total);
    var eff = (1 / Math.max(1, p)) / maxEff;
    var rs = c.reachScore == null ? 0 : c.reachScore;
    var s = W.distance * ds + W.grade * gs + W.availability * av + W.efficiency * eff + W.reach * rs;
    if (c.media === "metro") s *= W.metroMultiplier;
    return s;
  }

  function sortBus(bus, radius, maxEff, weeks, discount, W) {
    return bus.slice().sort(function (a, b) {
      var sa = scoreOf(a, radius, maxEff, weeks, discount, W) / unitNet("bus", a.grade, weeks, discount);
      var sb = scoreOf(b, radius, maxEff, weeks, discount, W) / unitNet("bus", b.grade, weeks, discount);
      if (sb !== sa) return sb - sa;
      return a.distance - b.distance || a.name.localeCompare(b.name, "zh");
    });
  }

  function sortMetro(metro, radius, maxEff, weeks, discount, W) {
    var rank = { "A++": 0, "A+": 1, AA: 2 };
    return metro.slice().sort(function (a, b) {
      var sa = scoreOf(a, radius, maxEff, weeks, discount, W) / unitNet("metro", a.grade, weeks, discount);
      var sb = scoreOf(b, radius, maxEff, weeks, discount, W) / unitNet("metro", b.grade, weeks, discount);
      if (sb !== sa) return sb - sa;
      var ra = rank[a.grade] == null ? 3 : rank[a.grade];
      var rb = rank[b.grade] == null ? 3 : rank[b.grade];
      if (ra !== rb) return ra - rb;
      // 同级别优先选有平台触达数据的口，避免整站“无数据”。
      var ka = a.dailyReach != null ? 0 : 1;
      var kb = b.dailyReach != null ? 0 : 1;
      if (ka !== kb) return ka - kb;
      return a.distance - b.distance || a.name.localeCompare(b.name, "zh");
    });
  }

  function reasonOf(data, c) {
    var short = c.anchorLabel || shortAnchor(data, c.reachAnchor || c.anchors[0] || "");
    // 公交是线路：距离 = 线路最近经过锚点的距离
    var base = c.media === "metro"
      ? "距" + short + " " + Math.round(c.distance) + "m · " + c.station + " " + c.exit + " · " + c.grade + " · 空" + c.free + "/" + c.total
      : "线路最近经过 " + (c.pointName || "—") + " · 距" + short + " " + Math.round(c.distance) + "m · " + c.grade + " · 空" + c.free + "/" + c.total;
    if (c.media === "bus") base += " · " + (c.company || "公交");
    if (c.anchors.length > 1) base += " · 覆盖" + c.anchors.length + "个点";
    return base;
  }

  function pickSubstitutes(c, all, selectedIds, radius, maxEff, weeks, discount, W) {
    var pool = all.filter(function (x) {
      if (x.media !== c.media || selectedIds.has(x.id)) return false;
      if (x.grade !== c.grade) return false;
      if (c.media === "bus" && x.line === c.line) return false;
      return true;
    });
    pool.sort(function (a, b) {
      var sa = scoreOf(a, radius, maxEff, weeks, discount, W);
      var sb = scoreOf(b, radius, maxEff, weeks, discount, W);
      return sb - sa || a.distance - b.distance;
    });
    return pool.slice(0, 2).map(function (x) {
      return { id: x.id, name: x.name, grade: x.grade, free: x.free, distance: x.distance, station: x.station || "" };
    });
  }

  function makeItem(data, c, qty, weeks, discount, allCandidates, selectedIds, radius, maxEff, W) {
    var media = c.media;
    var mediaUnit = unitMedia(media, c.grade, weeks);
    var prodUnit = unitProd(media);
    var listSubtotal = Math.round(mediaUnit * qty);
    var production = prodUnit * qty;
    var net = Math.round((mediaUnit * qty + production) * discount);
    return {
      media: media,
      id: c.id,
      name: c.name,
      line: c.line || "",
      station: c.station || "",
      exit: c.exit || "",
      grade: c.grade,
      qty: qty,
      free: c.free,
      total: c.total,
      contract: c.contract,
      reserved: c.reserved,
      maintenance: c.maintenance || 0,
      company: c.company || "",
      area: c.area || "",
      district: c.district || "",
      citywide: !!c.citywide,
      unitPrice: priceOf(media, c.grade),
      months: round2(monthsOf(weeks)),
      listSubtotal: listSubtotal,
      production: production,
      net: net,
      distance: c.distance,
      pointName: c.pointName || "",
      pointDistance: c.pointDistance || 0,
      stationLines: c.stationLines || [],
      anchors: c.anchors || [],
      anchorLabel: c.anchorLabel || "",
      reachAnchor: c.reachAnchor || (c.anchors || [])[0] || "",
      dailyReach: c.dailyReach == null ? null : c.dailyReach,
      reachSource: c.reachSource || "none",
      reachScope: c.reachScope || "none",
      reachEst: c.reachEst == null ? null : c.reachEst,
      reason: reasonOf(data, c),
      substitutes: pickSubstitutes(c, allCandidates[media], selectedIds, radius, maxEff, weeks, discount, W)
    };
  }

  function quoteOf(items, budget, discount, monitoringRate) {
    var media = 0, production = 0, net = 0;
    items.forEach(function (it) { media += it.listSubtotal; production += it.production; net += it.net; });
    var beforeDiscount = media + production;
    var discountAmount = beforeDiscount - net;
    var monitoring = Math.round(net * (monitoringRate || 0));
    var netTotal = net + monitoring;
    return {
      media: media,
      production: production,
      discountRate: discount,
      discountAmount: discountAmount,
      monitoring: monitoring,
      net: netTotal,
      budget: budget,
      remaining: budget - netTotal,
      overBudget: netTotal > budget + 1
    };
  }

  function selectPlan(data, brief) {
    var warnings = [];
    var budget = Math.max(0, Math.round(brief.budget || 0));
    var weeks = Math.max(1, Number(brief.weeks || 6));
    var media = brief.media || { bus: true, metro: true };
    configurePricing(data);
    var pricing = brief.pricing || {};
    var discount = brief.discount != null ? Number(brief.discount)
      : (pricing.discount == null ? PRICING.discount : Number(pricing.discount));
    if (!(discount > 0 && discount <= 1)) discount = PRICING.discount;
    var monitoringRate = pricing.monitoringRate == null ? PRICING.monitoringRate : Number(pricing.monitoringRate);
    var startDate = brief.startDate || (data.meta && data.meta.range && data.meta.range.start) || "2027-04-01";
    var ind = (data.industries || []).find(function (x) { return x.id === brief.industryId; });
    var bundle = ind && ind.anchorBundle;
    var W = weightsFor(data, brief);
    var mixShare = ind && ind.mediaMix && ind.mediaMix.metro != null ? Number(ind.mediaMix.metro) : null;

    var built = buildCandidates(data, brief);
    warnings = warnings.concat(built.warnings || []);
    var radius = Number(built.radius || brief.radius || 3000);
    var bus = built.bus || [];
    var metro = built.metro || [];
    var allCandidates = { bus: bus, metro: metro };

    if (!bus.length && !metro.length) {
      return emptyPlan(data, brief, built, warnings, discount, monitoringRate, startDate);
    }

    var maxEff = 0;
    bus.concat(metro).forEach(function (c) {
      var e = maxEfficiency(c.media, c.grade, weeks, discount);
      if (e > maxEff) maxEff = e;
    });

    var busSorted = sortBus(bus, radius, maxEff, weeks, discount, W);
    var metroSorted = sortMetro(metro, radius, maxEff, weeks, discount, W);

    var share;
    if (media.metro && !media.bus) share = 1;
    else if (!media.metro && media.bus) share = 0;
    else share = mixShare != null ? mixShare : metroShare(budget);
    // 该锚点没有可售地铁口时，预算全部给公交，避免 20% 预算空转。
    if (!metroSorted.length) share = 0;

    var metroBudget = Math.round(budget * share);
    var busBudget = budget - metroBudget;

    var selectedMetro = [];
    var selectedMetroIds = new Set();
    var stationCounts = new Map();
    var metroSpent = 0;

    function tryPickMetro(c, maxPerStation) {
      if (selectedMetroIds.has(c.id)) return false;
      if ((stationCounts.get(c.station) || 0) >= maxPerStation) return false;
      var cost = unitNet("metro", c.grade, weeks, discount);
      if (metroSpent + cost > metroBudget) return false;
      selectedMetro.push(c);
      selectedMetroIds.add(c.id);
      stationCounts.set(c.station, (stationCounts.get(c.station) || 0) + 1);
      metroSpent += cost;
      return true;
    }

    if (media.metro) {
      if (bundle && bundle.spreadMetro) {
        // 全城铺送：先做到“每站 1 口、每区 1 站”，再补第二站/第二口。
        // 这样同样的钱不会全砸在一个站，而是铺到多个区；有平台人流的站
        // 仍按触达/级别优先，缺数据的站不会被强行塞进方案。
        var districtStations = {};
        metroSorted.forEach(function (c) {
          if (stationCounts.get(c.station)) return;
          var d = c.district || "_";
          if ((districtStations[d] || 0) >= 1) return;
          if (tryPickMetro(c, 1)) districtStations[d] = (districtStations[d] || 0) + 1;
        });
        metroSorted.forEach(function (c) {
          if (selectedMetroIds.has(c.id)) return;
          var d = c.district || "_";
          var sameStation = (stationCounts.get(c.station) || 0) > 0;
          if (!sameStation && (districtStations[d] || 0) >= 2) return;
          tryPickMetro(c, MAX_EXITS_PER_STATION);
        });
      } else {
        metroSorted.forEach(function (c) { tryPickMetro(c, MAX_EXITS_PER_STATION); });
      }
    }

    // 纯公交（或该锚点没有可售地铁口）时允许铺到 20 条线，避免预算排不满。
    var busLineCap = share === 0 ? Math.min(20, busSorted.length)
      : (bundle && bundle.maxBusLines ? Math.min(bundle.maxBusLines, busSorted.length) : MAX_BUS_LINES);
    var qtyCap = share === 0 ? Math.max(MAX_QTY_PER_LINE, 8)
      : (bundle && bundle.maxQtyPerLine ? bundle.maxQtyPerLine : MAX_QTY_PER_LINE);
    var busQuota = !!(bundle && bundle.allocateBusByWeight && bundle.members && bundle.members.length > 1);
    var busRanked;
    if (busQuota) {
      // 网点公交名额按人流权重分（最大余数法），避免预算全被最高分网点吸走。
      var totalW = bundle.members.reduce(function (s, m) { return s + Number(m.weight || 1); }, 0) || 1;
      var caps = bundle.members.map(function (m) {
        var raw = busLineCap * Number(m.weight || 1) / totalW;
        return { base: Math.floor(raw), frac: raw - Math.floor(raw) };
      });
      var assigned = caps.reduce(function (s, x) { return s + x.base; }, 0);
      var order = caps.map(function (x, i) { return i; }).sort(function (a, b) { return caps[b].frac - caps[a].frac; });
      for (var ci = 0; assigned < busLineCap; ci = (ci + 1) % order.length) { caps[order[ci]].base += 1; assigned += 1; }
      var nodeLists = bundle.members.map(function (m, i) {
        var list = busSorted.filter(function (c) { return c.free >= 1 && c.reachAnchor === m.anchor; });
        return list.slice(0, Math.max(1, caps[i].base));
      });
      // 按网点轮转取线，保证加车时不会先把第一个网点的额度吃光。
      busRanked = [];
      var maxList = nodeLists.reduce(function (n, list) { return Math.max(n, list.length); }, 0);
      for (var li = 0; li < maxList; li++) {
        nodeLists.forEach(function (list) { if (list[li]) busRanked.push(list[li]); });
      }
      busRanked = busRanked.slice(0, busLineCap);
    } else {
      busRanked = busSorted.filter(function (c) { return c.free >= 1; }).slice(0, busLineCap);
    }
    var busQty = new Map();
    var busSpent = 0;
    if (media.bus) {
      var added = true;
      var guard = 0;
      while (added && busSpent < busBudget && guard < 200) {
        added = false;
        guard += 1;
        busRanked.forEach(function (c) {
          var cap = Math.min(c.free, qtyCap);
          if ((busQty.get(c.line) || 0) >= cap) return;
          var p = unitNet("bus", c.grade, weeks, discount);
          if (busSpent + p > busBudget) return;
          busQty.set(c.line, (busQty.get(c.line) || 0) + 1);
          busSpent += p;
          added = true;
        });
      }
    }

    // Fill remaining budget with the selected media only (never cross-buy).
    var remaining = budget - metroSpent - busSpent;
    var changed = true;
    var fillGuard = 0;
    while (changed && remaining > 0 && fillGuard < 400) {
      changed = false;
      fillGuard += 1;
      if (media.metro) {
        for (var i = 0; i < metroSorted.length; i++) {
          var mc = metroSorted[i];
          if (selectedMetroIds.has(mc.id)) continue;
          if ((stationCounts.get(mc.station) || 0) >= MAX_EXITS_PER_STATION) continue;
          if (bundle && bundle.spreadMetro) {
            var sameStation = (stationCounts.get(mc.station) || 0) > 0;
            if (!sameStation) {
              var dSet = {};
              selectedMetro.forEach(function (x) {
                if ((x.district || "_") === (mc.district || "_")) dSet[x.station] = 1;
              });
              if (Object.keys(dSet).length >= 2) continue;
            }
          }
          var mp = unitNet("metro", mc.grade, weeks, discount);
          if (mp > remaining) continue;
          selectedMetro.push(mc);
          selectedMetroIds.add(mc.id);
          stationCounts.set(mc.station, (stationCounts.get(mc.station) || 0) + 1);
          remaining -= mp;
          metroSpent += mp;
          changed = true;
          break;
        }
      }
      if (changed) continue;
      if (media.bus) {
        for (var j = 0; j < busRanked.length; j++) {
          var bc = busRanked[j];
          var cap2 = Math.min(bc.free, qtyCap);
          if ((busQty.get(bc.line) || 0) >= cap2) continue;
          var bp = unitNet("bus", bc.grade, weeks, discount);
          if (bp > remaining) continue;
          busQty.set(bc.line, (busQty.get(bc.line) || 0) + 1);
          remaining -= bp;
          busSpent += bp;
          changed = true;
          break;
        }
      }
    }

    var items = [];
    selectedMetro.forEach(function (m) {
      items.push(makeItem(data, m, 1, weeks, discount, allCandidates, selectedMetroIds, radius, maxEff, W));
    });
    var selectedBusIds = new Set();
    busQty.forEach(function (qty, line) {
      var c = busRanked.find(function (x) { return x.line === line; });
      if (!c || qty <= 0) return;
      selectedBusIds.add(c.id);
      items.push(makeItem(data, c, qty, weeks, discount, allCandidates, selectedBusIds, radius, maxEff, W));
    });

    // Trim if per-row rounding pushed us over budget.
    var quote = quoteOf(items, budget, discount, monitoringRate);
    var trimGuard = 0;
    while (quote.net > budget + 1 && trimGuard < 500) {
      trimGuard += 1;
      var busItem = null;
      for (var k = items.length - 1; k >= 0; k--) {
        if (items[k].media === "bus" && items[k].qty > 0) { busItem = items[k]; break; }
      }
      if (busItem && busItem.qty > 1) {
        busItem.qty -= 1;
      } else if (busItem) {
        items.splice(items.indexOf(busItem), 1);
      } else if (items.length) {
        items.pop();
      } else {
        break;
      }
      quote = quoteOf(items, budget, discount, monitoringRate);
    }

    items.sort(function (a, b) {
      if (a.media !== b.media) return a.media === "metro" ? -1 : 1;
      return b.net - a.net || a.name.localeCompare(b.name, "zh");
    });

    var busCount = items.reduce(function (s, it) { return s + (it.media === "bus" ? it.qty : 0); }, 0);
    var metroCount = items.reduce(function (s, it) { return s + (it.media === "metro" ? it.qty : 0); }, 0);
    var busLines = items.filter(function (it) { return it.media === "bus"; }).length;
    var metroStations = uniq(items.filter(function (it) { return it.media === "metro"; }).map(function (it) { return it.station; })).length;
    var anchors = uniq(items.reduce(function (arr, it) { return arr.concat(it.anchors || []); }, []));
    var areas = uniq(items.filter(function (it) { return it.media === "metro"; }).map(function (it) { return it.area; }).filter(Boolean));
    var busNet = items.reduce(function (s, it) { return s + (it.media === "bus" ? it.net : 0); }, 0);
    var metroNet = items.reduce(function (s, it) { return s + (it.media === "metro" ? it.net : 0); }, 0);
    var reachInfo = reachOf(data, built.anchors || [built.anchor], items, weeks * 7);

    var unitLabel = (ind && ind.anchorBundle && ind.anchorBundle.unitLabel) || "网点";
    if (quote.remaining > budget * 0.05 && items.length) {
      warnings.push("预算未用完（余额 " + (quote.remaining / 10000).toFixed(1) + " 万）：当前" + unitLabel + "可售候选或媒体配比已到上限。");
    }
    if (built.anchorCount > 1) {
      var selectedNodes = uniq(items.reduce(function (arr, it) { return arr.concat(it.anchors || []); }, []));
      var missingNodes = (built.anchors || []).filter(function (a) { return selectedNodes.indexOf(a) < 0; });
      if (missingNodes.length) {
        warnings.push("本轮预算优先给了评分更高的" + unitLabel + "；" + missingNodes.map(function (a) { return shortAnchor(data, a); }).join("、") +
          " 暂无选中条目。可加预算，或把媒体/半径改成单点模式再算。");
      }
    }
    if (weeks * 7 > 46) {
      warnings.push("档期 " + (weeks * 7) + " 天超出当前库存快照窗口（2027-04-01～05-15），后段库存未验证。");
    }
    if (media.metro && !media.bus && !metro.length) warnings.push("只地铁不可行：当前锚点/半径没有红豆可售地铁口，请放开公交或换半径。");
    if (media.metro && media.bus && !metro.length && items.length) warnings.push("当前锚点/半径没有红豆可售地铁口，已全部用公交。");    if (!media.metro && metroCount === 0) warnings.push("已按「只公交」生成，未选地铁。");
    if (!media.bus && busCount === 0) warnings.push("已按「只地铁」生成，未选公交。");

    var stats = Object.assign({}, built.stats, {
      selectedBusLines: busLines,
      selectedMetroExits: metroCount,
      selectedRows: items.length
    });

    return {
      items: items,
      summary: {
        busCount: busCount,
        metroCount: metroCount,
        busLines: busLines,
        metroStations: metroStations,
        metroDistricts: uniq(items.filter(function (it) { return it.media === "metro"; })
          .map(function (it) { return it.district; }).filter(Boolean)).length,
        citywide: !!(bundle && bundle.citywide),
        weeks: weeks,
        days: weeks * 7,
        anchors: anchors.length ? anchors : (built.anchors || []),
        anchorCount: built.anchorCount || 1,
        anchorLabels: built.anchorLabels || [],
        areas: areas,
        reach: reachInfo.total,
        reachDaily: reachInfo.daily,
        reachLabel: reachInfo.label,
        reachSource: reachInfo.source,
        reachInfo: reachInfo,
        mix: {
          busNet: busNet,
          metroNet: metroNet,
          busPct: quote.net ? Math.round(busNet / quote.net * 100) : 0,
          metroPct: quote.net ? Math.round(metroNet / quote.net * 100) : 0
        },
        anchor: built.anchor,
        radius: radius,
        startDate: startDate
      },
      quote: quote,
      schedule: buildSchedule(startDate),
      stats: stats,
      warnings: uniq(warnings),
      pricing: { discount: discount, isList: discount >= 0.9999, floor: PRICING.floor, monitoringRate: monitoringRate }
    };
  }

  function emptyPlan(data, brief, built, warnings, discount, monitoringRate, startDate) {
    var budget = Math.round(brief.budget || 0);
    var media = brief.media || { bus: true, metro: true };
    if (media.metro && !media.bus) warnings = warnings.concat(["只地铁不可行：当前锚点/半径没有红豆可售地铁口，请放开公交或换半径。"]);
    return {
      items: [],
      summary: {
        busCount: 0, metroCount: 0, busLines: 0, metroStations: 0,
        weeks: Number(brief.weeks || 6), days: Number(brief.weeks || 6) * 7,
        anchors: built.anchors || [], anchorCount: built.anchorCount || 1, anchorLabels: built.anchorLabels || [],
        areas: [], reach: 0, reachDaily: 0, reachLabel: "无", reachSource: "none",
        reachInfo: { source: "none", label: "无", daily: 0, busDaily: 0, metroDaily: 0, total: 0, stations: [], missing: [], note: "" },
        mix: { busNet: 0, metroNet: 0, busPct: 0, metroPct: 0 },
        anchor: built.anchor, radius: Number(built.radius || 3000), startDate: startDate
      },
      quote: quoteOf([], budget, discount, monitoringRate),
      schedule: buildSchedule(startDate),
      stats: built.stats,
      warnings: uniq(warnings.concat(["没有可售候选，无法生成方案。"])),
      pricing: { discount: discount, isList: discount >= 0.9999, floor: PRICING.floor, monitoringRate: monitoringRate }
    };
  }

  return {
    PRICING: PRICING,
    GRADE_SCORE: GRADE_SCORE,
    MAX_BUS_LINES: MAX_BUS_LINES,
    MAX_QTY_PER_LINE: MAX_QTY_PER_LINE,
    MAX_EXITS_PER_STATION: MAX_EXITS_PER_STATION,
    BUS_DAILY_REACH: BUS_DAILY_REACH,
    metroShare: metroShare,
    configurePricing: configurePricing,
    reachOf: reachOf,
    unitNet: unitNet,
    unitMedia: unitMedia,
    quoteOf: quoteOf,
    buildCandidates: buildCandidates,
    anchorsOf: anchorsOf,
    selectPlan: selectPlan,
    buildSchedule: buildSchedule
  };
});
