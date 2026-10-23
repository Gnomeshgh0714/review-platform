<template>
  <div class="task-create-page">
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>创建审稿任务</span>
          <el-button text @click="$router.back()">返回</el-button>
        </div>
      </template>

      <el-form ref="formRef" :model="form" :rules="rules" label-width="120px" class="task-form">
        <el-form-item label="稿件标题" prop="title">
          <el-input v-model="form.title" placeholder="请输入论文标题" />
        </el-form-item>

        <el-form-item label="作者" prop="author_user_id">
          <el-select v-model="form.author_user_id" placeholder="选择作者账号" filterable style="width: 320px">
            <el-option
              v-for="a in authors"
              :key="a.user_id"
              :label="`${a.name}（${a.email}）`"
              :value="a.user_id"
            />
          </el-select>
          <div class="text-muted text-sm mt-4">作者账号由编辑部预先创建</div>
        </el-form-item>

        <el-form-item label="学科领域" prop="subject_area">
          <el-select v-model="form.subject_area" placeholder="选择学科" filterable allow-create style="width: 320px">
            <el-option v-for="s in subjectOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>

        <el-form-item label="关键词" prop="keywords">
          <el-select
            v-model="form.keywords"
            multiple filterable allow-create
            default-first-option
            placeholder="输入后回车添加，3-10个"
            style="width: 100%"
          >
            <el-option v-for="k in form.keywords" :key="k" :label="k" :value="k" />
          </el-select>
        </el-form-item>

        <el-form-item label="摘要" prop="abstract">
          <el-input v-model="form.abstract" type="textarea" :rows="4" placeholder="论文摘要" />
        </el-form-item>

        <el-form-item label="稿件类型" prop="manuscript_type">
          <el-radio-group v-model="form.manuscript_type">
            <el-radio value="论文">论文</el-radio>
            <el-radio value="综述">综述</el-radio>
            <el-radio value="案例研究">案例研究</el-radio>
            <el-radio value="其他">其他</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="审稿模式" prop="review_mode">
          <el-radio-group v-model="form.review_mode">
            <el-radio value="SINGLE_BLIND">单盲（作者不可见审稿人）</el-radio>
            <el-radio value="DOUBLE_BLIND">双盲（互不可见）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="稿件PDF" prop="manuscript_file">
          <el-upload
            ref="uploadRef"
            :auto-upload="true"
            :http-request="handleUpload"
            :before-upload="beforeUpload"
            accept=".pdf"
            :limit="1"
          >
            <el-button type="primary" :loading="uploading">
              <el-icon><Upload /></el-icon> 上传PDF
            </el-button>
            <template #tip>
              <div class="text-muted text-sm">仅支持PDF格式，最大20MB</div>
            </template>
          </el-upload>

          <!-- 上传进度 -->
          <el-progress v-if="uploading" :percentage="uploadProgress" :stroke-width="6" class="mt-8" />

          <!-- 文件信息 -->
          <div v-if="uploadedFile" class="uploaded-file mt-8">
            <el-icon color="#67c23a"><CircleCheck /></el-icon>
            <span>{{ uploadedFile.original_name }}</span>
            <el-button text type="primary" @click="checkAnonymization">检查匿名化</el-button>
          </div>

          <!-- 匿名化检查结果 -->
          <el-alert
            v-if="anonCheck"
            :type="anonCheck.passed ? 'success' : 'warning'"
            :closable="false"
            show-icon
            class="mt-8"
          >
            <template #title>匿名化检查</template>
            <div v-for="c in anonCheck.checks" :key="c.item" class="text-sm">
              {{ c.item }}：{{ c.detail }}
            </div>
            <div v-if="pdfMetadataAuthor" class="text-sm mt-4">
              PDF元数据作者字段：{{ pdfMetadataAuthor }}
            </div>
          </el-alert>
        </el-form-item>

        <el-form-item label="审稿模板" prop="template_id">
          <el-select v-model="form.template_id" placeholder="选择审稿模板" filterable style="width: 320px">
            <el-option
              v-for="t in templates"
              :key="t.template_id"
              :label="`${t.template_name}（${t.dimensions?.length || 0}维）`"
              :value="t.template_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="期望审稿人数" prop="expected_reviewer_count">
          <el-input-number v-model="form.expected_reviewer_count" :min="1" :max="5" />
        </el-form-item>

        <el-form-item label="审稿截止日期" prop="deadline">
          <el-date-picker
            v-model="form.deadline"
            type="date"
            placeholder="选择截止日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            :disabled-date="disabledPastDate"
          />
        </el-form-item>

        <el-form-item label="附加说明" prop="additional_notes">
          <el-input
            v-model="form.additional_notes"
            type="textarea" :rows="2"
            maxlength="1000" show-word-limit
            placeholder="给审稿人的额外说明（选填）"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">创建任务</el-button>
          <el-button @click="$router.back()">取消</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { taskApi, fileApi, templateApi, userApi } from '@/api/modules'
import { ElMessage } from 'element-plus'
import { Upload, CircleCheck } from '@element-plus/icons-vue'

