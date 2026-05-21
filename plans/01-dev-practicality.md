# Plan: 实用性增强

> 目标：让工具从"能跑的原型"变成"日常可用的生产力工具"
> 优先级按 P0 → P3 排列，P0 为最高

---

## P0 — 多步撤销/重做

**问题**：目前 undo 只能删除最后一个对象，没有重做，且不可回溯。

**方案**：
1. 维护 `undoStack` 和 `redoStack` 数组
2. 每次画布变化（对象添加/删除/修改/移动）时，快照 canvas.toJSON() 推入 undoStack，清空 redoStack
3. Ctrl+Z 从 undoStack 弹出恢复，推入 redoStack；Ctrl+Shift/Y 从 redoStack 恢复
4. 限制栈深度 50 步，防止内存溢出

**涉及文件**：`sketch-to-ui.html`
- 新增 `saveSnapshot()`, `undoAction()`, `redoAction()` 函数
- 修改 `initCanvas()` 注册 `object:added`, `object:removed`, `object:modified` 事件
- 修改 `undo()` 函数，替换当前逻辑
- 修改 `initKeyboard()` 添加 Ctrl+Shift+Z / Ctrl+Y

**预估工时**：1h

---

## P0 — 导出 HTML 文件

**问题**：生成后只能复制代码，无法直接保存为文件。

**方案**：
1. 在"复制代码"按钮旁增加"下载"按钮
2. 点击后用 `Blob` + `URL.createObjectURL` + `<a download>` 触发下载
3. 文件名格式：`sketch-ui-{timestamp}.html`

**涉及文件**：`sketch-to-ui.html`
- 在 `preview-tabs` 区域添加下载按钮
- 添加 `downloadHTML()` 函数
- 美化完成后显示下载按钮

**预估工时**：20min

---

## P1 — 保存/加载草图

**问题**：关闭页面后画布内容丢失，无法恢复。

**方案**：
1. 点击"保存"时将 `canvas.toJSON()` 存入 localStorage，key 为 `s2u_sketch_{name}`
2. 支持命名保存多个草图
3. 提供"我的草图"面板，列出已保存的草图（名称 + 缩略图 + 时间）
4. 点击可加载恢复画布
5. 支持删除已保存草图

**涉及文件**：`sketch-to-ui.html`
- header 区域增加"保存"和"我的草图"按钮
- 新增保存/加载 Modal UI
- 新增 `saveSketch(name)`, `loadSketch(name)`, `listSketches()`, `deleteSketch(name)` 函数
- 用 canvas.toDataURL() 生成缩略图

**预估工时**：2h

---

## P1 — 选择工具下拖拽移动/调整大小

**问题**：当前选择工具切换后所有对象 `selectable:true`，但 Fabric 默认的控制点（缩放/旋转）小且不好用，且形状的 `_uiLabel` 在移动后不会重新计算。

**方案**：
1. 切换到选择工具时，开启对象的移动和缩放控制点
2. 对象移动或缩放结束后（`object:modified` 事件），重新调用 `autoLabel()` 更新标签
3. 禁用旋转控制（草图布局不需要旋转）

**涉及文件**：`sketch-to-ui.html`
- 修改 `setTool('select')` 分支，设置 `lockRotation: true`, 隐藏旋转控制点
- 在 `initCanvas()` 中注册 `object:modified` 事件，触发 `autoLabel()`

**预估工时**：30min

---

## P2 — 画布缩放/平移

**问题**：大型布局无法缩放查看细节或看全貌。

**方案**：
1. 添加缩放控件（+ / - 按钮 + 百分比显示）
2. 鼠标滚轮缩放（以鼠标位置为中心）
3. 中键/空格+拖拽平移画布
4. 缩放范围：25% — 400%
5. 双击缩放控件恢复 100%

**涉及文件**：`sketch-to-ui.html`
- 状态栏添加缩放控件
- 添加 `zoomIn()`, `zoomOut()`, `zoomReset()`, `panCanvas()` 函数
- 修改 `initCanvas()` 注册 `mouse:wheel` 事件
- 注意：缩放后坐标换算需正确处理 `canvas.getPointer()`

**预估工时**：1.5h

---

## P2 — 迭代修改（增量生成）

**问题**：每次美化都是全量重新生成，无法在当前结果上微调。

**方案**：
1. 首次美化正常生成
2. 生成后，"美化"按钮变为"重新生成"，同时新增"迭代修改"按钮
3. 点击"迭代修改"时，弹出输入框让用户描述要修改的内容
4. 将当前生成的 HTML + 用户修改指令 + 更新后的布局描述一起发送给 AI
5. AI 返回修改后的完整 HTML

**涉及文件**：`sketch-to-ui.html`
- 新增"迭代修改"按钮和输入 Modal
- 保存当前生成的 HTML 到变量 `lastGeneratedHTML`
- 修改 `beautify()` 或新增 `iterateBeautify()` 函数
- prompt 中增加"当前 HTML"和"修改指令"部分

**预估工时**：2h

---

## P3 — 更多形状（线条、箭头）

**问题**：缺少线条、箭头等常用布局元素。

**方案**：
1. 工具栏添加"线条"和"箭头"工具
2. 线条用 `fabric.Line`，箭头用 `fabric.Line` + 自定义箭头三角形
3. 自动标签识别：线条/箭头标记为"分隔线"或"指示箭头"
4. 快捷键：L = 线条，A = 箭头

**涉及文件**：`sketch-to-ui.html`
- header 添加工具按钮
- `onDown/onMove/onUp` 中添加线条/箭头绘制逻辑
- `autoLabel()` 中添加线条/箭头类型识别
- `initKeyboard()` 添加快捷键

**预估工时**：1h

---

## P3 — 图层管理面板

**问题**：无法查看和调整形状的上下层级。

**方案**：
1. 左侧画布下方或右侧面板添加可折叠的图层面板
2. 列出所有形状（按 z-index 从上到下），显示类型图标 + 标签名
3. 支持拖拽排序调整层级
4. 点击图层项高亮对应形状
5. 每个图层项有可见性切换（眼睛图标）和删除按钮

**涉及文件**：`sketch-to-ui.html`
- 新增图层面板 UI
- 新增 `renderLayerPanel()` 函数
- 在 `object:added/removed/modified` 后刷新面板

**预估工时**：2.5h

---

## 总预估

| 优先级 | 工时 |
|--------|------|
| P0     | ~1.3h |
| P1     | ~2.5h |
| P2     | ~3.5h |
| P3     | ~3.5h |
| **合计** | **~10.8h** |
