"""模型调用：Jev（快速判断，只做选择题）+ DeepSeek（读正文，生成标题、日期、摘要）。"""
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


def deepseek_analyze(file_name: str, text: str, customer_short: str = "", type_name: str = "",
                     timeout: float = 40) -> Tuple[Dict, Dict, Dict, int]:
    key = str(config.get("deepseek_api_key") or "").strip()
    if not key:
        raise AIError("未配置 DeepSeek API Key")
    hint = []
    if customer_short:
        hint.append(f"客户简称：{customer_short}")
    if type_name:
        hint.append(f"文档类型：{type_name}")
    user = f"文件名：{file_name}\n" + ("\n".join(hint) + "\n" if hint else "") + f"正文开头：\n{text or '（无可读正文）'}"
    body = {
        "model": config.get("deepseek_model") or "deepseek-v4-flash",
        "messages": [{"role": "system", "content": TITLE_PROMPT}, {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": 300,
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
    result, _, resp, ms = deepseek_analyze("澄湾科技等保测评报告-最终版(2).docx",
                                           "上海澄湾科技有限公司 网络安全等级保护测评报告 2026年10月16日")
    return {"ok": True, "ms": ms, "model": resp.get("model"), "title": result.get("title")}
