// 从已保存的研判版本提取展示章节；不在前端硬编码行业判断。
export function assessmentSections(markdown = '') {
  return String(markdown).split(/^##\s+/m).slice(1).map(section => {
    const newline = section.indexOf('\n')
    return { title: section.slice(0, newline).trim(), content: section.slice(newline + 1).trim() }
  }).filter(section => section.title && section.content)
}

export function assessmentState(overview, records = []) {
  const topic = overview?.topic_report
  const report = topic?.report
  if (!report) return 'missing'
  const staleChildren = overview.categories?.some(c => c.evidence_count !== 0 && c.freshness === 'stale')
  const activeIds = new Set(records.map(r => r.id))
  const removedReference = report.evidence_ids?.some(id => !activeIds.has(id))
  return topic.freshness === 'stale' || staleChildren || removedReference ? 'stale' : 'current'
}
