/*
 * One-line brief parser for ATLAS.
 *
 * Two modes:
 *   1) local rules (offline, always available) — keywords/regex → structured brief
 *   2) optional LLM (online) — POST {text} to <script data-ai="...">
 *      The LLM only maps text to allowed fields; all money/inventory numbers are
 *      recomputed by engine.js. If the endpoint is missing or slow, local rules
 *      take over so the live demo never breaks.
 */
(function () {
  "use strict";

  var App = window.ProposalApp;
  if (!App) return;

  var DATA = window.APP_DATA || {};
  var SCRIPT = document.currentScript;
  var INDUSTRIES = DATA.industries || [];
  var WINDOWS = DATA.windows || [];
  var INDUSTRY_KEYS = {};
  INDUSTRIES.forEach(function (x) { INDUSTRY_KEYS[x.id] = x; });
  var WINDOW_KEYS = {};
  WINDOWS.forEach(function (x) { WINDOW_KEYS[x.id] = x; });

  var ALIASES = {
    bank: "bank-insurance", insurance: "bank-insurance", "bank-insurance": "bank-insurance",
    hospital: "private-hospital", medical: "private-hospital", "private-hospital": "private-hospital",
    food: "food-beverage", drink: "food-beverage", "food-beverage": "food-beverage",
    health: "health-supplement", supplement: "health-supplement", "health-supplement": "health-supplement",
    park: "theme-park", disney: "theme-park", "theme-park": "theme-park"
  };
  var ALLOWED_WINDOWS = ["kaimenhong", "q2", "summer", "midautumn"];
  var ALLOWED_RADII = [1000, 3000, 5000];

  function normIndustry(v) {
    if (!v) return null;
    var k = String(v).trim().toLowerCase();
    return ALIASES[k] || (INDUSTRY_KEYS[k] ? k : null);
  }

  function normWindow(v) {
    if (!v) return null;
    var k = String(v).trim().toLowerCase();
    return ALLOWED_WINDOWS.indexOf(k) >= 0 ? k : null;
  }

  function normMedia(v) {
    if (!v) return null;
    if (typeof v === "string") {
      var s = v.toLowerCase();
      if (s === "bus" || s === "metro" || s === "both") return s;
      if (/公交|车身/.test(v) && /地铁|出入口/.test(v)) return "both";
      if (/公交|车身/.test(v)) return "bus";
      if (/地铁|出入口/.test(v)) return "metro";
      return null;
    }
    if (typeof v === "object") {
      var bus = !!v.bus, metro = !!v.metro;
      if (bus && metro) return "both";
      if (bus) return "bus";
      if (metro) return "metro";
    }
    return null;
  }

  function normBudget(v) {
    var n = Number(v);
    if (!isFinite(n) || n <= 0) return null;
    if (n <= 1000) n = n * 10000;                 // 100–500 万
    if (n < 1000000 || n > 5000000) return null;
    return Math.round(n / 100000) * 100000;        // 步长 10 万，与 slider 一致
  }

  // Only keep fields that the product actually supports.
  function normalizeBrief(raw) {
    if (!raw || typeof raw !== "object") return null;
    var out = {};
    var ind = normIndustry(raw.industryId || raw.industry);
    if (ind) out.industryId = ind;
    var budget = normBudget(raw.budget);
    if (budget) out.budget = budget;
    var weeks = Number(raw.weeks);
    if (weeks === 4 || weeks === 6) out.weeks = weeks;
    var win = normWindow(raw.windowId || raw.window);
    if (win) out.windowId = win;
    var media = normMedia(raw.media);
    if (media) out.media = media;
    var radius = Number(raw.radius);
    if (ALLOWED_RADII.indexOf(radius) >= 0) out.radius = radius;
    var discount = Number(raw.discount);
    if (discount === 1 || discount === 0.92) out.discount = discount;
    return Object.keys(out).length ? out : null;
  }

  var CN_NUM = { "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5 };

  function parseLocal(text) {
    var t = String(text || "").trim();
    if (!t) return null;
    var out = {};

    if (/银行|保险|理财|开户|存款|金融|财富管理/.test(t)) out.industryId = "bank-insurance";
    else if (/医院|妇产|儿科|体检|医疗|诊所|门诊/.test(t)) out.industryId = "private-hospital";
    else if (/饮料|饮用水|矿泉水|食品|快消|即饮|农夫山泉/.test(t)) out.industryId = "food-beverage";
    else if (/保健品|营养品|膳食补充|汤臣倍健|蓝帽子/.test(t)) out.industryId = "health-supplement";
    else if (/乐园|迪士尼|主题公园|度假区|亲子游/.test(t)) out.industryId = "theme-park";

    var budget = null;
    var m = t.match(/(\d{2,4})\s*(?:万|w|W)/);
    if (m) budget = Number(m[1]);
    if (!budget) {
      m = t.match(/([一二两三四五])\s*百万/);
      if (m) budget = CN_NUM[m[1]] * 100;
    }
    if (!budget) {
      m = t.match(/预算\s*(\d{2,4})/);
      if (m) budget = Number(m[1]);
    }
    if (budget >= 100 && budget <= 500) out.budget = budget * 10000;

    m = t.match(/(\d+)\s*周/);
    if (m && (Number(m[1]) === 4 || Number(m[1]) === 6)) out.weeks = Number(m[1]);

    if (/开门红|春节|年货|Q1|一季度|[12]\s*月/i.test(t)) out.windowId = "kaimenhong";
    else if (/中秋|国庆|双节|9\s*月|10\s*月/.test(t)) out.windowId = "midautumn";
    else if (/暑期|暑假|7\s*月|8\s*月|亲子出游/.test(t)) out.windowId = "summer";
    else if (/Q2|二季度|春季|4\s*月|5\s*月/i.test(t)) out.windowId = "q2";

    var bus = /公交|车身|巴士/.test(t);
    var metro = /地铁|出入口|站点/.test(t);
    if (bus && metro) out.media = "both";
    else if (metro) out.media = "metro";
    else if (bus) out.media = "bus";

    m = t.match(/([135])\s*(?:km|公里|千米)/i);
    if (m) out.radius = Number(m[1]) * 1000;

    if (/92\s*折|0\.92|九二折/.test(t)) out.discount = 0.92;
    else if (/刊例|不打折|1\.0/.test(t)) out.discount = 1;

    return Object.keys(out).length ? out : null;
  }

  function mergeBrief(local, ai) {
    if (!local) return ai;
    if (!ai) return local;
    var out = {};
    Object.keys(local).forEach(function (k) { out[k] = local[k]; });
    Object.keys(ai).forEach(function (k) {
      if (ai[k] != null) out[k] = ai[k];
    });
    return out;
  }

  function aiEndpoint() {
    if (SCRIPT && SCRIPT.dataset && SCRIPT.dataset.ai) return SCRIPT.dataset.ai;
    if (window.BRIEF_AI_ENDPOINT) return window.BRIEF_AI_ENDPOINT;
    // Explicit direct mode for testing the static/Pages path.
    if (/[?&]ai=direct(?:&|$)/.test(location.search)) return "direct";
    // Local proxy shortcut: open index-atlas.html?ai=1 with tools/brief_proxy.py running.
    if (/[?&]ai=1(?:&|$)/.test(location.search)) return "http://127.0.0.1:8791/api/parse-brief";
    // Formal static build: call the committee model directly (key in ai-config.js).
    if (window.AIClient && window.AIClient.configured) return "direct";
    return "";
  }

  function withTimeout(p, ms) {
    var timer = null;
    var timeout = new Promise(function (_, reject) {
      timer = setTimeout(function () { reject(new Error("AI timeout")); }, ms);
    });
    return Promise.race([p, timeout]).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  function parseWithAI(text, endpoint) {
    if (endpoint === "direct" && window.AIClient) return withTimeout(window.AIClient.parseBrief(text), 25000);
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 18000) : null;
    var primary = fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      return j && (j.brief || j);
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
    return primary.catch(function (err) {
      // Local proxy down/slow: the static Pages path can still call the model.
      if (window.AIClient && window.AIClient.configured) return withTimeout(window.AIClient.parseBrief(text), 25000);
      throw err;
    });
  }

  function labels() {
    var b = window.ProposalApp && window.ProposalApp.state ? window.ProposalApp.state : {};
    return b;
  }

  function describe(applied) {
    var parts = [];
    if (applied.industryId && INDUSTRY_KEYS[applied.industryId]) parts.push(INDUSTRY_KEYS[applied.industryId].label || applied.industryId);
    if (applied.budget) parts.push("<b>" + Math.round(applied.budget / 10000) + "</b> 万");
    if (applied.windowId && WINDOW_KEYS[applied.windowId]) parts.push(WINDOW_KEYS[applied.windowId].name || applied.windowId);
    if (applied.weeks) parts.push(applied.weeks + " 周");
    if (applied.media) {
      var m = applied.media;
      var bus = m === "bus" || m === "both" || (m && m.bus);
      var metro = m === "metro" || m === "both" || (m && m.metro);
      parts.push(bus && metro ? "公交 + 地铁" : (bus ? "公交" : "地铁"));
    }
    if (applied.radius) parts.push((applied.radius / 1000) + "km");
    if (applied.discount) parts.push(applied.discount >= 0.9999 ? "刊例 1.0" : "92 折示例");
    return parts.join(" · ");
  }

  function setNote(kind, html) {
    var el = document.getElementById("aiBriefNote");
    if (!el) return;
    el.className = "hint" + (kind ? " " + kind : "");
    el.innerHTML = html;
  }

  function sampleBrief() {
    var chip = document.querySelector(".preset-chip");
    return (chip && chip.getAttribute("data-brief")) || "银行 200 万，开门红，地铁和公交";
  }

  function run(useSample) {
    var input = document.getElementById("aiBriefText");
    var btn = document.getElementById("aiBriefBtn");
    if (!input || !btn || !App.applyBrief) return;
    var text = input.value.trim();
    if (!text && useSample) {
      text = sampleBrief();
      input.value = text;
    }
    if (!text) {
      setNote("err", "先说一句需求，例如：银行 200 万，开门红，陆家嘴 3km，地铁为主；或直接按 Enter 跑银行案例。");
      input.focus();
      return;
    }
    var local = parseLocal(text);
    var endpoint = aiEndpoint();
    var prog = document.getElementById("aiBriefProgress");
    btn.disabled = true;
    if (prog) prog.hidden = !endpoint;
    setNote("", endpoint ? "AI 解析中…" : "规则解析中…");

    var chain = endpoint
      ? parseWithAI(text, endpoint).then(function (raw) {
          return { brief: mergeBrief(local, normalizeBrief(raw)), source: "ai" };
        }).catch(function () {
          return { brief: local, source: "local-fallback" };
        })
      : Promise.resolve({ brief: local, source: "local" });

    chain.then(function (res) {
      var brief = res.brief;
      if (!brief) {
        setNote("err", "没听懂。试试：<b>银行 200 万 开门红 地铁为主</b>，或 <b>医院 200 万 Q1 地铁</b>。");
        return;
      }
      var applied = App.applyBrief(brief) || {};
      var label = res.source === "ai" ? "AI 解析（组委会模型）" : (res.source === "local-fallback" ? "AI 不可用，规则解析" : "规则解析（离线）");
      setNote("ok", label + "：" + describe(applied) + "。数字由引擎重算，AI 不改数。");
    }).catch(function (err) {
      setNote("err", "解析失败：" + (err && err.message ? err.message : String(err)));
    }).finally(function () {
      btn.disabled = false;
      if (prog) prog.hidden = true;
    });
  }

  function init() {
    var input = document.getElementById("aiBriefText");
    var btn = document.getElementById("aiBriefBtn");
    if (!input || !btn) return;
    btn.addEventListener("click", function () { run(false); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); run(true); }
    });
    if (aiEndpoint()) setNote("", "AI 模式已配置（组委会模型）；直接按 Enter 跑银行案例，或输入后点解析。");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // Expose for tests / console.
  window.BriefParser = { parseLocal: parseLocal, normalizeBrief: normalizeBrief };
  if (App) App.parseBrief = parseLocal;
})();
