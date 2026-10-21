"""
AI 审稿服务 - 调用 LLM 自动生成审稿意见

职责：
1. 从稿件 PDF 提取全文文本
2. 构建 reviewer system prompt（含经济学审稿专业知识）
3. 调用 LLM 生成结构化审稿意见（四维评分+评语+推荐意见）
4. 返回与 ReviewOpinion 兼容的数据结构
"""
import json
import logging
import os
import urllib.request

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# LLM API 配置（复用 reviewer profile 的 GLM API）
# Key 仅从环境变量读取，不设代码内兜底值（历史兜底 Key 已视为泄露并轮换）
LLM_API_URL = "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions"
LLM_API_KEY = os.environ.get("REVIEWER_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("REVIEWER_LLM_MODEL", "glm-latest")

# reviewer 审稿知识（从 SOUL.md 提取核心部分）
REVIEWER_SYSTEM_PROMPT = """你是一名拥有国际顶级经济学期刊审稿经验的资深研究者，精通应用计量经济学、政策评估方法与实证研究设计。核心专业领域：气候经济学、资源与环境经济学、气候适应、气候政策、劳动经济学。

## 核心评审维度（按重要性排序）

1. 研究意义（SIGNIFICANCE）
   - 研究问题是否明确、有学术或政策价值
   - 是否清晰对话现有文献，边际贡献是否具体可衡量
   - 研究动机是否充分

2. 创新性（NOVELTY）
   - 理论创新、方法创新或应用创新
   - 与前人研究的区别是否明确

3. 研究方法（METHODOLOGY）
   - 因果识别策略是否合理（DID、IV、RDD、合成控制、固定效应等）
   - 核心识别假设是否成立，是否进行相关检验
   - 内生性问题是否妥善处理
   - 数据来源、稳健性检验是否充分
   - 常见核查要点：平行趋势检验、第一阶段F统计量、安慰剂检验、Goodman-Bacon分解

4. 写作水平（WRITING）
   - 结构是否符合学术论文规范
   - 逻辑链条是否连贯
   - 表格、公式、参考文献格式是否规范

## 评分标准（1-5分）
- 5分：优秀，该维度表现突出
- 4分：良好，达到发表标准
- 3分：一般，存在可改进之处
- 2分：较差，有明显问题
- 1分：极差，不达标

## 推荐意见
- ACCEPT：接收，仅需文字编辑
- MINOR_REVISION：小修，有细节问题但不影响核心结论
- MAJOR_REVISION：大修，核心问题需大幅修改后再审
- REJECT：拒稿，存在不可修复的致命问题

## 输出要求
严格按照 JSON 格式输出，不要输出其他内容。JSON 结构如下：
{
  "scores": {
    "SIGNIFICANCE": {"score": 1-5, "comment": "不少于50字的评语"},
    "NOVELTY": {"score": 1-5, "comment": "不少于50字的评语"},
    "METHODOLOGY": {"score": 1-5, "comment": "不少于50字的评语"},
    "WRITING": {"score": 1-5, "comment": "不少于50字的评语"}
  },
  "recommendation": "ACCEPT|MINOR_REVISION|MAJOR_REVISION|REJECT",
  "overall_comment": "不少于100字的综合评语，概括论文核心内容、主要优缺点和修改方向",
  "suggestions": ["具体修改建议1", "具体修改建议2", ...]
}
"""


class AIReviewService:
    """AI 审稿服务"""

    @staticmethod
    def extract_pdf_text(file_path: str) -> str:
        """
        从 PDF 文件提取全文文本

        :param file_path: PDF 文件路径（相对 media 路径，或 media 内的绝对路径）
        :return: 提取的文本内容
        :raises FileNotFoundError: 文件不存在
        :raises ValueError: 路径越界（评审意见 V1.2 致命#2）或提取失败
        """
        # 评审意见 V1.2 致命#2：稿件字段曾是自由字符串，绝对路径/…/ 穿越
        # 会被直接 fitz.open——结合 PATCH 通道即任意服务端文件读取。
        # realpath 归一化后强制约束在 MEDIA_ROOT 之内，越界一律拒绝
        from django.conf import settings
        media_root = os.path.realpath(settings.MEDIA_ROOT)
        candidate = file_path if os.path.isabs(file_path) else os.path.join(
            settings.MEDIA_ROOT, file_path,
        )
        candidate = os.path.realpath(candidate)
        if not candidate.startswith(media_root + os.sep):
            raise ValueError(f"非法的稿件文件路径（越出媒体目录）: {file_path}")
        file_path = candidate

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"稿件文件不存在: {file_path}")

        try:
            doc = fitz.open(file_path)
            text_parts = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text_parts.append(page.get_text())
            doc.close()

            full_text = "\n".join(text_parts).strip()
            if not full_text:
                raise ValueError("PDF 文本提取结果为空，可能是扫描版 PDF")

            # 截断超长文本（GLM 上下文限制，保留前 3 万字符约 1-1.5 万字）
            max_chars = 30000
            if len(full_text) > max_chars:
                full_text = full_text[:max_chars]
                logger.info("PDF 文本已截断: 原始 %d 字符 -> 截断至 %d 字符", len(full_text), max_chars)

            logger.info("PDF 文本提取成功: %d 字符", len(full_text))
            return full_text

        except Exception as e:
            logger.error("PDF 文本提取失败: %s", str(e))
            raise ValueError(f"PDF 文本提取失败: {str(e)}")

    @staticmethod
    def build_review_prompt(paper_text: str, task_info: dict) -> str:
        """
        构建审稿 prompt

        :param paper_text: 论文全文
        :param task_info: 任务信息（标题、学科、摘要等）
        :return: 完整的 user prompt
        """
        prompt = f"""请审阅以下学术论文，按照四个维度（研究意义、创新性、研究方法、写作水平）给出评分和评语，并提供总体推荐意见和修改建议。

## 论文信息
- 标题：{task_info.get('title', '未知')}
- 学科：{task_info.get('subject_area', '未知')}
- 摘要：{task_info.get('abstract', '无')}

## 论文全文

{paper_text}

## 请输出 JSON 格式的审稿意见（不要输出其他内容）：
"""
        return prompt

    @staticmethod
    def call_llm(system_prompt: str, user_prompt: str) -> dict:
        """
        调用 LLM API

        :param system_prompt: 系统提示词
        :param user_prompt: 用户提示词
        :return: LLM 返回的 JSON 字典
        :raises ValueError: API key 未配置、API 调用失败或响应解析失败
        """
        if not LLM_API_KEY:
            raise ValueError(
                '未配置 REVIEWER_LLM_API_KEY 环境变量，AI 审稿功能不可用'
                '（在 backend/.env 中填写后重启服务）'
            )

        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,  # 低温度保证一致性
            "max_tokens": 4096,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            LLM_API_URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            content = result["choices"][0]["message"]["content"]

            # 清理可能的 markdown 代码块标记
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            parsed = json.loads(content)
            logger.info("LLM 审稿意见生成成功: recommendation=%s", parsed.get("recommendation"))
            return parsed

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            logger.error("LLM API 调用失败: HTTP %d - %s", e.code, error_body[:200])
            raise ValueError(f"LLM API 调用失败 (HTTP {e.code}): {error_body[:200]}")
        except json.JSONDecodeError as e:
            logger.error("LLM 响应 JSON 解析失败: %s", str(e))
            raise ValueError(f"LLM 响应解析失败: {str(e)}")
        except Exception as e:
            logger.error("LLM 调用异常: %s", str(e))
            raise ValueError(f"LLM 调用异常: {str(e)}")

    @staticmethod
    def generate_review(task) -> dict:
        """
        AI 审稿主入口：提取论文 -> 构建 prompt -> 调用 LLM -> 返回结构化结果

        :param task: ReviewTask 实例
        :return: dict 与前端表单兼容的数据结构
            {
                "dimension_scores": [{dimensionId, score, comment}, ...],
                "recommendation": "ACCEPT|MINOR_REVISION|MAJOR_REVISION|REJECT",
                "overall_comment": str,
                "suggestions": [str, ...]
            }
        :raises FileNotFoundError: 稿件文件不存在
        :raises ValueError: 处理失败
        """
        logger.info("AI 审稿开始: task=%s", task.task_id)

        # 1. 提取论文文本
        paper_text = AIReviewService.extract_pdf_text(task.manuscript_file)

        # 2. 构建任务信息
        task_info = {
            "title": task.title,
            "subject_area": task.subject_area,
            "abstract": task.abstract,
        }

        # 3. 构建 prompt
        user_prompt = AIReviewService.build_review_prompt(paper_text, task_info)

        # 4. 调用 LLM
        result = AIReviewService.call_llm(REVIEWER_SYSTEM_PROMPT, user_prompt)

        # 5. 转换为平台兼容的数据结构
        scores = result.get("scores", {})
        dimension_scores = []
        for dim_id in ["SIGNIFICANCE", "NOVELTY", "METHODOLOGY", "WRITING"]:
            dim_data = scores.get(dim_id, {})
            dimension_scores.append({
                "dimensionId": dim_id,
                "score": dim_data.get("score", 3),
                "comment": dim_data.get("comment", ""),
            })

        return {
            "dimension_scores": dimension_scores,
            "recommendation": result.get("recommendation", "MINOR_REVISION"),
            "overall_comment": result.get("overall_comment", ""),
            "suggestions": result.get("suggestions", []),
        }
