// 定制型（kind==='custom'）员工 → 专属前端路由名映射
// 编排型员工不在此表，统一走 chat 路由。
// 新增定制型员工时，在此追加一条即可。
export const CUSTOM_EMPLOYEE_ROUTES = {
  xiaoshu: 'analyst',
}

// 根据会话的 employee_id 决定该跳到哪个前端路由
export function routeNameForEmployee(empId) {
  return CUSTOM_EMPLOYEE_ROUTES[empId] || 'chat'
}

export function isCustomEmployee(emp) {
  return (emp?.kind || 'composed') === 'custom'
}
