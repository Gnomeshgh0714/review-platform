/**
 * 状态映射工具
 */

// 任务状态
// V1.2 一般#3：删除 ARCHIVED/REJECTED 死键——后端任务状态机终态只有 DECIDED
// （P1 词表对齐时漏掉任务状态表），残留死键曾使作者仪表盘 ARCHIVED 统计恒 0、
// 看板终态判断引用不存在的状态
export const TASK_STATUS = {
  PENDING: { label: '待分配', color: 'info', icon: 'Clock' },
  ASSIGNED: { label: '待接受', color: '', icon: 'User' },
  REVIEWING: { label: '审稿中', color: 'warning', icon: 'EditPen' },
  SUBMITTED: { label: '待汇总', color: 'success', icon: 'CircleCheck' },
  SUMMARIZED: { label: '已汇总', color: '', icon: 'DataAnalysis' },
  DECIDED: { label: '已决策', color: 'success', icon: 'Select' },
}

// 审稿意见推荐（键值与后端 ReviewOpinion.Recommendation 对齐）
export const RECOMMENDATION = {
  ACCEPT: { label: '接收', color: 'success', score: 4 },
  MINOR_REVISION: { label: '小修', color: 'warning', score: 3 },
  MAJOR_REVISION: { label: '大修', color: 'warning', score: 2 },
  REJECT: { label: '拒稿', color: 'danger', score: 1 },
}

// 用户角色
export const USER_ROLE = {
  EDITOR: '编辑部',
  REVIEWER: '审稿人',
  AUTHOR: '作者',
}

// 分配状态（键值与后端 ReviewAssignment.assignment_status 对齐）
export const ASSIGNMENT_STATUS = {
  INVITED: { label: '待响应', color: 'info' },
  ACCEPTED: { label: '已接受', color: 'success' },
  REVIEWING: { label: '审稿中', color: 'warning' },
  SUBMITTED: { label: '已提交', color: 'success' },
  REJECTED: { label: '已拒绝', color: 'danger' },
  EXPIRED: { label: '已过期', color: 'info' },
  OVERDUE: { label: '已超时', color: 'danger' },
}

// 格式化日期
export const formatDate = (date, format = 'YYYY-MM-DD HH:mm') => {
  if (!date) return '-'
  return new Date(date).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).replace(/\//g, '-')
}

// 格式化日期（仅日期）
export const formatDateOnly = (date) => {
  if (!date) return '-'
  return date.substring(0, 10)
}

// 计算剩余天数
export const daysRemaining = (deadline) => {
  if (!deadline) return null
  const now = new Date()
  const dl = new Date(deadline)
  const diff = Math.ceil((dl - now) / (1000 * 60 * 60 * 24))
  return diff
}

// 截止日期状态
export const deadlineStatus = (deadline) => {
  const days = daysRemaining(deadline)
  if (days === null) return { color: '', text: '-' }
  if (days < 0) return { color: 'danger', text: `已超期 ${Math.abs(days)} 天` }
  if (days <= 3) return { color: 'danger', text: `剩余 ${days} 天` }
  if (days <= 7) return { color: 'warning', text: `剩余 ${days} 天` }
  return { color: 'success', text: `剩余 ${days} 天` }
}

// 获取状态标签
export const getStatusTag = (statusMap, status) => {
  return statusMap[status] || { label: status, color: 'info' }
}

// 评分转百分比
export const scoreToPercent = (score) => {
  return (score / 5 * 100).toFixed(0)
}

// 文件大小格式化
export const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
