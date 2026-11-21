# Direction Approved — 新云 AI 提案工作台

## 最新选择（2026-11-21）

- **用户原话：`就B吧，然后我需要实际的地图而不是现在这个假定的`**
- 方向：**纯 B · FIELD DOSSIER / 作战手册**（不再使用 B+C 混合）。
- 地图：**真实 OpenStreetMap**；在线模式用 Leaflet + OSM 瓦片（可缩放/拖动），离线模式用 `build_maps.py` 生成的 z14 静态快照（自动 fallback / 导出内嵌）。
- 坐标系修正（2026-11-21）：覆盖平台返回 BD-09，OSM 是 WGS84；已在 `build_data.py` 做 BD-09 → WGS84，`build_maps.py` 用 WGS84 中心重建 bbox。验证：451 路人民广场(武胜路) 平台点转 WGS 后与 OSM 同名公交站误差 **11.5m**；此前直接叠会偏约 1km。
- 首屏截图：`src/design/design-demos/shots/b-1440.png`；放大到 16 级：`shots/b-zoom16.png`；离线快照：`shots/b-offline.png`。
- 销售视图：`shots/b-sales.png`；500 万：`shots/b-500.png`；手机：`shots/b-390.png`。

## 历史（已被最新选择覆盖）

- 2026-11-21 早先展示 A / B / C 三方向 + 六候选缩略图。
- 用户当时选择 `b和c`，已实现过一版 B+C 混合；现在按最新指令改为纯 B。
- A（Transit Control）与 C（Municipal Modern）初稿保留在 `design/design-demos/`，不删除。

## B 的视觉规则

- 白纸黑字、报头 / issue、12 栏编辑网格、3×3 数据格、报价收据、密排清单。
- 首屏 3 栏：brief 3/12、真实地图 6/12（560px）、数据+报价右轨 3/12；首屏地图完整可见（top 269 / bottom 829）。
- 宋体大标题 + 黄色马克笔高亮；红/蓝批注色只做信号；黄格只标一个关键数。
- 真实 OSM 底图做灰度处理；点位、覆盖圈、选中线叠加在真实地理上。
- 不使用 C 的竖排大标题、扇形几何、朱红通栏、巨型数字。

## 实施

- 正式工作台：`src/index.html` + `src/styles.css` + `src/app.js` + `src/engine.js` + `src/data.js` + `src/realmap.js` + `src/map-assets.js` + `src/assets/`。
- 地图构建：`src/build_maps.py`（一次性，只读覆盖 JSON，写 `src/assets/` 与 `src/map-assets.js`）。
- 设计体检：Python 版 Playwright 未安装，`design_lint.py check/compare` 跳过；截图与 DOM dump 用 Edge headless 完成（1440×900 / 390×844，14 行，无 NaN/undefined）。

## 备注

- 底图：© OpenStreetMap contributors（ODbL）；UI 与导出 HTML 均保留 attribution。
- 真实地图为静态快照，不依赖现场网络；锚点切换时换对应图片。
- 导出 HTML 会把当前底图以 data URI 内嵌（约 1.8–2.7MB），离线也能看到地图。