const router = useRouter()
const formRef = ref()
const uploadRef = ref()
const submitting = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadedFile = ref(null)
const anonCheck = ref(null)
const pdfMetadataAuthor = ref('')
const templates = ref([])
const authors = ref([])

// 学科选项与后端 research_areas/subject_area 取值口径一致
const subjectOptions = [
  '经济学', '金融学', '管理学', '气候经济学', '环境经济学',
  '劳动经济学', '宏观经济学', '发展经济学', '应用计量', '政策评估',
]

// V1.2 建议#19：禁选今天之前的日期（今天可选），与 TaskAssign 统一
// 口径——此前本页禁选当天、TaskAssign 允许选到昨天，相邻页面同一
// 语义字段行为相反
const disabledPastDate = (d) => d.getTime() < new Date().setHours(0, 0, 0, 0)

// 字段名与 ReviewTaskCreateSerializer 对齐
const form = reactive({
  title: '',
  subject_area: '',
  keywords: [],
  abstract: '',
  manuscript_type: '论文',
  manuscript_file: '',
  review_mode: 'SINGLE_BLIND',
  author_user_id: '',
  template_id: '',
  expected_reviewer_count: 3,
  deadline: '',
  additional_notes: '',
})

const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  // 评审意见 V1.2 严重#3：后端 ReviewTaskCreateSerializer 必填，前端标「选填」
  // 会让用户留空提交直接吃 400
  abstract: [{ required: true, message: '请输入论文摘要', trigger: 'blur' }],
  subject_area: [{ required: true, message: '请选择学科', trigger: 'change' }],
  keywords: [
    { required: true, type: 'array', min: 3, max: 10, message: '关键词必须3-10个', trigger: 'change' },
  ],
  manuscript_type: [{ required: true, message: '请选择稿件类型', trigger: 'change' }],
  manuscript_file: [{ required: true, message: '请上传稿件PDF' }],
  review_mode: [{ required: true, message: '请选择审稿模式', trigger: 'change' }],
  author_user_id: [{ required: true, message: '请选择作者账号', trigger: 'change' }],
  template_id: [{ required: true, message: '请选择审稿模板', trigger: 'change' }],
  deadline: [{ required: true, message: '请选择截止日期', trigger: 'change' }],
}

const beforeUpload = (file) => {
  if (file.type !== 'application/pdf') {
    ElMessage.error('仅支持PDF格式')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过20MB')
    return false
  }
  return true
}

const handleUpload = async (options) => {
  const { file } = options
  uploading.value = true
  uploadProgress.value = 0
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await fileApi.upload(formData, (e) => {
      uploadProgress.value = Math.round((e.loaded / e.total) * 100)
    })
    uploadedFile.value = res
    // 后端任务关联的是文件存储路径（uploads/...），非 file_id
    form.manuscript_file = res.file_path
    ElMessage.success('文件上传成功')
  } catch (e) {
    // V1.2 一般#26：上传失败必须清理本地状态并 rethrow——否则 el-upload 显示假成功、
    // limit=1 阻止重传，直到创建任务才暴露「请上传稿件PDF」；
    // 具体 HTTP 错误提示已由 axios 拦截器统一弹出，此处不再重复弹笼统提示
    uploadedFile.value = null
    form.manuscript_file = ''
    anonCheck.value = null
    pdfMetadataAuthor.value = ''
    throw e
  } finally {
    uploading.value = false
  }
}

const checkAnonymization = async () => {
  if (!uploadedFile.value?.file_id) return
  try {
    const res = await fileApi.checkMetadata(uploadedFile.value.file_id)
    anonCheck.value = res.anonymization || null
    pdfMetadataAuthor.value = res.pdf_metadata_author || ''
  } catch (e) { /* handled */ }
}

const handleSubmit = async () => {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    submitting.value = true
    try {
      const res = await taskApi.create(form)
      ElMessage.success('任务创建成功')
      router.push(`/tasks/${res.task_id}`)
    } catch (e) { /* handled */ } finally {
      submitting.value = false
    }
  })
}

onMounted(async () => {
  // 审稿模板（后端默认只返回 ACTIVE 模板）
  try {
    const res = await templateApi.list({ status: 'ACTIVE' })
    templates.value = res.results || res || []
  } catch (e) { /* ignore */ }
  // 作者账号列表（编辑部权限，客户端过滤 AUTHOR 角色）
  // V1.2 一般#2：用户接口分页返回，原先只取第一页 20 条，作者超 20 人时
  // 选择器静默丢人——翻页取全后再过滤
  try {
    const all = []
    let p = 1
    for (;;) {
      const res = await userApi.list({ page: p, page_size: 100 })
      const users = res.results || res || []
      all.push(...users)
      const cnt = res.count ?? all.length
      if (all.length >= cnt || users.length === 0) break
      p += 1
    }
    authors.value = all.filter(u => (u.roles || []).includes('AUTHOR'))
  } catch (e) { /* ignore */ }
})
</script>

<style scoped>
.task-form { max-width: 700px; }
.uploaded-file { display: flex; align-items: center; gap: 8px; }
.mt-4 { margin-top: 4px; }
</style>
