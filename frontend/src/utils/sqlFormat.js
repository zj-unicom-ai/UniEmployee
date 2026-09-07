// SQL 工具：关键字高亮 + 简单格式化（统一供 SqlViewer / SqlExampleManager 使用）
const SQL_KEYWORDS = new Set([
  'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET',
  'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'OUTER JOIN', 'ON',
  'UNION', 'UNION ALL', 'WITH', 'AS', 'AND', 'OR', 'NOT', 'IN', 'EXISTS',
  'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
  'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER', 'INTO', 'VALUES', 'SET',
  'TABLE', 'INDEX', 'VIEW', 'NULL', 'IS', 'LIKE', 'BETWEEN',
])

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
}

// 高亮 SQL：关键字蓝色 + 字符串字面量琥珀色
export function highlightSql(sql) {
  if (!sql) return ''
  let out = escapeHtml(sql)
  const literals = []
  out = out.replace(/'[^']*'/g, m => {
    literals.push(m)
    return `__LIT${literals.length - 1}__`
  })
  for (const kw of SQL_KEYWORDS) {
    const re = new RegExp(`\\b${kw.replace(/\s+/g, '\\s+')}\\b`, 'gi')
    out = out.replace(re, m => `<span class="sql-kw">${m}</span>`)
  }
  out = out.replace(/__LIT(\d+)__/g, (_, i) => {
    const lit = literals[Number(i)]
    return `<span class="sql-str">${lit}</span>`
  })
  return out
}

// 简单 SQL 格式化：关键字换行 + 缩进（不追求完美，给对话流里的 SQL 提升可读性）
export function formatSql(sql) {
  if (!sql) return ''
  const lines = []
  let cur = ''
  const push = () => {
    if (cur.trim()) lines.push(cur.trim())
    cur = ''
  }
  // 在主关键字前换行（不在字符串内）
  const placeholders = []
  let work = String(sql).replace(/'[^']*'/g, m => {
    placeholders.push(m)
    return `__PH${placeholders.length - 1}__`
  })
  work = work.replace(/\s+/g, ' ').trim()
  const tokens = work.split(/\s+/)
  const BREAK_BEFORE = new Set([
    'FROM', 'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'UNION', 'ON', 'AND', 'OR', 'SET', 'VALUES',
  ])
  const INDENT_KW = { FROM: 0, WHERE: 0, 'GROUP': 0, 'ORDER': 0, JOIN: 0, 'LEFT': 0, 'RIGHT': 0, 'INNER': 0, 'OUTER': 0 }
  let indent = 0
  for (const tok of tokens) {
    const upper = tok.toUpperCase()
    if (BREAK_BEFORE.has(upper) && cur.trim()) {
      push()
      indent = INDENT_KW[upper] !== undefined ? 1 : (['AND', 'OR', 'ON'].includes(upper) ? 2 : 1)
    }
    cur += (cur ? ' ' : '') + tok
  }
  push()
  // 还原字符串
  return lines
    .map((l, i) => (i === 0 ? l : '  '.repeat(indent > 0 && /FROM|WHERE|GROUP|ORDER|JOIN/.test(lines[i - 1] || '') ? 1 : 0) + l))
    .join('\n')
    .replace(/__PH(\d+)__/g, (_, i) => placeholders[Number(i)])
}
