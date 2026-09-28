---
name: tencent-ima-wiki
description: "获取腾讯 ima 知识库（ima.qq.com/wikis）中的文章列表和原始文章详情。适用于：(1) 用户已经登录 ima 知识库，需要导出或读取知识库中的文章列表；(2) ima 网页端不支持直接查看文章详情，需要通过 source_path 原始链接获取内容；(3) 批量抓取个人知识库或共享知识库中的文章标题、来源和正文。触发词：ima知识库、ima.qq.com、腾讯ima、知识库文章列表、万仁刚的知识库。"
---

# 腾讯 ima 知识库内容获取

## 概述

通过浏览器自动化连接已登录的 ima.qq.com/wikis 页面，从 React 组件内部状态中提取文章的 `sourcePath`（原始微信公众号等外部链接），再逐个打开新标签页获取文章正文。

## 前置条件

- 用户已在 Chrome 中打开 https://ima.qq.com/wikis 并完成登录
- 当前选中了目标知识库（如"万仁刚的知识库"）
- 使用 `mac_computer_use_tool` 配合 `plane="bu"` 进行浏览器操作

## 工作流程

### 第一步：连接浏览器并确认页面状态

```python
import seed_browser_use as bu

# 同步连接浏览器
bu.resync()

# 确认页面已加载
bu.wait_for_load(timeout=15)
page_info = bu.page_info()
print("当前页面:", page_info.get("url"))
```

如果 `resync` 失败或没有活动页面，直接用 `bu.navigate("https://ima.qq.com/wikis")` 打开页面。

### 第二步：提取文章列表的 sourcePath

ima 知识库使用虚拟滚动列表，文章数据存储在 React Fiber 内部状态中，DOM 元素上没有直接的链接属性。需要通过遍历 React Fiber 提取。

使用 `scripts/extract_source_paths.js` 中的代码逻辑，提取前 N 条文章的标题和原始链接：

```python
js_code = """
(async () => {
    const results = [];
    const count = arguments[0] || 10;  // 要提取的条数
    
    for (let i = 0; i < count; i++) {
        const item = document.querySelector(`[data-index="${i}"]`);
        if (!item) continue;
        
        const fiberKey = Object.keys(item).find(k => k.startsWith('__reactFiber'));
        let fiber = item[fiberKey];
        
        let foundPath = null;
        let foundTitle = null;
        let depth = 0;
        
        function searchObj(obj, path, depth2) {
            if (!obj || depth2 > 8 || foundPath) return;
            if (typeof obj !== 'object') return;
            
            for (let key in obj) {
                try {
                    if ((key === 'sourcePath' || key === 'source_path') && typeof obj[key] === 'string') {
                        foundPath = obj[key];
                    }
                    if ((key === 'title' || key === 'name') && typeof obj[key] === 'string' && obj[key].length > 5) {
                        foundTitle = obj[key];
                    }
                    if (typeof obj[key] === 'object' && obj[key] !== null) {
                        searchObj(obj[key], path + '.' + key, depth2 + 1);
                    }
                } catch(e) {}
            }
        }
        
        while (fiber && depth < 30 && !foundPath) {
            if (fiber.memoizedProps) {
                searchObj(fiber.memoizedProps, 'props', 0);
            }
            fiber = fiber.return;
            depth++;
        }
        
        results.push({
            index: i,
            title: foundTitle || item.innerText.split('\\n')[0],
            sourcePath: foundPath
        });
    }
    return results;
})()
"""

# 传入要提取的条数
result = bu.js(js_code.replace('arguments[0] || 10', '5'))
```

**关键点：**
- 列表项通过 `data-index` 属性定位，从 0 开始
- 虚拟滚动列表：可视区域外的项可能不存在，需要滚动加载后才能提取更多
- `sourcePath` 通常是微信公众号链接（`mp.weixin.qq.com/s/...`）

### 第三步：打开原始链接获取文章详情

提取到 sourcePath 后，逐个打开新标签页获取正文：

```python
import time

for article in result:
    if not article.get('sourcePath'):
        continue
    
    # 关闭上一个标签页（可选，节省资源）
    # bu.close_tab()
    # time.sleep(1)
    
    # 打开新标签页
    bu.new_tab(article['sourcePath'])
    time.sleep(3)
    bu.wait_for_load(timeout=10)
    
    # 获取文章正文
    content = bu.get_page_text()
    print(f"标题: {article['title']}")
    print(f"内容: {content[:500]}...")
    
    # 处理完后关闭
    bu.close_tab()
    time.sleep(1)
```

### 第四步：滚动加载更多

虚拟滚动列表只渲染可视区域的项。要获取更多文章，需要先向下滚动：

```python
# 滚动列表区域
bu.scroll(500, 500, "down", amount=5)
time.sleep(1)

# 然后重新提取 data-index 更大的项
```

## 常见问题

### 找不到 data-index 元素
- 确认页面已完全加载，等待几秒后重试
- 确认当前在"内容"列表视图，而不是文件夹视图
- 先 `bu.snapshot()` 看看页面结构

### sourcePath 为 null
- 该条可能不是外部链接类型（如手动添加的笔记、PDF等）
- 尝试增加遍历深度（把 `depth < 30` 改大）
- 尝试搜索其他字段名：`url`、`link`、`originalUrl`

### 登录态失效
- 如果页面跳转到登录页，需要用户手动登录后再继续
- 调用 `interaction.request_action` 让用户接管完成登录

## 注意事项

- 不要直接调用 ima 的后端 API（`/cgi-bin/knowledge_tab_reader/get_knowledge_list`），需要复杂的签名和参数，容易失败
- 优先从 React Fiber 提取数据，这是最稳定的方式
- 批量打开标签页时注意间隔，避免被微信公众号反爬
- 提取到的微信公众号文章内容可以直接通过 `bu.get_page_text()` 获取
