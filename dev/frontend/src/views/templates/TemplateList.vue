<template>
  <div class="template-list-page">
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>审稿模板管理</span>
          <el-button type="primary" @click="handleAdd">新建模板</el-button>
        </div>
      </template>

      <!-- 字段与 TemplateSerializer 对齐 -->
      <el-table :data="list" v-loading="loading" border>
        <el-table-column prop="template_name" label="模板名称" min-width="180" />
        <el-table-column label="类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.template_type === 'SYSTEM_DEFAULT' ? 'primary' : 'info'" size="small">
              {{ row.template_type === 'SYSTEM_DEFAULT' ? '系统预设' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="适用学科" width="120">
          <template #default="{ row }">{{ row.subject_area || '通用' }}</template>
        </el-table-column>
        <el-table-column label="维度数" width="80" align="center">
          <template #default="{ row }">{{ (row.dimensions || []).length }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
              {{ row.status === 'ACTIVE' ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" @click="handleEdit(row)">编辑</el-button>
            <el-button text :type="row.status === 'ACTIVE' ? 'warning' : 'success'" @click="handleToggle(row)">
              {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 模板编辑对话框 -->
    <el-dialog v-model="editDialog" :title="editing.template_id ? '编辑模板' : '新建模板'" width="760" top="5vh">
      <el-form ref="formRef" :model="editing" :rules="rules" label-position="top">
        <el-form-item label="模板名称" prop="template_name">
          <el-input v-model="editing.template_name" placeholder="如：经济学论文四维审稿模板" />
        </el-form-item>
        <el-form-item label="适用学科（留空为通用）" prop="subject_area">
          <el-select v-model="editing.subject_area" placeholder="选择学科" clearable filterable allow-create style="width: 100%">
            <el-option v-for="s in subjectOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>

        <el-divider>审稿维度（dimensionId / dimensionName / description / minWords）</el-divider>

        <div v-for="(dim, idx) in editing.dimensions" :key="idx" class="dim-edit-block">
          <el-row :gutter="12">
            <el-col :span="5">
              <el-form-item label="维度ID" :prop="`dimensions.${idx}.dimensionId`" :rules="[{ required: true, message: '必填' }, { pattern: /^[A-Za-z0-9_-]+$/, message: '仅字母数字' }]">
                <el-input v-model="dim.dimensionId" placeholder="如 D1" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="维度名称" :prop="`dimensions.${idx}.dimensionName`" :rules="{ required: true, message: '必填' }">
                <el-input v-model="dim.dimensionName" placeholder="如 研究意义" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="维度说明">
                <el-input v-model="dim.description" placeholder="该维度考察内容（选填）" />
              </el-form-item>
            </el-col>
            <el-col :span="3">
              <el-form-item label="最少字数">
                <el-input-number v-model="dim.minWords" :min="10" :max="500" :step="10" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="2" class="flex-center">
              <el-button text type="danger" @click="removeDim(idx)" :icon="Delete" />
            </el-col>
          </el-row>
        </div>

        <el-button type="primary" plain @click="addDim" :icon="Plus">添加维度</el-button>
      </el-form>

      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { templateApi } from '@/api/modules'
import { formatDate } from '@/utils/status'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'

const loading = ref(false)
const saving = ref(false)
const list = ref([])

const editDialog = ref(false)
const formRef = ref()
const editing = reactive({
  template_id: null,
  template_name: '',
  subject_area: '',
  dimensions: [],
})

const subjectOptions = [
  '经济学', '金融学', '管理学', '气候经济学', '环境经济学',
  '劳动经济学', '宏观经济学', '发展经济学', '应用计量', '政策评估',
]

const rules = {
  template_name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
}

const fetchList = async () => {
  loading.value = true
  try {
    // status 传空串以包含启用+停用（后端默认只回 ACTIVE）
    const res = await templateApi.list({ status: '' })
    list.value = res.results || res
  } catch (e) {
    console.error('Failed to fetch templates:', e)
  } finally {
    loading.value = false
  }
}

const handleAdd = () => {
  Object.assign(editing, {
    template_id: null,
    template_name: '',
    subject_area: '',
    dimensions: [
      { dimensionId: 'D1', dimensionName: '研究意义', description: '研究问题的学术价值与现实意义', minWords: 50 },
      { dimensionId: 'D2', dimensionName: '创新性', description: '理论创新、方法创新或数据创新', minWords: 50 },
      { dimensionId: 'D3', dimensionName: '研究方法', description: '研究设计的合理性、方法的适当性', minWords: 50 },
      { dimensionId: 'D4', dimensionName: '写作水平', description: '论文结构、逻辑表达、规范性', minWords: 50 },
    ],
  })
  editDialog.value = true
}

const handleEdit = (row) => {
  Object.assign(editing, {
    template_id: row.template_id,
    template_name: row.template_name,
    subject_area: row.subject_area || '',
    dimensions: JSON.parse(JSON.stringify(row.dimensions || [])),
  })
  editDialog.value = true
}

const addDim = () => {
  editing.dimensions.push({ dimensionId: '', dimensionName: '', description: '', minWords: 50 })
}

const removeDim = (idx) => {
  editing.dimensions.splice(idx, 1)
}

const handleSave = async () => {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    if (editing.dimensions.length < 2) {
      ElMessage.warning('至少需要2个审稿维度')
      return
    }
    const dimIds = editing.dimensions.map(d => d.dimensionId)
    if (new Set(dimIds).size !== dimIds.length) {
      ElMessage.warning('维度ID不可重复')
      return
    }
    saving.value = true
    try {
      const data = {
        template_name: editing.template_name,
        subject_area: editing.subject_area || '',
        dimensions: editing.dimensions,
      }
      if (editing.template_id) {
        await templateApi.update(editing.template_id, data)
      } else {
        await templateApi.create(data)
      }
      ElMessage.success(editing.template_id ? '模板已更新' : '模板已创建')
      editDialog.value = false
      fetchList()
    } catch (e) { /* handled */ } finally {
      saving.value = false
    }
  })
}

const handleToggle = async (row) => {
  try {
    await templateApi.toggleStatus(row.template_id)
    ElMessage.success(row.status === 'ACTIVE' ? '模板已停用' : '模板已启用')
    fetchList()
  } catch (e) { /* handled */ }
}

onMounted(fetchList)
</script>

<style scoped>
.dim-edit-block {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 12px;
}
</style>
