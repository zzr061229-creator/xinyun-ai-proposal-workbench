/*
 * ATLAS skin — extra views on top of app.js (which still owns state, engine,
 * map, table and export). Everything here reads ProposalApp.state.plan and
 * redraws on every recompute:
 *   headline · budget strip · roster · waterfall · sift steps · gantt
 * Hovering a strip segment / roster row highlights the same item everywhere
 * (strip ↔ roster ↔ map marker).
 */
(function () {
  "use strict";

  var App = window.ProposalApp;
  if (!App) return;
  var $ = function (sel) { return document.querySelector(sel); };
  var wan = function (n) { return (Number(n || 0) / 10000).toFixed(1); };
  var fmt = function (n) { return Math.round(Number(n || 0)).toLocaleString("zh-CN"); };
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // metro → one circleMarker per exit id; bus → one polyline per route (see app.js markers)
  function keyOf(it) { return it.media === "metro" ? "metro:" + it.id : "bus:" + it.line; }
  function nameOf(it) { return it.media === "metro" ? it.station + " " + it.exit : it.name; }
  function shortAnchor(name) {
    var a = ((window.APP_DATA || {}).anchors || []).find(function (x) { return x.name === name; });
    return a ? a.short : name;
  }
  function anchorLine(state) {
    var b = state.anchorBundle;
    if (b && b.members && b.members.length > 1) return (b.shortLabel || b.label) + " · " + b.members.length + " 个" + (b.unitLabel || "网点");
    return shortAnchor(state.anchor) + " " + (state.radius / 1000) + "km";
  }

  // ---------- headline ----------
  function renderHeadline(state) {
    var p = state.plan, s = p.summary;
    var parts = [];
    if (s.metroCount) parts.push('<span class="n metro">' + s.metroCount + '</span> 个地铁口');
    if (s.busCount) parts.push('<span class="n bus">' + s.busCount + '</span> 辆公交');
    $("#atlasHeadline").innerHTML = parts.length ? parts.join('<span class="plus">+</span>') : "当前条件下没有可售组合";
    var reach = "";
    if ((s.reachSource === "platform" || s.reachSource === "mixed") && s.reachDaily) {
      reach = " · 日均触达约 " + (s.reachDaily / 10000).toFixed(1) + " 万人次（平台数据 " + s.reachLabel.replace("平台 ", "") + "，同站不相加" + (s.anchorCount > 1 ? "；" + ((state.anchorBundle && state.anchorBundle.unitLabel) || "点位") + "间未去重" : "") + "）";
    } else if (s.reachSource === "sample" && s.reachDaily) {
      reach = " · 公交日均触达约 " + (s.reachDaily / 10000).toFixed(1) + " 万人次（样本估算，地铁不计）";
    }
    var disc = p.quote.discountRate < 0.9999 ? " · " + Math.round(p.quote.discountRate * 100) + " 折示例" : " · 刊例价";
    var scope = state.anchorBundle ? anchorLine(state) + "范围内" : anchorLine(state) + " 内";
    $("#atlasEyebrow").textContent = scope + " · " + s.weeks + " 周 · " + p.items.length + " 行明细" + disc + reach;
    $("#atlasMs").textContent = Math.max(1, Math.round(state.calcMs)) + " ms";
    var mix = s.mix || {};
    $("#mixMetro").textContent = (mix.metroPct || 0) + "%";
    $("#mixBus").textContent = (mix.busPct || 0) + "%";
    $("#rosterMeta").textContent = s.metroCount + " 口 · " + s.busCount + " 辆 · " + p.items.length + " 行";
  }

  // ---------- budget strip ----------
  function renderStrip(state) {
    var p = state.plan, q = p.quote;
    var total = Math.max(q.budget, q.net);
    var items = p.items.slice().sort(function (a, b) {
      if (a.media !== b.media) return a.media === "metro" ? -1 : 1;
      return b.net - a.net;
    });
    var html = items.map(function (it) {
      var pct = it.net / total * 100;
      var label = pct > 7 ? '<span class="t">' + esc(nameOf(it)) + "</span><span class=\"v\">" + wan(it.net) + "</span>"
        : pct > 3.2 ? '<span class="v">' + wan(it.net) + "</span>" : "";
      return '<div class="seg ' + it.media + '" data-key="' + esc(keyOf(it)) + '" data-id="' + esc(it.id) + '" style="flex-basis:' + pct.toFixed(3) + '%" title="' +
        esc(nameOf(it) + " · " + it.qty + (it.media === "metro" ? " 口" : " 辆") + " · 净价 " + wan(it.net) + " 万") + '">' + label + "</div>";
    }).join("");
    if (q.remaining > 0) {
      var lp = q.remaining / total * 100;
      html += '<div class="seg left" style="flex-basis:' + lp.toFixed(3) + '%" title="余额 ' + wan(q.remaining) + ' 万">' + (lp > 3.2 ? '<span class="v">余 ' + wan(q.remaining) + "</span>" : "") + "</div>";
    }
    $("#strip").innerHTML = html;

    var step = total >= 4000000 ? 1000000 : 500000;
    var ticks = [];
    for (var v = 0; v <= total + 1; v += step) ticks.push(v);
    $("#stripAxis").innerHTML = ticks.map(function (v) {
      return '<span style="left:' + (v / total * 100) + '%">' + (v / 10000) + "</span>";
    }).join("") + '<span class="end" style="left:100%">' + Math.round(total / 10000) + " 万</span>";
  }

  // ---------- roster (right of map) ----------
  function renderRoster(state) {
    var p = state.plan;
    var groups = [
      { media: "metro", title: "地铁口", unit: "口" },
      { media: "bus", title: "公交车身", unit: "辆" }
    ];
    var html = groups.map(function (g) {
      var list = p.items.filter(function (x) { return x.media === g.media; });
      if (!list.length) return "";
      var sum = list.reduce(function (n, x) { return n + x.net; }, 0);
      var qty = list.reduce(function (n, x) { return n + x.qty; }, 0);
      return '<div class="grp ' + g.media + '"><div class="grp-head"><span><i></i>' + g.title + " · " + qty + " " + g.unit + '</span><b>' + wan(sum) + " 万</b></div>" +
        list.map(function (it) {
          var tight = it.free <= 2 ? '<em class="tight">空位 ' + it.free + "/" + it.total + "</em>" : '<span class="free">空 ' + it.free + "/" + it.total + "</span>";
          return '<button type="button" class="item ' + it.media + '" data-key="' + esc(keyOf(it)) + '" data-id="' + esc(it.id) + '">' +
            '<span class="nm">' + esc(nameOf(it)) + '<small>' + esc(it.grade) + " · " + esc(subOf(it)) + "</small></span>" +
            '<span class="qt">×' + it.qty + "</span>" +
            '<span class="am">' + wan(it.net) + "<small>" + tight + "</small></span>" +
            "</button>";
        }).join("") + "</div>";
    }).join("");
    var unit = (state.anchorBundle && state.anchorBundle.unitLabel) || "网点";
    $("#roster").innerHTML = html || '<div class="empty">当前' + unit + ' / 预算没有可售组合。试试放开媒体或换行业。</div>';
  }

  function subOf(it) {
    var r = App.reachText ? App.reachText(it) : "";
    var dist = it.media === "bus"
      ? (App.distanceText ? App.distanceText(it).replace("最近经过 ", "经") : "线路 · 经" + (it.pointName || "—") + " · 距锚点 " + Math.round(it.distance) + "m")
      : Math.round(it.distance) + "m" + (it.anchorLabel ? " · 距" + it.anchorLabel : "");
    // reach first so it survives the roster's ellipsis; full text stays in the table
    return "触达 " + r.replace(" 人次/日（线路）", "/日").replace(" 人次/日（单口）", "/日").replace("（05 样本估算）", "·样本") + " · " + dist;
  }

  // ---------- waterfall ----------
  function renderWaterfall(state) {
    var q = state.plan.quote;
    var gross = q.media + q.production + (q.monitoring || 0);
    var max = Math.max(gross, q.budget) * 1.04;
    var pct = function (v) { return (v / max * 100).toFixed(3) + "%"; };
    var rows = [
      { k: "媒体刊例", v: q.media, from: 0, to: q.media, cls: "base" },
      { k: "制作费", v: q.production, from: q.media, to: q.media + q.production, cls: "add", sign: "+" },
      { k: "监测费", v: q.monitoring || 0, from: q.media + q.production, to: gross, cls: "add", sign: "+" },
      { k: q.discountRate < 0.9999 ? Math.round(q.discountRate * 100) + " 折（示例）" : "折扣（刊例 1.0）", v: q.discountAmount, from: q.net, to: gross, cls: "sub", sign: "−" },
      { k: "净价", v: q.net, from: 0, to: q.net, cls: "net" }
    ];
    var html = rows.map(function (r) {
      return '<div class="wf-row ' + r.cls + '"><span class="k">' + r.k + '</span><div class="track"><i style="left:' + pct(r.from) + ";width:" + pct(Math.max(0, r.to - r.from)) + '"></i></div><span class="v">' + (r.sign || "") + wan(r.v) + " 万</span></div>";
    }).join("");
    html += '<div class="wf-budget" style="left:calc(var(--wf-k) + (100% - var(--wf-k) - var(--wf-v)) * ' + (q.budget / max).toFixed(4) + ')"><span>预算 ' + wan(q.budget) + "</span></div>";
    $("#waterfall").innerHTML = html;
  }

  // ---------- sift steps ----------
  function renderSift(state) {
    var st = state.plan.stats, s = state.plan.summary;
    var orphan = (st.orphanBus || []).concat(st.orphanStations || []);
    var steps = [
      { n: st.coverageTotal, u: "条", t: "大数据覆盖", d: st.citywide
        ? st.coverageBusLines + " 条公交线 · 4 枢纽覆盖；地铁另加 " + st.citywideStations + " 个在库站（全城 " + st.citywideDistricts + " 个区）"
        : st.coverageBusLines + " 条公交线 · " + st.coverageStations + " 个地铁站落在 " + (st.anchorCount > 1 ? st.anchorCount + " 个" + (state.anchorBundle && state.anchorBundle.unitLabel || "网点") : (state.radius / 1000) + "km 内") },
      { n: st.busLines + st.metroExits, u: "项", t: "红豆可售", d: st.busLines + " 条线 " + st.availableBusFree + " 辆空车 · " + st.metroStations + " 站 " + st.metroExits + " 个空口" + (orphan.length ? " · 不在库：" + orphan.join("、") : "") },
      { n: state.plan.items.length, u: "行", t: "预算内选中", d: s.busCount + " 辆公交 + " + s.metroCount + " 个地铁口 · 同线去重 · 同站 ≤2 口" }
    ];
    $("#siftSteps").innerHTML = steps.map(function (x, i) {
      return '<div class="step"><div class="idx">' + (i + 1) + '</div><div class="big">' + x.n + "<small>" + x.u + '</small></div><b>' + x.t + "</b><p>" + esc(x.d) + "</p></div>";
    }).join('<div class="arrow" aria-hidden="true"></div>');
  }

  // ---------- gantt ----------
  function day(s) { return Date.parse(s + "T00:00:00Z") / 864e5; }
  function renderGantt(state) {
    var p = state.plan;
    var sched = p.schedule || [];
    if (!sched.length) { $("#gantt").innerHTML = ""; return; }
    var start = day(p.summary.startDate || "2027-04-01");
    var flightEnd = start + p.summary.days;
    var lo = Math.min.apply(null, sched.map(function (x) { return day(x.date); })) - 2;
    var hi = Math.max(flightEnd, Math.max.apply(null, sched.map(function (x) { return day(x.end || x.date); }))) + 2;
    var pos = function (d) { return ((d - lo) / (hi - lo) * 100).toFixed(3) + "%"; };
    var iso = function (d) { return new Date(d * 864e5).toISOString().slice(5, 10); };

    var rows = sched.map(function (x) {
      var a = day(x.date), b = x.end ? day(x.end) : null;
      var mark = b ? '<i class="bar" style="left:' + pos(a) + ";width:calc(" + pos(b) + " - " + pos(a) + ')"></i>'
        : '<i class="dot" style="left:' + pos(a) + '"></i>';
      return '<div class="g-row' + (x.key === "launch" ? " launch" : "") + '"><span class="g-k"><b>' + esc(x.note || "") + "</b>" + esc(x.label) + '</span><div class="g-track">' + mark +
        '<span class="g-d" style="left:' + pos(b || a) + '">' + iso(a) + (b ? "—" + iso(b) : "") + "</span></div></div>";
    });
    rows.splice(5, 0, '<div class="g-row flight"><span class="g-k"><b>' + p.summary.weeks + " 周</b>在刊期</span><div class=\"g-track\"><i class=\"bar\" style=\"left:" + pos(start) +
      ";width:calc(" + pos(flightEnd) + " - " + pos(start) + ')"></i><span class="g-d in" style="left:' + pos(start) + '">' + iso(start) + " — " + iso(flightEnd - 1) + "</span></div></div>");

    // month ticks
    var ticks = "";
    for (var d = Math.ceil(lo); d <= hi; d++) {
      var dt = new Date(d * 864e5);
      if (dt.getUTCDate() === 1) ticks += '<span class="g-tick" style="left:' + pos(d) + '">' + (dt.getUTCMonth() + 1) + " 月</span>";
    }
    $("#gantt").innerHTML = '<div class="g-axis"><span class="g-k"></span><div class="g-track">' + ticks + '<span class="g-today" style="left:' + pos(start) + '"></span></div></div>' + rows.join("");
  }

  // ---------- cross-highlight ----------
  var hot = null;
  function setHot(key, id) {
    if (hot && hot.key === key && hot.id === id) return;
    clearHot();
    if (!key) return;
    hot = { key: key, id: id, items: [] };
    document.querySelectorAll('[data-id="' + CSS.escape(id) + '"]').forEach(function (el) { el.classList.add("hot"); });
    document.body.classList.add("has-hot");
    // Offline SVG: same data-key on the drawn route/exit ring.
    document.querySelectorAll('[data-key="' + CSS.escape(key) + '"]').forEach(function (el) { el.classList.add("map-hot"); });
    var m = App.markers[key];
    var list = Array.isArray(m) ? m : (m ? [m] : []);
    list.forEach(function (marker) {
      var node = marker.getElement ? marker.getElement() : null;
      if (node) node.classList.add("map-hot");
      if (typeof marker.getRadius === "function") {          // metro circleMarker
        hot.items.push({ m: marker, radius: marker.getRadius() });
        marker.setRadius(marker.getRadius() + 5);
        marker.setStyle({ weight: 3 });
      } else {                                               // bus polyline
        hot.items.push({ m: marker, line: { weight: marker.options.weight, opacity: marker.options.opacity } });
        marker.setStyle({ weight: 7, opacity: 1 });
      }
      if (marker.bringToFront) marker.bringToFront();
      if (marker.openTooltip) marker.openTooltip();
    });
  }
  function clearHot() {
    if (!hot) return;
    document.querySelectorAll(".hot").forEach(function (el) { el.classList.remove("hot"); });
    document.querySelectorAll(".map-hot").forEach(function (el) { el.classList.remove("map-hot"); });
    document.body.classList.remove("has-hot");
    (hot.items || []).forEach(function (it) {
      var m = it.m;
      if (it.radius && typeof m.setRadius === "function") {
        m.setRadius(it.radius);
        m.setStyle({ weight: 2.2 });
      } else if (it.line) {
        m.setStyle({ weight: it.line.weight, opacity: it.line.opacity });
        if (m.closeTooltip) m.closeTooltip();
      }
    });
    hot = null;
  }
  function bindHover(container) {
    container.addEventListener("mouseover", function (e) {
      var el = e.target.closest("[data-key]");
      if (el) setHot(el.getAttribute("data-key"), el.getAttribute("data-id"));
    });
    container.addEventListener("mouseleave", clearHot);
    container.addEventListener("click", function (e) {
      var el = e.target.closest("[data-key]");
      if (el) setHot(el.getAttribute("data-key"), el.getAttribute("data-id"));
    });
    container.addEventListener("focusin", function (e) {
      var el = e.target.closest("[data-key]");
      if (el) setHot(el.getAttribute("data-key"), el.getAttribute("data-id"));
    });
    container.addEventListener("focusout", clearHot);
  }

  function flash() {
    var el = $("#answer");
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }

  function render(state) {
    if (!state.plan) return;
    hot = null;
    document.body.classList.remove("has-hot");
    renderHeadline(state);
    renderStrip(state);
    renderRoster(state);
    renderWaterfall(state);
    renderSift(state);
    renderGantt(state);
    flash();
    fitStage();
  }

  // Map + roster fill exactly what is left of the first screen, so the
  // whole story (brief → answer → strip → map) is visible without scrolling.
  function fitStage() {
    var stage = $(".stage");
    if (!stage) return;
    if (document.body.classList.contains("focus-map")) return;
    if (window.innerWidth <= 1180) { stage.style.height = ""; return; }
    var top = stage.getBoundingClientRect().top + window.scrollY;
    var h = Math.max(440, Math.min(820, window.innerHeight - top - 16));
    stage.style.height = h + "px";
    var map = App.state.leaflet;
    if (map) setTimeout(function () { map.invalidateSize(); }, 0);
  }

  function init() {
    fitStage();
    window.addEventListener("resize", fitStage);
    bindHover($("#strip"));
    bindHover($("#roster"));
    bindHover($("#planRows"));
    $("#roster").addEventListener("click", function (e) {
      var el = e.target.closest("[data-key]");
      if (!el) return;
      var m = App.markers[el.getAttribute("data-key")];
      var map = App.state.leaflet;
      if (!m || !map) return;
      if (Array.isArray(m)) m = m[0];
      if (typeof m.getLatLng === "function") map.flyTo(m.getLatLng(), Math.max(map.getZoom(), 15), { duration: 0.6 });
      else if (typeof m.getBounds === "function") map.flyToBounds(m.getBounds(), { padding: [24, 24], duration: 0.6 });
    });
    App.onRender(render);
  }

  // ---------- AI brief：只留接口，暂不实现、不加 UI ----------
  // parseBrief(text) 约定：把一句自然语言需求解析成结构化 brief，返回
  //   { industryId, budget, weeks, media, radius, discount, windowId } 或 null（无法解析）
  //   industryId: "bank-insurance" | "private-hospital" | "food-beverage" | "health-supplement" | "theme-park"
  //               （也接受短名 bank/hospital/food/health/park）
  //   budget:   元（1000000–5000000），也接受“万”数值 100–500
  //   weeks:    4 | 6（在所选档期窗口内截取）
  //   windowId: "kaimenhong" | "q2" | "summer" | "midautumn"；缺省按行业默认
  //   media:    { bus: bool, metro: bool } | "bus" | "metro" | "both"
  //   radius:   米，必须是该锚点已有覆盖（1000/3000，乐园 3000/5000）
  //   discount: 1（刊例，默认）| 0.92（示例，待销售确认）
  //   字段可缺省；缺省 = 保持当前值。当前空实现永远返回 null。
  App.parseBrief = function (text) { return null; };  // eslint-disable-line no-unused-vars

  // applyBrief(brief)：把结构化 brief 应用到状态并重算；返回实际生效的字段。
  App.applyBrief = function (brief) {
    if (!brief || typeof brief !== "object") return null;
    var patch = {};
    ["industryId", "budget", "weeks", "media", "radius", "discount", "windowId"].forEach(function (k) {
      if (brief[k] != null) patch[k] = brief[k];
    });
    return App._apply ? App._apply(patch) : null;
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
