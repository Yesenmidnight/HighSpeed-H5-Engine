# Plan: 增量生成 + 右键菜单

> 目标：支持在已生成的 HTML 上迭代修改，支持按组件定向修改，右键菜单快速操作形状
> 前提：bug 已全部修复（Plan 03 已完成）

---

## 一、交互流程总览

```
首次美化 ──→ HTML 带区域标记生成 ──→ 保存 lastGenState
                                          │
              ┌───────────────────────────┤
              │                           │
              ▼                           ▼
     右键某个形状                  点「迭代修改」按钮
     ┌─────────────┐              ┌──────────────────┐
     │ ✏️ 迭代修改   │              │ 修改范围：        │
     │ 🏷 编辑标签   │              │ ● 仅「导航栏」    │
     │ 📋 复制      │              │ ○ 整页           │
     │ 🗑 删除      │              │ 修改指令：___     │
     │ ─────────── │              └──────────────────┘
     │ 🔝 置顶层    │                     │
     │ 🔽 置底层    │                     ▼
     │ 🔒 锁定      │              定向/全量迭代生成
     └─────────────┘
              │
              ▼「迭代修改」
     自动定位该形状对应的 region
     弹出 Modal（范围已锁定为该组件）
              │
              ▼
     定向迭代生成
```

---

## 二、右键菜单设计

### 2.1 触发条件

| 条件 | 行为 |
|------|------|
| 右键点击形状（非 path 类型） | 弹出菜单，菜单定位在鼠标位置 |
| 右键点击空白画布 | 不弹菜单 |
| 右键点击自由绘制路径 | 不弹菜单（路径是标注，不是组件） |
| 没有生成过 HTML | 「迭代修改」项灰显 + tooltip "请先美化" |

### 2.2 菜单项

```
┌──────────────────────────────┐
│ ✏️  迭代修改该组件             │  ← 有生成结果时可用
│ 🏷  编辑标签        标签名 >  │  ← 子菜单或内联显示当前标签
│ 📋  复制                      │
│ 🗑  删除                      │
│ ───────────────────────────  │
│ 🔝  置顶层                    │
│ 🔽  置底层                    │
│ 🔒  锁定位置                  │  ← 防误拖，锁定后拖不动
└──────────────────────────────┘
```

每个菜单项说明：

| 菜单项 | 作用 | 实现 |
|--------|------|------|
| **迭代修改该组件** | 定位该形状对应的 region，弹出迭代 Modal，范围锁定为该组件 | 需要 region 映射 |
| **编辑标签** | 快速改标签，比双击更直觉 | 复用现有 `prompt()` 改标签逻辑 |
| **复制** | 克隆形状，偏移 20px 放在旁边 | `clone()` + 偏移 |
| **删除** | 删除该形状 | `canvas.remove()` |
| **置顶层/置底层** | 调整 z-index | `bringToFront()` / `sendToBack()` |
| **锁定位置** | 形状变半透明边框样式，不可拖动 | `lockMovementX/Y`, `selectable` 切换 |

### 2.3 视觉设计

```
右键菜单样式：
- 背景：var(--surface2) (#191930)
- 边框：var(--border) (#2a2a48)
- 圆角：8px
- 阴影：0 8px 24px rgba(0,0,0,.5)
- 每项高度：32px，padding 8px 14px
- hover：var(--surface) + accent 文字
- 灰显项：opacity .4, cursor not-allowed
```

菜单用自定义 `div` 定位在鼠标处，点击其他任意位置关闭。

---

## 三、区域标记系统

### 3.1 首次生成 Prompt 变更

在 `beautify()` 的 textPrompt 末尾追加：

```
9. 每个布局区域必须用 <section> 标签包裹，格式为：
   <section id="region-N" data-label="标签名">
   N 从 1 开始，按页面从上到下、从左到右的顺序编号
```

### 3.2 生成后的映射构建

生成完成后，解析 HTML 提取 region 映射：

```js
// lastGenRegions 示例:
// [
//   { id: 'region-1', label: '导航栏',   shapeIdx: 3 },
//   { id: 'region-2', label: '英雄区域', shapeIdx: 1 },
//   { id: 'region-3', label: '卡片',     shapeIdx: 0 },
// ]
```

映射逻辑：**按标签名匹配**。遍历画布形状（按 analyzeLayout 的排序），与 HTML 中的 data-label 一一对应。形状排序顺序和 region 编号顺序一致（都是上到下、左到右）。

### 3.3 新增状态变量

```js
let lastGenHTML = '';           // 上次生成的完整 HTML
let lastGenLayout = null;       // 上次的 analyzeLayout() 结果
let lastGenRegions = [];        // region 映射表
```

---

## 四、迭代修改 Modal

### 4.1 从右键菜单触发

右键点击形状 → 选「迭代修改该组件」→ 打开 Modal：

```
┌─────────────────────────────────────┐
│  迭代修改                            │
│                                     │
│  修改范围：  ████ 「导航栏」 ████     │  ← 范围锁定，不可切换
│                                     │
│  修改指令：                          │
│  ┌─────────────────────────────────┐│
│  │                                 ││
│  │  (textarea, 3行)                ││
│  │                                 ││
│  └─────────────────────────────────┘│
│                                     │
│           [取消]  [应用修改]         │
└─────────────────────────────────────┘
```

### 4.2 从顶栏按钮触发

点击顶栏「迭代修改」按钮 → 打开 Modal：

