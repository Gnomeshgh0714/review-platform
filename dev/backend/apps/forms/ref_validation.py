"""
参考文献验证服务 - 从论文 PDF 提取参考文献并交叉验证真实性

核心流程：
1. 从 PDF 全文提取参考文献区（References/参考文献）
2. 解析每条参考文献（标题、作者、年份、期刊）
3. 调用 CrossRef / OpenAlex API 交叉验证
4. 返回验证结果（verified/partial/mismatch/not_found + 匹配详情）

参考项目：References-Validation (TypeScript) 的 Python 移植版
"""
import json
import logging
import re
import time
import urllib.request
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

# ===== 常量 =====
CROSSREF_API = "https://api.crossref.org/works"
OPENALEX_API = "https://api.openalex.org/works"
BATCH_DELAY = 1.2  # 秒，请求间延迟
MIN_TITLE_SIMILARITY = 70  # 最低标题相似度阈值


class ReferenceParser:
    """参考文献解析器 - 从 PDF 文本中提取参考文献列表"""

    # 参考文献区标题模式
    REFERENCES_SECTION_PATTERN = re.compile(
        r'(?:^|\n)\s*(References|REFERENCES|参考文献|Bibliography|BIBLIOGRAPHY|文献综述|引用文献)\s*(?:\n|\.|$)',
        re.MULTILINE
    )

    @staticmethod
    def extract_references_section(full_text: str) -> str:
        """从论文全文中提取参考文献区文本"""
        match = ReferenceParser.REFERENCES_SECTION_PATTERN.search(full_text)
        if not match:
            # 尝试找最后的 [1] 或 [1] 格式
            numbered = re.search(r'(\n\s*\[1\][\s\S]*)', full_text)
            if numbered:
                return numbered.group(1)
            return ""

        start = match.end()
        # 参考文献区一直到文末或下一个大标题
        rest = full_text[start:]
        # 截断到合理长度（避免提取附录）
        end_match = re.search(r'\n\s*(Appendix|附录|Acknowledg|致谢)\s*\n', rest)
        if end_match:
            rest = rest[:end_match.start()]
        return rest.strip()

    @staticmethod
    def parse_references(ref_text: str) -> list:
        """
        将参考文献区文本解析为单条参考文献列表

        支持格式：
        - [1] Author, Title, Journal, Year
        - 1. Author, Title, Journal, Year
        - Author, A., & Author, B. (Year). Title. Journal.
        """
        if not ref_text:
            return []

        refs = []

        # 尝试按编号分割 [1] [2] 或 1. 2.
        numbered = re.split(r'\n\s*(?:\[(\d+)\]|(\d+)\.)\s*', ref_text)
        if len(numbered) > 3:
            # numbered 格式：['', '1', '', ' ref1 text', '2', '', ' ref2 text', ...]
            current = ""
            for part in numbered:
                if part and not part.strip().isdigit() and len(part.strip()) > 10:
                    current = part.strip()
                    if current:
                        refs.append(current)
        else:
            # 按空行分割
            blocks = re.split(r'\n\s*\n', ref_text)
            for block in blocks:
                block = block.strip()
                if len(block) > 20:
                    # 合并跨行引用
                    refs.append(block.replace('\n', ' '))

        # 过滤太短的
        refs = [r for r in refs if len(r) > 15]
        logger.info("解析出 %d 条参考文献", len(refs))
        return refs

    @staticmethod
    def extract_metadata(ref: str) -> dict:
        """从单条参考文献中提取元数据（标题、作者、年份）"""
        result = {'raw': ref}

        # 提取 DOI
        doi_match = re.search(r'(?:DOI\s*[：:]\s*|https?://doi\.org/)?(10\.\d{4,}/[^\s,;]+)', ref, re.I)
        if doi_match:
            result['doi'] = doi_match.group(1).rstrip('.')

        # 提取年份
        years = re.findall(r'\b(19|20)\d{2}\b', ref)
        if years:
            result['year'] = years[0]

        # 提取标题（启发式：取最长的那段文字）
        # 去掉编号前缀
        cleaned = re.sub(r'^\s*\[?\d+\]?\.?\s*', '', ref)
        # 按句号/句点分割
        segments = re.split(r'[.。]', cleaned)
        segments = [s.strip() for s in segments if len(s.strip()) > 10]

        if segments:
            # 最长的段通常是标题
            title = max(segments, key=len)
            # 清理
            title = re.sub(r'^[A-Z]{1,4}\s+', '', title)  # 去掉作者缩写
            result['title'] = title[:300]
            result['search_query'] = title[:200]

        return result


