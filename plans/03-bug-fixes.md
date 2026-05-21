# Plan: Bug 修复

> 目标：修复现有功能中已确认的 bug，确保核心流程（绘制 → 生成 → 预览）稳定可靠
> 按 Bug ID 排列，标注严重程度和修复难度

---

## BUG-01：流式响应数据丢失

**严重程度**：🔴 高（直接影响生成结果完整性）
**修复难度**：中

### 问题描述

涉及两端：

**服务端 `server.py:78-90`**：`_stream_response()` 用 `resp.readline()` 逐行读取。如果上游返回的最后一行没有以 `\n` 结尾，该行数据会丢失。

**前端 `sketch-to-ui.html:458-466`**：流式解析中，`buf` 保存未完成的行。循环结束后 `buf` 中可能还有未解析的数据（包含有效的 SSE 事件），但被直接丢弃。

### 修复方案

**server.py**：
```python
def _stream_response(self, resp):
    # ... headers ...
    remainder = b""
    while True:
        chunk = resp.read(4096)
        if not chunk:
            # 处理剩余数据
            if remainder:
                self.wfile.write(remainder)
                self.wfile.flush()
            break
        data = remainder + chunk
        # 按行分割，保留最后一个可能不完整的行
        lines = data.split(b"\n")
        remainder = lines[-1]
        for line in lines[:-1]:
            self.wfile.write(line + b"\n")
        self.wfile.flush()
```

**sketch-to-ui.html**：
```javascript
// while 循环结束后，处理 buf 中残余数据
if (buf.trim()) {
  for (const line of buf.split('\n')) {
    if (line.startsWith('data:')) {
      try {
        const j = JSON.parse(line.slice(6));
        if (j.type === 'content_block_delta' && j.delta?.text) {
          full += j.delta.text;
        }
      } catch(e) {}
    }
  }
}
```

### 涉及文件
- `server.py:78-90`
- `sketch-to-ui.html:458-466`

### 预估工时：30min

---

## BUG-02：安全超时后请求未取消

**严重程度**：🔴 高（超时后响应到达会导致状态混乱）
**修复难度**：低

### 问题描述

`beautify()` 中设了 60s 安全超时（`sketch-to-ui.html:411-415`），超时后重置 `generating=false` 和按钮状态。但 `fetch` 请求仍在进行中，如果后续收到响应：
1. `generating` 已是 false，但代码仍会执行 DOM 操作
2. 可能覆盖用户已经重新开始的操作
3. 两次响应交错导致预览区内容混乱

### 修复方案

使用 `AbortController` 取消请求：

```javascript
let abortCtrl = null;

// beautify() 中
abortCtrl = new AbortController();
const resp = await fetch(CONFIG.endpoint, {
  // ...
  signal: abortCtrl.signal,
});

// safety timeout 中
const safety = setTimeout(() => {
  if (abortCtrl) abortCtrl.abort();
  generating = false;
  // ... 重置 UI
}, 60000);

// catch 中区分 abort 和真实错误
catch (e) {
  if (e.name === 'AbortError') return; // 超时取消，不报错
  // ... 正常错误处理
}
```

### 涉及文件
- `sketch-to-ui.html:393-480`

### 预估工时：20min

---

## BUG-03：文字工具编辑状态残留

**严重程度**：🟡 中（影响工具切换后的键盘交互）
**修复难度**：低

### 问题描述

文字工具创建的 `Textbox` 设了 `editable:true`。用户输入文字后切换到其他工具（如矩形），Textbox 仍在编辑模式（光标闪烁）。此时按快捷键（如 R 切矩形）会被 Textbox 截获，变成输入文字而非切换工具。

### 修复方案

在 `setTool()` 中，切换工具前退出所有编辑状态：

```javascript
function setTool(t) {
  // 退出当前编辑中的文字对象
  if (canvas.getActiveObject()?.isEditing) {
    canvas.getActiveObject().exitEditing();
  }
  // ... 原有逻辑
}
```

同时在 `initKeyboard()` 中，检查 `isEditing` 时也应包含 Textbox 类型：

```javascript
if (canvas.getActiveObject()?.isEditing) return;
// 这行已有，但需确认 Textbox 也走这个分支（Textbox 的 isEditing 属性正常工作）
```

