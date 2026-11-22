/*
 * Direct browser client for the B1X committee model.
 *
 * The static Pages build cannot reach the local 8791 proxy, so this file calls
 * the OpenAI-compatible endpoint directly. The key in ai-config.js is an
 * ephemeral competition key for 2026-11-22 only; all money/inventory numbers
 * still come from engine.js.
 */
(function () {
  "use strict";

  var CFG = window.AI_CONFIG || {};
  var READY = !!(CFG.baseUrl && CFG.apiKey && CFG.model);

  var BRIEF_PROMPT = [
    "你是户外媒体提案的 brief 参数解析器。只输出 JSON，不要解释、不要 Markdown。",
    "把用户的一句话需求映射到下列字段；只输出文本中明确出现的字段，没出现就省略，不要猜。",
    "",
    "字段与允许值：",
    "- industryId: bank-insurance | private-hospital | food-beverage | health-supplement | theme-park",
    "- budget: 数字，单位元，1000000–5000000。超出范围就省略，不要截断、四舍五入或猜。",
    "- weeks: 4 | 6。只有文本明确写“4周”或“6周”才输出；写 2 周、3 周、8 周等不支持的值时，省略 weeks，不要猜。",
    "- windowId: kaimenhong（开门红/春节/Q1）| q2（春季/4-5月/Q2）| summer（暑期/7-8月）| midautumn（中秋国庆/9-10月）",
    "- media: bus | metro | both",
    "- radius: 1000 | 3000 | 5000（米）。只接受 1km / 3km / 5km；其他半径省略。",
    "- discount: 1 | 0.92。只有文本明确写“92折/0.92/九二折”或“刊例/不打折/1.0”才输出。",
    "",
    "示例：",
    "用户：银行 200 万，2027 开门红，3km，地铁+公交",
    "输出：{\"industryId\":\"bank-insurance\",\"budget\":2000000,\"windowId\":\"kaimenhong\",\"radius\":3000,\"media\":\"both\"}",
    "",
    "用户：医院 200 万 Q1 只要地铁出入口",
    "输出：{\"industryId\":\"private-hospital\",\"budget\":2000000,\"windowId\":\"kaimenhong\",\"media\":\"metro\"}",
    "",
    "用户：乐园 500 万 暑期 公交加地铁",
    "输出：{\"industryId\":\"theme-park\",\"budget\":5000000,\"windowId\":\"summer\",\"media\":\"both\"}",
    "",
    "用户：保健品 100 万 中秋 公交车身",
    "输出：{\"industryId\":\"health-supplement\",\"budget\":1000000,\"windowId\":\"midautumn\",\"media\":\"bus\"}",
    "",
    "不要输出价格、库存、触达等数字；这些由规则引擎计算。"
  ].join("\n");

  var EXPLAIN_PROMPT = [
    "你是户外媒体公司的策略总监。下面是一份已经由规则引擎算好的方案 JSON。",
    "请写一段 120–180 字的中文解释，回答三件事：",
    "1) 为什么选这个锚点和半径；",
    "2) 为什么地铁/公交是这个主次；",
    "3) 为什么是这些线路/口。",
    "只使用 JSON 里出现的信息；不要写任何数字，包括金额、口数、车辆数、线路数、触达人次、公里数、百分比；不要承诺效果；不要编客户、案例或媒体资源。所有数字由页面显示，解释只讲取舍。",
    "语气像在给客户当面讲，不要分点，不要 Markdown。只输出 JSON：{\"explanation\":\"...\"}"
  ].join("\n");

  function endpoint() {
    return String(CFG.baseUrl || "").replace(/\/+$/, "") + "/chat/completions";
  }

  function salvage(text) {
    var s = String(text || "").trim();
    if (!s) throw new Error("empty model content");
    s = s.replace(/^```[a-zA-Z]*\s*/, "").replace(/\s*```$/, "");
    try { return JSON.parse(s); } catch (e) { /* find object */ }
    var a = s.indexOf("{"), b = s.lastIndexOf("}");
    if (a >= 0 && b > a) return JSON.parse(s.slice(a, b + 1));
    throw new Error("model did not return JSON");
  }

  function once(system, user, maxTokens, temperature) {
    if (!READY) return Promise.reject(new Error("AI_CONFIG missing"));
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 45000) : null;
    return fetch(endpoint(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + CFG.apiKey
      },
      body: JSON.stringify({
        model: CFG.model,
        temperature: temperature,
        max_tokens: maxTokens,
        messages: [
          { role: "system", content: system },
          { role: "user", content: user }
        ],
        response_format: { type: "json_object" },
        thinking: { type: "disabled" }
      }),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (j) {
      var ch = (j.choices || [{}])[0] || {};
      var msg = ch.message || {};
      return { content: String(msg.content || "").trim(), finish: ch.finish_reason };
    }).finally(function () {
      if (timer) clearTimeout(timer);
    });
  }

  function call(system, user, maxTokens, temperature) {
    var budgets = [maxTokens, Math.min(maxTokens * 2, 2400)];
    var i = 0;
    var last = null;
    function next() {
      if (i >= budgets.length) return Promise.reject(last || new Error("AI failed"));
      var mt = budgets[i++];
      return once(system, user, mt, temperature).then(function (res) {
        if (!res.content) {
          last = new Error("empty model content (" + (res.finish || "?") + ")");
          return next();
        }
        try {
          return salvage(res.content);
        } catch (e) {
          last = e;
          return next();
        }
      }).catch(function (e) {
        last = e;
        return next();
      });
    }
    return next();
  }

  function parseBrief(text) {
    return call(BRIEF_PROMPT, String(text || ""), 700, 0).then(function (out) {
      if (out && out.brief && Object.keys(out).length === 1) return out.brief;
      return out;
    });
  }

  function explain(plan) {
    return call(EXPLAIN_PROMPT, JSON.stringify(plan || {}), 1800, 0).then(function (out) {
      if (!out || !out.explanation) throw new Error("model returned no explanation");
      return String(out.explanation).trim();
    });
  }

  window.AIClient = {
    configured: READY,
    model: CFG.model || "",
    parseBrief: parseBrief,
    explain: explain
  };
})();