class SimilarityCalculator:
    """文本相似度计算"""

    @staticmethod
    def normalize(s: str) -> str:
        """标准化字符串：去重音、转小写、去标点"""
        import unicodedata
        nfkd = unicodedata.normalize('NFKD', s)
        without_accents = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return re.sub(r'[^\w\s]', '', without_accents.lower()).strip()

    @staticmethod
    def levenshtein(a: str, b: str) -> int:
        """Levenshtein 编辑距离"""
        m, n = len(a), len(b)
        if m == 0:
            return n
        if n == 0:
            return m
        dp = list(range(n + 1))
        for i in range(1, m + 1):
            prev = dp[0]
            dp[0] = i
            for j in range(1, n + 1):
                temp = dp[j]
                dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (0 if a[i - 1] == b[j - 1] else 1))
                prev = temp
        return dp[n]

    @staticmethod
    def word_overlap(s1: str, s2: str) -> int:
        """词重叠相似度（Jaccard）"""
        w1 = set(re.sub(r'[^\w\s]', '', s1.lower()).split())
        w2 = set(re.sub(r'[^\w\s]', '', s2.lower()).split())
        if not w1 or not w2:
            return 0
        intersection = w1 & w2
        union = w1 | w2
        return round(len(intersection) / len(union) * 100) if union else 0

    @classmethod
    def title_similarity(cls, expected: str, actual: str) -> int:
        """计算标题相似度（取 Levenshtein 和 word-overlap 的最大值）"""
        if not expected or not actual:
            return 0
        n1 = cls.normalize(expected)
        n2 = cls.normalize(actual)
        if n1 == n2:
            return 100

        # Levenshtein 相似度
        dist = cls.levenshtein(n1, n2)
        max_len = max(len(n1), len(n2))
        leven_sim = max(0, round((1 - dist / max_len) * 100)) if max_len > 0 else 0

        # Word overlap
        word_sim = cls.word_overlap(expected, actual)

        return max(leven_sim, word_sim)

    @classmethod
    def author_similarity(cls, expected: str, actual_authors: list) -> int:
        """计算作者相似度"""
        if not expected or not actual_authors:
            return 100
        n_expected = cls.normalize(expected)
        match_count = 0
        valid = 0
        for author in actual_authors:
            parts = cls.normalize(author).split()
            parts = [p for p in parts if not re.match(r'^\d+$', p)]
            if not parts:
                continue
            family = parts[-1]
            if len(family) > 1:
                valid += 1
                if family in n_expected:
                    match_count += 1
        if valid == 0:
            return 100
        # "et al" 处理
        if re.search(r'et\s*al|and\s*others', expected, re.I) and match_count > 0:
            return 100
        return round(match_count / valid * 100)


