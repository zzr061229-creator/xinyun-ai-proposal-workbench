# DS Harness 启动说明

> 目标：让 DS Harness 在 `src/` 实现 P0，ZCode 继续负责浏览器取数。

## 1. API 配置（2026-11-21 已完成，无需再配）

已接入黑客松赞助的 B1X 中转站（专用余额 187.6388 元，限用 `deepseek-v4.1-flash-1017`，**2026/11/22 23:00（北京时间）到期**）：

- 密钥：`~/.dsh/.credentials.yaml` 的 `refs.B1X_API_KEY`（web / desktop 走 credentials 服务）+ `~/.dsh/.env` 的 `B1X_API_KEY`（headless 的 credentials 服务被禁用，只从启动环境解析）。
- 供应商：`~/.dsh/profiles/headless/cordis.patch.yml` 里 `llm-pi-ai` 的 `b1x` provider（OpenAI 协议，`https://token.b1x.work/v1`，`thinkingFormat: deepseek`）；desktop profile 早已配置；headless 默认模型已指向 `b1x / deepseek-v4.1-flash-1017`（reasoningEffort max）。

验证（应输出 `ok`）：

```bash
dsh headless "只回答：ok"
```

key 过期或轮换后：只需更新上面两个密钥文件里的值，配置层不用动。

---

## 2. 启动开发任务

```bash
cd C:\Users\zzr\Desktop\新云AI提案工作台
dsh headless "读 HANDOFF.md 和 docs/开发任务书.md，在 src/ 实现 P0。只改 src/；不要改 data/、tools/、materials/、config.local.json。直接用 data/app_data.json（含库存 431/861、15 个覆盖、6 份配置与 join 映射）；默认行业银行、品牌浦发、锚点陆家嘴，报价默认 1.0，92 折可切换；切医院时用美华，500 万切 hospital-network 三院区并集。预算滑块只改预算，不改周期。完成后用 python -m http.server 8788 自测，并给出验收清单。"
```

> `data/app_data.json` 已含：库存 431/861、15 个覆盖、6 份配置、5 个锚点 2023-05 人流（陆家嘴/人民广场/徐家汇/美华/迪士尼）与 5 份几何；五行业各一配置。无标签的站/线路显示“无数据”。

如果任务较长，建议后台跑：

```bash
dsh headless "..." > dsh_run.log 2>&1 &
```

---

## 3. 开发边界

| 角色 | 负责 | 不碰 |
|---|---|---|
| DS Harness | `src/`（index.html / styles.css / app.js / engine.js） | `data/`、`tools/`、`materials/`、`config.local.json` |
| ZCode | 红豆 API、覆盖分析、`data/` 快照、`tools/` | `src/` |
| 人类 | 定行业/预算、验收、路演 | — |

需要新数据时，DS Harness 在根目录写 `data_requests.json`（格式见 HANDOFF 第 8 节），由 ZCode 补。

---

## 4. 验收命令

```bash
cd C:\Users\zzr\Desktop\新云AI提案工作台
python -m http.server 8788
# 打开 http://127.0.0.1:8788/src/index.html
```

按 `docs/开发任务书.md` 第 4 节逐项验收。
