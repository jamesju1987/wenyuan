"""模型调用：Jev（快速判断，只做选择题）+ DeepSeek（读正文，生成标题、日期、摘要；关键词拿不准时也判断项目和类型）。"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import config
from . import standards as S


class AIError(Exception):
    pass


# ---------------------------------------------------------------- Jev
def jev_request(state: Any, questions: Dict[str, Dict], timeout: float = 30) -> Tuple[Dict, Dict, int]:
    """POST /v1/systemone；429/529 指数退避重试。返回 (响应, 请求体, 耗时毫秒)。"""
    key = str(config.get("jev_api_key") or "").strip()
    if not key:
        raise AIError("未配置 Jev API Key")
    body = {"model": config.get("jev_model") or "jev-latest", "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    t0 = time.time()
    last = ""
    for attempt in range(3):
        try:
            r = httpx.post(str(config.get("jev_endpoint")), json=body, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            last = f"网络错误：{e}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 529):
            last = f"Jev 繁忙（{r.status_code}）"
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            raise AIError(f"Jev 返回 {r.status_code}：{r.text[:300]}")
        return r.json(), body, int((time.time() - t0) * 1000)
    raise AIError(last or "Jev 调用失败")


def jev_classify(file_name: str, folder: str, text: str, projects: List[Dict],
                 include_project: bool = True) -> Tuple[Dict, Dict, Dict, int]:
    """一次调用并行问四个问题：项目、类型、状态、是否敏感。"""
    state = {"文件名": file_name, "所在文件夹": folder, "正文开头": text or "（无可读正文）"}
    questions: Dict[str, Dict] = {}
    if include_project and projects:
        criteria: Dict[str, Optional[str]] = {}
        for p in projects[:254]:
            desc = f"客户：{p['customer_short']}（{p.get('customer_full') or p['customer_short']}）；项目：{p['name']}"
            if p.get("biz_line"):
                desc += f"；业务线：{p['biz_line']}"
            if p.get("aliases"):
                desc += f"；别名：{'、'.join(p['aliases'][:5])}"
            criteria[p["project_no"]] = desc
        criteria["none"] = "以上项目都不符合，或无法判断"
        questions["project"] = {
            "type": "choice",
            "instructions": "这个文件属于哪个项目？依据文件名、客户名称、系统名称和正文内容判断；不确定时选 none。",
            "criteria": criteria,
        }
    questions["doc_type"] = {
        "type": "choice",
        "instructions": "这个文件是哪一类项目文档？",
        "criteria": {t["code"]: f"{t['name']}，常见关键词：{'、'.join(t['kw'][:6]) or '无'}" for t in S.TYPE_CODES},
    }
    questions["status"] = {
        "type": "choice",
        "instructions": "这个文件处于什么状态？",
        "criteria": dict(S.STATUS_DESC),
    }
    questions["sensitive"] = {
        "type": "noul",
        "instructions": "正文是否包含漏洞细节、账号口令、密钥或个人身份信息？",
        "criteria": {"true": "包含上述任一敏感信息", "false": "不包含"},
    }
    resp, body, ms = jev_request(state, questions)
    answers = resp.get("answers") or {}
    return answers, body, resp, ms


def choice_top(answer: Optional[Dict]) -> Tuple[Optional[str], float, List[Tuple[str, float]]]:
    if not answer or answer.get("type") != "choice":
        return None, 0.0, []
    probs = answer.get("probabilities") or {}
    ranked = sorted(((k, float(v)) for k, v in probs.items()), key=lambda kv: kv[1], reverse=True)
    choice = answer.get("choice")
    p = float(probs.get(choice, answer.get("confidence") or 0.0))
    return choice, p, ranked


# ---------------------------------------------------------------- DeepSeek
TITLE_PROMPT = """你是项目文档归档助手。阅读文件名和正文开头，输出 JSON：
{"title": "文档标题", "doc_date": "YYYY-MM-DD 或 空字符串", "summary": "一句话摘要"}
规则：
1. title 不超过 30 个字，格式为「客户简称 + 内容主题」，例如「澄湾科技等保测评报告」。
2. title 去掉「最终版」「最新」「终稿」「修改版」「副本」、版本号、日期、项目编号等噪声。
3. title 中不要出现空格、下划线和 \\ / : * ? " < > | 等字符。
4. doc_date 取报告落款日期、会议日期或文档内容日期；找不到填空字符串，不要编造。
5. summary 不超过 60 个字，说明这是什么文件、主要内容。
只输出 JSON，不要其他文字。"""


JUDGE_PROMPT = """你是项目文档归档助手。阅读文件名、所在文件夹和正文开头，判断文件属于哪个项目、是哪类文档，并生成标题。输出 JSON：
{"project": "候选项目编号，或 none", "project_confidence": 0到1的小数, "project_evidence": "能证明归属的原文片段",
 "doc_type": "类型码", "type_confidence": 0到1的小数,
 "title": "文档标题", "doc_date": "YYYY-MM-DD 或 空字符串", "summary": "一句话摘要"}
