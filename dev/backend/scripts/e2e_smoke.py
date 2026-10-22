"""审稿协作平台全链路冒烟测试

默认路径（纯 API 直连）：编辑部建任务 -> 分配3位审稿人 -> 接受邀请 -> 各自提交意见
     -> 自动转SUBMITTED -> 生成汇总报告 -> 录入终审决策 -> 验证状态日志与通知

可选路径（--frontend，决策 #014 挂账项）：在 API 冒烟前先做「经前端构建产物」的
冒烟——npx vite build 产出 dist 后起本地静态服务，断言入口 HTML 与其引用的
JS/CSS 资源均可达。范围是构建产物完整性，不含浏览器渲染级验证。
不带开关时与本脚本既往行为完全一致。
"""
import argparse
import functools
import http.server
import json
import re
import socket
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:8000/api'
FRONTEND_DIR = Path(__file__).resolve().parents[2] / 'frontend'
DIST_DIR = FRONTEND_DIR / 'dist'
OK, FAIL = [], []

parser = argparse.ArgumentParser(description='审稿协作平台全链路冒烟测试')
parser.add_argument('--frontend', action='store_true',
                    help='先做前端构建产物冒烟（vite build + 静态服务断言），再跑 API 全链路')
ARGS = parser.parse_args()


def call(method, path, token=None, body=None, expect=200):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json',
                 **({'Authorization': f'Bearer {token}'} if token else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            status = resp.status
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode())
        status = e.code
    label = f'{method} {path} -> {status}'
    if status == expect:
        OK.append(label)
    else:
        FAIL.append(f'{label} (期望{expect}): {json.dumps(data, ensure_ascii=False)[:200]}')
    return status, data


def login(email):
    _, data = call('POST', '/users/login/', body={'email': email, 'password': 'Demo@2026'})
    return data['access'], data['user']


# ============ 可选：经前端构建产物的冒烟路径（--frontend，决策 #014 挂账项） ============

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _record(ok, label, detail=''):
    if ok:
        OK.append(label)
    elif detail:
        FAIL.append(f'{label}: {detail}')
    else:
        FAIL.append(label)
    print(f'   {"PASS" if ok else "FAIL"}  {label}')


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _http_get(url):
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.status, resp.read().decode('utf-8', 'replace')


def frontend_smoke():
    """构建产物完整性这一档：可构建、入口可达、引用资源均 200。"""
    print('== 0. 前端构建产物冒烟（--frontend）==')
    # 0-1 构建可产出 dist（复用前端工程自身的 vite build，不额外接构建逻辑）
    build = subprocess.run(['npx', 'vite', 'build'], cwd=FRONTEND_DIR,
                           capture_output=True, text=True)
    _record(build.returncode == 0, 'vite build 产出 dist',
            (build.stderr or build.stdout).strip().splitlines()[-1] if build.returncode else '')
    if build.returncode != 0:
        return
    # 0-2 入口与资源文件存在
    index = DIST_DIR / 'index.html'
    _record(index.is_file(), 'dist/index.html 存在')
    assets_dir = DIST_DIR / 'assets'
    assets = sorted(assets_dir.glob('*')) if assets_dir.is_dir() else []
    _record(any(a.suffix == '.js' for a in assets) and any(a.suffix == '.css' for a in assets),
            f'dist/assets 含 JS 与 CSS（共 {len(assets)} 个文件）')
    if not index.is_file():
        return
    # 0-3 入口 HTML 可达且引用的 JS/CSS 资源全部 200（用 Python 标准库静态服务）
    port = _free_port()
    handler = functools.partial(_QuietHandler, directory=str(DIST_DIR))
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, html = _http_get(f'http://127.0.0.1:{port}/')
        _record(status == 200 and 'id="app"' in html, 'GET / 返回入口 index.html')
        refs = re.findall(r'(?:src|href)="(/assets/[^"]+?\.(?:js|css))"', html)
        missing = []
        for ref in refs:
            try:
                st, body = _http_get(f'http://127.0.0.1:{port}{ref}')
                if st != 200 or not body:
                    missing.append(ref)
            except Exception as e:  # noqa: BLE001
                missing.append(f'{ref} ({e})')
        _record(bool(refs) and not missing,
                f'入口引用的 JS/CSS 资源全部可达（{len(refs)} 个）', '; '.join(missing))
    finally:
        httpd.shutdown()
        httpd.server_close()


if ARGS.frontend:
    frontend_smoke()

print('== 1. 登录三类角色 ==')
tok_editor, editor = login('editor@review.local')
tok_author, author = login('author@review.local')
# 演示审稿人：ID 与登录令牌一一对应（不依赖 reviewers 列表的筛选顺序）
reviewer_logins = [login(f'reviewer{i + 1}@review.local') for i in range(3)]
reviewer_tokens = [t for t, _ in reviewer_logins]
reviewer_ids = [u['user_id'] for _, u in reviewer_logins]
print(f'   editor={editor["user_id"]} author={author["user_id"]} reviewers={reviewer_ids}')

print('== 2. 权限负例：审稿人建任务应被拒 ==')
call('POST', '/tasks/', reviewer_tokens[0], body={'title': 'x'}, expect=403)

