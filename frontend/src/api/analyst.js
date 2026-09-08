// 数据分析员工（analyst）API 封装
// 集中管理数据源、术语、SQL 示例的 CRUD 与 SSE 问数流
import api from '../api.js'

/* ---------- 数据源 ---------- */

export const listDatasources = () => api.get('/analyst/datasources').then(r => r.data)

export const getDatasource = (id) =>
  api.get(`/analyst/datasources/${id}`).then(r => r.data)

export const createDatasource = (payload) =>
  api.post('/analyst/datasources', payload).then(r => r.data)

export const updateDatasource = (id, payload) =>
  api.put(`/analyst/datasources/${id}`, payload).then(r => r.data)

export const deleteDatasource = (id) =>
  api.delete(`/analyst/datasources/${id}`).then(r => r.data)

export const testDatasourceConnection = (payload) =>
  api.post('/analyst/datasources/test', payload).then(r => r.data)

export const discoverTables = (id) =>
  api.get(`/analyst/datasources/${id}/tables`).then(r => r.data)

export const getTableSchema = (id, tableName) =>
  api.get(`/analyst/datasources/${id}/tables/${tableName}/schema`).then(r => r.data)

export const getTableRelationships = (id, tables) =>
  api.get(`/analyst/datasources/${id}/relationships`, { params: { tables } }).then(r => r.data)

export const listAnnotations = (id) =>
  api.get(`/analyst/datasources/${id}/annotations`).then(r => r.data)

export const getAnnotation = (id, tableName) =>
  api.get(`/analyst/datasources/${id}/annotations/${tableName}`).then(r => r.data)

export const upsertAnnotation = (id, tableName, payload) =>
  api.put(`/analyst/datasources/${id}/annotations/${tableName}`, payload).then(r => r.data)

/* ---------- 术语 ---------- */

export const listTerminologies = (params = {}) =>
  api.get('/analyst/terminologies', { params }).then(r => r.data)

export const getTerminology = (id) =>
  api.get(`/analyst/terminologies/${id}`).then(r => r.data)

export const createTerminology = (payload) =>
  api.post('/analyst/terminologies', payload).then(r => r.data)

export const updateTerminology = (id, payload) =>
  api.put(`/analyst/terminologies/${id}`, payload).then(r => r.data)

export const deleteTerminology = (id) =>
  api.delete(`/analyst/terminologies/${id}`).then(r => r.data)

export const addSynonym = (id, synonym) =>
  api.post(`/analyst/terminologies/${id}/synonyms`, { synonym }).then(r => r.data)

export const removeSynonym = (id, synonym) =>
  api.delete(`/analyst/terminologies/${id}/synonyms/${synonym}`).then(r => r.data)

export const toggleTerminology = (id, enabled) =>
  api.post(`/analyst/terminologies/${id}/toggle`, null, { params: { enabled } }).then(r => r.data)

export const generateSynonyms = (word) =>
  api.post('/analyst/terminologies/generate-synonyms', { word }).then(r => r.data)

export const previewTableData = (dsId, tableName, limit = 10) =>
  api.get(`/analyst/datasources/${dsId}/tables/${encodeURIComponent(tableName)}/preview`, { params: { limit } }).then(r => r.data)

/* ---------- 数据源聚合（数据库 + 知识库 + 连接器） ---------- */

export const listAllDataSources = () =>
  api.get('/analyst/data-sources').then(r => r.data)

/* ---------- 知识库绑定（xiaoshu 工作台专用） ---------- */

export const listAllKbs = () =>
  api.get('/analyst/kbs').then(r => r.data)

export const listBoundKbs = () =>
  api.get('/analyst/kbs/bound').then(r => r.data)

export const bindKb = (kbId) =>
  api.post(`/analyst/kbs/${kbId}`).then(r => r.data)

export const unbindKb = (kbId) =>
  api.delete(`/analyst/kbs/${kbId}`).then(r => r.data)

/* ---------- 连接器绑定（xiaoshu 工作台专用） ---------- */

export const listAllConnectors = () =>
  api.get('/analyst/connectors').then(r => r.data)

export const listBoundConnectors = () =>
  api.get('/analyst/connectors/bound').then(r => r.data)

export const bindConnector = (connectorId) =>
  api.post(`/analyst/connectors/${connectorId}`).then(r => r.data)

export const unbindConnector = (connectorId) =>
  api.delete(`/analyst/connectors/${connectorId}`).then(r => r.data)

/* ---------- SQL 示例 ---------- */

export const listSqlExamples = (params = {}) =>
  api.get('/analyst/sql-examples', { params }).then(r => r.data)

export const getSqlExample = (id) =>
  api.get(`/analyst/sql-examples/${id}`).then(r => r.data)

export const createSqlExample = (payload) =>
  api.post('/analyst/sql-examples', payload).then(r => r.data)

export const updateSqlExample = (id, payload) =>
  api.put(`/analyst/sql-examples/${id}`, payload).then(r => r.data)

export const deleteSqlExample = (id) =>
  api.delete(`/analyst/sql-examples/${id}`).then(r => r.data)

export const toggleSqlExample = (id, enabled) =>
  api.post(`/analyst/sql-examples/${id}/toggle`, null, { params: { enabled } }).then(r => r.data)

/* ---------- SSE 问数流 ----------
 * 复用 /api/conversations/{id}/messages 的 SSE 流，但 conversation 通过
 * /api/employees/xiaoshu/conversations 创建（与 ChatView 同模式）。
 */

export const createAnalystConversation = () =>
  api.post('/employees/xiaoshu/conversations').then(r => r.data)

export const listAnalystConversations = (limit = 15) =>
  api.get('/conversations', { params: { employee_id: 'xiaoshu', limit, exclude_auto: true } }).then(r => r.data)

export const getAnalystConversation = (id) =>
  api.get(`/conversations/${id}`).then(r => r.data)
