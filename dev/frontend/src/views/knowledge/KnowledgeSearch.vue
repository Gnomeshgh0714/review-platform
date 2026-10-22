<template>
  <div class="knowledge-search-page">
    <el-card shadow="never" class="mb-16">
      <!-- 搜索栏 -->
      <div class="search-bar mb-16">
        <el-input
          v-model="searchParams.keyword"
          placeholder="搜索关键词（摘要/关键词/标签/学科）..."
          clearable
          size="large"
          @keyup.enter="handleSearch"
          class="search-input"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" size="large" @click="handleSearch" :loading="loading">搜索</el-button>
      </div>

      <!-- 筛选条件（与后端检索参数对齐） -->
      <el-row :gutter="16">
        <el-col :span="5">
          <el-select v-model="searchParams.subject_area" placeholder="学科领域" clearable filterable @change="handleSearch">
            <el-option v-for="s in subjectOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="searchParams.manuscript_type" placeholder="稿件类型" clearable @change="handleSearch">
            <el-option label="论文" value="论文" />
            <el-option label="综述" value="综述" />
            <el-option label="案例研究" value="案例研究" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-col>
        <el-col :span="5">
          <el-select v-model="searchParams.final_decision" placeholder="终审决策" clearable @change="handleSearch">
            <el-option v-for="(v, k) in RECOMMENDATION" :key="k" :label="v.label" :value="k" />
          </el-select>
        </el-col>
        <el-col :span="5">
          <el-date-picker
            v-model="dateRange"
            type="monthrange"
            start-placeholder="起始年月"
            end-placeholder="截止年月"
            value-format="YYYY-MM"
            @change="handleDateChange"
            style="width: 100%"
          />
        </el-col>
        <el-col :span="5">
          <el-select v-model="searchParams.score_range" placeholder="评分区间" clearable @change="handleSearch">
            <el-option label="高分（均分≥4）" value="high" />
            <el-option label="中高分（均分≥3）" value="mid_high" />
          </el-select>
        </el-col>
      </el-row>
    </el-card>

    <!-- 搜索结果 -->
    <el-card shadow="never">
      <template #header>
        <div class="flex-between">
          <span>搜索结果（{{ total }} 条）</span>
        </div>
      </template>

      <div v-loading="loading">
        <div v-if="results.length === 0 && !loading" class="text-center py-24">
          <el-empty description="暂无搜索结果">
            <template v-if="!hasSearched">
              <el-text type="info">输入关键词或选择筛选条件开始搜索</el-text>
            </template>
          </el-empty>
        </div>

        <!-- 冷启动降级提示（is_cold_start + cold_start_guide） -->
        <template v-if="isColdStart && coldStartGuide">
          <el-alert type="info" :closable="false" show-icon class="mb-16">
            <template #title>{{ coldStartGuide.title }}</template>
            <span>{{ coldStartGuide.description }}</span>
          </el-alert>
          <el-card shadow="never" class="mb-16" body-style="padding: 12px 16px;">
            <div v-for="dim in coldStartGuide.dimensions || []" :key="dim.code" class="mb-8">
              <strong>{{ dim.name }}</strong>
              <div class="text-muted text-sm mt-4">
                <div v-for="(text, score) in dim.guidelines" :key="score" class="guide-line">
                  {{ score }} 分：{{ text }}
                </div>
              </div>
            </div>
          </el-card>
        </template>

        <!-- 结果卡片（brief 字段：knowledge_id/subject_area/keywords/tags/final_decision/review_year/review_month） -->
        <div v-for="item in results" :key="item.knowledge_id" class="knowledge-item" @click="showDetail(item)">
          <div class="ki-header">
            <el-tag size="small" type="info">{{ item.subject_area || '未标注学科' }}</el-tag>
            <el-tag v-if="item.final_decision" :type="recTagType(item.final_decision)" size="small">
              {{ recLabel(item.final_decision) }}
            </el-tag>
            <span class="text-muted text-sm">审稿时间：{{ item.review_year }}-{{ String(item.review_month).padStart(2, '0') }}</span>
          </div>
          <div v-if="(item.keywords || []).length" class="ki-keywords mt-8">
            <el-tag v-for="kw in item.keywords" :key="kw" size="small" effect="plain">{{ kw }}</el-tag>
          </div>
          <div v-if="(item.tags || []).length" class="ki-tags mt-8">
            <el-tag v-for="tag in item.tags" :key="tag" size="small" type="warning" effect="plain">{{ tag }}</el-tag>
          </div>
        </div>

        <el-pagination
          v-if="total > 20"
          class="mt-16"
          :total="total"
          :page-size="20"
          layout="total, prev, pager, next"
          v-model:current-page="page"
          @current-change="fetchResults"
        />
      </div>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="知识库详情" width="700">
      <div v-if="currentDetail">
        <el-descriptions :column="2" border class="mb-16">
          <el-descriptions-item label="学科">{{ currentDetail.subject_area || '-' }}</el-descriptions-item>
          <el-descriptions-item label="稿件类型">{{ currentDetail.manuscript_type || '-' }}</el-descriptions-item>
          <el-descriptions-item label="终审决策">
            <el-tag v-if="currentDetail.final_decision" :type="recTagType(currentDetail.final_decision)" size="small">
              {{ recLabel(currentDetail.final_decision) }}
            </el-tag>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="审稿时间">
            {{ currentDetail.review_year }}-{{ String(currentDetail.review_month).padStart(2, '0') }}
          </el-descriptions-item>
        </el-descriptions>
        <template v-if="(currentDetail.anonymized_dimensions || []).length">
          <h4>维度评分（匿名化）</h4>
          <el-table :data="currentDetail.anonymized_dimensions" border size="small" class="mb-16">
            <el-table-column prop="dimensionName" label="维度" width="140" />
            <!-- V1.2 一般#4：anonymized_dimensions 实际结构为 {dimensionName, scores:[{score,...}]}，
                 无 avg 键，原读 row.avg 恒为 '-'，改为由 scores 现算均分 -->
            <el-table-column label="均分" width="80" align="center">
              <template #default="{ row }">{{ dimAvg(row) }}</template>
            </el-table-column>
          </el-table>
        </template>
        <h4>匿名化摘要</h4>
        <div class="detail-content">{{ currentDetail.anonymized_summary || '（无摘要）' }}</div>
        <div v-if="currentDetail.tags && currentDetail.tags.length" class="mt-16">
          <el-tag v-for="tag in currentDetail.tags" :key="tag" size="small" type="warning" effect="plain" class="mr-8">{{ tag }}</el-tag>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { knowledgeApi } from '@/api/modules'
