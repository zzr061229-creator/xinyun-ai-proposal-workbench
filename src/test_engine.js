#!/usr/bin/env node
/* Self-test for src/engine.js against the generated src/data.js. Run: node src/test_engine.js */
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = __dirname;
const ctx = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(SRC, "data.js"), "utf8"), ctx, { filename: "data.js" });
const data = ctx.window.APP_DATA;
const Engine = require(path.join(SRC, "engine.js"));

let failures = 0;
let checks = 0;
function assert(cond, msg) {
  checks += 1;
  if (!cond) { failures += 1; console.log("  FAIL " + msg); }
}
const sum = (items, fn) => items.reduce((s, it) => s + fn(it), 0);
const wan = (n) => (n / 10000).toFixed(1);

// Generic invariants for every plan.
function invariants(label, brief, plan) {
  const items = plan.items;
  const bus = items.filter((x) => x.media === "bus");
  const metro = items.filter((x) => x.media === "metro");
  assert(plan.quote.net <= brief.budget + 1, `${label}: net ${plan.quote.net} <= budget ${brief.budget}`);
  assert(plan.quote.media === sum(items, (x) => x.listSubtotal), `${label}: quote.media == Σ row listSubtotal`);
  assert(plan.quote.production === sum(items, (x) => x.production), `${label}: quote.production == Σ row production`);
  assert(plan.quote.net === sum(items, (x) => x.net) + plan.quote.monitoring, `${label}: 行净价和 == 总净价`);
  assert(new Set(bus.map((x) => x.line)).size === bus.length, `${label}: no duplicate bus line`);
  assert(new Set(metro.map((x) => x.id)).size === metro.length, `${label}: no duplicate metro exit`);
  const st = {};
  metro.forEach((x) => { st[x.station] = (st[x.station] || 0) + x.qty; });
  Object.keys(st).forEach((s) => assert(st[s] <= 2, `${label}: 同站 ${s} <= 2 口 (got ${st[s]})`));
  items.forEach((x) => assert(x.qty <= x.free, `${label}: ${x.name} qty ${x.qty} <= free ${x.free}`));
  items.forEach((x) => assert(x.dailyReach === null || (typeof x.dailyReach === "number" && x.dailyReach > 0),
    `${label}: ${x.name} dailyReach is null or > 0 (got ${x.dailyReach})`));
  assert(Math.abs(plan.quote.discountRate - (brief.discount == null ? 1 : brief.discount)) < 1e-9, `${label}: discountRate follows brief`);
  assert(Number.isFinite(plan.summary.reach) && Number.isFinite(plan.summary.reachDaily), `${label}: reach is finite`);
  if (brief.media.metro === false) assert(metro.length === 0, `${label}: bus-only → metro 0`);
  if (brief.media.bus === false) assert(bus.length === 0, `${label}: metro-only → bus 0`);
}

function run(label, brief, extra, quiet) {
  const plan = Engine.selectPlan(data, brief);
  const s = plan.summary;
  if (!quiet) {
    console.log(`${label}: ${s.metroCount} 口 + ${s.busCount} 辆 (${plan.items.length} 行) 净价 ${wan(plan.quote.net)} 万 余额 ${wan(plan.quote.remaining)} 万 · 触达 ${s.reachLabel} 日均 ${wan(s.reachDaily || 0)} 万`);
  }
  invariants(label, brief, plan);
  if (extra) extra(plan);
  return plan;
}

const B = (anchor, radius, wanBudget, weeks, media, discount) => ({
  anchor, radius, budget: wanBudget * 10000, weeks,
  media: media === "bus" ? { bus: true, metro: false } : media === "metro" ? { bus: false, metro: true } : { bus: true, metro: true },
  discount: discount == null ? 1 : discount, startDate: "2027-04-01"
});

// ---------------------------------------------------------------- data shape
console.log("== data ==");
const lj = data.coverage["陆家嘴金融城"] && data.coverage["陆家嘴金融城"]["3000"];
assert(!!lj, "陆家嘴金融城 3km coverage exists");
if (lj) {
  const nb = lj.list.filter((r) => r.mediaType === "bus").length;
  assert(lj.list.length === 87 && nb === 76, `陆家嘴 3km = 87 (76/11), got ${lj.list.length} (${nb}/${lj.list.length - nb})`);
}
assert(data.meta.join.busMatched === 152 && data.meta.join.busNames === 156, "bus join 152/156");
assert(data.meta.join.stationsInInventory === 24 && data.meta.join.stations === 31, "metro join 24/31");
assert((data.industries || []).length === 5, "5 industries");
assert(data.defaultIndustryId === "bank-insurance", "default industry = bank-insurance");
const bank = data.industries.find((x) => x.id === "bank-insurance");
assert(bank && bank.brand === "浦发银行" && bank.anchor === "浦发银行上海分行", "bank = 浦发银行 / 上海分行");
assert(Engine.PRICING.discount === 1 || (Engine.configurePricing(data), Engine.PRICING.discount === 1), "default discount 1.0");

