import api from './index'

// ============ 用户模块 ============
export const userApi = {
  login: (data) => api.post('/users/login/', data),
  list: (params) => api.get('/users/', { params }),
  getMe: () => api.get('/users/me/'),
  updateProfile: (data) => api.put('/users/update_profile/', data),
  getReviewers: (params) => api.get('/users/reviewers/', { params }),
  // 用户管理（编辑部专用，#024）：对应 UserViewSet create/update/partial_update/destroy；
  // 编辑部重置密码（update 传 password）会拉黑该用户全部 refresh token
  create: (data) => api.post('/users/', data),
  update: (id, data) => api.patch(`/users/${id}/`, data),
  remove: (id) => api.delete(`/users/${id}/`),
}

// ============ 任务模块 ============
export const taskApi = {
  list: (params) => api.get('/tasks/', { params }),
  retrieve: (id) => api.get(`/tasks/${id}/`),
  create: (data) => api.post('/tasks/', data),
  update: (id, data) => api.patch(`/tasks/${id}/`, data),
  dashboard: (params) => api.get('/tasks/dashboard/', { params }),
  myTasks: (params) => api.get('/tasks/my_tasks/', { params }),
  myArticles: (params) => api.get('/tasks/my_articles/', { params }),
  assignReviewers: (id, data) => api.post(`/tasks/${id}/assign_reviewers/`, data),
  acceptInvitation: (id, data) => api.post(`/tasks/${id}/accept_invitation/`, data),
  rejectInvitation: (id, data) => api.post(`/tasks/${id}/reject_invitation/`, data),
  forceSummarize: (id, data) => api.post(`/tasks/${id}/force_summarize/`, data),
  handleOverdue: (id, data) => api.post(`/tasks/${id}/handle_overdue/`, data),
  makeDecision: (id, data) => api.post(`/tasks/${id}/make_decision/`, data),
  stateLogs: (id) => api.get(`/tasks/${id}/state_logs/`),
}

// ============ 模板模块 ============
export const templateApi = {
  list: (params) => api.get('/templates/', { params }),
  retrieve: (id) => api.get(`/templates/${id}/`),
  create: (data) => api.post('/templates/', data),
  update: (id, data) => api.patch(`/templates/${id}/`, data),
  toggleStatus: (id) => api.post(`/templates/${id}/toggle_status/`),
}

// ============ 通知模块 ============
export const notificationApi = {
  list: (params) => api.get('/notifications/', { params }),
  unreadCount: () => api.get('/notifications/unread_count/'),
  markRead: (data) => api.post('/notifications/mark_read/', data),
  markAllRead: () => api.post('/notifications/mark_all_read/'),
}

// ============ 文件模块 ============
export const fileApi = {
  upload: (formData, onProgress) => api.post('/files/upload/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  }),
  download: (fileId) => api.get(`/files/${fileId}/download/`, { responseType: 'blob' }),
  checkMetadata: (fileId) => api.get(`/files/${fileId}/check_metadata/`),
  delete: (fileId) => api.delete(`/files/${fileId}/`),
}

// ============ 审稿表单模块 ============
export const formApi = {
  getForm: (taskId) => api.get('/forms/get_form/', { params: { task_id: taskId } }),
  // 决策 #026（F-3）：AI 审稿异步化——提交秒回 {job_id, status}，
  // 原同步 180s 超时配置随阻塞链路一并移除（提交不再等待 LLM）
  aiReview: (taskId) => api.post('/forms/ai_review/', { task_id: taskId }),
  // 轮询 AI 审稿任务状态（仅本人 job 可查，他人 403）
  aiReviewStatus: (jobId) => api.get('/forms/ai_review_status/', { params: { job_id: jobId } }),
  validateReferences: (taskId) => api.post('/forms/validate_references/', { task_id: taskId }, { timeout: 300000 }),
  submitOpinion: (data) => api.post('/opinions/submit/', data),
  saveDraft: (data) => api.post('/opinions/save_draft/', data),
  // #015 遗留2：my_opinion 无记录时后端正常返回 404（业务空态），
  // 传 silent404 避免全局拦截器误弹「请求的资源不存在」toast
  myOpinion: (taskId) => api.get('/opinions/my_opinion/', { params: { task_id: taskId }, silent404: true }),
  taskOpinions: (taskId) => api.get('/opinions/task_opinions/', { params: { task_id: taskId } }),
}

// ============ 汇总报告模块 ============
export const summaryApi = {
  list: (params) => api.get('/summaries/', { params }),
  generate: (taskId) => api.post('/summaries/generate/', { task_id: taskId }),
  detail: (taskId) => api.get(`/summaries/${taskId}/detail/`),
  matchRulePreview: (data) => api.post('/summaries/match_rule_preview/', data),
}

// ============ 知识库模块 ============
export const knowledgeApi = {
  search: (params) => api.get('/knowledge/search/', { params }),
  detail: (id) => api.get(`/knowledge/${id}/detail/`),
  pendingReviews: (params) => api.get('/knowledge/pending_reviews/', { params }),
  reviewAnonymization: (id, data) => api.post(`/knowledge/${id}/review/`, data),
  export: (params) => api.get('/knowledge/export/', { params }),
}
