<template>
  <div class="profile-page">
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="never">
          <div class="profile-header">
            <el-avatar :size="80" :icon="UserFilled" />
            <h3 class="mt-16">{{ auth.displayName }}</h3>
            <el-tag type="info" size="small">{{ auth.roleLabel }}</el-tag>
          </div>
          <el-divider />
          <el-descriptions :column="1" border>
            <el-descriptions-item label="邮箱">{{ auth.user?.email }}</el-descriptions-item>
            <el-descriptions-item label="姓名">{{ auth.user?.name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="机构">{{ auth.user?.institution || '-' }}</el-descriptions-item>
            <el-descriptions-item label="学科领域">
              {{ (auth.user?.research_areas || []).join('、') || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="注册时间">{{ formatDate(auth.user?.created_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card shadow="never">
          <template #header><span>编辑资料</span></template>
          <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
            <el-form-item label="姓名" prop="name">
              <el-input v-model="form.name" />
            </el-form-item>
            <el-form-item label="机构" prop="institution">
              <el-input v-model="form.institution" placeholder="所在机构" />
            </el-form-item>
            <el-form-item v-if="auth.isReviewer" label="学科领域" prop="research_areas">
              <el-select
                v-model="form.research_areas"
                placeholder="选择或输入学科领域"
                multiple
                filterable
                allow-create
                style="width: 100%"
              >
                <el-option
                  v-for="s in subjectOptions"
                  :key="s"
                  :label="s"
                  :value="s"
                />
              </el-select>
              <div class="text-muted text-sm mt-8">学科领域用于任务分配时的匹配度计算，可多选</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="handleSave">保存修改</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { userApi } from '@/api/modules'
import { formatDate } from '@/utils/status'
import { ElMessage } from 'element-plus'
import { UserFilled } from '@element-plus/icons-vue'

const auth = useAuthStore()
const formRef = ref()
const saving = ref(false)

// 与后端 UserProfileSerializer 对齐：仅 name / institution / research_areas 可改
const form = reactive({
  name: auth.user?.name || '',
  institution: auth.user?.institution || '',
  research_areas: auth.user?.research_areas || [],
})

// 学科领域选项与任务学科词表保持一致（中文自由文本，支持自定义）
const subjectOptions = [
  '经济学', '金融学', '管理学', '气候经济学', '环境经济学',
  '劳动经济学', '宏观经济学', '发展经济学', '应用计量', '政策评估',
]

const rules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

const handleSave = async () => {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    saving.value = true
    try {
      await userApi.updateProfile({
        name: form.name,
        institution: form.institution,
        research_areas: form.research_areas,
      })
      await auth.fetchUser()
      ElMessage.success('保存成功')
    } catch (e) { /* handled */ } finally {
      saving.value = false
    }
  })
}
</script>

<style scoped>
.profile-header { text-align: center; padding: 16px 0; }
</style>