import { RECOMMENDATION } from '@/utils/status'
import { Search } from '@element-plus/icons-vue'

const loading = ref(false)
const hasSearched = ref(false)
const results = ref([])
const total = ref(0)
const page = ref(1)
const isColdStart = ref(false)
const coldStartGuide = ref(null)
const dateRange = ref(null)

const searchParams = reactive({
  keyword: '',
  subject_area: '',
  manuscript_type: '',
  final_decision: '',
  score_range: '',
})

const subjectOptions = [
  '经济学', '金融学', '管理学', '气候经济学', '环境经济学',
  '劳动经济学', '宏观经济学', '发展经济学', '应用计量', '政策评估',
]

const recTagType = (key) => RECOMMENDATION[key]?.color || 'info'
const recLabel = (key) => RECOMMENDATION[key]?.label || key

// V1.2 一般#4：后端归档时未预计算 avg 字段，维度均分由 scores 数组现算
const dimAvg = (row) => {
  const scores = (row.scores || []).map(s => s.score).filter(s => typeof s === 'number')
  if (!scores.length) return '-'
  return (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1)
}

const handleSearch = () => {
  page.value = 1
  fetchResults()
}

const handleDateChange = (val) => {
  if (val && val.length === 2) {
    searchParams.date_start = val[0]
    searchParams.date_end = val[1]
  } else {
    delete searchParams.date_start
    delete searchParams.date_end
  }
  handleSearch()
}

const fetchResults = async () => {
  loading.value = true
  hasSearched.value = true
  try {
    const params = { page: page.value, ...searchParams }
    // 清空空值
    Object.keys(params).forEach(k => {
      if (params[k] === '' || params[k] === null) delete params[k]
    })
    const res = await knowledgeApi.search(params)
    results.value = res.results || []
    total.value = res.count || 0
    isColdStart.value = res.is_cold_start || false
    coldStartGuide.value = res.cold_start_guide || null
  } catch (e) {
    console.error('Search error:', e)
    results.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

const showDetail = async (item) => {
  try {
    const detail = await knowledgeApi.detail(item.knowledge_id)
    currentDetail.value = detail
    detailVisible.value = true
  } catch (e) { /* handled */ }
}

const detailVisible = ref(false)
const currentDetail = ref(null)
</script>

<style scoped>
.search-bar { display: flex; gap: 12px; }
.search-input { flex: 1; }
.knowledge-item {
  padding: 16px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 12px;
  border: 1px solid #ebeef5;
}
.knowledge-item:hover { background: #ecf5ff; border-color: #409eff; }
.ki-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ki-keywords { display: flex; gap: 4px; flex-wrap: wrap; }
.ki-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.py-24 { padding: 24px 0; }
.mt-4 { margin-top: 4px; }
.mb-8 { margin-bottom: 8px; }
.mr-8 { margin-right: 8px; }
.guide-line { line-height: 1.8; }
.detail-content {
  margin-top: 12px;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
  max-height: 400px;
  overflow-y: auto;
}
</style>
