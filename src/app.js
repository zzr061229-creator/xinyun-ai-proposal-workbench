(function () {
  "use strict";

  var DATA = window.APP_DATA;
  var Engine = window.Engine;
  var MediaMap = window.MediaMap;
  var $ = function (sel) { return document.querySelector(sel); };

  // Industries come from APP_DATA.industries (built from data/config/industries.json
  // by src/build_data.py; DEMO_LINEUP fallback lives there, not here).
  // One brand + one anchor per industry.
  var INDUSTRY_LIST = (DATA && DATA.industries) || [];
  var INDUSTRIES = {};
  INDUSTRY_LIST.forEach(function (x) { INDUSTRIES[x.id] = x; });
  var DEFAULT_INDUSTRY = (DATA && DATA.defaultIndustryId && INDUSTRIES[DATA.defaultIndustryId]) ? DATA.defaultIndustryId : (INDUSTRY_LIST[0] ? INDUSTRY_LIST[0].id : "");
  function industryIdOf(v) {
    if (!v) return null;
    if (INDUSTRIES[v]) return v;
    var hit = INDUSTRY_LIST.find(function (x) { return x.key === v || x.label === v; });
    return hit ? hit.id : null;
  }
  var WINDOWS = (DATA && DATA.windows) || [];
var WINDOW_MAP = {};
WINDOWS.forEach(function (w) { WINDOW_MAP[w.id] = w; });
function windowForIndustry(id) {
    var p = INDUSTRIES[id] || {};
    if (p.defaultWindowId && WINDOW_MAP[p.defaultWindowId]) return WINDOW_MAP[p.defaultWindowId];
    var hit = WINDOWS.find(function (w) { return (w.industries || []).indexOf(id) >= 0; });
    return hit || WINDOWS[0] || null;
}
function activeWindow() {
    if (!WINDOWS.length) return null;
    var w = WINDOW_MAP[state.windowId];
    if (!w) {
        w = windowForIndustry(state.industryId) || WINDOWS[0];
        state.windowId = w.id;
    }
    return w;
}
function isoAddDays(iso, days) {
    var t = Date.parse(iso + "T00:00:00Z");
    if (isNaN(t)) return iso;
    var d = new Date(t + days * 86400000);
    return d.toISOString().slice(0, 10);
}
function mmdd(iso) { return iso ? iso.slice(5) : "—"; }
function activeRange() {
    var w = activeWindow();
    if (w) {
        var weeks = state.weeks || w.weeks || 6;
        return { start: w.start, end: isoAddDays(w.start, weeks * 7 - 1), weeks: weeks, name: w.name };
    }
    return (DATA.meta && DATA.meta.range) || {};
}
function activeSnapshot() {
    var w = activeWindow();
    return (w && w.snapshotAt) || (DATA.meta && DATA.meta.inventoryFetchedAt) || "—";
}
var _windowDataCache = {};
function dataForWindow(id) {
    if (!id || !DATA.windowInventory || !DATA.windowInventory[id]) return DATA;
    if (_windowDataCache[id]) return _windowDataCache[id];
    var ov = DATA.windowInventory[id];
    var bus = (DATA.bus || []).map(function (b) {
        var f = (ov.bus || {})[String(b.id) + "|" + (b.media || "")];
        return f ? Object.assign({}, b, { free: f[0], contract: f[1], reserved: f[2] })
                  : Object.assign({}, b, { free: 0 });
    });
    var stations = {};
    Object.keys(DATA.stations || {}).forEach(function (name) {
        var st = DATA.stations[name];
        var exits = (st.exits || []).map(function (e) {
            var f = (ov.metro || {})[e.id];
            return f ? Object.assign({}, e, { free: f[0], contract: f[1], reserved: f[2] })
                      : Object.assign({}, e, { free: 0 });
        });
        stations[name] = Object.assign({}, st, { exits: exits });
    });
    var out = Object.assign({}, DATA, { bus: bus, stations: stations });
    _windowDataCache[id] = out;
    return out;
}

var PRICING_CFG = (DATA && DATA.pricing) || {};
  var DISCOUNT_DEFAULT = (PRICING_CFG.discount && PRICING_CFG.discount["default"] != null) ? Number(PRICING_CFG.discount["default"]) : 1;
  var DISCOUNT_FLOOR = (PRICING_CFG.discount && PRICING_CFG.discount.floor != null) ? Number(PRICING_CFG.discount.floor) : 0.88;
  var DISCOUNT_OPTIONS = [DISCOUNT_DEFAULT].concat(((PRICING_CFG.discount || {}).options || [0.92]).map(Number));
  function normDiscount(v) {
    var n = Number(v);
    var hit = DISCOUNT_OPTIONS.find(function (x) { return Math.abs(x - n) < 1e-6; });
    return hit == null ? DISCOUNT_DEFAULT : hit;
  }
  function discountLabel(d) {
    if (d >= 0.9999) return "刊例价（1.0，不打折）";
    return Math.round(d * 100) + " 折（示例假设，待销售确认）";
  }
  function discountShort(d) { return d >= 0.9999 ? "1.0 刊例" : (Math.round(d * 100) / 100).toFixed(2) + " 示例"; }

  var state = {
    industryId: DEFAULT_INDUSTRY,
    brand: (INDUSTRIES[DEFAULT_INDUSTRY] || {}).brand || "",
    budget: 2000000,
    weeks: 6,
    windowId: (windowForIndustry(DEFAULT_INDUSTRY) || {}).id || "",
    discount: DISCOUNT_DEFAULT,
    media: { bus: true, metro: true },
    anchor: (INDUSTRIES[DEFAULT_INDUSTRY] || {}).anchor || "",
    anchorBundle: bundleOf(INDUSTRIES[DEFAULT_INDUSTRY]),
    radius: 3000,
    view: "client",
    plan: null,
    calcMs: 0,
    runToken: 0,
    debounceTimer: null,
    mapDataUri: null,
    mapDataUriFile: null,
    mapDataUriLoading: null,
    mapDataUriPromise: null,
    // 默认用内置离线底图：展会/酒店网络经常连不上 OSM，在线瓦片只作可选增强。
    mapMode: "offline",
    leaflet: null,
    leafletLayers: null,
    tileLayer: null,
    svgRenderer: null,
    focusMode: false,
    focusScrollY: 0,
    tileErrors: 0,
    mapZoom: null,
    mapKey: null
  };

  // Map colors come from CSS custom properties so each skin (index / index-b2 /
  // index-atlas) can restyle the map without touching this file.
  var THEME_DEFAULTS = {
    ring: "#C8443A", anchor: "#C8443A", busSel: "#C8443A", metroSel: "#C8443A",
    cand: "#2F5FD0", line: "#2F5FD0", label: "#151515", halo: "#FAF8F2",
    labelFont: "Consolas, monospace"
  };
  function theme() {
    var cs = window.getComputedStyle ? getComputedStyle(document.documentElement) : null;
    var pick = function (name, key) {
      var v = cs ? cs.getPropertyValue(name).trim() : "";
      return v || THEME_DEFAULTS[key];
    };
    return {
      ring: pick("--map-ring", "ring"), anchor: pick("--map-anchor", "anchor"),
      busSel: pick("--map-bus", "busSel"), metroSel: pick("--map-metro", "metroSel"),
      cand: pick("--map-cand", "cand"), line: pick("--map-line", "line"),
      label: pick("--map-label", "label"), halo: pick("--map-halo", "halo"),
      labelFont: pick("--map-font", "labelFont")
    };
  }

  // Tiny extension point for alternative skins: they can read state and
  // highlight markers without forking the renderer.
  // markers: "metro:<exitId>" → L.circleMarker；"bus:<line>" → L.polyline（公交是线路，不是点）。
  var hooks = [];
  var markers = {};
  window.ProposalApp = {
    state: state,
    markers: markers,
    industries: INDUSTRY_LIST,
    onRender: function (fn) { hooks.push(fn); if (state.plan) fn(state); },
    wan: function (n) { return wan(n); },
    // internal: structured patch → state → recompute (wrapped by atlas.js applyBrief)
    _apply: function (patch) { return applyPatch(patch); }
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function wan(n) { return (Number(n || 0) / 10000).toFixed(1); }
  function int(n) { return Math.round(Number(n || 0)); }
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

  function profile() {
    return INDUSTRIES[state.industryId] || INDUSTRIES[DEFAULT_INDUSTRY] ||
      { id: "", key: "", label: "—", brand: "", anchor: "", radii: [1000, 3000], insight: "", compliance: [], note: "" };
  }
  function complianceText(p) {
    var c = p.compliance;
    return Array.isArray(c) ? c.join("；") : String(c || "");
  }
  function anchorObj(name) {
    return (DATA.anchors || []).find(function (x) { return x.name === name; }) || null;
  }
  function hasPlatformReach(anchor) { return !!((DATA.footfall || {})[anchor]); }
  function geoOf(anchor) { return (DATA.geo || {})[anchor] || null; }
  function availableRadii(anchor) {
    var cov = (DATA.coverage || {})[anchor] || {};
    return Object.keys(cov).map(Number).sort(function (a, b) { return a - b; });
  }
  function chooseRadius(anchor, preferred) {
    var avail = availableRadii(anchor);
    var prefs = [3000].concat(preferred || []).concat([1000, 5000]);
    for (var i = 0; i < prefs.length; i++) {
      if (avail.indexOf(prefs[i]) >= 0) return prefs[i];
    }
    return avail[0] || 3000;
  }
  function coverageOf(anchor, radius) {
    return ((DATA.coverage || {})[anchor] || {})[String(radius)] || null;
  }
  function shortAnchor(name) {
    var a = (DATA.anchors || []).find(function (x) { return x.name === name; });
    return a ? a.short : name;
  }
  function bundleOf(p) {
    var b = p && p.anchorBundle;
    return (b && b.members && b.members.length > 1) ? b : null;
  }
  function currentBundle() { return bundleOf(profile()); }
  function bundleNames(b) {
    return (b ? b.members : []).map(function (m) { return m.label || shortAnchor(m.anchor); });
  }
  function bundleRadiusText(b) {
    var rs = (b ? b.members : []).map(function (m) { return Math.round(Number(m.radius || 0) / 1000); })
      .filter(function (x) { return x > 0; });
    var u = rs.filter(function (x, i) { return rs.indexOf(x) === i; }).sort(function (a, b) { return a - b; });
    return u.length ? u.join("/") + "km" : "";
  }
  function anchorSummary() {
    var b = currentBundle();
    if (!b) return shortAnchor(state.anchor) + " " + (state.radius / 1000) + "km";
    return (b.shortLabel || b.label) + " · " + b.members.length + " " + (b.unitLabel || "网点");
  }

  function renderTopMeta() {
    var range = activeRange();
    if ($("#snapshot")) $("#snapshot").textContent = activeSnapshot();
    if ($("#range")) $("#range").textContent = (range.start || "—") + "—" + (range.end || "—");
    if ($("#heroKicker")) $("#heroKicker").textContent = profile().label + " / " + state.brand + " / " + anchorSummary();
    if ($("#heroBudget")) $("#heroBudget").textContent = String(Math.round(state.budget / 10000));
    if ($("#footWindow")) $("#footWindow").textContent = (range.name ? range.name + " · " : "") + "2027";
  }

  // One brand per industry: no brand chips, no anchor tabs.
  function renderBrandChips() {
    var el = $("#brandChips");
    if (el) { el.innerHTML = ""; el.hidden = true; }
  }

  function renderAnchorTabs() {
    var el = $("#anchorTabs");
    if (el) el.innerHTML = "";
  }

  function renderRadiusChips() {
    var p = profile();
    var b = currentBundle();
    var el = $("#radiusChips");
    if (!el) return;
    if (b) {
      var bu = b.unitLabel || "网点";
      el.innerHTML = '<button type="button" class="chip on" data-bundle="1" title="多点模式：每个' + bu + '单独取覆盖，半径由配置决定">' +
        b.members.length + " " + bu + " · " + esc(bundleRadiusText(b)) + (b.citywide ? " · 全城" : "") + "</button>";
      return;
    }
    var avail = availableRadii(state.anchor).filter(function (r) { return p.radii.indexOf(r) >= 0; });
    if (!avail.length) avail = availableRadii(state.anchor);
    el.innerHTML = avail.map(function (r) {
      return '<button type="button" class="chip' + (state.radius === r ? " on" : "") + '" data-radius="' + r + '">' + (r / 1000) + "km</button>";
    }).join("");
  }

  function renderDiscount() {
    var sel = $("#discount");
    if (sel) sel.value = String(state.discount >= 0.9999 ? 1 : state.discount);
    var isList = state.discount >= 0.9999;
    var note = $("#discountNote");
    if (note) {
      note.textContent = isList ? "" : "示例假设，待销售确认";
      note.hidden = isList;
      note.classList.toggle("on", !isList);
    }
    var fine = $("#discountFine");
    if (fine) fine.textContent = isList ? "默认刊例价（1.0）" : Math.round(state.discount * 100) + " 折为示例假设，待销售确认";
  }

  function renderBriefCopy() {
    var p = profile();
    var b = currentBundle();
    if ($("#briefInsight")) $("#briefInsight").innerHTML = "<b>" + esc(p.label) + " · " + esc(p.brand) + "</b> · " + esc(p.insight);
    if ($("#briefCompliance")) $("#briefCompliance").textContent = "合规：" + complianceText(p);
    var note;
    if (b) {
      note = b.citywide
        ? "锚点：4 个客源枢纽 · " + bundleRadiusText(b) + " · 全城 " + (state.plan && state.plan.summary.metroStations || 0) + "/" + (state.plan && state.plan.stats ? state.plan.stats.citywideStations : 24) + " 站"
        : "锚点：" + bundleNames(b).join(" / ") + " · " + bundleRadiusText(b) +
          (b.weightLabel ? " · " + b.weightLabel : "") +
          (b.status === "sample" ? " · " + (b.unitLabel || "网点") + "选点为演示假设" : "");
    } else {
      note = "锚点：" + state.anchor + " · " + (state.radius / 1000) + "km";
      if (p.note) note = p.note + " · " + (state.radius / 1000) + "km";
    }
    if ($("#anchorNote")) $("#anchorNote").textContent = note;
    var logic = $("#logicNote");
    if (logic) {
      logic.textContent = p.logic ? "选点逻辑 · " + p.logic : "";
      logic.hidden = !p.logic;
    }
    renderAssumptionBook();
  }

  // ---- campaign 假设书（七要素，按行业切换；导出提案第一页复用） ----
  function briefOf(industryId) {
    var all = DATA && DATA.briefs && DATA.briefs.briefs;
    return all && all[industryId] ? all[industryId] : null;
  }

  function ensureAssumptionStyle() {
    if (document.getElementById("assumptionStyle")) return;
    var st = document.createElement("style");
    st.id = "assumptionStyle";
    st.textContent = [
      ".ab-oneline{margin:0 0 10px;font-weight:600;font-size:14px;line-height:1.7;max-width:1100px}",
      ".ab-table{width:100%;min-width:0;border-collapse:collapse;table-layout:fixed;max-width:1180px}",
      ".ab-table th,.ab-table td{border-bottom:1px solid rgba(21,21,21,.14);padding:9px 10px;text-align:left;vertical-align:top;font-size:14px;line-height:1.7;overflow-wrap:anywhere;white-space:normal}",
      ".ab-table th{width:120px;font-weight:700;white-space:normal;line-height:1.55;opacity:.72}",
      ".ab-table td b{font-weight:600}",
      ".ab-list{margin:0;max-width:1180px}",
      ".ab-item{padding:9px 0;border-bottom:1px solid rgba(21,21,21,.14)}",
      ".ab-item:last-child{border-bottom:0}",
      ".ab-label{font-weight:700;font-size:13px;line-height:1.4;opacity:.72;margin-bottom:3px}",
      ".ab-value{font-size:14px;line-height:1.7}",
      ".ab-basis{display:block;margin-top:4px;font-size:12px;opacity:.62;line-height:1.6}",
      ".ab-note{margin:10px 0 0;font-size:12px;line-height:1.65;opacity:.65;max-width:1180px}",
      ".ab-risk{margin-top:5px}",
      "@media (max-width:720px){.ab-table th,.ab-table td{font-size:13px;padding:7px 6px}.ab-table th{width:76px}.ab-note,.ab-basis{font-size:11px}}",
      "@media print{.ab-table th,.ab-table td{font-size:10.5px;padding:5px 6px}.ab-note{font-size:9px}}"
    ].join("");
    document.head.appendChild(st);
  }

  function buildAssumptionHtml(b, opts) {
    var note = (DATA.briefs && DATA.briefs.desensitization && DATA.briefs.desensitization.brandNames) || "";
    var footnote = "<p class='ab-note'>" + esc(note) + " 价格为刊例价，非成交价；库存为快照，人流为 2023-05、仅作相对权重。</p>" +
      "<p class='ab-note ab-risk'>风险与承诺：雨天/政府管制顺延；4A 误一补二、直客损一补一；夜间分批施工，单晚有作业上限（具体以运营确认）；库存不足时用同锚点替补并明示。</p>";
    var lead = opts.head ? "" : "<p class='ab-oneline'>" + esc(b.oneLine || "") + "</p>";
    if (opts.compact) {
      var items = (b.elements || []).map(function (x) {
        return "<div class='ab-item'><div class='ab-label'>" + esc(x.label) + "</div><div class='ab-value'>" +
          esc(x.value) + (x.basis ? "<span class='ab-basis'>依据：" + esc(x.basis) + "</span>" : "") + "</div></div>";
      }).join("");
      return lead + "<div class='ab-list'>" + items + "</div>" + footnote;
    }
    var rows = (b.elements || []).map(function (x) {
      return "<tr><th>" + esc(x.label) + "</th><td>" + esc(x.value) +
        (x.basis ? "<span class='ab-basis'>依据：" + esc(x.basis) + "</span>" : "") + "</td></tr>";
    }).join("");
    return lead + "<table class='ab-table'><tbody>" + rows + "</tbody></table>" + footnote;
  }

  function renderAssumptionBook() {
    var host = $("#assumptionBody");
    if (!host) return;
    ensureAssumptionStyle();
    var b = briefOf(state.industryId);
    var book = $("#assumptionBook");
    if (!b) { host.innerHTML = ""; if (book) book.hidden = true; return; }
    if (book) book.hidden = false;
    var head = $("#assumptionOneLine");
    if (head) head.textContent = b.oneLine || "";
    host.innerHTML = buildAssumptionHtml(b, { head: !!head, compact: !head });
  }

  function renderDatePreset() {
    var sel = $("#datePreset");
    if (!sel) return;
    var opts = [];
    if (WINDOWS.length) {
      WINDOWS.forEach(function (w) {
        [6, 4].forEach(function (weeks) {
          if (weeks > (w.weeks || 6)) return;
          opts.push('<option value="' + w.id + ":" + weeks + '">' + w.name + " · " + weeks + " 周（" +
            mmdd(w.start) + "–" + mmdd(isoAddDays(w.start, weeks * 7 - 1)) + "）</option>");
        });
      });
    } else {
      opts.push('<option value=":6">6 周</option><option value=":4">4 周</option>');
    }
    sel.innerHTML = opts.join("");
}

function syncControls() {
    if ($("#industry")) $("#industry").value = state.industryId;
    if ($("#brandInput")) { $("#brandInput").value = state.brand; $("#brandInput").readOnly = true; }
    if ($("#budget")) $("#budget").value = String(Math.round(state.budget / 10000));
    if ($("#budgetVal")) $("#budgetVal").textContent = String(Math.round(state.budget / 10000));
    if ($("#mediaBus")) $("#mediaBus").checked = !!state.media.bus;
    if ($("#mediaMetro")) $("#mediaMetro").checked = !!state.media.metro;
    if ($("#datePreset")) {
      renderDatePreset();
      var val = (state.windowId || "") + ":" + state.weeks;
      var found = Array.prototype.some.call($("#datePreset").options, function (o) { return o.value === val; });
      if (!found && $("#datePreset").options.length) {
        var first = $("#datePreset").options[0].value.split(":");
        state.windowId = first[0];
        state.weeks = Number(first[1]) || state.weeks;
        val = $("#datePreset").options[0].value;
      }
      $("#datePreset").value = val;
    }
    renderBrandChips();
    renderAnchorTabs();
    renderRadiusChips();
    renderDiscount();
    renderBriefCopy();
    renderTopMeta();
  }

  function setIndustry(id) {
    var p = INDUSTRIES[industryIdOf(id)] || INDUSTRIES[DEFAULT_INDUSTRY];
    if (!p) return;
    state.industryId = p.id;
    state.brand = p.brand;
    state.anchorBundle = bundleOf(p);
    var primary = state.anchorBundle ? state.anchorBundle.members[0] : null;
    state.anchor = primary ? primary.anchor : ((DATA.coverage || {})[p.anchor] ? p.anchor : ((DATA.anchors || [])[0] || {}).name);
    var prefR = Number(primary ? primary.radius : p.radiusDefault || 0);
    state.radius = (prefR && availableRadii(state.anchor).indexOf(prefR) >= 0) ? prefR : chooseRadius(state.anchor, p.radii);
    var bf = briefOf(p.id);
    if (bf && p.anchorBundle && p.anchorBundle.citywide &&
        Number(bf.primaryBudgetWan) >= 100 && Number(bf.primaryBudgetWan) <= 500) {
      state.budget = Number(bf.primaryBudgetWan) * 10000;
    }
    var win = windowForIndustry(p.id);
    if (win) state.windowId = win.id;
    state.mapZoom = null;
    state.mapKey = null;
  }

  function applyIndustry(id) {
    setIndustry(id);
    syncControls();
    runPlan(false);
  }

  // Brand is fixed by the industry; typing into the box just restores it.
  function onBrandChange() {
    state.brand = profile().brand;
    syncControls();
  }

  // Structured brief → state → recompute. Used by atlas.js applyBrief().
  // patch: {industryId, budget(元 或 万), weeks, media:{bus,metro}|"bus"|"metro"|"both", radius, discount}
  function applyPatch(patch) {
    patch = patch || {};
    var applied = {};
    if (patch.industryId != null && industryIdOf(patch.industryId)) { setIndustry(patch.industryId); applied.industryId = state.industryId; }
    if (patch.windowId != null && WINDOW_MAP[patch.windowId]) { state.windowId = patch.windowId; applied.windowId = state.windowId; }
    if (patch.budget != null) {
      var b = Number(patch.budget);
      if (b > 0 && b <= 1000) b = b * 10000;
      if (b >= 1000000 && b <= 5000000) { state.budget = Math.round(b / 100000) * 100000; applied.budget = state.budget; }
    }
    if (patch.weeks != null && (Number(patch.weeks) === 4 || Number(patch.weeks) === 6)) { state.weeks = Number(patch.weeks); applied.weeks = state.weeks; }
    if (patch.media != null) {
      var m = patch.media;
      if (m === "bus") m = { bus: true, metro: false };
      else if (m === "metro") m = { bus: false, metro: true };
      else if (m === "both") m = { bus: true, metro: true };
      if (m && (m.bus || m.metro)) { state.media = { bus: !!m.bus, metro: !!m.metro }; applied.media = state.media; }
    }
    if (patch.radius != null && !currentBundle() && availableRadii(state.anchor).indexOf(Number(patch.radius)) >= 0) {
      state.radius = Number(patch.radius); state.mapZoom = null; state.mapKey = null; applied.radius = state.radius;
    }
    if (patch.discount != null) { state.discount = normDiscount(patch.discount); applied.discount = state.discount; }
    syncControls();
    runPlan(false);
    return applied;
  }

  function onRadiusChange(r) {
    state.radius = Number(r);
    state.mapZoom = null;
    state.mapKey = null;
    syncControls();
    runPlan(false);
  }

  function runPlan(animate) {
    clearTimeout(state.debounceTimer);
    state.runToken += 1;
    var token = state.runToken;
    var pipe = $("#pipeline");
    if (animate && pipe) {
      pipe.classList.add("running");
      var steps = pipe.querySelectorAll(".step");
      steps.forEach(function (s, i) {
        setTimeout(function () { if (token === state.runToken) s.classList.add("active"); }, i * 70);
      });
      setTimeout(function () {
        if (token !== state.runToken) return;
        pipe.classList.remove("running");
        compute();
      }, 450);
    } else {
      if (pipe) pipe.classList.remove("running");
      compute();
    }
  }

  function debouncedRun() {
    clearTimeout(state.debounceTimer);
    state.debounceTimer = setTimeout(function () { runPlan(false); }, 70);
  }

  function compute() {
    if (!DATA || !Engine) return;
    var win = activeWindow();
    var bundle = currentBundle();
    var brief = {
      industryId: state.industryId,
      brand: state.brand,
      budget: state.budget,
      weeks: state.weeks,
      media: { bus: !!state.media.bus, metro: !!state.media.metro },
      anchor: state.anchor,
      anchors: bundle ? bundle.members.map(function (m) {
        return { anchor: m.anchor, radius: m.radius, weight: m.weight, label: m.label };
      }) : null,
      citywide: !!(bundle && bundle.citywide),
      radius: state.radius,
      discount: state.discount,
      startDate: (win && win.start) || "2027-04-01",
      windowId: state.windowId
    };
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    try {
      state.plan = Engine.selectPlan(dataForWindow(state.windowId), brief);
      var t1 = (window.performance && performance.now) ? performance.now() : Date.now();
      state.calcMs = Math.max(0, t1 - t0);
      renderAll();
    } catch (err) {
      console.error(err);
      showError("方案计算失败", String(err && err.message ? err.message : err));
    }
  }

  function renderAll() {
    renderTopMeta();
    renderHero();
    renderLedger();
    renderQuote();
    renderTable();
    renderMap();
    renderPipeline();
    renderSchedule();
    renderSource();
    renderWarnings();
    renderBriefCopy();
    markQA();
    hooks.forEach(function (fn) {
      try { fn(state); } catch (e) { console.error(e); }
    });
  }

  function markQA() {
    try {
      var qs = new URLSearchParams(window.location.search);
      if (!qs.get("qa")) return;
      var root = document.documentElement;
      root.setAttribute("data-scrollwidth", String(root.scrollWidth));
      root.setAttribute("data-clientwidth", String(root.clientWidth));
      root.setAttribute("data-planrows", String((state.plan && state.plan.items.length) || 0));
      root.setAttribute("data-radius", String(state.radius));
      root.setAttribute("data-anchor", state.anchor);
      root.setAttribute("data-mapmode", state.mapMode);
      root.setAttribute("data-mapfull", state.focusMode ? "1" : "0");
      var mb = document.querySelector(".map-box");
      if (mb) {
        var r = mb.getBoundingClientRect();
        root.setAttribute("data-map-top", String(Math.round(r.top)));
        root.setAttribute("data-map-bottom", String(Math.round(r.bottom)));
      }
      setTimeout(function () {
        try {
          var tiles = document.querySelectorAll("#map img.leaflet-tile");
          var loaded = 0;
          Array.prototype.forEach.call(tiles, function (img) {
            if (img.complete && img.naturalWidth > 0) loaded += 1;
          });
          root.setAttribute("data-tiles", String(tiles.length));
          root.setAttribute("data-tiles-loaded", String(loaded));
        } catch (e) { /* ignore */ }
      }, 2200);
      if (qs.get("qa") === "export" && state.plan) {
        cacheMapDataUri(mapMetaFor(state.anchor, state.radius, currentBundle())).then(function () {
          try {
            var html = buildProposalHtml();
            var csv = buildCsv();
            root.setAttribute("data-export-html", String(html.length));
            root.setAttribute("data-export-csv", String(csv.length));
            root.setAttribute("data-export-has-map", String(html.indexOf("<svg") >= 0));
            root.setAttribute("data-export-has-basemap", String(html.indexOf("data:image/") >= 0));
            root.setAttribute("data-export-has-quote", String(html.indexOf("净价") >= 0));
          } catch (e) { /* ignore */ }
        });
      }
    } catch (e) { /* ignore */ }
  }

  function renderHero() {
    var p = state.plan;
    var budgetWan = Math.round(state.budget / 10000);
    var metro = p ? p.summary.metroCount : 0;
    var bus = p ? p.summary.busCount : 0;
    var title;
    if (!p || (!metro && !bus)) {
      title = budgetWan + " 万，<br>先算一版<em>。</em>";
    } else if (metro > 0) {
      title = budgetWan + " 万，<br>先打穿 <em>" + metro + " 个口</em>。";
    } else {
      title = budgetWan + " 万，<br>先铺 <em>" + bus + " 辆车</em>。";
    }
    $("#heroTitle").innerHTML = title;
    if (p) {
      var b = currentBundle();
      var spread = b
        ? (b.citywide
          ? "<b>全城 4 个枢纽 + " + (p.summary.metroStations || 0) + " 个地铁站引流，迪士尼 5km 公交收口。</b>"
          : "<b>" + b.members.length + " 个" + (b.unitLabel || "网点") + "一起铺，" + bundleRadiusText(b) + "。</b>")
        : "<b>先赢下最近的 " + (state.radius / 1000) + " 公里。</b>";
      $("#heroDeck").innerHTML = bus + " 辆公交 + " + metro + " 个地铁口；" + p.summary.weeks + " 周；净价 " + wan(p.quote.net) + " 万，余额 " + wan(p.quote.remaining) + " 万。每条都能回到红豆的空位、合同、预定与查询档期。" + spread;
      $("#heroMeta").innerHTML = "<span>ACTIVE <b>" + esc(anchorSummary()) + "</b></span>" +
        "<span>WEEKS <b>" + p.summary.weeks + "</b></span>" +
        "<span>ROWS <b>" + p.items.length + "</b></span>" +
        "<span>NET <b>" + wan(p.quote.net) + " 万</b></span>";
      $("#heroNet").innerHTML = "净价 <b>" + wan(p.quote.net) + " 万</b>";
    } else {
      $("#heroMeta").innerHTML = "<span>ACTIVE <b>" + esc(anchorSummary()) + "</b></span>";
      $("#heroNet").textContent = "净价 —";
    }
  }

  function renderLedger() {
    var p = state.plan;
    var s = p ? p.summary : null;
    var st = p ? p.stats : null;
    var q = p ? p.quote : null;
    var cells = [
      { v: q ? wan(q.net) : "—", l: "净价 / 万元", cls: "hi" },
      { v: s ? s.busCount : "—", l: "公交 / 辆" },
      { v: s ? s.metroCount : "—", l: "地铁 / 口" },
      { v: s ? s.weeks : "—", l: "周期 / 周" },
      { v: st ? st.coverageTotal : "—", l: "覆盖候选 / 条" },
      { v: st ? st.busLines : "—", l: "可售公交 / 线" },
      { v: st ? st.metroExits : "—", l: "可售地铁 / 口" },
      { v: p ? p.items.length : "—", l: "方案明细 / 行" },
      { v: q ? wan(q.remaining) : "—", l: "预算余额 / 万", cls: "red" }
    ];
    $("#dataGrid").innerHTML = cells.map(function (c) {
      return '<div class="cell ' + (c.cls || "") + '"><b>' + esc(c.v) + "</b><span>" + esc(c.l) + "</span></div>";
    }).join("");
  }

  function renderQuote() {
    var p = state.plan;
    if (!p) {
      $("#quoteNet").innerHTML = "—<small>万元</small>";
      $("#quoteStatus").textContent = "—";
      $("#quoteStatus").className = "status";
      $("#usageBar").style.width = "0%";
      $("#usagePct").textContent = "—";
      $("#quoteBalance").textContent = "—";
      $("#quoteRows").innerHTML = "";
      $("#salesPanel").innerHTML = "";
      return;
    }
    var q = p.quote;
    $("#quoteNet").innerHTML = wan(q.net) + "<small>万元</small>";
    $("#quoteStatus").textContent = q.overBudget ? "OVER" : "WITHIN";
    $("#quoteStatus").className = "status" + (q.overBudget ? " over" : "");
    var usage = q.budget ? clamp(q.net / q.budget * 100, 0, 100) : 0;
    $("#usageBar").style.width = usage + "%";
    $("#usagePct").textContent = usage.toFixed(1) + "%";
    $("#quoteBalance").textContent = wan(q.remaining) + " 万";
    $("#quoteRows").innerHTML = [
      row("媒体刊例", wan(q.media) + " 万"),
      row("制作费", wan(q.production) + " 万"),
      row("报价口径", discountLabel(q.discountRate)),
      q.discountAmount ? row("折让", "−" + wan(q.discountAmount) + " 万") : "",
      row("监测费", q.monitoring ? wan(q.monitoring) + " 万" : "0"),
      '<div class="qrow total"><span>净价 / NET</span><b>' + wan(q.net) + " 万</b></div>",
      row("预算余额", wan(q.remaining) + " 万"),
      row("税", "不含税（6% 专票另计）")
    ].join("");

    var tight = p.items.filter(function (x) { return x.free <= 2; }).length;
    var contracts = p.items.reduce(function (n, x) { return n + (x.contract || 0); }, 0);
    var reserved = p.items.reduce(function (n, x) { return n + (x.reserved || 0); }, 0);
    var subs = [];
    p.items.forEach(function (x) {
      (x.substitutes || []).forEach(function (s) {
        if (subs.indexOf(s.name) < 0) subs.push(s.name);
      });
    });
    // 销售视图才写入 DOM；客户视图的源码里不能出现折扣底线/替补池。
    if (state.view === "sales") {
      $("#salesPanel").innerHTML = '<div class="sales-panel">' +
        '<div><b>当前口径</b> ' + esc(discountLabel(q.discountRate)) + ' · <b>折扣底线</b> <span class="floor">' + Math.round(DISCOUNT_FLOOR * 100) + ' 折（仅销售视图，示例，待销售确认）</span></div>' +
        '<div><b>合同 / 预定</b> ' + contracts + " / " + reserved + " 辆/口 · <b>空位≤2</b> " + tight + " 条</div>" +
        '<div><b>替补池</b> <span class="subs">' + (subs.slice(0, 3).map(esc).join(" · ") || "无同级替补") + "</span></div>" +
        '<div><b>锁定建议</b> 空位≤2 的条目建议 48h 内锁定；签约前回红豆复核。</div>' +
        "</div>";
    } else {
      $("#salesPanel").innerHTML = "";
    }
  }

  function row(k, v) { return '<div class="qrow"><span>' + esc(k) + "</span><b>" + esc(v) + "</b></div>"; }

  function renderTable() {
    var p = state.plan;
    var tbody = $("#planRows");
    var COLS = 12;
    if (!p || !p.items.length) {
      var unit0 = (currentBundle() && currentBundle().unitLabel) || "网点";
      tbody.innerHTML = '<tr><td colspan="' + COLS + '" style="padding:18px;color:var(--muted)">当前' + unit0 + '/预算没有可售组合。可尝试放开媒体或调整预算。</td></tr>';
      $("#tableMeta").textContent = "无可售组合";
      return;
    }
    $("#tableMeta").textContent = p.items.length + " 行 · " + p.summary.busCount + " 辆公交 / " + p.summary.metroCount + " 个口 · 净价 " + wan(p.quote.net) + " 万 · " + discountShort(p.quote.discountRate) + " · 触达口径：" + reachSourceText(p.summary);
    tbody.innerHTML = p.items.map(function (it, i) {
      var salesView = state.view === "sales";
      var type = it.media === "metro" ? '<span class="type m">地铁口</span>' : '<span class="type b">公交线路</span>';
      var name = it.media === "metro" ? it.station + " " + it.exit : it.name;
      var subs = salesView ? ((it.substitutes || []).map(function (s) { return s.name + "（空" + s.free + "）"; }).join(" · ") || "无同级替补") : "";
      return '<tr class="plan-row" data-key="' + esc(it.media === "metro" ? "metro:" + it.id : "bus:" + it.line) + '" data-id="' + esc(it.id) + '">' +
        "<td>" + type + "</td>" +
        '<td class="name">' + esc(name) + "</td>" +
        "<td>" + esc(it.grade) + "</td>" +
        "<td>" + it.qty + "</td>" +
        "<td>" + it.free + "/" + it.total + "</td>" +
        "<td>" + it.months + "</td>" +
        '<td class="num">' + wan(it.listSubtotal) + " 万</td>" +
        '<td class="num" style="color:var(--red)">' + wan(it.net) + " 万</td>" +
        '<td class="num">' + reachCell(it) + "</td>" +
        "<td>" + esc(distanceText(it)) + "</td>" +
        '<td class="reason">' + esc(it.reason) + "</td>" +
        '<td><button class="expand" type="button" aria-expanded="false" data-i="' + i + '">证据</button></td>' +
        "</tr>" +
        '<tr class="detail" hidden><td colspan="' + COLS + '"><div class="ev">' +
        ev("快照", activeSnapshot()) +
        ev("查询档期", (activeRange().start || "—") + "—" + (activeRange().end || "—")) +
        ev("空位 / 合同 / 预定", it.free + "/" + it.total + " · " + (it.contract || 0) + " · " + (it.reserved || 0)) +
        ev(it.media === "bus" ? "线路最近经过" : "最近距离", distanceText(it)) +
        ev("日均触达(2023-05)", reachText(it)) +
        ev("覆盖" + ((currentBundle() && currentBundle().unitLabel) || "网点"), (it.anchors || []).join(" / ") || state.anchor) +
        ev("资源 ID", it.id) +
        (it.maintenance ? ev("保养影响", it.maintenance + " 辆/口") : "") +
        (it.stationLines && it.stationLines.length ? ev("覆盖线路", it.stationLines.join(" / ")) : "") +
        '<div class="wide"><span class="lab">选择理由</span><b>' + esc(it.reason) + "</b></div>" +
        (salesView ? '<div class="wide sales-only"><span class="lab">替补 / 锁定</span><b class="subs">' + esc(subs) + "</b></div>" : "") +
        "</div></td></tr>";
    }).join("");
  }

  // 公交是线路：距离 = 线路最近经过网点的距离。
  function lineGeoMissing(it) {
    var g = geoOf(it.reachAnchor || state.anchor);
    return it.media === "bus" && !!g && !((g.bus || {})[it.line]);
  }
  function distanceText(it) {
    var node = it.anchorLabel || "锚点";
    if (it.media === "bus") return "线路 · 最近经过 " + (it.pointName || "—") + " · 距" + node + " " + int(it.distance) + "m" + (lineGeoMissing(it) ? " · 线路几何缺失" : "");
    return int(it.distance) + "m · " + (it.anchorLabel ? "距" + it.anchorLabel : (it.pointName || it.station || "—"));
  }
  function fmtInt(n) { return Math.round(Number(n || 0)).toLocaleString("zh-CN"); }
  function reachText(it) {
    if (it.dailyReach != null) {
      var scope = it.media === "bus" ? "线路" : (it.reachScope === "station" ? "站点" : "单口");
      return fmtInt(it.dailyReach) + " 人次/日（" + scope + "）";
    }
    if (it.reachSource === "sample" && it.reachEst != null) return "≈" + (it.reachEst / 10000).toFixed(1) + " 万/辆/日（05 样本估算）";
    return "无数据";
  }
  function reachCell(it) {
    if (it.dailyReach != null) {
      var tag = it.reachScope === "station" ? '<span title="该口无出口级数据，用站点 aggregateReach（平台已去重）" style="color:var(--muted);font-size:10px"> 站</span>' : "";
      return fmtInt(it.dailyReach) + tag;
    }
    if (it.reachSource === "sample" && it.reachEst != null) return '<span title="05 历史提案样本级别均值，每辆/日">≈' + (it.reachEst / 10000).toFixed(1) + "万/辆·样本</span>";
    return '<span class="nodata" style="color:var(--muted)">无数据</span>';
  }
  function reachSourceText(s) {
    if (!s) return "—";
    var lab = String(s.reachLabel || "").replace(/^平台\s*/, "");
    if (s.reachSource === "platform") return "平台数据（" + lab + "）";
    if (s.reachSource === "mixed") return "平台数据 + 样本估算（" + lab + "）";
    if (s.reachSource === "sample") return "样本估算（05 历史提案）";
    return "—";
  }
  window.ProposalApp.reachText = reachText;
  window.ProposalApp.distanceText = distanceText;
  window.ProposalApp.reachSourceText = reachSourceText;
  window.ProposalApp.discountLabel = discountLabel;

  function ev(label, value) {
    return '<div><span class="lab">' + esc(label) + "</span><b>" + esc(value) + "</b></div>";
  }

  function offlineTileMeta() {
    var t = window.TILE_ASSETS;
    return (t && t.tileRoot && t.count) ? t : null;
  }

  function mapMetaFor(anchor, radius, bundle) {
    var assets = window.MAP_ASSETS || {};
    if (bundle && bundle.mapAssetKey && assets[bundle.mapAssetKey]) {
      var bm = assets[bundle.mapAssetKey];
      return bm.file ? bm : (bm[String(radius)] || bm["1000"] || bm["3000"] || null);
    }
    var a = anchorObj(anchor);
    var names = [anchor].concat(a ? (a.aliases || []).concat([a.short]) : []);
    for (var i = 0; i < names.length; i++) {
      var bucket = assets[names[i]];
      if (bucket) return bucket[String(radius)] || bucket["3000"] || null;
    }
    return null;
  }

  function cacheMapDataUri(meta) {
    if (!meta || !window.fetch) return Promise.resolve(null);
    if (window.location && window.location.protocol === "file:") return Promise.resolve(null);
    if (state.mapDataUri && state.mapDataUriFile === meta.file) return Promise.resolve(state.mapDataUri);
    if (state.mapDataUriLoading === meta.file && state.mapDataUriPromise) return state.mapDataUriPromise;

    state.mapDataUriLoading = meta.file;
    state.mapDataUriPromise = fetch(meta.file).then(function (res) {
      if (!res.ok) throw new Error("map fetch " + res.status);
      return res.blob();
    }).then(function (blob) {
      return new Promise(function (resolve, reject) {
        var fr = new FileReader();
        fr.onload = function () { resolve(fr.result); };
        fr.onerror = reject;
        fr.readAsDataURL(blob);
      });
    }).then(function (uri) {
      state.mapDataUri = uri;
      state.mapDataUriFile = meta.file;
      state.mapDataUriLoading = null;
      return uri;
    }).catch(function () {
      // file:// or blocked fetch: the app still shows the real map via <image>;
      // the exported HTML falls back to the projected points only.
      state.mapDataUri = null;
      state.mapDataUriLoading = null;
      return null;
    });
    return state.mapDataUriPromise;
  }

  function updateMapModeBtn() {
    var btn = $("#mapModeBtn");
    if (!btn) return;
    var online = state.mapMode === "online" && window.L;
    btn.textContent = online ? "切离线底图" : "切在线地图";
    btn.title = online
      ? "当前为在线 OSM 瓦片；点击切内置离线底图"
      : "当前为内置离线底图（OSM z14 快照），不依赖网络；点击尝试在线地图";
  }

  function updateMapFullBtn() {
    var btn = $("#mapFullBtn");
    if (!btn) return;
    btn.textContent = state.focusMode ? "退出全屏" : "全屏";
    btn.setAttribute("aria-pressed", state.focusMode ? "true" : "false");
    btn.title = state.focusMode ? "退出全屏（Esc）" : "全屏查看地图（保留预算条和清单）";
    try {
      if (new URLSearchParams(window.location.search).get("qa")) {
        document.documentElement.setAttribute("data-mapfull", state.focusMode ? "1" : "0");
      }
    } catch (e) { /* no query */ }
  }

  function refitAfterFocus() {
    if (state.leaflet) {
      try { state.leaflet.invalidateSize(); } catch (e) { /* ignore */ }
    }
    state.lastFitSize = null; // force a refit even if the size delta is small
    refitMapToSize();
  }

  function setFocusMode(on, useNative) {
    on = !!on;
    var wrap = document.getElementById("focusWrap");
    if (state.focusMode === on) {
      updateMapFullBtn();
      if (on) setTimeout(refitAfterFocus, 0);
      return;
    }
    state.focusMode = on;
    if (on) {
      state.focusScrollY = window.scrollY || document.documentElement.scrollTop || 0;
      document.body.classList.add("focus-map");
      updateMapFullBtn();
      if (useNative !== false && wrap && wrap.requestFullscreen) {
        try {
          var req = wrap.requestFullscreen();
          if (req && req.catch) req.catch(function () { /* CSS fallback stays */ });
        } catch (e) { /* CSS fallback stays */ }
      }
      setTimeout(refitAfterFocus, 260);
      setTimeout(function () { if (state.focusMode) refitAfterFocus(); }, 700);
    } else {
      document.body.classList.remove("focus-map");
      updateMapFullBtn();
      if (document.fullscreenElement) {
        try {
          var exit = document.exitFullscreen();
          if (exit && exit.catch) exit.catch(function () { /* ignore */ });
        } catch (e) { /* ignore */ }
      }
      setTimeout(function () {
        if (state.focusMode) return;
        refitAfterFocus();
        window.dispatchEvent(new Event("resize"));
        window.scrollTo(0, state.focusScrollY || 0);
      }, 260);
    }
  }

  function toggleFocusMode() {
    setFocusMode(!state.focusMode, true);
  }

  function leafletZoomFor(radius) {
    if (radius >= 5000) return 13;
    if (radius >= 3000) return 14;
    return 15;
  }

  // Frame the whole coverage circle (plus a little air) unless the user or a
  // ?zoom= deep link already chose a zoom level. Network mode frames all nodes.
  function frameMap(center, radius, anchors, bounds) {
    if (state.mapZoom) { state.leaflet.setView(center, state.mapZoom); return; }
    state.leaflet.invalidateSize();
    var pad = state.focusMode ? 40 : 22;
    var padSingle = state.focusMode ? 32 : 18;
    if (bounds) {
      state.leaflet.fitBounds([[bounds.minLat, bounds.minLng], [bounds.maxLat, bounds.maxLng]], { padding: [pad, pad] });
      return;
    }
    if (anchors && anchors.length > 1) {
      var pts = [];
      anchors.forEach(function (a) {
        var dLat = a.radius / 111320;
        var dLng = a.radius / (111320 * Math.cos(a.lat * Math.PI / 180));
        pts.push([a.lat - dLat, a.lng - dLng], [a.lat + dLat, a.lng + dLng]);
      });
      state.leaflet.fitBounds(pts, { padding: [pad, pad] });
      return;
    }
    var dLat = radius / 111320;
    var dLng = radius / (111320 * Math.cos(center[0] * Math.PI / 180));
    state.leaflet.fitBounds([[center[0] - dLat, center[1] - dLng], [center[0] + dLat, center[1] + dLng]], { padding: [padSingle, padSingle] });
    if (!state.leaflet.getZoom()) state.leaflet.setView(center, leafletZoomFor(radius));
  }

  // A slow network can initialize the map before its container has its final
  // size; Leaflet then fits a 0×0 box and locks to max zoom. Refit once the
  // real size is known (and on later resizes). Keep `bounds` in the snapshot:
  // the citywide plan frames 4 hubs + 24 stations by bounds, not by anchors.
  function refitMapToSize() {
    if (!state.leaflet || !state.lastMapSample) return;
    state.leaflet.invalidateSize();
    var size = state.leaflet.getSize();
    if (!size.x || !size.y) return;
    var last = state.lastFitSize;
    if (last && Math.abs(last.x - size.x) < 24 && Math.abs(last.y - size.y) < 24) return;
    state.lastFitSize = { x: size.x, y: size.y };
    state.mapZoom = null;
    var sm = state.lastMapSample;
    frameMap([sm.center.lat, sm.center.lng], sm.radius, sm.anchors, sm.bounds);
    state.mapKey = sm.mapKey || state.mapKey;
  }

  function renderLeafletMap(sample) {
    if (!window.L) return;
    var center = [Number(sample.center.lat), Number(sample.center.lng)];
    var anchors = (sample.anchors && sample.anchors.length) ? sample.anchors.slice() : [];
    if (!anchors.length) anchors = [{ lat: center[0], lng: center[1], radius: sample.radius, label: sample.anchorLabel }];
    state.lastMapSample = {
      center: sample.center,
      radius: sample.radius,
      anchors: anchors,
      bounds: sample.bounds || null,
      mapKey: sample.mapKey || (sample.activeAnchor + "|" + sample.radius)
    };
    var ot = offlineTileMeta();
    var useOfflineTiles = state.mapMode !== "online" && !!ot;
    var url = useOfflineTiles ? ot.tileRoot + "/{z}/{x}/{y}.png" : "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
    var minZ = useOfflineTiles ? ot.minZoom : 11;
    var maxZ = useOfflineTiles ? ot.maxZoom : 18;
    function attachTiles() {
      if (state.tileLayer && state.leaflet) state.leaflet.removeLayer(state.tileLayer);
      var opts = { minZoom: minZ, maxZoom: maxZ, noWrap: true };
      if (useOfflineTiles) opts.bounds = ot.bounds;
      state.tileLayer = window.L.tileLayer(url, opts).addTo(state.leaflet);
      state.tileUrl = url;
      state.tileLayer.on("tileerror", function () {
        state.tileErrors += 1;
        if (state.tileErrors >= 4 && state.mapMode === "online") {
          state.mapMode = "offline";
          toast("在线瓦片加载失败，已切离线瓦片");
          renderMap();
        }
      });
    }
    if (!state.leaflet) {
      state.leaflet = window.L.map("map", {
        zoomControl: true,
        attributionControl: false,
        minZoom: minZ,
        maxZoom: maxZ,
        preferCanvas: true,
        zoomSnap: 0.25,
        scrollWheelZoom: false
      });
      // Don't hijack page scroll: wheel-zoom only after the map is clicked.
      state.leaflet.on("click focus", function () { state.leaflet.scrollWheelZoom.enable(); });
      state.leaflet.on("mouseout blur", function () { state.leaflet.scrollWheelZoom.disable(); });
      frameMap(center, sample.radius, anchors, sample.bounds);
      state.leafletLayers = window.L.layerGroup().addTo(state.leaflet);
      state.leaflet.on("zoomend", function () { state.mapZoom = state.leaflet.getZoom(); });
      attachTiles();
      if (window.ResizeObserver && !state.mapRO) {
        state.mapRO = new ResizeObserver(function () { setTimeout(refitMapToSize, 0); });
        state.mapRO.observe(document.getElementById("map"));
      }
    } else {
      if (state.tileUrl !== url) {
        state.leaflet.setMinZoom(minZ);
        state.leaflet.setMaxZoom(maxZ);
        attachTiles();
      }
      var key = sample.mapKey || (sample.activeAnchor + "|" + sample.radius);
      if (state.mapKey !== key) {
        frameMap(center, sample.radius, anchors, sample.bounds);
        state.mapKey = key;
      }
    }
    if (!state.mapKey) state.mapKey = sample.mapKey || (sample.activeAnchor + "|" + sample.radius);
    // Selected paths render as SVG so the existing CSS glow/filters apply;
    // candidates stay on Canvas for performance.
    if (window.L && typeof window.L.svg === "function" && !state.svgRenderer) {
      state.svgRenderer = window.L.svg({ padding: 0.5 });
    }
    // Permanent tooltips live in their own pane; unbind them before clearing or
    // switching industry leaves the previous network's labels on the map.
    function tipDirection(latlng, preferred) {
      try {
        if (preferred === "top" || preferred === "bottom") return preferred;
        var pt = state.leaflet.latLngToContainerPoint(latlng);
        return pt.x > state.leaflet.getSize().x * 0.62 ? "left" : (preferred || "right");
      } catch (e) { return preferred || "right"; }
    }
    state.leafletLayers.eachLayer(function (layer) {
      if (layer.unbindTooltip) layer.unbindTooltip();
    });
    state.leafletLayers.clearLayers();
    var tooltipPane = state.leaflet.getPane && state.leaflet.getPane("tooltipPane");
    if (tooltipPane) tooltipPane.innerHTML = "";
    Object.keys(markers).forEach(function (k) { delete markers[k]; });
    var T = theme();

    anchors.forEach(function (a, ai) {
      var ac = [Number(a.lat), Number(a.lng)];
      var anchorDirs = anchors.length > 1 ? ["top", "bottom", "right"] : ["right"];
      var radii = [5000, 3000, 1000].filter(function (r) { return r <= (a.radius || sample.radius); });
      radii.forEach(function (r, i) {
        window.L.circle(ac, {
          radius: r,
          color: T.ring,
          weight: i === 0 ? 1.8 : 1,
          opacity: i === 0 ? 0.7 : 0.38,
          fill: false,
          dashArray: i === 0 ? "6 7" : "2 5",
          interactive: false
        }).addTo(state.leafletLayers);
      });
      var anchorMarker = window.L.circleMarker(ac, {
        radius: 6, color: T.halo, weight: 2,
        fillColor: T.anchor, fillOpacity: 1
      });
      anchorMarker.bindTooltip(a.label || sample.anchorLabel, {
        permanent: true, direction: tipDirection(anchorMarker.getLatLng(), anchorDirs[ai % anchorDirs.length]), className: "map-tip", opacity: 1
      }).addTo(state.leafletLayers);
    });

    // Bus = route, never a dot. Candidates first (faint), selected on top.
    // Network mode can draw several fragments of the same line, one per node.
    var lines = (sample.lines || []).slice().sort(function (a, b) { return (a.selected ? 1 : 0) - (b.selected ? 1 : 0); });
    lines.forEach(function (ln) {
      var latlngs = ln.path.map(function (x) { return [x[1], x[0]]; });
      var pl = window.L.polyline(latlngs, ln.selected ? {
        color: T.busSel, weight: 4.2, opacity: 0.96, lineJoin: "round", lineCap: "round",
        className: "bus-selected", renderer: state.svgRenderer
      } : {
        color: T.cand, weight: 1, opacity: 0.24, interactive: false, className: "bus-candidate"
      });
      if (ln.selected) {
        pl.bindTooltip(ln.name + " · 线路最近经过 " + (ln.pointName || "—") + " · 距" + (ln.anchorLabel || "网点") + " " + ln.distance + "m", {
          sticky: true, direction: "top", className: "map-tip"
        });
      }
      pl.addTo(state.leafletLayers);
      if (ln.selected) {
        var bk = "bus:" + ln.line;
        (markers[bk] = markers[bk] || []).push(pl);
      }
      // tiny tick where the route passes closest to the anchor
      if (ln.selected && ln.tick) {
        window.L.circleMarker([ln.tick[1], ln.tick[0]], {
          radius: 2.2, color: T.halo, weight: 1, fillColor: T.busSel, fillOpacity: 1, interactive: false
        }).addTo(state.leafletLayers);
      }
    });

    (sample.points.metro || []).forEach(function (p) {
      if (p.lat == null) return;
      var pt = [Number(p.lat), Number(p.lng)];
      var marker = window.L.circleMarker(pt, {
        radius: p.selected ? 8 : (p.stationDot ? 5 : (p.exit ? 3 : 4)),
        color: p.selected ? T.metroSel : T.cand,
        weight: p.selected ? 2.6 : (p.stationDot ? 1.6 : 1.2),
        fillColor: p.selected ? T.metroSel : T.cand,
        fillOpacity: p.selected ? 0.35 : (p.stationDot ? 0.12 : 0),
        className: p.selected ? "metro-selected" : "metro-candidate",
        renderer: p.selected ? state.svgRenderer : undefined
      });
      marker.bindTooltip(p.label + (p.selected ? " · 已选" : "") + (p.anchorLabel ? " · " + p.anchorLabel : ""), {
        permanent: !!p.selected && !currentBundle(), direction: tipDirection(marker.getLatLng()), className: "map-tip", opacity: 1
      });
      marker.addTo(state.leafletLayers);
      (p.selectedIds || []).forEach(function (id) {
        var mk = "metro:" + id;
        (markers[mk] = markers[mk] || []).push(marker);
      });
    });

    setTimeout(function () {
      if (state.leaflet) {
        state.leaflet.invalidateSize();
        refitMapToSize();
      }
    }, 350);
  }

  function mapNodes() {
    var b = currentBundle();
    if (!b) {
      var cov = coverageOf(state.anchor, state.radius);
      return cov ? [{ anchor: state.anchor, label: shortAnchor(state.anchor), radius: state.radius, center: cov.center, cov: cov }] : [];
    }
    return b.members.map(function (m) {
      var c = coverageOf(m.anchor, m.radius);
      if (!c) return null;
      return { anchor: m.anchor, label: m.label || shortAnchor(m.anchor), radius: m.radius, center: c.center, cov: c };
    }).filter(Boolean);
  }

  function renderMap() {
    var b = currentBundle();
    var nodes = mapNodes();
    var p = state.plan;
    var st = p ? p.stats : null;
    var s = p ? p.summary : null;
    var items = p ? p.items : [];
    var selectedBus = new Set(items.filter(function (x) { return x.media === "bus"; }).map(function (x) { return x.line; }));
    var selectedMetro = new Set(items.filter(function (x) { return x.media === "metro"; }).map(function (x) { return x.station; }));
    var primary = nodes[0];
    $("#mapTitle").textContent = b
      ? (b.citywide
        ? (b.shortLabel || b.label) + " · " + (s ? s.metroStations : 0) + " / " + (st ? st.citywideStations : 24) + " 站"
        : (b.shortLabel || b.label) + " · " + ((primary ? primary.radius : state.radius) / 1000) + "KM")
      : shortAnchor(state.anchor) + " / " + (state.radius / 1000) + "KM";
    $("#mapStats").textContent = "COVERAGE " + (st ? st.coverageTotal : "—") + " / STOCK " + (st ? (st.busLines + st.metroExits) : "—") +
      (b && b.citywide ? " / CITY " + (st ? st.citywideStations : 24) + " ST · SEL " + (s ? s.metroStations : 0) : "");
    if (!nodes.length) {
      $("#mapStatic").innerHTML = "";
      $("#mapBadge").textContent = "该锚点没有覆盖数据";
      updateMapModeBtn();
      return;
    }
    var ctr = primary.center;
    // Bus = whole route polyline from platform geometry (GCJ-02→WGS84 at build time).
    // No geometry → draw nothing for bus (no fake straight lines), show a corner note.
    // 网点模式：每个网点画自己覆盖到的线路片段；同一条线在多个网点出现时各画一段。
    var lines = [];
    var busItems = {};
    items.forEach(function (x) { if (x.media === "bus") busItems[x.line] = x; });
    var drawnBus = new Set();
    nodes.forEach(function (node) {
      var geo = geoOf(node.anchor);
      var seenLine = {};
      node.cov.list.filter(function (r) { return r.mediaType === "bus"; }).forEach(function (r) {
        var alias = (DATA.aliases || {})[r.lineName] || {};
        var line = alias.inventoryName || r.lineName;
        if (seenLine[line]) return;
        seenLine[line] = true;
        var sel = !!(alias.inventoryName && selectedBus.has(alias.inventoryName));
        var g = geo && geo.bus ? geo.bus[line] : null;
        if (!g || !g.path || g.path.length < 2) return;
        if (sel) drawnBus.add(line);
        var it = busItems[line];
        var best = null, bestD = Infinity;
        g.path.forEach(function (pt) {
          var dy = (pt[1] - node.center.lat) * 111320, dx = (pt[0] - node.center.lng) * 111320 * Math.cos(node.center.lat * Math.PI / 180);
          var d = dx * dx + dy * dy;
          if (d < bestD) { bestD = d; best = pt; }
        });
        lines.push({
          line: line, name: it ? it.name : r.lineName, path: g.path, selected: sel,
          distance: Math.round(r.minDistance), pointName: r.pointName || "", tick: best,
          anchorLabel: node.label
        });
      });
    });
    var missingGeo = Array.from(selectedBus).filter(function (x) { return !drawnBus.has(x); }).length;
    var anyGeo = nodes.some(function (n) { return !!geoOf(n.anchor); });
    var geoNote = "";
    if (!anyGeo) geoNote = "网点线路几何待补，公交见右侧清单";
    else if (missingGeo) geoNote = missingGeo + " 条选中线路无几何，见清单";

    // Metro: real exit coordinates where the platform has them; otherwise the station point.
    var metroItemsByStation = {};
    items.forEach(function (x) { if (x.media === "metro") (metroItemsByStation[x.station] = metroItemsByStation[x.station] || []).push(x); });
    var metro = [];
    var seenSt = {};
    if (b && b.citywide) {
      // 全城：24 个在库站都上图（灰点），选中的口画蓝环；
      // 口有真实坐标用出入口坐标，没有就用站中心，绝不把站中心伪装成口。
      var exitGeo = {};
      Object.keys(DATA.geo || {}).forEach(function (a) {
        var g = DATA.geo[a] || {};
        Object.keys(g.exits || {}).forEach(function (id) { if (!exitGeo[id]) exitGeo[id] = g.exits[id]; });
      });
      Object.keys(DATA.stations || {}).forEach(function (name) {
        var st = DATA.stations[name];
        if (!st || !st.inInventory || !st.coord) return;
        var firstDistrict = (st.exits || []).map(function (e) { return e.district; }).filter(Boolean)[0] || "";
        var selItems = metroItemsByStation[name] || [];
        metro.push({
          station: name, exit: "", label: name,
          lng: st.coord.lng, lat: st.coord.lat,
          selected: false, selectedIds: [], real: false, distance: 0,
          stationDot: true, anchorLabel: firstDistrict
        });
        selItems.forEach(function (it) {
          var ge = exitGeo[it.id];
          metro.push({
            station: name, exit: it.exit, label: name + " " + it.exit,
            lng: (ge || st.coord).lng, lat: (ge || st.coord).lat,
            selected: true, selectedIds: [it.id], real: !!ge, distance: 0,
            anchorLabel: it.district || firstDistrict
          });
        });
      });
    } else {
      nodes.forEach(function (node) {
        var geo = geoOf(node.anchor);
        node.cov.list.filter(function (r) { return r.mediaType === "metro"; }).forEach(function (r) {
          var st = r.pointName;
          if (seenSt[st]) return;
          seenSt[st] = true;
          var selItems = metroItemsByStation[st] || [];
          var selIds = selItems.map(function (x) { return x.id; });
          var invExits = ((DATA.stations || {})[st] || {}).exits || [];
          var placed = {};
          if (geo && geo.exits) {
            invExits.forEach(function (e) {
              var ge = geo.exits[e.id];
              if (!ge) return;
              placed[e.id] = true;
              var sel = selIds.indexOf(e.id) >= 0;
              metro.push({ station: st, exit: e.exit, label: st + " " + e.exit, lng: ge.lng, lat: ge.lat,
                selected: sel, selectedIds: sel ? [e.id] : [], real: true, distance: Math.round(r.minDistance),
                anchorLabel: node.label });
            });
          }
          var rest = selIds.filter(function (id) { return !placed[id]; });
          var anyPlaced = Object.keys(placed).length > 0;
          if (rest.length || !anyPlaced) {
            metro.push({ station: st, exit: "", label: st + (rest.length ? " " + selItems.filter(function (x) { return rest.indexOf(x.id) >= 0; }).map(function (x) { return x.exit; }).join("/") : ""),
              lng: r.pointLng, lat: r.pointLat, selected: rest.length > 0, selectedIds: rest, real: false,
              distance: Math.round(r.minDistance), anchorLabel: node.label });
          }
        });
      });
    }
    var boundsPts = [];
    nodes.forEach(function (n) {
      var dLat = n.radius / 111000;
      var dLng = n.radius / (111000 * Math.cos(n.center.lat * Math.PI / 180));
      boundsPts.push([n.center.lng - dLng, n.center.lat - dLat], [n.center.lng + dLng, n.center.lat + dLat]);
    });
    if (b && b.citywide) {
      Object.keys(DATA.stations || {}).forEach(function (name) {
        var st = DATA.stations[name];
        if (st && st.inInventory && st.coord) boundsPts.push([st.coord.lng, st.coord.lat]);
      });
    }
    var sample = {
      center: primary.center,
      radius: primary.radius,
      activeAnchor: state.anchor,
      anchorLabel: shortAnchor(state.anchor),
      anchors: nodes.map(function (n) { return { lng: n.center.lng, lat: n.center.lat, radius: n.radius, label: String(n.label || "").replace(/（[^）]*）/g, "") }; }),
      bounds: boundsPts.length ? {
        minLng: Math.min.apply(null, boundsPts.map(function (p) { return p[0]; })) - 0.012,
        maxLng: Math.max.apply(null, boundsPts.map(function (p) { return p[0]; })) + 0.012,
        minLat: Math.min.apply(null, boundsPts.map(function (p) { return p[1]; })) - 0.01,
        maxLat: Math.max.apply(null, boundsPts.map(function (p) { return p[1]; })) + 0.01
      } : null,
      mapKey: b ? b.bundleId + "|" + nodes.map(function (n) { return n.anchor; }).join(",") : state.anchor + "|" + state.radius,
      lines: lines,
      geoNote: geoNote,
      points: { bus: [], metro: metro }
    };
    setGeoNote(geoNote);
    var meta = mapMetaFor(state.anchor, state.radius, b);
    var T = theme();
    var opts = {
      ringColor: T.ring, candidateColor: T.cand, selectedColor: T.metroSel,
      busSelectedColor: T.busSel, anchorColor: T.anchor, haloColor: T.halo,
      lineColor: T.line, labelColor: T.label, labelSize: 10,
      labelFont: T.labelFont, numbered: false, maxBusLabels: 5
    };

    // Always render the static OSM snapshot: it is the offline fallback and
    // the map embedded into exported HTML (Leaflet DOM cannot be serialized).
    var staticEl = $("#mapStatic");
    var drewReal = false;
    if (meta && window.RealMap) {
      drewReal = window.RealMap.render(staticEl, sample, meta, opts);
      cacheMapDataUri(meta);
    }
    if (!drewReal && window.MediaMap) {
      window.MediaMap.render(staticEl, sample, Object.assign(opts, {
        width: 640, height: 360, background: "transparent",
        grid: true, gridColor: "#171717", gridOpacity: .10,
        rings: true, ringOpacity: .38, ringFill: "none", ringDash: "5 6"
      }));
    }

    var useLeaflet = !!window.L && (state.mapMode === "online" || !!offlineTileMeta());
    if (useLeaflet) staticEl.setAttribute("hidden", "");
    else staticEl.removeAttribute("hidden");
    $("#map").style.display = useLeaflet ? "block" : "none";
    var vig = document.querySelector(".map-vignette");
    if (vig) vig.hidden = useLeaflet; // live Leaflet uses #map::after so controls stay above
    if (useLeaflet) renderLeafletMap(sample);
    updateMapModeBtn();

    var orphan = (st ? st.orphanBus.length + st.orphanStations.length : 0);
    $("#mapBadge").innerHTML = "覆盖候选 " + (st ? st.coverageTotal : "—") +
      " / 可售 " + (st ? (st.busLines + st.metroExits) : "—") +
      " / 选中 " + items.length +
      (orphan ? ' <span class="warn">/ 不在库 ' + orphan + "</span>" : "");
  }

  function setGeoNote(text) {
    var box = document.querySelector(".map-box") || ($("#map") ? $("#map").parentNode : null);
    if (!box) return;
    var el = box.querySelector(".map-geo-note");
    if (!el) {
      el = document.createElement("div");
      el.className = "map-geo-note";
      el.setAttribute("style", "position:absolute;right:10px;top:46px;z-index:760;max-width:60%;font-size:12px;line-height:1.4;padding:5px 9px;border-radius:8px;background:var(--map-halo,#fff);color:var(--map-label,#151515);border:1px dashed var(--map-cand,#999);box-shadow:0 1px 3px rgba(0,0,0,.08)");
      box.appendChild(el);
    }
    el.textContent = text || "";
    el.hidden = !text;
    el.style.display = text ? "" : "none";
  }

  function renderPipeline() {
    var p = state.plan;
    var s = p ? p.summary : null;
    var st = p ? p.stats : null;
    var q = p ? p.quote : null;
    var b = currentBundle();
    var steps = [
      { n: "01 / ANCHOR", v: b ? (b.shortLabel || b.label) : shortAnchor(state.anchor) + " " + (state.radius / 1000) + "km", s: b ? b.members.length + " 个" + (b.unitLabel || "网点") : "1 个锚点" },
      { n: "02 / COVERAGE", v: (st ? st.coverageTotal : "—") + " 条", s: b ? "各" + (b.unitLabel || "网点") + "覆盖合计" : "大数据平台" },
      { n: "03 / STOCK", v: (st ? (st.busLines + st.metroExits) : "—") + " 可售", s: "红豆快照 · 去重后" },
      { n: "04 / SELECT", v: (p ? p.items.length : "—") + " 行", s: s ? (s.busCount + " 辆 + " + s.metroCount + " 口") : "—" },
      { n: "05 / QUOTE", v: (q ? wan(q.net) : "—") + " 万", s: "重算 " + Math.max(0, Math.round(state.calcMs)) + "ms" }
    ];
    $("#pipeline").innerHTML = steps.map(function (x) {
      return '<div class="step"><div class="n">' + esc(x.n) + '</div><div class="v">' + esc(x.v) + '</div><div class="s">' + esc(x.s) + "</div></div>";
    }).join("");
  }

  function renderSchedule() {
    var p = state.plan;
    var sched = p ? p.schedule : (Engine ? Engine.buildSchedule(activeRange().start || "2027-04-01") : []);
    var keep = ["design", "production", "install", "launch", "proof", "monitor", "monthly"];
    var html = sched.filter(function (x) { return keep.indexOf(x.key) >= 0; }).map(function (x) {
      return '<div class="s"><div class="d">' + esc(x.note || "") + '</div><div class="l">' + esc(x.label) + '</div><div class="n">' + esc(x.date || "") + (x.end ? "—" + esc(x.end) : "") + "</div></div>";
    }).join("");
    $("#schedule").innerHTML = html;
  }

  function renderSource() {
    var meta = DATA.meta || {};
    var range = activeRange();
    var b = currentBundle();
    var cf = (meta.coverageFiles || []).find(function (f) { return f.anchor === state.anchor && Number(f.radius) === Number(state.radius); });
    var covText;
    var anchorText;
    if (b) {
      covText = b.members.map(function (m) {
        var f = (meta.coverageFiles || []).find(function (x) { return x.anchor === m.anchor && Number(x.radius) === Number(m.radius); });
        return (m.label || shortAnchor(m.anchor)) + " " + (m.radius / 1000) + "km" + (f ? "（" + f.count + " 条）" : "");
      }).join("；");
      anchorText = (b.label || "多点模式") + " · " + b.members.length + " 个" + (b.unitLabel || "网点") + " · " + bundleRadiusText(b) +
        (b.citywide ? " · 全城 " + (state.plan ? state.plan.summary.metroStations : 0) + " 站" : "") +
        " · 品牌 " + state.brand +
        (b.status === "sample" ? " · " + (b.unitLabel || "网点") + "选点为演示假设" : "");
    } else {
      covText = cf ? cf.file : "—";
      anchorText = state.anchor + " / " + (state.radius / 1000) + "km · 品牌 " + state.brand;
    }
    $("#sourceInfo").innerHTML =
      "<div><b>库存</b> 红豆 " + (meta.counts ? meta.counts.busRows : "—") + " 公交 / " + (meta.counts ? meta.counts.metroRows : "—") + " 口（接口 total " + (meta.counts ? meta.counts.busInterfaceTotal : "—") + "）</div>" +
      "<div><b>快照</b> " + esc(activeSnapshot()) + "</div>" +
      "<div><b>档期</b> " + esc(range.start || "—") + "—" + esc(range.end || "—") + "（" + esc(range.name || "") + "）</div>" +
      "<div><b>覆盖</b> " + esc(covText) + "</div>" +
      "<div><b>底图</b> © OpenStreetMap contributors (ODbL)</div>" +
      "<div><b>坐标</b> 覆盖 BD-09 → WGS84；线路/出入口几何 GCJ-02 → WGS84（OSM/Leaflet）</div>" +
      "<div><b>锚点</b> " + esc(anchorText) + "</div>" +
      "<div><b>join</b> 公交覆盖名 " + (meta.join ? meta.join.busMatched + "/" + meta.join.busNames : "—") + " 匹配库存；地铁站 " + (meta.join ? meta.join.stationsInInventory + "/" + meta.join.stations : "—") + " 在库</div>" +
      "<div><b>报价</b> " + esc(discountLabel(state.discount)) + "；不含税（6% 专票另计）；监测费 0</div>" +
      "<div><b>触达</b> " + esc(reachLine()) + "</div>" +
      "<div><b>口径</b> " + esc(meta.footfallDisclaimer || "2023 数据仅作相对权重，不代表 2027 绝对值。") + " 2023 数据仅作相对权重。</div>";
  }

  function reachLine() {
    var p = state.plan;
    var b = currentBundle();
    var ff = (DATA.footfall || {})[state.anchor];
    if (b) {
      var info = p && p.summary.reachInfo;
      var miss = info && info.missing && info.missing.length ? "；无数据 " + info.missing.length + " 项未计（" + info.missing.slice(0, 3).join("、") + "）" : "";
      var bu = b.unitLabel || "网点";
      return "平台数据（2023-05，触达人群-日均人次）：" + b.members.length + " 个" + bu + "各取本点人流；公交 = 车辆数 × 线路日均触达；地铁同站多口按合并去重、不相加；" + bu + "之间未去重" + miss;
    }
    if (ff) {
      var info2 = p && p.summary.reachInfo;
      var miss2 = info2 && info2.missing && info2.missing.length ? "；无数据 " + info2.missing.length + " 项未计（" + info2.missing.slice(0, 3).join("、") + "）" : "";
      return "平台数据（" + ff.label + "，触达人群-日均人次）：公交 = 车辆数 × 线路日均触达；地铁同站多口按合并去重、不相加" + miss2 + (ff.missingStations && ff.missingStations.length ? "；" + ff.missingStations.join("、") + " 平台无标签" : "");
    }
    return "样本估算：该锚点暂无平台人流，公交按 05 历史提案样本级别均值估算，地铁不计（待 ZCode 补人流）";
  }

  function renderWarnings() {
    var p = state.plan;
    if (!p || !p.warnings || !p.warnings.length) {
      $("#warnings").innerHTML = "";
      return;
    }
    $("#warnings").innerHTML = p.warnings.map(function (w) {
      var info = /预算未用完|已按|1km|建议切/.test(w);
      return '<div class="w' + (info ? " info" : "") + '">' + esc(w) + "</div>";
    }).join("");
  }

  function showError(title, detail) {
    var el = $("#error");
    el.hidden = false;
    el.innerHTML = "<b>" + esc(title) + "</b>" + esc(detail || "");
  }
  function toast(msg) {
    var el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.remove("show"); }, 2200);
  }

  function csvCell(s) {
    s = String(s == null ? "" : s);
    if (/[",\r\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
    return s;
  }
  function buildCsv() {
    var p = state.plan;
    if (!p || !p.items.length) return "";
    var lines = [];
    var d = p.quote.discountRate;
    lines.push(["媒体类型", "媒体名称", "级别", "数量", "空车数", "周数", "单价(元/月)", "刊例小计", "折扣", "净价(含制作)", "日均触达(2023-05)", "触达口径", "最近距离(m)", "最近站点", "选择理由"].join(","));
    p.items.forEach(function (it) {
      lines.push([
        it.media === "metro" ? "地铁口" : "公交线路",
        it.media === "metro" ? it.station + " " + it.exit : it.name,
        it.grade, it.qty, it.free + "/" + it.total, it.months, it.unitPrice,
        it.listSubtotal, d.toFixed(2), it.net,
        it.dailyReach != null ? it.dailyReach : (it.reachSource === "sample" && it.reachEst != null ? "≈" + it.reachEst + "/辆(样本)" : "无数据"),
        it.dailyReach != null ? (it.reachScope === "station" ? "平台2023-05(站点)" : "平台2023-05") : (it.reachSource === "sample" ? "05样本估算" : "无数据"),
        Math.round(it.distance), it.pointName || "", it.reason
      ].map(csvCell).join(","));
    });
    lines.push("");
    lines.push(["报价汇总"].map(csvCell).join(","));
    lines.push(["媒体刊例", wan(p.quote.media), "制作费", wan(p.quote.production), "报价口径", discountLabel(d), "净价", wan(p.quote.net), "预算", wan(p.quote.budget), "余额", wan(p.quote.remaining), "税", "不含税(6%专票另计)"].map(csvCell).join(","));
    lines.push(["触达", reachSourceText(p.summary), "日均", Math.round(p.summary.reachDaily || 0), "档期合计", Math.round(p.summary.reach || 0), "说明", "2023 数据仅作相对权重，不代表 2027 绝对值"].map(csvCell).join(","));
    var ar = activeRange();
    var b = currentBundle();
    var anchorLabel = b ? (b.shortLabel || b.label) : state.anchor;
    var anchorDetail = b ? b.members.map(function (m) { return (m.label || shortAnchor(m.anchor)) + " " + (m.radius / 1000) + "km"; }).join(" / ") : (state.anchor + " " + (state.radius / 1000) + "km");
    lines.push(["数据来源", "红豆 " + activeSnapshot() + " / 档期 " + ar.start + "—" + ar.end + "（" + (ar.name || "") + "） / " + anchorDetail].map(csvCell).join(","));
    return "\uFEFF" + lines.join("\r\n");
  }

  function exportCsv() {
    var p = state.plan;
    if (!p || !p.items.length) { toast("没有可导出的方案"); return; }
    var csv = buildCsv();
    var b = currentBundle();
    var name = "新云提案_" + profile().label + "_" + (b ? (b.shortLabel || b.label) : state.anchor) + "_" + Math.round(state.budget / 10000) + "万_" + new Date().toISOString().slice(0, 10) + ".csv";
    download(name, csv, "text/csv;charset=utf-8");
    toast("已导出 CSV");
  }

  function buildProposalHtml() {
    var p = state.plan;
    if (!p || !p.items.length) return "";
    var q = p.quote;
    var s = p.summary;
    var b = currentBundle();
    var anchorShort = b ? (b.shortLabel || b.label) : state.anchor;
    var anchorLine = b
      ? (b.citywide
        ? (b.shortLabel || b.label) + " · " + b.members.length + " 枢纽 + " + (p.stats.citywideStations || 24) + " 站在库 / 选中 " + p.summary.metroStations + " 站"
        : b.members.map(function (m) { return (m.label || shortAnchor(m.anchor)) + " " + (m.radius / 1000) + "km"; }).join(" / "))
      : (state.anchor + " " + (state.radius / 1000) + "km");
    var mapSvg = $("#mapStatic") ? $("#mapStatic").outerHTML : "";
    mapSvg = mapSvg.replace(/\shidden(="[^"]*")?/, "");
    if (state.mapDataUri) {
      mapSvg = mapSvg.replace(/href="[^"]*"/, 'href="' + state.mapDataUri + '"');
    } else {
      mapSvg = mapSvg.replace(/<image[\s\S]*?<\/image>|<image[^>]*\/>/, "");
      mapSvg = mapSvg.replace("</svg>", '<text x="10" y="18" fill="#6A7077" font-size="10" font-family="Consolas,monospace">OSM 底图未内嵌（离线导出）；点位为真实坐标</text></svg>');
    }
    var title = s.metroCount > 0 ? (Math.round(state.budget / 10000) + " 万，" + s.metroCount + " 个口。") : (Math.round(state.budget / 10000) + " 万，" + s.busCount + " 辆车。");
    var rows = p.items.map(function (it) {
      var name = it.media === "metro" ? it.station + " " + it.exit : it.name;
      var reach = it.dailyReach != null ? fmtInt(it.dailyReach) : (it.reachSource === "sample" && it.reachEst != null ? "≈" + (it.reachEst / 10000).toFixed(1) + "万" : "无数据");
      var dist = int(it.distance) + "m" + (it.media === "bus" && it.pointName ? " · " + it.pointName : "");
      return "<tr><td><span class='badge " + it.media + "'>" + (it.media === "metro" ? "地铁口" : "公交") + "</span></td><td class='name'>" + esc(name) + "</td><td>" + esc(it.grade) + "</td><td class='num'>" + it.qty + "</td><td class='num'>" + it.free + "/" + it.total + "</td><td class='num'>" + it.months + "</td><td class='num'>" + wan(it.listSubtotal) + "</td><td class='num strong'>" + wan(it.net) + "</td><td class='num'>" + esc(reach) + "</td><td>" + esc(dist) + "</td><td class='reason'>" + esc(it.reason) + "</td></tr>";
    }).join("");
    var busNet = 0, metroNet = 0;
    p.items.forEach(function (it) { if (it.media === "metro") metroNet += it.net; else busNet += it.net; });
    var totalNet = Math.max(1, metroNet + busNet);
    var segs = p.items.map(function (it) {
      return "<i class='" + it.media + "' style='width:" + (it.net / totalNet * 100).toFixed(3) + "%' title='" + esc(it.media === "metro" ? it.station + " " + it.exit : it.name) + "'></i>";
    }).join("");
    var metroPct = Math.round(metroNet / totalNet * 100), busPct = 100 - metroPct;
    var dl = discountLabel(q.discountRate);
    var brief = briefOf(state.industryId);
    var briefHtml = brief ? ("<table class='brief-table'><tbody>" +
      (brief.elements || []).map(function (x) {
        return "<tr><th>" + esc(x.label) + "</th><td>" + esc(x.value) +
          (x.basis ? "<div class='basis'>依据：" + esc(x.basis) + "</div>" : "") + "</td></tr>";
      }).join("") + "</tbody></table><p class='fine'>" +
      esc((DATA.briefs && DATA.briefs.desensitization && DATA.briefs.desensitization.brandNames) || "") +
      " 价格为刊例价，非成交价；库存为快照，人流为 2023-05、仅作相对权重。</p>") : "";
    var reachSum = s.reachSource === "none" ? "—" : (reachSourceText(s) + "：日均约 " + (s.reachDaily / 10000).toFixed(1) + " 万人次，" + s.days + " 天合计约 " + Math.round(s.reach / 10000) + " 万人次");
    var sched = p.schedule.filter(function (x) { return ["design", "production", "install", "launch", "proof", "monitor", "monthly"].indexOf(x.key) >= 0; }).map(function (x) {
      return "<div class='sch'><div class='d'>" + esc(x.note || "") + "</div><div class='l'>" + esc(x.label) + "</div><div class='n'>" + esc(x.date || "") + "</div></div>";
    }).join("");
    var countHtml = "";
    if (s.metroCount) countHtml += "<span class='n metro'>" + s.metroCount + "</span> 个地铁口";
    if (s.metroCount && s.busCount) countHtml += " <span class='plus'>+</span> ";
    if (s.busCount) countHtml += "<span class='n bus'>" + s.busCount + "</span> 辆公交";
    var usage = Math.round(q.net / state.budget * 1000) / 10;
    var stats = [
      ["净价", wan(q.net) + " 万", "COST"],
      ["预算使用率", usage + "%", "USAGE"],
      ["公交", s.busCount + " 辆", "BUS"],
      ["地铁", s.metroCount + " 口", "METRO"],
      ["在刊", s.weeks + " 周", "FLIGHT"],
      ["覆盖候选", p.stats.coverageTotal + " 条", "COVERAGE"],
      ["日均触达", s.reachDaily ? (s.reachDaily / 10000).toFixed(1) + " 万" : "无数据", "REACH"],
      ["预算余额", wan(q.remaining) + " 万", "LEFT"]
    ].map(function (x) { return "<div class='stat'><span>" + x[0] + " / " + x[2] + "</span><b>" + x[1] + "</b></div>"; }).join("");
    var css = [
      "@page{size:A4;margin:12mm}",
      "*{box-sizing:border-box}",
      ":root{--bg:#F2F2EE;--surface:#fff;--ink:#121417;--ink2:#3A3F45;--muted:#6A7077;--line:#E3E3DD;--line2:#CBCBC3;--metro:#0B63FF;--metro-soft:#E6EEFF;--bus:#FF4D00;--bus-soft:#FFE9DF;--num:'Bahnschrift','DIN Alternate','Arial Narrow',sans-serif;--sans:'PingFang SC','Microsoft YaHei UI','Microsoft YaHei',sans-serif;--mono:'Cascadia Mono',Consolas,monospace}",
      "body{margin:0;background:#E8E8E2;color:var(--ink);font:13px/1.65 var(--sans);-webkit-print-color-adjust:exact;print-color-adjust:exact}",
      ".doc{width:190mm;margin:10mm auto;background:var(--bg);padding:9mm;box-shadow:0 10px 40px rgba(0,0,0,.08)}",
      ".top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid var(--ink);padding-bottom:3mm}",
      ".brand b{font-size:26px;letter-spacing:-.05em}.brand span{font-size:18px;margin-left:2mm}.brand em{font:600 10px var(--num);letter-spacing:.2em;color:var(--metro);font-style:normal;margin-left:2mm}",
      ".snap{text-align:right;font:9px/1.7 var(--mono);color:var(--muted)}.snap b{color:var(--ink);font-weight:600}",
      ".hero{display:grid;grid-template-columns:1.65fr .85fr;gap:10mm;padding:8mm 0 6mm;border-bottom:1px solid var(--line)}",
      ".kicker{font:9px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}",
      "h1{font:800 40px/1.05 var(--sans);letter-spacing:-.055em;margin:3mm 0 2mm}h1 .n.metro{color:var(--metro)}h1 .n.bus{color:var(--bus)}h1 .plus{color:var(--muted);font-weight:400}",
      ".sub{font:9.5px/1.8 var(--mono);color:var(--muted)}",
      ".netbox{text-align:right}.netbox .lab{font:9px var(--mono);color:var(--muted);letter-spacing:.12em}.net{font:800 44px/1 var(--num);letter-spacing:-.02em}.net small{font-size:12px;margin-left:1mm}",
      ".pill{display:inline-block;margin-top:2mm;padding:1mm 3mm;border-radius:999px;background:#E3F4EC;color:#1F7A4D;font:700 8px var(--mono);letter-spacing:.08em}",
      ".stats{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--ink);border-left:1px solid var(--ink);margin:6mm 0}",
      ".stat{border-right:1px solid var(--ink);border-bottom:1px solid var(--ink);padding:3mm}.stat span{display:block;font:7px var(--mono);letter-spacing:.08em;color:var(--muted);text-transform:uppercase}.stat b{display:block;font:700 17px var(--num);margin-top:1mm}",
      ".card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:4mm}",
      ".strip{display:flex;height:9mm;border-radius:5px;overflow:hidden;background:var(--bg)}.strip i{display:block;height:100%}.strip i.metro{background:var(--metro)}.strip i.bus{background:var(--bus)}",
      ".legend{display:flex;flex-wrap:wrap;gap:5mm;margin-top:2.5mm;font:8.5px var(--mono);color:var(--muted)}.legend b{color:var(--ink)}.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:1.5mm}.legend i.metro{background:var(--metro)}.legend i.bus{background:var(--bus)}",
      ".block{margin:7mm 0}h2{display:flex;align-items:baseline;gap:2.5mm;font:700 17px/1.2 var(--sans);letter-spacing:-.02em;margin:0 0 3mm;padding-bottom:2mm;border-bottom:1px solid var(--ink)}h2 .no{font:700 11px var(--num);color:var(--metro);letter-spacing:.06em}",
      ".brief-table{width:100%;border-collapse:collapse}.brief-table th{width:16%;text-align:left;vertical-align:top;padding:2mm 2mm 2mm 0;font:8.5px var(--mono);font-weight:400;color:var(--muted);border-bottom:1px solid var(--line)}.brief-table td{padding:2mm 0;border-bottom:1px solid var(--line);font-size:9.5px;line-height:1.55}.basis{margin-top:1mm;font:8px/1.5 var(--mono);color:var(--muted)}",
      ".fine{font:8px/1.7 var(--mono);color:var(--muted);margin:2mm 0 0}",
      ".map-card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:3mm}.map-card svg{width:100%;height:auto;display:block;border-radius:8px}",
      ".mlegend{display:flex;gap:6mm;margin-top:2.5mm;font:8.5px var(--mono);color:var(--muted)}.mlegend i{display:inline-block;width:12px;height:3px;background:var(--bus);margin-right:1.5mm;vertical-align:middle}.mlegend i.ring{width:8px;height:8px;border:2px solid var(--metro);border-radius:50%;background:transparent}",
      "table.manifest{width:100%;border-collapse:collapse;table-layout:fixed;font-size:8.2px}table.manifest th:nth-child(1){width:7%}table.manifest th:nth-child(2){width:16%}table.manifest th:nth-child(3){width:6%}table.manifest th:nth-child(4){width:5%}table.manifest th:nth-child(5){width:6%}table.manifest th:nth-child(6){width:5%}table.manifest th:nth-child(7){width:7%}table.manifest th:nth-child(8){width:7%}table.manifest th:nth-child(9){width:10%}table.manifest th:nth-child(10){width:12%}table.manifest th:nth-child(11){width:19%}table.manifest th{border-bottom:1px solid var(--ink);padding:1.8mm 1mm;text-align:left;font:7px var(--mono);letter-spacing:.05em;color:var(--muted);text-transform:uppercase}table.manifest td{border-bottom:1px solid var(--line);padding:1.8mm 1mm;vertical-align:top;line-height:1.45}table.manifest td.num{font-family:var(--num);text-align:right;white-space:nowrap}table.manifest td.strong{font-weight:700}table.manifest td.name{font-weight:600}table.manifest td.reason{color:var(--ink2);font-size:7.6px}",
      ".badge{display:inline-block;padding:.5mm 1.5mm;border-radius:3px;font:700 7px var(--mono)}.badge.metro{background:var(--metro-soft);color:#0A3FA8}.badge.bus{background:var(--bus-soft);color:#A33600}",
      ".two{display:grid;grid-template-columns:1.05fr .95fr;gap:6mm}.receipt{padding:0}.qrow{display:flex;justify-content:space-between;gap:4mm;border-bottom:1px dotted var(--line2);padding:1.8mm 0;font:9px var(--mono)}.qrow span{color:var(--muted)}.qrow b{font-family:var(--num)}.qrow.total{border-bottom:0;border-top:1px solid var(--ink);margin-top:2mm;padding-top:2.5mm;font-size:12px;color:var(--ink)}.qrow.total span{color:var(--ink)}",
      ".schs{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--ink);border-left:1px solid var(--ink)}.sch{border-right:1px solid var(--ink);border-bottom:1px solid var(--ink);padding:2mm}.sch .d{font:7px var(--mono);color:var(--muted)}.sch .l{font-weight:600;font-size:9px;margin-top:.5mm}.sch .n{font:7px var(--mono);color:var(--muted);margin-top:.5mm}",
      ".note{font:8px/1.7 var(--mono);color:var(--muted);border-top:1px solid var(--line);margin-top:6mm;padding-top:3mm}",
      ".foot{display:flex;justify-content:space-between;gap:4mm;margin-top:4mm;font:7.5px var(--mono);color:var(--muted)}",
      ".print{display:inline-block;border:0;border-radius:999px;background:var(--metro);color:#fff;padding:8px 16px;font:10px var(--mono);cursor:pointer;margin-top:5mm}",
      "@media print{body{background:#fff}.doc{width:auto;margin:0;box-shadow:none;padding:0}.print{display:none}.block,.stats,.card{break-inside:avoid}.block{page-break-inside:avoid}}"
    ].join("\n");
    var html = "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><title>" + esc(title) + " · 新云提案</title><style>" + css + "</style></head><body><div class='doc'>" +
      "<div class='top'><div class='brand'><b>新云</b><span>预算落图</span><em>ATLAS</em></div><div class='snap'><div>库存快照 <b>" + esc(activeSnapshot()) + "</b></div><div>可售档期 <b>" + esc(activeRange().start) + "—" + esc(activeRange().end) + "</b></div></div></div>" +
      "<section class='hero'><div><div class='kicker'>" + esc(profile().label) + " / " + esc(state.brand) + " / " + esc(anchorShort) + "</div>" +
      "<h1>" + countHtml + "</h1><div class='sub'>" + esc(anchorLine) + " · " + s.weeks + " 周 · 覆盖候选 " + p.stats.coverageTotal + " 条 · 选中 " + p.items.length + " 行 · " + esc(reachSourceText(s)) + "</div></div>" +
      "<div class='netbox'><div class='lab'>净价 / 万元</div><div class='net'>" + wan(q.net) + "<small>万</small></div><div class='pill'>预算内 · 用掉 " + usage + "%</div></div></section>" +
      "<section class='stats'>" + stats + "</section>" +
      "<section class='card'><div class='strip'>" + segs + "</div><div class='legend'><span><i class='metro'></i>地铁口 <b>" + metroPct + "%</b></span><span><i class='bus'></i>公交 <b>" + busPct + "%</b></span><span>净价 <b>" + wan(q.net) + " 万</b> / 预算 <b>" + Math.round(state.budget / 10000) + " 万</b></span></div></section>" +
      "<section class='block'><h2><span class='no'>00</span>campaign 假设书</h2>" +
        (function () { var bf = briefOf(state.industryId); return bf && bf.oneLine ? "<p class='fine'>" + esc(bf.oneLine) + "</p>" : ""; })() +
        briefHtml + "</section>" +
      "<section class='block'><h2><span class='no'>01</span>品牌理解 / INSIGHT</h2><p><b>" + esc(profile().brand) + "</b> · " + esc(profile().insight) + "</p><p class='fine'>合规提示：" + esc(complianceText(profile())) + (profile().complianceNotice ? "（" + esc(profile().complianceNotice) + "）" : "") + "</p></section>" +
      "<section class='block'><h2><span class='no'>02</span>覆盖与选中 / MAP</h2><div class='map-card'>" + mapSvg + "</div><div class='mlegend'><span><i></i>已选公交线路</span><span><i class='ring'></i>已选地铁口</span><span>距离 = 线路最近经过点位的距离</span></div></section>" +
      "<section class='block'><h2><span class='no'>03</span>清单 / MANIFEST</h2><table class='manifest'><thead><tr><th>类型</th><th>媒体 / 名称</th><th>级别</th><th>数量</th><th>空位</th><th>周数</th><th>刊例</th><th>净价</th><th>日均触达</th><th>距离</th><th>理由</th></tr></thead><tbody>" + rows + "</tbody></table><p class='fine'>触达：" + esc(reachSum) + "。2023 数据仅作相对权重，不代表 2027 绝对值。</p></section>" +
      "<section class='two'><div class='card'><h2><span class='no'>04</span>报价 / QUOTE</h2><div class='qrow'><span>媒体刊例</span><b>" + wan(q.media) + " 万</b></div><div class='qrow'><span>制作费</span><b>" + wan(q.production) + " 万</b></div><div class='qrow'><span>报价口径</span><b>" + esc(dl) + "</b></div><div class='qrow'><span>监测费</span><b>" + (q.monitoring ? wan(q.monitoring) + " 万" : "0") + "</b></div><div class='qrow total'><span>净价</span><b>" + wan(q.net) + " 万</b></div><div class='qrow'><span>预算余额</span><b>" + wan(q.remaining) + " 万</b></div></div>" +
      "<div class='card'><h2><span class='no'>05</span>排期 / SCHEDULE</h2><div class='schs'>" + sched + "</div></div></section>" +
      "<div class='note'>直客合同：车辆损坏「损一补一」；雨天/政府管制顺延。4A 框架：非甲方原因延误/制作不合格/维护不及时「误一补二」；上刊 T+1、上刊监测 T+5、下刊监测 T+5、月监测。夜间施工、分批安装、雨天停工；T-14 制作/审批为计划前置期假设。数据说明：红豆库存快照 " + esc(activeSnapshot()) + "，档期 " + esc(activeRange().start) + "—" + esc(activeRange().end) + "；2023 人流仅作相对权重，不构成合同承诺；报价不含税（6% 专票另计）；底图 © OpenStreetMap contributors (ODbL)。</div>" +
      "<div class='foot'><span>新云传媒 · 预算落图 ATLAS · " + esc(activeRange().name || "") + "</span><span>本文件为提案演示，不构成合同报价</span></div>" +
      "<button class='print' onclick='window.print()'>打印 / PRINT</button></div></body></html>";
    return html;
  }

  window.ProposalApp.buildProposalHtml = buildProposalHtml;
  window.ProposalApp.buildCsv = buildCsv;

  function exportHtml() {
    var p = state.plan;
    if (!p || !p.items.length) { toast("没有可导出的方案"); return; }
    var b = currentBundle();
    var meta = mapMetaFor(state.anchor, state.radius, b);
    cacheMapDataUri(meta).then(function () {
      var html = buildProposalHtml();
      var name = "新云提案_" + profile().label + "_" + (b ? (b.shortLabel || b.label) : state.anchor) + "_" + Math.round(state.budget / 10000) + "万_" + new Date().toISOString().slice(0, 10) + ".html";
      download(name, html, "text/html;charset=utf-8");
      toast("已导出 HTML 提案");
    });
  }

  function download(name, content, type) {
    var blob = new Blob([content], { type: type || "application/octet-stream" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1200);
  }

  function init() {
    if (!DATA) {
      showError("数据未加载", "请先运行 python src/build_data.py 生成 src/data.js，再用 python -m http.server 8788 打开。");
      return;
    }
    if (!Engine) {
      showError("引擎未加载", "请确认 src/engine.js 存在且无语法错误。");
      return;
    }
    if (!MediaMap) {
      showError("地图模块未加载", "请确认 src/map.js 存在。");
      return;
    }

    if (!INDUSTRY_LIST.length) {
      showError("行业配置缺失", "APP_DATA.industries 为空：请重新运行 python src/build_data.py。");
      return;
    }
    $("#industry").innerHTML = INDUSTRY_LIST.map(function (x) {
      return '<option value="' + esc(x.id) + '">' + esc(x.label) + "</option>";
    }).join("");

    setIndustry(DEFAULT_INDUSTRY);
    var startFocus = false;

    // Optional deep link, useful for the demo and for headless QA:
    // ?industry=bank|hospital|food|health|park（或完整 id）&budget=500&weeks=6&media=both&discount=0.92&view=sales&mapfull=1
    try {
      var qs = new URLSearchParams(window.location.search);
      var qi = industryIdOf(qs.get("industry"));
      if (qi) setIndustry(qi);
      var qd = qs.get("discount");
      if (qd != null) state.discount = normDiscount(qd);
      var qb = Number(qs.get("budget"));
      if (qb >= 100 && qb <= 500) state.budget = Math.round(qb) * 10000;
      var qw = Number(qs.get("weeks"));
      if (qw === 4 || qw === 6) state.weeks = qw;
      var qwin = qs.get("window") || qs.get("schedule");
      if (qwin && WINDOW_MAP[qwin]) state.windowId = qwin;
      var qr = Number(qs.get("radius"));
      if (qr && !currentBundle() && availableRadii(state.anchor).indexOf(qr) >= 0) state.radius = qr;
      var qm = qs.get("media");
      if (qm === "bus") state.media = { bus: true, metro: false };
      if (qm === "metro") state.media = { bus: false, metro: true };
      if (qm === "both") state.media = { bus: true, metro: true };
      var qv = qs.get("view");
      if (qv === "sales") state.view = "sales";
      var qmap = qs.get("map");
      if (qmap === "offline") state.mapMode = "offline";
      if (qmap === "online") state.mapMode = "online";
      var qz = Number(qs.get("zoom"));
      if (qz >= 11 && qz <= 18) state.mapZoom = qz;
      if (qs.get("mapfull") === "1") startFocus = true;
    } catch (e) { /* no query */ }

    if (!window.L) state.mapMode = "offline";
    syncControls();
    document.body.dataset.view = state.view;
    if (state.view === "sales") {
      $("#viewSales").classList.add("on"); $("#viewClient").classList.remove("on");
    }

    $("#industry").addEventListener("change", function (e) { applyIndustry(e.target.value); });
    if ($("#brandInput")) $("#brandInput").addEventListener("change", onBrandChange);
    if ($("#discount")) $("#discount").addEventListener("change", function (e) {
      state.discount = normDiscount(e.target.value);
      renderDiscount();
      runPlan(false);
    });
    $("#radiusChips").addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-radius]");
      if (btn) onRadiusChange(btn.getAttribute("data-radius"));
    });
    $("#budget").addEventListener("input", function (e) {
      state.budget = Number(e.target.value) * 10000;
      $("#budgetVal").textContent = e.target.value;
      $("#heroBudget").textContent = e.target.value;
      debouncedRun();
    });
    $("#mediaBus").addEventListener("change", function (e) {
      state.media.bus = e.target.checked;
      if (!state.media.bus && !state.media.metro) { state.media.bus = true; e.target.checked = true; }
      runPlan(false);
    });
    $("#mediaMetro").addEventListener("change", function (e) {
      state.media.metro = e.target.checked;
      if (!state.media.bus && !state.media.metro) { state.media.metro = true; e.target.checked = true; }
      runPlan(false);
    });
    $("#datePreset").addEventListener("change", function (e) {
      var parts = String(e.target.value).split(":");
      var wid = parts[0], wk = Number(parts[1]);
      if (WINDOWS.length) {
        if (wid && WINDOW_MAP[wid]) state.windowId = wid;
        if (wk === 4 || wk === 6) state.weeks = wk;
      } else if (wk === 4 || wk === 6) {
        state.weeks = wk;
      }
      runPlan(false);
    });
    $("#generateBtn").addEventListener("click", function () { runPlan(true); });
    $("#mapModeBtn").addEventListener("click", function () {
      if (!window.L) { toast("Leaflet 未加载，只能查看离线快照"); return; }
      state.mapMode = state.mapMode === "online" ? "offline" : "online";
      state.tileErrors = 0;
      if (state.mapMode === "online" && state.tileLayer) state.tileLayer.redraw();
      renderMap();
    });
    var mapFullBtn = $("#mapFullBtn");
    if (mapFullBtn) mapFullBtn.addEventListener("click", toggleFocusMode);
    document.addEventListener("fullscreenchange", function () {
      var wrap = document.getElementById("focusWrap");
      var isNative = !!wrap && document.fullscreenElement === wrap;
      if (isNative && !state.focusMode) {
        state.focusScrollY = window.scrollY || document.documentElement.scrollTop || 0;
        state.focusMode = true;
        document.body.classList.add("focus-map");
        updateMapFullBtn();
        setTimeout(refitAfterFocus, 260);
      } else if (!isNative && state.focusMode) {
        setFocusMode(false, false);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || !state.focusMode) return;
      if (document.fullscreenElement) return; // native fullscreen exits itself
      setFocusMode(false, false);
    });
    $("#viewClient").addEventListener("click", function () {
      state.view = "client";
      document.body.dataset.view = "client";
      $("#viewClient").classList.add("on");
      $("#viewSales").classList.remove("on");
      renderQuote();
      renderTable();
    });
    $("#viewSales").addEventListener("click", function () {
      state.view = "sales";
      document.body.dataset.view = "sales";
      $("#viewSales").classList.add("on");
      $("#viewClient").classList.remove("on");
      renderQuote();
      renderTable();
    });
    $("#exportCsv").addEventListener("click", exportCsv);
    $("#exportHtml").addEventListener("click", exportHtml);
    $("#planRows").addEventListener("click", function (e) {
      var btn = e.target.closest(".expand");
      if (!btn) return;
      var tr = btn.closest("tr");
      var detail = tr ? tr.nextElementSibling : null;
      if (!detail || !detail.classList.contains("detail")) return;
      var open = detail.hidden;
      detail.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });

    renderAll();
    runPlan(false);
    if (startFocus) setTimeout(function () { setFocusMode(true, false); }, 80);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