```
┌─────────────────────────────────────┐
│  迭代修改                            │
│                                     │
│  修改范围：                          │
│   ● 仅修改「导航栏」                 │  ← 如果画布上有选中形状，默认选中它
│   ● 仅修改「英雄区域」               │
│   ● 仅修改「卡片」                   │
│   ○ 修改整个页面                     │
│                                     │
│  修改指令：                          │
│  ┌─────────────────────────────────┐│
│  │                                 ││
│  │  (textarea, 3行)                ││
│  │                                 ││
│  └─────────────────────────────────┘│
│                                     │
│           [取消]  [应用修改]         │
└─────────────────────────────────────┘
```

区别：从右键进入时范围锁定，从按钮进入时可以选择范围。

### 4.3 定向迭代的 Prompt

**仅修改某个 region 时**：

```
system: 你是专业前端设计师。用户会给你一个网页组件（一个 <section> 标签）
        和一个修改指令。请只修改该组件，保持其 HTML 结构完整性。
        只输出修改后的该 <section> 标签（包含其 id 和 data-label 属性）。

user:
  当前组件代码：
  <section id="region-1" data-label="导航栏">
    ...该 region 的 HTML...
  </section>

  用户修改指令：把导航栏改成深色背景，加上 logo
```

注意：**只发该 region 的 HTML**，不发整个页面。这样 AI 不可能改到其他部分。

**修改整个页面时**：

```
system: 你是专业前端设计师。用户会给你一个完整的 HTML 页面和一个修改指令。
        请在已有页面基础上进行修改，保持整体结构和风格不变。
        只输出修改后的完整 HTML。

user:
  当前页面代码：
  {lastGenHTML}

  用户修改指令：{instruction}

  更新后的布局结构（如有变化）：
  {newLayoutDesc}
```

---

## 五、核心工具函数

```js
function extractRegion(html, regionId) {
  // 用正则提取指定 region 的内容
  const regex = new RegExp(
    `<section\\s+id="${regionId}"[^>]*>[\\s\\S]*?</section>`, 'i'
  );
  const match = html.match(regex);
  return match ? match[0] : null;
}

function spliceRegion(html, regionId, newRegionHTML) {
  // 替换指定 region，其余内容一字不动
  const regex = new RegExp(
    `<section\\s+id="${regionId}"[^>]*>[\\s\\S]*?</section>`, 'i'
  );
  return html.replace(regex, newRegionHTML);
}
```

---

## 六、完整代码修改清单

| # | 位置 | 修改 |
|---|------|------|
| 1 | ~L192 全局变量 | 新增 `lastGenHTML`, `lastGenLayout`, `lastGenRegions`, `contextTarget` |
| 2 | `<style>` 区 | 新增右键菜单样式（`.ctx-menu`, `.ctx-item`, `.ctx-sep`, `.ctx-disabled`） |
| 3 | ~L119-123 header HTML | 「美化」按钮后加「迭代修改」按钮（默认隐藏） |
| 4 | ~L167 Modal HTML 后 | 新增 `iterateModal`（迭代输入 Modal） |
| 5 | body 末尾 | 新增 `ctxMenu` div（右键菜单容器） |
| 6 | `beautify()` textPrompt | 追加第 9 条区域标记规则 |
| 7 | `beautify()` 成功分支 | 保存 `lastGenHTML/Layout/Regions`，切换按钮文字，显示迭代按钮 |
| 8 | `initCanvas()` | 注册 `contextmenu` 事件 → `showContextMenu(e)` |
| 9 | 新函数 `showContextMenu(e)` | 检测是否点击形状，构建菜单项，定位显示 |
| 10 | 新函数 `hideContextMenu()` | 隐藏菜单，点击任意处触发 |
| 11 | 新函数 `ctxEditLabel()` | 菜单「编辑标签」→ prompt() 改标签 |
| 12 | 新函数 `ctxDuplicate()` | 菜单「复制」→ clone + 偏移 |
| 13 | 新函数 `ctxDelete()` | 菜单「删除」→ remove |
| 14 | 新函数 `ctxBringTop/Bottom()` | 菜单「置顶/置底」→ z-index 调整 |
| 15 | 新函数 `ctxToggleLock()` | 菜单「锁定」→ 切换 lockMovement + 视觉反馈 |
| 16 | 新函数 `ctxIterate()` | 菜单「迭代修改」→ 打开 Modal，范围锁定为该形状的 region |
| 17 | 新函数 `iterateBeautify()` | 迭代主函数：定向/全量 prompt 构建 → API → 流式 → spliceRegion |
| 18 | 新函数 `extractRegion()` | 提取指定 region HTML |
| 19 | 新函数 `spliceRegion()` | 替换指定 region HTML |
| 20 | 新函数 `buildRegionMap()` | 解析 HTML 构建 region → shape 映射 |
| 21 | `clearAll()` | 重置 `lastGenHTML/Regions`，恢复按钮状态 |
| 22 | `initToolbar()` | 迭代按钮 click → 打开 iterateModal（范围可选） |
| 23 | 全局 `click` 事件 | 点击非菜单区域时关闭右键菜单 |

---

## 七、不做的边界

- 不做版本历史 / undo 迭代
- 不做迭代 diff 可视化
- 不做画布形状与 HTML 的实时双向同步
- 右键菜单不做子菜单（标签编辑直接用 prompt 弹窗）