class ReferenceValidator:
    """参考文献验证器 - 调用学术 API 交叉验证"""

    @staticmethod
    def _fetch_json(url: str, timeout: int = 15) -> dict:
        """HTTP GET 并返回 JSON"""
        req = urllib.request.Request(url, headers={
            'User-Agent': 'ReviewPlatform/1.0 (mailto:editor@test.com)',
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))

    @staticmethod
    def check_crossref(query: str, expected: dict) -> Optional[dict]:
        """查询 CrossRef API"""
        try:
            encoded = urllib.parse.quote(query[:200])
            url = f"{CROSSREF_API}?query={encoded}&rows=3"
            data = ReferenceValidator._fetch_json(url)
            items = data.get('message', {}).get('items', [])
            if not items:
                return None

            best = items[0]
            title = best.get('title', [''])[0] if best.get('title') else ''
            authors = best.get('author', [])
            author_names = [f"{a.get('family', '')}" for a in authors]
            year = ''
            for field in ['published-print', 'published', 'issued']:
                dp = best.get(field, {}).get('date-parts', [[None]])
                if dp and dp[0] and dp[0][0]:
                    year = str(dp[0][0])
                    break
            journal = best.get('container-title', [''])[0] if best.get('container-title') else ''
            doi = best.get('DOI', '')
            is_retracted = best.get('is-referenced-by-count', 0) > 0 and best.get('reference', []) == []

            # 计算匹配度
            title_sim = SimilarityCalculator.title_similarity(
                expected.get('title', query), title
            )
            author_sim = SimilarityCalculator.author_similarity(
                expected.get('authors', query), author_names
            )

            confidence = (title_sim * 2 + author_sim) // 3

            return {
                'exists': title_sim >= MIN_TITLE_SIMILARITY,
                'title': title,
                'authors': ', '.join(author_names),
                'year': year,
                'journal': journal,
                'doi': doi,
                'retracted': is_retracted,
                'match_confidence': min(100, confidence),
                'title_match_score': title_sim,
                'author_match_score': author_sim,
                'source': 'CrossRef',
                'issues': [],
            }
        except Exception as e:
            logger.warning("CrossRef 查询失败: %s", str(e))
            return None

    @staticmethod
    def check_openalex(query: str, expected: dict) -> Optional[dict]:
        """查询 OpenAlex API"""
        try:
            encoded = urllib.parse.quote(query[:200])
            url = f"{OPENALEX_API}?search={encoded}&per_page=3"
            data = ReferenceValidator._fetch_json(url)
            results = data.get('results', [])
            if not results:
                return None

            best = results[0]
            title = best.get('title', '') or best.get('display_name', '')
            author_objs = best.get('authorships', [])
            author_names = [a.get('author', {}).get('display_name', '') for a in author_objs]
            year = str(best.get('publication_year', '')) if best.get('publication_year') else ''
            journal = ''
            if best.get('host_venue'):
                journal = best['host_venue'].get('display_name', '')
            doi = (best.get('doi', '') or '').replace('https://doi.org/', '')
            citations = best.get('cited_by_count', 0)
            is_retracted = best.get('is_retracted', False)

            title_sim = SimilarityCalculator.title_similarity(
                expected.get('title', query), title
            )
            author_sim = SimilarityCalculator.author_similarity(
                expected.get('authors', query), author_names
            )
            confidence = (title_sim * 2 + author_sim) // 3

            return {
                'exists': title_sim >= MIN_TITLE_SIMILARITY,
                'title': title,
                'authors': ', '.join(author_names),
                'year': year,
                'journal': journal,
                'doi': doi,
                'retracted': is_retracted,
                'citations': citations,
                'match_confidence': min(100, confidence),
                'title_match_score': title_sim,
                'author_match_score': author_sim,
                'source': 'OpenAlex',
                'issues': [],
            }
        except Exception as e:
            logger.warning("OpenAlex 查询失败: %s", str(e))
            return None

    @staticmethod
    def classify_result(result: dict) -> str:
        """分类验证结果"""
        if not result or not result.get('exists'):
            return 'not_found'
        conf = result.get('match_confidence', 0)
        if conf >= 80:
            return 'verified'
        if conf >= 50:
            return 'partial_match'
        return 'mismatch'

    @staticmethod
    def validate_single(ref: str) -> dict:
        """
        验证单条参考文献

        :param ref: 参考文献文本
        :return: 验证结果字典
        """
        metadata = ReferenceParser.extract_metadata(ref)
        query = metadata.get('search_query', ref[:200])

        # 先查 CrossRef，再查 OpenAlex
        result = ReferenceValidator.check_crossref(query, metadata)
        if result and result['exists'] and result['match_confidence'] >= 80:
            result['status'] = ReferenceValidator.classify_result(result)
            result['input'] = ref
            return result

        # OpenAlex fallback
        oa_result = ReferenceValidator.check_openalex(query, metadata)
        if oa_result and oa_result['exists']:
            if not result or oa_result['match_confidence'] > result.get('match_confidence', 0):
                result = oa_result

        if not result:
            result = {
                'exists': False,
                'source': 'NotFound',
                'match_confidence': 0,
                'title_match_score': 0,
                'author_match_score': 0,
                'issues': [],
            }

        result['status'] = ReferenceValidator.classify_result(result)
        result['input'] = ref
        return result

    @staticmethod
    def validate_batch(refs: list, progress_callback=None) -> dict:
        """
        批量验证参考文献

        :param refs: 参考文献文本列表
        :param progress_callback: 可选的进度回调 (current, total)
        :return: {total, verified, partial, mismatch, not_found, results: [...]}
        """
        results = []
        total = len(refs)

        for i, ref in enumerate(refs):
            if progress_callback:
                progress_callback(i + 1, total)

            result = ReferenceValidator.validate_single(ref)
            results.append(result)

            # 速率限制
            if i < total - 1:
                time.sleep(BATCH_DELAY)

        # 统计
        stats = {'verified': 0, 'partial_match': 0, 'mismatch': 0, 'not_found': 0}
        for r in results:
            stats[r['status']] += 1

        return {
            'total': total,
            'verified': stats['verified'],
            'partial_match': stats['partial_match'],
            'mismatch': stats['mismatch'],
            'not_found': stats['not_found'],
            'results': results,
        }


class ReferenceValidationService:
    """参考文献验证服务 - 主入口"""

    @staticmethod
    def validate_task_references(task) -> dict:
        """
        验证任务关联稿件的参考文献

        :param task: ReviewTask 实例
        :return: 验证结果字典
        """
        from apps.forms.ai_review import AIReviewService

        # 1. 提取 PDF 全文
        paper_text = AIReviewService.extract_pdf_text(task.manuscript_file)

        # 2. 提取参考文献区
        ref_section = ReferenceParser.extract_references_section(paper_text)
        if not ref_section:
            return {
                'total': 0,
                'error': '未找到参考文献区（References/参考文献）',
                'results': [],
            }

        # 3. 解析参考文献
        refs = ReferenceParser.parse_references(ref_section)
        if not refs:
            return {
                'total': 0,
                'error': '参考文献区未解析出有效条目',
                'results': [],
            }

        # 限制批量大小（避免超时）
        max_refs = 20
        if len(refs) > max_refs:
            logger.info("参考文献 %d 条，截断至 %d 条", len(refs), max_refs)
            refs = refs[:max_refs]

        # 4. 批量验证
        logger.info("开始验证 %d 条参考文献: task=%s", len(refs), task.task_id)
        result = ReferenceValidator.validate_batch(refs)
        logger.info(
            "参考文献验证完成: task=%s, total=%d, verified=%d, not_found=%d",
            task.task_id, result['total'], result['verified'], result['not_found']
        )
        return result