### 涉及文件
- `sketch-to-ui.html:218-228`（setTool 函数）

### 预估工时：10min

---

## BUG-04：橡皮擦与选择工具状态冲突

**严重程度**：🟡 中（偶发性的交互问题）
**修复难度**：低

### 问题描述

1. 用选择工具选中一个形状（出现选中框）
2. 切换到橡皮擦工具
3. 虽然所有对象 `evented:true`，但之前选中状态没有被清除
4. 可能导致点击时触发的是移动/缩放而非删除

### 修复方案

在 `setTool()` 开头始终清除选中状态：

```javascript
function setTool(t) {
  // 清除当前选中
  canvas.discardActiveObject();
  // ... 原有逻辑中已有这行，但位置在最后
  // 应该移到最前面，确保在任何模式切换前清除
}
```

当前代码 `sketch-to-ui.html:227` 行末已有 `canvas.discardActiveObject()`，但它在设置对象 selectable/evented 之后才执行。将其移到函数开头即可。

### 涉及文件
- `sketch-to-ui.html:218-228`（setTool 函数）

### 预估工时：5min

---

## BUG-05：HTML 提取正则匹配不完整

**严重程度**：🟡 中（AI 返回格式不标准时生成失败）
**修复难度**：低

### 问题描述

`sketch-to-ui.html:470-471` 中的 HTML 提取逻辑：

```javascript
const fm = html.match(/```html?\s*\n([\s\S]*?)```/);
if (fm) html = fm[1];
else {
  const dm = html.match(/(<!DOCTYPE html[\s\S]*)/i);
  if (dm) html = dm[1];
}
```

问题：
1. 如果 AI 返回 ` ```HTML `（大写）或 ` ```html\n ` 后无换行，第一个正则匹配失败
2. 第二个正则 `[\s\S]*` 是贪婪匹配但没有终止条件，可能匹配到 HTML 之后的思考过程文本
3. 如果 AI 不输出 `<!DOCTYPE` 但输出了完整的 `<html>` 标签，也匹配不到

### 修复方案

```javascript
// 更健壮的提取逻辑
function extractHTML(raw) {
  // 1. 尝试提取代码块（忽略大小写和空格变体）
  const codeBlock = raw.match(/```(?:html|HTML)\s*\n?([\s\S]*?)```/);
  if (codeBlock) return codeBlock[1].trim();

  // 2. 尝试匹配 DOCTYPE 到最后一个 </html>
  const doctypeMatch = raw.match(/(<!DOCTYPE\s+html[\s\S]*?<\/html\s*>)/i);
  if (doctypeMatch) return doctypeMatch[1];

  // 3. 尝试匹配 <html> 到 </html>
  const htmlMatch = raw.match(/(<html[\s\S]*?<\/html\s*>)/i);
  if (htmlMatch) return htmlMatch[1];

  // 4. 尝试匹配 <style> + <body> 组合（最小完整页面）
  if (raw.includes('<style') && raw.includes('<body')) {
    const start = raw.indexOf('<style');
    const end = raw.lastIndexOf('</body>');
    if (end > start) return raw.substring(start, end + 7);
  }

  // 5. 兜底返回原文
  return raw;
}
```

### 涉及文件
- `sketch-to-ui.html:470-471`

### 预估工时：20min

---

## BUG-06：窗口 resize 无防抖 + 画布内容丢失风险

**严重程度**：🟢 低（正常使用不常触发，但触发时体验差）
**修复难度**：低

### 问题描述

`sketch-to-ui.html:205`：resize 事件直接调用 `canvas.setDimensions()`，无防抖。快速拖拽窗口会频繁触发。

更关键的问题：`setDimensions` 只改变画布大小，不缩放对象。如果窗口变小，已画在右侧的形状可能超出可视区域；变大则形状挤在左上角。

### 修复方案

```javascript
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const w = document.getElementById('canvasWrap');
    canvas.setDimensions({ width: w.clientWidth, height: w.clientHeight });
    canvas.renderAll();
  }, 200);
});
```

注意：不自动缩放对象（这会破坏用户精心放置的位置），只防抖减少不必要的重绘。未来如果加入缩放功能，可以在此基础上提供"适应画布"按钮。

### 涉及文件
- `sketch-to-ui.html:205`

