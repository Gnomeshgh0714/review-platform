<template>
  <div class="summary-detail-page">
    <div v-loading="loading">
      <!-- 稿件信息 -->
      <el-card shadow="never" class="mb-16">
        <template #header>
          <div class="flex-between">
            <span>汇总报告详情</span>
            <div class="gap-12 flex">
              <el-button text @click="$router.push('/summaries')">报告列表</el-button>
              <el-button text @click="$router.push(`/tasks/${report.task_id}`)">任务详情</el-button>
              <el-button text @click="$router.push(`/opinions/${report.task_id}`)">审稿意见</el-button>
              <el-button text @click="$router.push(`/refs/${report.task_id}`)">参考文献</el-button>
              <el-button v-if="auth.isEditor && taskStatus === 'SUMMARIZED'" type="primary"
                @click="$router.push(`/tasks/${report.task_id}/decision`)">
                终审决策
              </el-button>
            </div>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="稿件标题">{{ report.task_title }}</el-descriptions-item>
          <el-descriptions-item label="任务编号">{{ report.task_id }}</el-descriptions-item>
          <el-descriptions-item label="审稿人数量">{{ report.recommendation_distribution?.total ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="生成时间">{{ formatDate(report.generated_at) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-row :gutter="16">
        <!-- 左侧：图表+规则 -->
        <el-col :span="12">
          <!-- 推荐分布饼图 -->
          <el-card shadow="never" class="mb-16">
            <template #header><span>推荐意见分布</span></template>
            <v-chart :option="pieOption" autoresize style="height: 300px;" />
          </el-card>

          <!-- 系统规则建议（仅供参考） -->
          <el-card shadow="never" class="mb-16">
            <template #header><span>规则匹配结果</span></template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="匹配规则">
                <el-tag v-if="systemRec?.matchedRuleId" type="warning">{{ systemRec.matchedRuleId }}</el-tag>
                <span v-else>未匹配</span>
              </el-descriptions-item>
              <el-descriptions-item label="规则结论">
                <span v-if="systemRec?.conclusion">{{ systemRec.conclusion }}</span>
                <span v-else>-</span>
              </el-descriptions-item>
            </el-descriptions>
            <el-alert
              v-if="systemRec?.advisoryOnly"
              class="mt-8"
              type="info"
              :closable="false"
              show-icon
              title="系统建议仅为辅助参考，最终决策由编辑部结合分歧点自行判断"
            />
          </el-card>
        </el-col>

        <!-- 右侧：维度对比 -->
        <el-col :span="12">
          <el-card shadow="never" class="mb-16">
            <template #header><span>维度评分对比</span></template>
            <v-chart :option="radarOption" autoresize style="height: 300px;" />
          </el-card>

          <el-card shadow="never" class="mb-16">
            <template #header><span>维度评分明细</span></template>
            <el-table :data="dimensionTable" border size="small">
              <el-table-column prop="dimensionName" label="维度" width="120" />
              <el-table-column v-for="(_, idx) in reviewerSlots" :key="idx" :label="`审稿人${idx+1}`" width="90" align="center">
                <template #default="{ row }">
                  {{ row.scores[idx] ?? '-' }}
                </template>
              </el-table-column>
              <el-table-column prop="avg" label="均值" width="80" align="center">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.avg?.toFixed(1) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <!-- 分歧分析 -->
      <el-card v-if="(report.conflict_points || []).length" shadow="never" class="mb-16">
        <template #header><span class="text-danger">分歧点分析</span></template>
        <el-table :data="report.conflict_points" border>
          <el-table-column prop="dimensionName" label="维度" width="150" />
          <el-table-column label="程度" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.level === 'SEVERE' ? 'danger' : 'warning'" size="small">
                {{ row.levelLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="distributionText" label="评分分布" min-width="200" show-overflow-tooltip />
          <el-table-column prop="maxScore" label="最高分" width="80" align="center" />
          <el-table-column prop="minScore" label="最低分" width="80" align="center" />
          <el-table-column prop="diff" label="差距" width="80" align="center">
            <template #default="{ row }">
              <el-tag type="danger" size="small">{{ row.diff }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 一致点分析 -->
      <el-card v-if="(report.consensus_points || []).length" shadow="never" class="mb-16">
        <template #header><span class="text-success">一致点分析</span></template>
        <el-table :data="report.consensus_points" border>
          <el-table-column prop="dimensionName" label="维度" width="150" />
          <el-table-column label="类型" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.type === 'POSITIVE' ? 'success' : 'danger'" size="small">
                {{ row.typeLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="distributionText" label="评分分布" min-width="200" show-overflow-tooltip />
          <el-table-column prop="avgScore" label="平均分" width="100" align="center" />
        </el-table>
      </el-card>

      <!-- 修改建议汇总 -->
      <el-card v-if="(suggestionGroups || []).length" shadow="never" class="mb-16">
        <template #header><span>修改建议汇总</span></template>
        <div v-for="g in suggestionGroups" :key="g.dimensionId" class="suggestion-group mb-16">
          <el-divider content-position="left">{{ g.dimensionName }}</el-divider>
          <ul class="suggestion-list">
            <li v-for="(s, i) in g.suggestions" :key="i">{{ s.suggestion }}</li>
          </ul>
        </div>
      </el-card>

      <!-- 综合评语汇总（编辑部视角，含审稿人署名） -->
      <el-card shadow="never" class="mb-16">
        <template #header><span>审稿人综合评语</span></template>
        <div v-for="(op, idx) in report.overall_comments || []" :key="op.opinionId || idx" class="opinion-summary">
          <div class="flex-between mb-8">
            <div class="flex-center gap-8">
              <strong>{{ op.reviewerName || `审稿人 ${idx + 1}` }}</strong>
              <el-tag v-if="op.recommendation" :type="recTagType(op.recommendation)" size="small">
                {{ op.recommendationDisplay || recLabel(op.recommendation) }}
              </el-tag>
            </div>
          </div>
          <div class="comment-text">{{ op.comment }}</div>
        </div>
        <el-empty
          v-if="!(report.overall_comments || []).length"
          description="暂无综合评语"
          :image-size="60"
        />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { summaryApi, taskApi } from '@/api/modules'
import { formatDate, RECOMMENDATION } from '@/utils/status'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, RadarChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, TitleComponent, GridComponent } from 'echarts/components'

use([CanvasRenderer, PieChart, RadarChart, TooltipComponent, LegendComponent, TitleComponent, GridComponent])

const route = useRoute()
const auth = useAuthStore()

const loading = ref(true)
const report = ref({})
const taskStatus = ref('')

const recTagType = (key) => RECOMMENDATION[key]?.color || 'info'
const recLabel = (key) => RECOMMENDATION[key]?.label || key

const systemRec = computed(() => report.value.system_recommendation || null)

// dimension_comparison: [{dimensionId, dimensionName, scores: [{reviewerId, reviewerName, opinionId, score, comment}]}]
const dimensionTable = computed(() =>
  (report.value.dimension_comparison || []).map((dim) => {
    const scores = (dim.scores || []).map(s => s.score)
    const valid = scores.filter(s => s !== null && s !== undefined)
    const avg = valid.length > 0 ? valid.reduce((a, b) => a + b, 0) / valid.length : 0
    return { dimensionName: dim.dimensionName, scores, avg }
  })
)

// 审稿人列数以首个维度的 scores 长度为准（各意见按维度对齐）
const reviewerSlots = computed(() =>
  (report.value.dimension_comparison?.[0]?.scores) || []
)

// 修改建议汇总：by_dimension 的 dimensionId → 维度名对齐
const suggestionGroups = computed(() => {
  const byDim = report.value.revision_suggestions_summary?.by_dimension || {}
  const nameMap = {}
  for (const dim of report.value.dimension_comparison || []) {
    nameMap[dim.dimensionId] = dim.dimensionName
  }
  return Object.entries(byDim).map(([dimensionId, suggestions]) => ({
    dimensionId,
    dimensionName: nameMap[dimensionId] || (dimensionId === 'GENERAL' ? '总体建议' : dimensionId),
    suggestions,
  }))
})

// 饼图配置（recommendation_distribution 含 total 键，需排除）
const pieOption = computed(() => {
  const dist = report.value.recommendation_distribution || {}
  const colorMap = {
    ACCEPT: '#67c23a', MINOR_REVISION: '#e6a23c', MAJOR_REVISION: '#f56c6c', REJECT: '#909399',
  }
  const data = Object.entries(dist)
    .filter(([k, v]) => k !== 'total' && v > 0)
    .map(([k, v]) => ({ name: recLabel(k), value: v, itemStyle: { color: colorMap[k] } }))
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      label: { show: true, formatter: '{b}\n{c}' },
      data,
    }],
  }
})

// 雷达图配置
const radarOption = computed(() => {
  const dims = report.value.dimension_comparison || []
  const reviewerCount = dims.length > 0 ? (dims[0].scores?.length || 0) : 0

  const indicator = dims.map(d => ({ name: d.dimensionName, max: 5 }))
  const series = []
  for (let i = 0; i < reviewerCount; i++) {
    series.push({
      value: dims.map(d => d.scores?.[i]?.score ?? 0),
      name: `审稿人${i + 1}`,
    })
  }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, data: series.map(s => s.name) },
    radar: { indicator, radius: '65%' },
    series: [{ type: 'radar', data: series, areaStyle: { opacity: 0.1 } }],
  }
})

const fetchData = async () => {
  loading.value = true
  try {
    const [rep, task] = await Promise.all([
      summaryApi.detail(route.params.taskId),
      taskApi.retrieve(route.params.taskId).catch(() => null),
    ])
    report.value = rep
    taskStatus.value = rep.task_status || task?.status || ''
  } catch (e) {
    console.error('Failed to fetch summary:', e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)
</script>

<style scoped>
.comment-text {
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  color: #606266;
  white-space: pre-wrap;
  margin-bottom: 12px;
}
.opinion-summary { margin-bottom: 16px; }
.suggestion-list {
  margin: 0;
  padding-left: 20px;
  color: #606266;
  line-height: 1.8;
}
</style>
