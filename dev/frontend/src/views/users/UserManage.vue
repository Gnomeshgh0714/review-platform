<template>
  <div class="user-manage-page">
    <!-- 页内权限防御：路由层 meta.roles 已拦非编辑部，此处再兜一层（auth.isEditor） -->
    <el-card v-if="auth.isEditor" shadow="never">
      <template #header>
        <div class="flex-between">
          <span>用户管理</span>
          <el-button type="primary" @click="handleAdd">新建用户</el-button>
        </div>
      </template>

      <!-- 搜索：按姓名/邮箱关键词（当前页客户端过滤，分页为服务端） -->
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="按姓名 / 邮箱搜索（当前页内过滤）"
          clearable
          :prefix-icon="Search"
          style="width: 280px"
        />
      </div>

      <!-- 字段与 UserSerializer 对齐：user_id/name/email/roles/institution/research_areas/created_at -->
      <el-table :data="filteredList" v-loading="loading" border>
        <el-table-column prop="name" label="姓名" min-width="110" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column label="角色" min-width="150">
          <template #default="{ row }">
            <el-tag
              v-for="r in row.roles || []"
              :key="r"
              :type="ROLE_TAG_TYPES[r] || 'info'"
              size="small"
              class="role-tag"
            >
              {{ ROLE_LABELS[r] || r }}
            </el-tag>
            <span v-if="!(row.roles || []).length">-</span>
          </template>
        </el-table-column>
        <el-table-column label="机构" min-width="130">
          <template #default="{ row }">{{ row.institution || '-' }}</template>
        </el-table-column>
        <el-table-column label="研究方向" min-width="150">
          <template #default="{ row }">{{ (row.research_areas || []).join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="handleEdit(row)">编辑</el-button>
            <el-button text type="danger" @click="handleRemove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页接后端 StandardPagination（count/results，PAGE_SIZE 20） -->
      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="fetchList"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-empty v-else description="仅编辑部可访问用户管理" />

    <!-- 新建 / 编辑对话框 -->
    <el-dialog v-model="editDialog" :title="editing.user_id ? '编辑用户' : '新建用户'" width="560">
      <el-form ref="formRef" :model="editing" :rules="rules" label-position="top">
        <el-form-item label="姓名" prop="name">
          <el-input v-model="editing.name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editing.email" placeholder="登录邮箱" />
        </el-form-item>
        <el-form-item label="角色（可多选）" prop="roles">
          <el-select v-model="editing.roles" multiple placeholder="选择角色（EDITOR/REVIEWER/AUTHOR）" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="机构" prop="institution">
          <el-input v-model="editing.institution" placeholder="所属机构（选填）" />
        </el-form-item>
        <el-form-item label="研究方向" prop="research_areas">
          <el-input v-model="editing.research_areas" placeholder="多个方向用顿号或逗号分隔（选填）" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="editing.password"
            type="password"
            show-password
            :placeholder="editing.user_id ? '留空则不修改密码' : '留空使用初始密码 changeme123'"
          />
          <div class="form-tip">
            {{
              editing.user_id
                ? '填写即重置密码，该用户将被强制重新登录'
                : '初始密码随邀请邮件告知本人，首次登录后应尽快修改'
            }}
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { userApi } from '@/api/modules'
import { useAuthStore } from '@/stores/auth'
import { formatDate } from '@/utils/status'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

const auth = useAuthStore()

// 角色口径与后端 User.Role 一致（EDITOR/REVIEWER/AUTHOR），标签与 auth.roleLabel 同源
const ROLE_LABELS = { EDITOR: '编辑部', REVIEWER: '审稿人', AUTHOR: '作者' }
const ROLE_TAG_TYPES = { EDITOR: 'danger', REVIEWER: 'primary', AUTHOR: 'success' }
const roleOptions = [
  { value: 'EDITOR', label: '编辑部' },
  { value: 'REVIEWER', label: '审稿人' },
  { value: 'AUTHOR', label: '作者' },
]