// ------------------------------------------- 5 industries × 100/200/500 × 4/6
console.log("\n== 五行业默认锚点 × 100/200/500 万 × 4/6 周（折扣 1.0）==");
for (const ind of data.industries) {
  const radius = ind.radii.indexOf(3000) >= 0 ? 3000 : ind.radii[0];
  for (const budget of [100, 200, 500]) {
    for (const weeks of [4, 6]) {
      const label = `${ind.key} ${ind.anchor} ${radius / 1000}km ${budget}万/${weeks}周`;
      run(label, B(ind.anchor, radius, budget, weeks), (plan) => {
        assert(plan.items.length > 0, `${label}: has items`);
        const cand = Engine.buildCandidates(data, { anchor: ind.anchor, radius });
        if (!cand.metro.length) {
          // 迪士尼：红豆无迪士尼站地铁口 → 合理降级为全公交 + warning
          assert(plan.summary.metroCount === 0, `${label}: no metro stock → 0 口`);
          assert(plan.warnings.some((w) => /没有红豆可售地铁口/.test(w)), `${label}: degrade warning present`);
        } else {
          assert(plan.summary.metroCount >= 1, `${label}: has metro`);
        }
        const expectSource = data.footfall[ind.anchor] ? "platform" : "sample";
        assert(plan.summary.reachSource === expectSource, `${label}: reachSource ${plan.summary.reachSource} == ${expectSource}`);
      }, budget !== 200 || weeks !== 6);
    }
  }
}

// ------------------------------------------------------- park citywide
console.log("\n== 乐园全城铺送（4 枢纽 + 24 站在库）==");
{
  const parkBrief = (budget, weeks) => ({
    industryId: "theme-park", anchor: "上海迪士尼度假区", radius: 5000,
    budget: budget * 10000, weeks, media: { bus: true, metro: true }, startDate: "2027-07-01"
  });
  const p500 = Engine.selectPlan(data, parkBrief(500, 6));
  console.log(`park citywide 500万/6周: ${p500.summary.metroCount} 口 / ${p500.summary.metroStations} 站 / ${p500.summary.metroDistricts} 区 + ${p500.summary.busCount} 辆，净价 ${wan(p500.quote.net)} 万`);
  assert(p500.summary.citywide === true, "park 500: citywide flag");
  assert(p500.summary.metroCount >= 4, `park 500: metro exits >= 4 (got ${p500.summary.metroCount})`);
  assert(p500.summary.metroStations >= 4, `park 500: metro stations >= 4 (got ${p500.summary.metroStations})`);
  assert(p500.summary.metroDistricts >= 3, `park 500: metro districts >= 3 (got ${p500.summary.metroDistricts})`);
  assert(p500.summary.busCount > 0, "park 500: bus > 0");
  assert(!p500.warnings.some((w) => /只地铁不可行|没有红豆可售地铁口/.test(w)), "park 500: no metro-infeasible warning");
  p500.items.filter((x) => x.media === "metro").forEach((x) => {
    assert(!!x.district, `park 500: metro ${x.station} has district`);
  });
  [100, 200].forEach((b) => {
    const p = Engine.selectPlan(data, parkBrief(b, b === 100 ? 4 : 6));
    assert(p.summary.metroCount >= 1, `park ${b}: metro >= 1 (got ${p.summary.metroCount})`);
    assert(p.summary.busCount >= 1, `park ${b}: bus >= 1`);
    assert(p.quote.net <= b * 10000 + 1, `park ${b}: within budget`);
  });
}

// ------------------------------------------------------- only-metro / only-bus
console.log("\n== 只地铁 / 只公交（200 万 / 6 周）==");
for (const ind of data.industries) {
  const radius = ind.radii.indexOf(3000) >= 0 ? 3000 : ind.radii[0];
  run(`${ind.key} 只公交`, B(ind.anchor, radius, 200, 6, "bus"), (plan) => {
    assert(plan.summary.busCount > 0 && plan.summary.metroCount === 0, `${ind.key} 只公交: bus > 0, metro 0`);
  });
  run(`${ind.key} 只地铁`, B(ind.anchor, radius, 200, 6, "metro"), (plan) => {
    const cand = Engine.buildCandidates(data, { anchor: ind.anchor, radius });
    if (cand.metro.length) {
      assert(plan.summary.metroCount > 0 && plan.summary.busCount === 0, `${ind.key} 只地铁: metro > 0, bus 0`);
    } else {
      assert(plan.items.length === 0, `${ind.key} 只地铁: no metro stock → empty plan`);
      assert(plan.warnings.some((w) => /只地铁不可行/.test(w)), `${ind.key} 只地铁: infeasible warning present`);
    }
  });
}

