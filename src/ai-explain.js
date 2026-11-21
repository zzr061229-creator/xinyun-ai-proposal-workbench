/*
 * "AI 解释" for ATLAS.
 *
 * The rules engine already decided the plan. This module only turns the plan
 * into a short Chinese rationale. It never changes numbers.
 *
 * Endpoint: <script data-ai="http://127.0.0.1:8791/api/explain">
 * Fallback: local template built from the same plan (no network needed).
 */
(function () {
  "use strict";

  var App = window.ProposalApp;
  if (!App) return;
  var SCRIPT = document.currentScript;

  var GOALS = {
    "bank-insurance": "网点与线上预约",
    "private-hospital": "院区预约",
    "food-beverage": "便利店与试饮点",
    "health-supplement": "药店复购",
    "theme-park": "乐园入口"
  };

  function endpoint() {
    if (SCRIPT && SCRIPT.dataset && SCRIPT.dataset.ai) return SCRIPT.dataset.ai;
    if (window.AI_EXPLAIN_ENDPOINT) return window.AI_EXPLAIN_ENDPOINT;
    if (/[?&]ai=1(?:&|$)/.test(location.search)) return "http://127.0.0.1:8791/api/explain";
    return "";
  }

  function industryLabel(id) {
    var hit = ((window.APP_DATA || {}).industries || []).find(function (x) { return x.id === id; });
    return hit ? (hit.label || hit.name || id) : id;
  }

  function windowLabel(id) {
    var hit = ((window.APP_DATA || {}).windows || []).find(function (x) { return x.id === id; });
    return hit ? (hit.name || id) : id;
  }

  function buildPayload() {
    var s = App.state;
    if (!s || !s.plan) return null;
    var p = s.plan;
    var sm = p.summary || {};
    var st = p.stats || {};
    var items = (p.items || []).slice(0, 12).map(function (x) {
      return {
        media: x.media === "metro" ? "地铁口" : "公交线路",
        name: x.media === "metro" ? (x.station + " " + x.exit) : x.name,
        grade: x.grade,
        qty: x.qty,
        free: x.free,
        total: x.total,
        reason: x.reason
      };
    });
    return {
      industry: industryLabel(s.industryId),
      industryId: s.industryId,
      brand: s.brand,
      budgetWan: Math.round(s.budget / 10000),
      weeks: s.weeks,
      window: windowLabel(s.windowId),
      anchor: s.anchor,
      anchors: sm.anchors || [],
      anchorLabels: sm.anchorLabels || [],
      anchorCount: sm.anchorCount || 1,
      unitLabel: (App.state.anchorBundle && App.state.anchorBundle.unitLabel) || "网点",
      radiusKm: Math.round(s.radius / 100) / 10,
      media: {
        metroCount: sm.metroCount || 0,
        busCount: sm.busCount || 0,
        metroStations: sm.metroStations || 0,
        busLines: sm.busLines || 0
      },
      budgetSplit: sm.mix ? { metroPct: sm.mix.metroPct, busPct: sm.mix.busPct } : null,
      coverage: {
        total: st.coverageTotal,
        busLines: st.busLines,
        metroExits: st.metroExits,
        availableBusFree: st.availableBusFree,
        availableMetroFree: st.availableMetroFree
      },
      warnings: (p.warnings || []).slice(0, 4),
      items: items
    };
  }

  function localExplain(payload) {
    var m = payload.media;
    var goal = GOALS[payload.industryId] || "主目标客群";
    var metro = m.metroCount ? (m.metroCount + " 个地铁口") : "没有可售地铁口";
    var bus = m.busCount ? (m.busCount + " 辆公交") : "没有公交";
    var multi = (payload.anchorCount || 1) > 1;
    var scope = multi
      ? (payload.anchorCount + " 个" + (payload.unitLabel || "网点") + "（" + (payload.anchorLabels || payload.anchors || []).join(" / ") + "）")
      : (payload.anchor + " " + payload.radiusKm + "km");
    var noMetro = !m.metroCount ? (multi ? "这些" + (payload.unitLabel || "点位") + " 1km 内没有可售地铁口，所以方案全走公交，没有硬凑地铁组合。" : "这个锚点没有可售地铁口，所以方案全走公交，没有硬凑地铁组合。") : "";
    return "这版方案把预算分在" + scope + "：" +
      metro + "负责把人带到" + goal + "，" + bus + "补通勤和社区覆盖。" +
      "选中的媒体都先过覆盖候选，再和红豆空车数核对；地铁同站多口按合并去重算，公交与地铁之间不重复相加。" +
      noMetro +
      "库存是快照，签约前回红豆复核；这里的解释只讲取舍，不改页面上的数字。";
  }

  function setNote(text) {
    var el = document.getElementById("aiExplainNote");
    if (el) el.textContent = text;
  }

  function setBody(text) {
    var el = document.getElementById("aiExplainBody");
    if (el) el.textContent = text;
  }

  function planSignature() {
    var s = App.state;
    if (!s || !s.plan) return "";
    var p = s.plan;
    var items = (p.items || []).map(function (x) {
      return (x.media || "") + ":" + (x.id || x.line || x.name) + ":" + x.qty;
    }).join(",");
    return [s.industryId, s.brand, s.budget, s.weeks, s.windowId, s.radius, s.discount,
      s.media && s.media.bus ? 1 : 0, s.media && s.media.metro ? 1 : 0, items].join("|");
  }

  var lastSig = "";
  var runToken = 0;

  function invalidateIfChanged() {
    var sig = planSignature();
    if (!sig) return;
    if (lastSig && sig !== lastSig) {
      runToken++;
      setBody("方案已更新，点“重新生成”让 AI 重新解释。");
      setNote("旧解释已失效");
    }
    lastSig = sig;
  }

  function requestExplain(payload, url) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 12000) : null;
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: payload }),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      return j && j.explanation ? String(j.explanation).trim() : "";
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  function run() {
    var btn = document.getElementById("aiExplainBtn");
    var payload = buildPayload();
    if (!btn) return;
    if (!payload) {
      setNote("先生成方案，再让 AI 解释。");
      return;
    }
    var url = endpoint();
    var token = ++runToken;
    var sig = planSignature();
    lastSig = sig;
    btn.disabled = true;
    btn.textContent = "生成中…";
    setNote(url ? "AI 正在读这份方案…" : "未配置 AI，使用模板解释。");

    var chain = url
      ? requestExplain(payload, url).then(function (text) {
          if (!text) throw new Error("empty");
          return { text: text, source: "ai" };
        }).catch(function () {
          return { text: localExplain(payload), source: "fallback" };
        })
      : Promise.resolve({ text: localExplain(payload), source: "template" });

    chain.then(function (res) {
      if (token !== runToken || sig !== planSignature()) return;
      setBody(res.text);
      if (res.source === "ai") setNote("AI 生成 · 只解释取舍，数字以页面为准");
      else if (res.source === "fallback") setNote("AI 不可用，已用模板解释");
      else setNote("模板解释（未配置 AI）");
    }).catch(function (err) {
      if (token !== runToken || sig !== planSignature()) return;
      setBody(localExplain(payload));
      setNote("生成失败，已用模板解释：" + (err && err.message ? err.message : String(err)));
    }).finally(function () {
      if (token !== runToken) return;
      btn.disabled = false;
      btn.textContent = "重新生成";
    });
  }

  function init() {
    var btn = document.getElementById("aiExplainBtn");
    if (!btn) return;
    btn.addEventListener("click", run);
    if (typeof App.onRender === "function") App.onRender(invalidateIfChanged);
    invalidateIfChanged();
    if (endpoint()) setNote("AI 已配置；点按钮生成解释。");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  window.AIExplain = { buildPayload: buildPayload, localExplain: localExplain };
})();