const loading = ref(false)
const saving = ref(false)
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')

const editDialog = ref(false)
const formRef = ref()
const editing = reactive({
  user_id: null,
  name: '',
  email: '',
  roles: [],
  institution: '',
  research_areas: '',
  password: '',
})

const rules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  roles: [{ required: true, type: 'array', message: '请至少选择一个角色', trigger: 'change' }],
  password: [{ min: 8, message: '密码至少 8 位（后端密码校验器口径）', trigger: 'blur' }],
}

// 姓名或邮箱包含关键词即命中（客户端过滤，仅作用于当前页）
const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return list.value
  return list.value.filter(
    (u) => (u.name || '').toLowerCase().includes(kw) || (u.email || '').toLowerCase().includes(kw),
  )
})

const fetchList = async () => {
  loading.value = true
  try {
    const res = await userApi.list({ page: page.value, page_size: pageSize.value })
    list.value = res.results || []
    total.value = res.count ?? list.value.length
  } catch (e) {
    console.error('Failed to fetch users:', e)
  } finally {
    loading.value = false
  }
}

const handleSizeChange = () => {
  // 每页条数变化后回到第 1 页，避免停留在越界页码
  page.value = 1
  fetchList()
}

// research_areas 后端为数组；编辑态以顿号文本呈现，保存时拆回数组
const splitAreas = (text) =>
  (text || '').split(/[、,，;；]/).map((s) => s.trim()).filter(Boolean)

const resetEditing = () => {
  Object.assign(editing, {
    user_id: null,
    name: '',
    email: '',
    roles: [],
    institution: '',
    research_areas: '',
    password: '',
  })
}

const handleAdd = () => {
  resetEditing()
  editDialog.value = true
}

const handleEdit = (row) => {
  Object.assign(editing, {
    user_id: row.user_id,
    name: row.name || '',
    email: row.email || '',
    roles: [...(row.roles || [])],
    institution: row.institution || '',
    research_areas: (row.research_areas || []).join('、'),
    password: '',
  })
  editDialog.value = true
}

const handleSave = () => {
  formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      const data = {
        name: editing.name.trim(),
        email: editing.email.trim(),
        roles: editing.roles,
        institution: editing.institution.trim(),
        research_areas: splitAreas(editing.research_areas),
      }
      // 密码留空不提交：创建时后端缺省 changeme123（随邀请邮件告知），编辑时不动密码
      if (editing.password) data.password = editing.password
      if (editing.user_id) {
        await userApi.update(editing.user_id, data)
        ElMessage.success('用户已更新')
      } else {
        // 创建成功后后端发送邀请邮件（#023 路线A），初始密码随邮件告知本人
        await userApi.create(data)
        ElMessage.success('用户创建成功，邀请邮件已发送（初始密码随邮件告知）')
      }
      editDialog.value = false
      fetchList()
    } catch (e) { /* 全局拦截器已提示 */ } finally {
      saving.value = false
    }
  })
}

const handleRemove = (row) => {
  // 后端为硬删除 + FK 级联：该用户的审稿记录会一并删除，提示不淡化
  ElMessageBox.confirm(
    `删除用户「${row.name}」不可恢复，该用户的审稿记录将一并删除`,
    '删除用户',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  ).then(async () => {
    try {
      await userApi.remove(row.user_id)
      ElMessage.success('用户已删除')
      // 删除当前页最后一条时回退一页，避免停留在空页
      if (list.value.length === 1 && page.value > 1) page.value -= 1
      fetchList()
    } catch (e) { /* 全局拦截器已提示 */ }
  }).catch(() => {})
}

// 页内防御：非编辑部不渲染也不发请求（路由层 meta.roles 已拦截，此处兜底）
onMounted(() => {
  if (auth.isEditor) fetchList()
})
</script>

<style scoped>
.toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.role-tag {
  margin-right: 4px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
</style>