// ------------------------------------------------------------ discount 1.0/0.92
console.log("\n== 陆家嘴 折扣 1.0 vs 0.92 ==");
for (const [budget, weeks] of [[100, 4], [200, 6], [500, 6], [500, 12]]) {
  const a = run(`陆家嘴 ${budget}万/${weeks}周 1.0 `, B("陆家嘴金融城", 3000, budget, weeks, "both", 1));
  const b = run(`陆家嘴 ${budget}万/${weeks}周 0.92`, B("陆家嘴金融城", 3000, budget, weeks, "both", 0.92));
  assert(a.quote.discountAmount === 0, `${budget}/${weeks} 1.0: no discount amount`);
  assert(b.quote.discountAmount > 0, `${budget}/${weeks} 0.92: discount amount > 0`);
  b.items.forEach((it) => assert(it.net === Math.round((it.listSubtotal + it.production) * 0.92) ||
    Math.abs(it.net - (it.listSubtotal + it.production) * 0.92) <= 1, `0.92 row ${it.name} net = (刊例+制作)×0.92`));
  // 0.92 may swap buses for an extra exit, so compare list value bought, not headcount.
  assert(b.quote.media + b.quote.production >= a.quote.media + a.quote.production,
    `${budget}/${weeks}: 0.92 buys >= 1.0 list value`);
}

// ---------------------------------------------------- reach: metro not additive
console.log("\n== 触达口径 ==");
{
  const ff = data.footfall["陆家嘴金融城"];
  assert(!!ff, "陆家嘴 has platform footfall");
  const cand = Engine.buildCandidates(data, { anchor: "陆家嘴金融城", radius: 3000 });
  // two exits of 陆家嘴站 with platform reach
  const two = cand.metro.filter((c) => c.station === "陆家嘴" && c.dailyReach != null).slice(0, 2);
  assert(two.length === 2, "陆家嘴站 has 2 sellable exits with reach");
  if (two.length === 2) {
    const items = two.map((c) => Object.assign({}, c, { qty: 1 }));
    const r = Engine.reachOf(data, "陆家嘴金融城", items, 42);
    const naive = two[0].dailyReach + two[1].dailyReach;
    const agg = ff.stations["陆家嘴"].aggregateReach;
    const expect = Math.max(agg, two[0].dailyReach, two[1].dailyReach);
    console.log(`  陆家嘴站 ${two[0].exit}+${two[1].exit}: 单口 ${two[0].dailyReach}+${two[1].dailyReach}=${naive}（不能相加）→ 计 ${r.metroDaily}（aggregate ${agg}）`);
    assert(r.metroDaily === expect, `同站两口触达 = max(aggregateReach, 最大单口) = ${expect} (got ${r.metroDaily})`);
    assert(r.metroDaily < naive, "同站两口触达 < 两口相加");
    const one = Engine.reachOf(data, "陆家嘴金融城", [items[0]], 42);
    assert(one.metroDaily === two[0].dailyReach, "单口触达 = 该口 dailyReach");
  }
  // missing platform label → null, not 0
  const noLabel = cand.metro.find((c) => c.station === "豫园" && /3A/.test(c.exit));
  if (noLabel) assert(noLabel.dailyReach === null, "豫园 3A 号口无平台标签 → dailyReach null");
  const allMetroNullOrPos = cand.metro.every((c) => c.dailyReach === null || c.dailyReach > 0);
  assert(allMetroNullOrPos, "陆家嘴地铁候选 dailyReach 为 null 或正数，无 0");
  assert(cand.bus.every((c) => c.dailyReach === null || c.dailyReach > 0), "陆家嘴公交候选 dailyReach 为 null 或正数");
  assert(cand.bus.filter((c) => c.dailyReach != null).length >= 60, "陆家嘴公交候选大多有平台触达");
  // non-platform anchor: metro null, bus sample estimate
  const mh = Engine.buildCandidates(data, { anchor: "上海美华妇儿医院", radius: 3000 });
  assert(mh.metro.every((c) => c.dailyReach != null ? c.reachSource === "platform" : c.reachSource === "none"), "美华 地铁触达：有平台数据用平台，无标签标 none");
  assert(mh.bus.some((c) => c.dailyReach != null && c.reachSource === "platform"), "美华 公交有平台 2023-05 触达");
  assert(mh.bus.every((c) => c.dailyReach != null || c.reachSource === "none"), "美华 公交无平台数据时不伪造估算");
  // plan-level: platform plan with ≥2 exits at one station is not a naive sum
  const big = Engine.selectPlan(data, B("陆家嘴金融城", 3000, 500, 6));
  const naiveMetro = sum(big.items.filter((x) => x.media === "metro" && x.dailyReach != null), (x) => x.dailyReach);
  const multi = (big.summary.reachInfo.stations || []).some((s) => s.exits >= 2);
  console.log(`  陆家嘴 500万/6周：地铁站 ${JSON.stringify(big.summary.reachInfo.stations)}；逐口相加 ${naiveMetro} → 计 ${big.summary.reachInfo.metroDaily}`);
  if (multi) assert(big.summary.reachInfo.metroDaily !== naiveMetro || naiveMetro === 0, "500 万方案地铁触达不是逐口相加");
  assert(big.summary.reachLabel === "平台 2023-05", "陆家嘴 reachLabel = 平台 2023-05");
}