### 预估工时：10min

---

## BUG-07：server.py end_headers CORS 逻辑错误

**严重程度**：🟢 低（功能上不影响，但代码逻辑有误）
**修复难度**：低

### 问题描述

`server.py:100-102`：

```python
def end_headers(self):
    if not any(h[0].lower() == 'access-control-allow-origin' for h in self._headers_buffer if isinstance(h, tuple)):
        pass  # already set by caller
    super().end_headers()
```

这段代码的意图是"如果没设过 CORS header 就补一个"，但 `pass` 什么都不做。而每个响应方法（`_proxy_api`, `do_OPTIONS` 等）都已经手动设了 CORS header，所以这个检查实际上永远不会触发"补设"逻辑。

功能上无影响（因为 CORS 都已经手动设了），但代码具有误导性。

### 修复方案

两种选择：

**方案 A：删除此覆盖**（推荐）
既然每个方法都已经手动设了 CORS，这个 override 没有意义：

```python
# 删除整个 end_headers 覆盖方法
```

**方案 B：改为正确的兜底逻辑**
```python
def end_headers(self):
    if not any(h[0].lower() == 'access-control-allow-origin' for h in self._headers_buffer if isinstance(h, tuple)):
        self.send_header("Access-Control-Allow-Origin", "*")
    super().end_headers()
```

推荐方案 A，简单直接。

### 涉及文件
- `server.py:99-102`

### 预估工时：5min

---

## BUG-08：画笔路径对象被工具切换影响

**严重程度**：🟢 低（边缘情况）
**修复难度**：低

### 问题描述

`setTool()` 中切换工具时，对所有对象设置 `selectable` 和 `evented`：

```javascript
canvas.forEachObject(o => { o.selectable = false; o.evented = false })
```

这包括画笔绘制的 `path` 对象。但 `path` 对象（自由手绘线条）不应该被选择/事件化，它们只是装饰性的。在橡皮擦模式下设 `evented:true` 会导致用户误删手绘线条。

### 修复方案

在设置对象属性时，跳过 `path` 类型：

```javascript
// 橡皮擦模式
canvas.forEachObject(o => {
  if (o.type !== 'path') { o.selectable = false; o.evented = true; }
});

// 其他形状工具模式
canvas.forEachObject(o => {
  if (o.type !== 'path') { o.selectable = false; o.evented = false; }
});

// 选择模式
canvas.forEachObject(o => {
  if (o.type !== 'path') { o.selectable = true; o.evented = true; }
});
```

或者更简洁：在画笔绘制完成后立即将 path 对象标记为 `selectable: false, evented: false`，且后续 `forEachObject` 中统一跳过 `path`。

### 涉及文件
- `sketch-to-ui.html:222-226`（setTool 函数中的 forEachObject 调用）

### 预估工时：10min

---

## 修复总览

| Bug ID | 严重程度 | 修复难度 | 预估工时 |
|--------|---------|---------|---------|
| BUG-01 | 🔴 高 | 中 | 30min |
| BUG-02 | 🔴 高 | 低 | 20min |
| BUG-03 | 🟡 中 | 低 | 10min |
| BUG-04 | 🟡 中 | 低 | 5min |
| BUG-05 | 🟡 中 | 低 | 20min |
| BUG-06 | 🟢 低 | 低 | 10min |
| BUG-07 | 🟢 低 | 低 | 5min |
| BUG-08 | 🟢 低 | 低 | 10min |
| **合计** | | | **~1.8h** |

## 推荐修复顺序

1. **BUG-02**（超时未取消请求）→ 5min 改动，效果显著
2. **BUG-01**（流式数据丢失）→ 核心功能保障
3. **BUG-03**（文字编辑残留）→ 日常使用高频触发
4. **BUG-04**（橡皮擦状态冲突）→ 与 BUG-03 同一函数，一起改
5. **BUG-05**（HTML 提取）→ 提升生成成功率
6. **BUG-08**（画笔 path 对象）→ 与 BUG-03/04 同一函数，一起改
7. **BUG-06**（resize 防抖）→ 独立修改
8. **BUG-07**（server.py CORS）→ 独立修改

注：BUG-03、BUG-04、BUG-08 都修改 `setTool()` 函数，建议一次性修复。
