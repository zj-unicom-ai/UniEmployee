// 从 ima 知识库页面提取文章列表的 sourcePath
// 使用方式：通过 bu.js() 调用，传入要提取的条数
//
// 示例：
//   count = 10
//   js_code = extract_source_paths_js(count)
//   result = bu.js(js_code)

function extract_source_paths_js(count = 10) {
    return `
(async () => {
    const results = [];
    const count = ${count};
    
    for (let i = 0; i < count; i++) {
        const item = document.querySelector('[data-index="' + i + '"]');
        if (!item) continue;
        
        const fiberKey = Object.keys(item).find(k => k.startsWith('__reactFiber'));
        if (!fiberKey) continue;
        
        let fiber = item[fiberKey];
        let foundPath = null;
        let foundTitle = null;
        let depth = 0;
        
        function searchObj(obj, depth2) {
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
                        searchObj(obj[key], depth2 + 1);
                    }
                } catch(e) {}
            }
        }
        
        while (fiber && depth < 30 && !foundPath) {
            if (fiber.memoizedProps) {
                searchObj(fiber.memoizedProps, 0);
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
`;
}

// 如果在 Node.js 环境中，导出函数
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { extract_source_paths_js };
}