print('== 3. 编辑部创建审稿任务 ==')
_, templates = call('GET', '/templates/', tok_editor)
tpl_id = next(t['template_id'] for t in templates['results']
              if t['template_type'] == 'SYSTEM_DEFAULT')
_, task = call('POST', '/tasks/', tok_editor, body={
    'title': '气候风险与企业劳动收入份额——冒烟测试稿件',
    'abstract': '本文利用全球企业调查数据考察气候风险对劳动收入份额的影响。',
    'keywords': ['气候风险', '劳动收入份额', '企业调查'],
    'subject_area': '经济学', 'manuscript_type': '论文',
    'manuscript_file': 'smoke_test.pdf', 'review_mode': 'SINGLE_BLIND',
    'expected_reviewer_count': 3, 'deadline': '2026-12-31',
    'template_id': tpl_id, 'author_user_id': author['user_id'],
}, expect=201)
task_id = task['task_id']
print(f'   任务 {task_id} 状态={task["status"]}')

print('== 4. 分配3位审稿人 ==')
call('POST', f'/tasks/{task_id}/assign_reviewers/', tok_editor,
     body={'reviewer_user_ids': reviewer_ids}, expect=200)

print('== 5. 三位审稿人接受邀请 ==')
for tok in reviewer_tokens:
    call('POST', f'/tasks/{task_id}/accept_invitation/', tok, body={}, expect=200)
_, task = call('GET', f'/tasks/{task_id}/', tok_editor)
print(f'   任务状态={task["status"]}（期望 REVIEWING）')
assert task['status'] == 'REVIEWING', '状态机 REVIEWING 转换失败'

print('== 6. 三位审稿人提交四维意见（含分歧设计：接收/小修/拒稿 -> Rule-7）==')
recs = ['ACCEPT', 'MINOR_REVISION', 'REJECT']
for i, tok in enumerate(reviewer_tokens):
    scores = [
        {'dimensionId': d, 'score': 5 if i == 0 else (2 if i == 2 else 4),
         'comment': '该维度表现' + '总体符合学术规范与发表要求，论证链条完整清晰' * 3}
        for d in ['D1', 'D2', 'D3', 'D4']
    ]
    base_comment = ('综合来看，论文选题具有学术价值与现实意义，实证设计基本合理，'
                    '但识别策略与稳健性检验仍有明显不足，结论的外部效度需要进一步论证。')
    call('POST', '/opinions/submit/', tok, body={
        'task_id': task_id, 'dimension_scores': scores,
        'recommendation': recs[i],
        'overall_comment': base_comment * 2,
        'revision_suggestions': ['补充平行趋势检验', '报告不含控制变量的对照回归'],
    }, expect=201)

_, task = call('GET', f'/tasks/{task_id}/', tok_editor)
print(f'   全部提交后任务状态={task["status"]}（期望 SUBMITTED，自动转换）')
assert task['status'] == 'SUBMITTED', 'C-04 自动转换失败'

print('== 7. 生成汇总报告 ==')
_, report = call('POST', '/summaries/generate/', tok_editor,
                 body={'task_id': task_id}, expect=201)
print(f'   规则={report["system_recommendation"]["matchedRuleId"]} '
      f'分歧点={len(report["conflict_points"])} 一致点={len(report["consensus_points"])}')
assert report['system_recommendation']['matchedRuleId'] == 'Rule-7', '规则引擎期望 Rule-7'

print('== 8. 录入终审决策 ==')
decision_notes = (
    '鉴于三位审稿人意见存在严重分歧（接收与拒稿并存，规则引擎命中 Rule-7），'
    '且方法论维度评分差距显著，编辑部经讨论决定给予大修机会。'
    '请作者按照审稿意见逐条修改，重点补充识别策略的讨论与稳健性检验，'
    '并随修改稿提交逐条修改说明。修改稿将返回原审稿人复审，'
    '若复审后分歧仍未收敛，将提交主编会议裁定。'
)
assert len(decision_notes) >= 100
call('POST', f'/tasks/{task_id}/make_decision/', tok_editor, body={
    'decision': 'MAJOR_REVISION',
    'notes': decision_notes,
    'publish': True,
}, expect=200)
_, task = call('GET', f'/tasks/{task_id}/', tok_editor)
print(f'   终审后任务状态={task["status"]}（期望 DECIDED）')
assert task['status'] == 'DECIDED'

print('== 9. 状态日志链 ==')
_, logs = call('GET', f'/tasks/{task_id}/state_logs/', tok_editor)
chrono = list(reversed(logs))
chain = ' -> '.join([chrono[0]['from_state']] + [l['to_state'] for l in chrono])
print(f'   {chain}')
assert chain == 'PENDING -> ASSIGNED -> REVIEWING -> SUBMITTED -> SUMMARIZED -> DECIDED'

print('== 10. 作者侧可见性（通知+稿件列表）==')
_, articles = call('GET', '/tasks/my_articles/', tok_author)
assert any(a['task_id'] == task_id for a in articles['results']), '作者看不到自己稿件'
print(f'   作者稿件数={articles["count"]}')

print()
print(f'通过 {len(OK)} 项')
for f in FAIL:
    print('失败:', f)
exit(1 if FAIL else 0)
