# brief 解析怎么用、怎么接 AI

> 入口：ATLAS 首屏「一句话」输入框。
> 代码：`src/brief.js`（解析 + 应用）；可选代理 `tools/brief_proxy.py`（在线大模型）。

---

## 0. 当前接入：组委会模型（2026-11-22）

本机已接入 B1X 发放的比赛模型，AI 解析与 AI 解释都走它：

| 项 | 值 |
|---|---|
| 模型 | `deepseek-v4.1-flash-1017` |
| OpenAI 兼容地址 | `https://token.b1x.work/v1` |
| 密钥 | 在 `config.local.json` 的 `ai.apiKey`（已 gitignore，不提交） |
| 额度 | 比赛专用余额，到期 2026-11-22 23:00（北京时间） |

启动（端口 8791 在本机可用；8790 被系统占用）：

```bash
python -I tools/brief_proxy.py --port 8791
```

或双击 `tools/start_ai_demo.bat`：会同时起代理、静态服务（8788）并打开带 `?ai=1` 的页面。

打开：

```text
http://127.0.0.1:8788/src/index-atlas.html?ai=1
```

首屏应显示「AI 模式已配置（组委会模型）」；输入一句话点「解析」，或点「生成解释」，结果会标注「AI 解析（组委会模型）」/「AI 生成（组委会模型）」。

注意：

- 密钥只在本地代理里，不进前端、不进 Git；`config.local.json` 不要提交。
- 线上 Pages 是静态站，没有代理；不加 `?ai=1` 或换别人的机器时，自动回退规则解析/模板解释，页面不会坏。
- 比赛密钥到期后 AI 自动不可用，仍可用规则解析与模板解释。
- 模型是 reasoning 模型，会先输出 `reasoning_content`；代理已把 `max_tokens` 调高并做一次重试，正常 2–15 秒。

---

## 1. 现在能做什么

在 ATLAS 首屏输入一句中文，例如：

- `银行 200 万，2027 开门红，陆家嘴 3km，地铁为主`
- `医院 200 万 Q1 地铁`
- `乐园 500 万 暑期 公交+地铁`
- `保健品 100 万 中秋 公交车身`
- `食品 200 万 7月 公交+地铁`

点「解析」后，会自动填上方的行业、预算、档期、媒体、半径、折扣，并立即重算方案。

解析结果会显示一行，例如：

> 规则解析（离线）：私立医院 · 200 万 · 开门红 · 地铁。数字由引擎重算，AI 不改数。

**边界**：解析器只负责“把话翻译成参数”，不产生价格、库存、触达数字；这些仍由 `engine.js` 按规则算。所以即使 AI 解析错了，也不会改错钱。

---

## 2. 两种模式

| 模式 | 触发条件 | 说明 |
|---|---|---|
| 规则解析（离线） | 默认 | 关键词 + 正则，永远可用；不依赖网络 |
| AI 解析（在线） | `brief.js` 的 `data-ai` 指向代理 | 大模型把自由文本映射成同一组参数；失败/超时自动回退规则解析 |

界面上会标明是「AI 解析」还是「规则解析（离线）」，不冒充。

---

## 3. 接在线大模型（可选）

> 当前机器状态：已按第 0 节接入组委会模型；`config.local.json` 的 `ai` 指向 `https://token.b1x.work/v1`，密钥不入 Git。代理未启动时仍走规则/模板。

### 3.1 配置 key（不进 Git）

`config.local.json` 已 gitignore。加一段：

```json
{
  "ai": {
    "baseUrl": "https://token.b1x.work/v1",
    "apiKey": "sk-你的比赛密钥",
    "model": "deepseek-v4.1-flash-1017"
  }
}
```

任何 OpenAI 兼容的 `/chat/completions` 都可以（DeepSeek、Kimi、GLM、OpenAI 等）。

### 3.2 启动本地代理

```bash
python -I tools/brief_proxy.py --port 8791
```

健康检查：

```bash
curl http://127.0.0.1:8791/health
# {"ok": true, "configured": true}
```

### 3.3 让页面走 AI

把 `src/index-atlas.html` 里的：

```html
<script src="brief.js?v=20261121a" data-ai=""></script>
```

改成：

```html
<script src="brief.js?v=20261121a" data-ai="http://127.0.0.1:8791/api/parse-brief"></script>
```

刷新页面，输入框下方会提示「AI 模式已配置」。没启动代理或没配 key 时，会自动回退规则解析，演示不会断。

也可以不改文件，直接打开 `index-atlas.html?ai=1`，默认连 `http://127.0.0.1:8791/api/parse-brief`。

> 端口 8790 在本机可能被占用；示例用 8791。

---

## 4. 解析字段（只允许这些）