判断规则：
1. project 只能填候选项目里的项目编号。看不出属于哪个客户或项目时填 none，不要猜。
2. 先认客户：客户全称、简称、英文名、缩写、系统或产品名称都可以作依据。同一客户有多个项目时，再按正文讲的业务（渗透测试、等保测评、数据安全、攻防演练、驻场运维等）和项目名称区分。
3. project_evidence 原样摘抄文件名、文件夹或正文里出现的文字（不超过 20 字），最好是客户名称或系统名称；找不到填空字符串。
4. confidence 如实给：有明确依据 0.9 以上；有一些线索但不确定 0.6 左右；基本靠猜 0.3 以下。
5. doc_type 只能填下面列出的类型码，选最贴切的一个。
6. title 不超过 30 个字，格式为「客户简称 + 内容主题」；去掉「最终版」「最新」「终稿」「修改版」「副本」、版本号、日期、项目编号等噪声；不要出现空格、下划线和 \\ / : * ? " < > | 等字符。
7. doc_date 取报告落款日期、会议日期或文档内容日期；找不到填空字符串，不要编造。summary 不超过 60 个字。
只输出 JSON，不要其他文字。

类型码（类型码｜名称｜常见关键词）：
"""


def _project_line(p: Dict) -> str:
    line = f"{p['project_no']}｜客户：{p['customer_short']}"
    if p.get("customer_full") and p["customer_full"] != p["customer_short"]:
        line += f"（{p['customer_full']}）"
    line += f"｜项目：{p['name']}"
    if p.get("biz_line"):
        line += f"｜业务线：{p['biz_line']}"
    if p.get("aliases"):
        line += f"｜别名：{'、'.join(p['aliases'][:5])}"
    return line


def _conf(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    if x > 1:            # 有时会给成百分数
        x = x / 100
    return max(0.0, min(1.0, x))


def deepseek_analyze(file_name: str, text: str, customer_short: str = "", type_name: str = "",
                     timeout: float = 40, projects: Optional[List[Dict]] = None, ask_type: bool = False,
                     folder: str = "") -> Tuple[Dict, Dict, Dict, int]:
    """默认只生成标题、日期、摘要。传 projects / ask_type 时同一次调用里顺便判断项目、类型
    （这时不给关键词的结论作提示，让它独立判断）。"""
    key = str(config.get("deepseek_api_key") or "").strip()
    if not key:
        raise AIError("未配置 DeepSeek API Key")
    judge = bool(projects) or ask_type
    if judge:
        system = JUDGE_PROMPT + "\n".join(
            f"{t['code']}｜{t['name']}｜{'、'.join(t['kw'][:6]) or '无'}" for t in S.TYPE_CODES)
        parts = []
        if projects:
            parts.append("候选项目（项目编号｜客户｜项目｜业务线）：\n" + "\n".join(_project_line(p) for p in projects[:200]))
        else:
            parts.append("项目已经确定，project 填 none、project_confidence 填 0 即可。")
        parts.append(f"文件名：{file_name}")
        if folder:
            parts.append(f"所在文件夹：{folder}")
        parts.append(f"正文开头：\n{text or '（无可读正文）'}")
        user = "\n\n".join(parts)
    else:
        system = TITLE_PROMPT
        hint = []
        if customer_short:
            hint.append(f"客户简称：{customer_short}")
        if type_name:
            hint.append(f"文档类型：{type_name}")
        user = f"文件名：{file_name}\n" + ("\n".join(hint) + "\n" if hint else "") + f"正文开头：\n{text or '（无可读正文）'}"
    body = {
        "model": config.get("deepseek_model") or "deepseek-v4-flash",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.1 if judge else 0.2,
        "max_tokens": 500 if judge else 300,
        "response_format": {"type": "json_object"},
    }
    url = str(config.get("deepseek_base_url") or "https://api.deepseek.com").rstrip("/") + "/chat/completions"
    t0 = time.time()
    last = ""
    for attempt in range(3):
        try:
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        except httpx.HTTPError as e:
            last = f"网络错误：{e}"
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 503):
            last = f"DeepSeek 繁忙（{r.status_code}）"
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 400:
            raise AIError(f"DeepSeek 返回 {r.status_code}：{r.text[:300]}")
        resp = r.json()
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        data = _parse_json(content)
        d = str(data.get("doc_date") or "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            d = ""
        result = {"title": str(data.get("title") or "").strip(), "doc_date": d,
                  "summary": str(data.get("summary") or "").strip()[:120]}
        if judge:
            nos = {p["project_no"] for p in (projects or [])}
            pj = str(data.get("project") or "").strip()
            if projects:
                result["project"] = pj if pj in nos else "none"
                result["project_p"] = _conf(data.get("project_confidence"))
                result["project_evidence"] = str(data.get("project_evidence") or "").strip()[:40]
            if ask_type:
                tc = str(data.get("doc_type") or "").strip().upper()
                result["doc_type"] = tc if tc in S.TYPE_MAP else ""
                result["type_p"] = _conf(data.get("type_confidence"))
        return result, body, resp, int((time.time() - t0) * 1000)
    raise AIError(last or "DeepSeek 调用失败")


def _parse_json(s: str) -> Dict:
    s = (s or "").strip()
    s = re.sub(r"^```(json)?|```$", "", s, flags=re.M).strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


# ---------------------------------------------------------------- 连接测试
def test_jev() -> Dict:
    answers, _, resp, ms = None, None, None, 0
    resp, _, ms = jev_request("测试：上海某公司渗透测试报告，含漏洞详情。", {
        "kind": {"type": "choice", "instructions": "这是什么文件？",
                 "criteria": {"report": "报告", "contract": "合同"}}})
    a = (resp.get("answers") or {}).get("kind") or {}
    return {"ok": True, "ms": ms, "model": resp.get("model"), "answer": a.get("choice")}


def test_deepseek() -> Dict:
    """顺便试一次判断：两个虚构的候选项目里应该选中等保那个。"""
    demo = [{"project_no": "TEST-001", "customer_short": "澄湾科技", "customer_full": "上海澄湾科技有限公司",
             "name": "澄湾科技等保测评2026", "biz_line": "等保"},
            {"project_no": "TEST-002", "customer_short": "澄湾科技", "customer_full": "上海澄湾科技有限公司",
             "name": "澄湾科技渗透测试2026", "biz_line": "渗透测试"}]
    result, _, resp, ms = deepseek_analyze("最终版(2).docx",
                                           "上海澄湾科技有限公司 网络安全等级保护测评报告 2026年10月16日",
                                           projects=demo, ask_type=True)
    return {"ok": True, "ms": ms, "model": resp.get("model"), "title": result.get("title"),
            "judge": result.get("project") == "TEST-001", "project_p": result.get("project_p"),
            "doc_type": result.get("doc_type")}