console.log("== anchor bundles / 多网点 ==");
{
  const bank = data.industries.find((x) => x.id === "bank-insurance");
  const food = data.industries.find((x) => x.id === "food-beverage");
  assert(!!bank.anchorBundle && bank.anchorBundle.members.length === 3, "bank has 3-node anchor bundle");
  assert(!!food.anchorBundle && food.anchorBundle.members.length === 3, "food has 3-node anchor bundle");
  assert(Engine.anchorsOf(data, { industryId: "bank-insurance", anchor: bank.anchor, radius: 1000 }).length === 3,
    "anchorsOf resolves 3 bank branches");
  assert(bank.anchorBundle.members.every((m) => /^浦发银行/.test(m.anchor)), "bank members are real SPDB branches");

  const bc = Engine.buildCandidates(data, { industryId: "bank-insurance", anchor: bank.anchor, radius: 1000 });
  assert(bc.anchorCount === 3, `bank candidates cover 3 nodes (got ${bc.anchorCount})`);
  assert(bc.stats.coverageTotal === 97, `bank 3×1km coverage = 97 (got ${bc.stats.coverageTotal})`);
  const seen = new Set();
  bc.bus.concat(bc.metro).forEach((c) => (c.anchors || []).forEach((a) => seen.add(a)));
  ["浦发银行上海分行", "浦发银行九江路支行", "浦发银行徐家汇支行"].forEach((a) => assert(seen.has(a), `bank candidates include ${a}`));
  assert(bc.bus.every((c) => c.localRadius === 1000 && c.reachAnchor), "bank bus candidates carry local radius + reach anchor");
  assert(new Set(bc.bus.map((c) => c.line)).size === bc.bus.length, "bank candidates dedupe bus lines across nodes");

  for (const budget of [100, 200, 500]) {
    const plan = run(`bank 网点 ${budget}万/6周`, {
      industryId: "bank-insurance", anchor: bank.anchor, radius: 1000,
      budget: budget * 10000, weeks: 6, media: { bus: true, metro: true }, startDate: "2027-01-04"
    }, null, true);
    assert(plan.summary.anchorCount === 3, `bank ${budget}万 summary.anchorCount = 3`);
    assert(plan.summary.reachInfo.source === "platform", `bank ${budget}万 reach source = platform`);
    const selectedNodes = new Set();
    plan.items.forEach((it) => (it.anchors || []).forEach((a) => selectedNodes.add(a)));
    if (budget === 100) assert(selectedNodes.size >= 2, `bank 100万 selects at least 2 branches (got ${selectedNodes.size})`);
    else assert(selectedNodes.size === 3, `bank ${budget}万 selects all 3 branches (got ${selectedNodes.size})`);
    plan.items.forEach((it) => assert(it.anchors && it.anchors.length >= 1, `bank ${budget}万 item has anchors`));
    plan.items.forEach((it) => assert(it.anchorLabel, `bank ${budget}万 item has anchorLabel: ${it.name}`));
  }

  const foodPlan = run("food 门店 200万/6周", {
    industryId: "food-beverage", anchor: food.anchor, radius: 1000,
    budget: 2000000, weeks: 6, media: { bus: true, metro: true }, startDate: "2027-07-01"
  }, null, true);
  assert(foodPlan.summary.anchorCount === 3, "food 200万 summary.anchorCount = 3");
  const foodNodes = new Set();
  foodPlan.items.forEach((it) => (it.anchors || []).forEach((a) => foodNodes.add(a)));
  assert(foodNodes.size === 3, `food 200万 selects all 3 stores (got ${foodNodes.size})`);
  assert(foodPlan.items.every((it) => it.reachAnchor), "food item carries reachAnchor");
}

console.log(`\n${checks} checks · ` + (failures ? `FAILURES: ${failures}` : "ALL PASS"));
if (failures) process.exit(1);