| 字段 | 允许值 |
|---|---|
| `industryId` | `bank-insurance` / `private-hospital` / `food-beverage` / `health-supplement` / `theme-park` |
| `budget` | 元，100 万–500 万（步长 10 万） |
| `weeks` | `4` / `6` |
| `windowId` | `kaimenhong` / `q2` / `summer` / `midautumn` |
| `media` | `bus` / `metro` / `both` |
| `radius` | `1000` / `3000` / `5000` |
| `discount` | `1` / `0.92` |

`brief.js` 的 `normalizeBrief()` 会丢弃越界/不认识的字段；`applyBrief()` 只应用产品支持的字段。所以模型返回多余字段不会把页面搞崩。

---

## 5. 本地规则怎么认

| 参数 | 关键词/格式 |
|---|---|
| 行业 | 银行/保险/理财/开户；医院/妇产/儿科/体检；饮料/饮用水/食品；保健/营养/汤臣倍健；乐园/迪士尼/主题公园 |
| 预算 | `200万`、`两百万`、`预算 200`（按万） |
| 档期 | 开门红/春节/Q1；Q2/春季/4-5月；暑期/7-8月；中秋/国庆/9-10月 |
| 媒体 | 公交/车身；地铁/出入口；同时出现 = 组合 |
| 半径 | `1km` / `3km` / `5km`、`1公里` |
| 折扣 | `92折` / `0.92` / `九二折`；`刊例` / `1.0` |

规则解析是“宁缺勿错”：没识别到的字段不填，保持当前值。

---

## 6. 自测

浏览器控制台：

```js
BriefParser.parseLocal("医院 200 万 Q1 地铁")
// { industryId: "private-hospital", budget: 2000000, windowId: "kaimenhong", media: "metro" }
```

页面操作：

1. 输入 `医院 200 万 Q1 地铁` → 私立医院 / 200 万 / 开门红 / 只地铁。
2. 输入 `乐园 500 万 暑期 公交+地铁` → 乐园 / 500 万 / 暑期 / 公交+地铁（自动切全城 4 枢纽 + 24 个在库站；迪士尼站本身仍无地铁口）。
3. 输入 `保健品 100 万 中秋 公交车身` → 保健品 / 100 万 / 中秋国庆 / 只公交。
4. 停掉代理再点解析 → 提示「AI 不可用，规则解析」，结果仍然正确。

---

## 7. 为什么不让 AI 直接算钱

评分文件要求“AI 承担调研、组合决策、生成、校验”，但也要求“数字有依据、现场能复算”。我们的分工：

- AI：把自然语言翻译成参数、生成解释、合规初筛（表达层）。
- 规则引擎：选点、报价、库存校验、排期（数字层）。
- 每个 AI 输出都要经过 `normalizeBrief()` 的允许值校验；数字由引擎重新算。

这样既能讲“AI 在工作流里”，又不会出现“AI 编了一个触达数/价格”的硬伤。

---

## 8. AI 解释（WHY）

ATLAS 答案下方有一块「AI 解释 / WHY」。点「生成解释」，会做两件事：

1. 把当前方案压成一个小 JSON：行业、品牌、预算、档期、锚点、半径、地铁口/公交数量、覆盖/可售数、前 12 条选中媒体及引擎给的理由、警告。
2. POST 到 `http://127.0.0.1:8791/api/explain`，让 DeepSeek 写 120–180 字解释：为什么这个锚点、为什么地铁/公交这个主次、为什么是这些线/口。

边界：
- 提示词明确要求“不写金额、触达人次或新数字”；页面上的数字仍以引擎为准。
- 没配 AI / 代理挂了 → 用本地模板解释，按钮仍可用。
- 解释只讲取舍，不改 `state.plan`，不会影响报价。

代理新增路由：

```text
POST /api/parse-brief   {text}  → {brief:{...}}
POST /api/explain       {plan}  → {explanation:"..."}
```

页面开关：

- `?ai=1`：解析和解释都连 `127.0.0.1:8791`。
- 或分别改 `brief.js` / `ai-explain.js` 的 `data-ai`。
- 也可以只开其中一个：只配解析、不配解释，解释会走模板。

### 组委会模型配置（当前）

`config.local.json` 已配置（密钥不入 Git）：

```json
"ai": {
  "baseUrl": "https://token.b1x.work/v1",
  "apiKey": "sk-你的比赛密钥",
  "model": "deepseek-v4.1-flash-1017"
}
```

密钥到期后（2026-11-22 23:00）AI 自动不可用，回退规则/模板。也支持环境变量（不用改文件）：

```bash
export DEEPSEEK_API_KEY=sk-...
python -I tools/brief_proxy.py --port 8791
```

如果你本机已有 `~/.codex/deepseek-gateway` 的 LiteLLM 网关（`http://127.0.0.1:4111/v1`，模型 `deepseek-v4-flash`），设置 `CODEX_DEEPSEEK_GATEWAY_KEY` 后代理会自动用它；但该网关本身仍需要 `DEEPSEEK_API_KEY` 才能转发。
