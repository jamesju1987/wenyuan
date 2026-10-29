"""归档规范：阶段目录、交付物类型码、业务线、状态与命名规则。"""
from __future__ import annotations

import json
import re
from typing import Dict, List

STAGES: List[str] = [
    "00_项目管理",
    "01_售前商务",
    "02_项目启动",
    "03_过程文档",
    "04_交付成果",
    "05_验收结项",
    "06_客户资料",
    "_历史版本",
    "_归档包",
]
EVIDENCE_DIR = "03_过程文档/证据"
HISTORY_DIR = "_历史版本"
PACKAGE_DIR = "_归档包"

STATUSES: List[str] = ["草稿", "内审", "送审", "正式", "签字"]
DRAFT_STATUSES = {"草稿", "内审", "送审"}

STATUS_DESC: Dict[str, str] = {
    "草稿": "初稿、草稿、征求意见稿，尚未定稿",
    "内审": "公司内部审核中的版本",
    "送审": "已提交客户评审、待客户反馈的版本",
    "正式": "定稿、正式发布或正式交付的版本",
    "签字": "已签字或盖章的扫描件、确认件",
}

STATUS_KEYWORDS: Dict[str, List[str]] = {
    "签字": ["签字", "签章", "盖章", "签署", "已签", "扫描件"],
    "正式": ["正式", "定稿", "终稿", "final", "发布版"],
    "送审": ["送审", "评审稿", "送客户", "待确认"],
    "内审": ["内审", "内部审核", "审核稿"],
    "草稿": ["草稿", "初稿", "draft", "征求意见", "讨论稿"],
}

# 类型码 → 名称、归档目录、识别关键词（越长越具体，权重越高）
BUILTIN_TYPES: List[Dict] = [
    {"code": "PM-PLAN", "name": "项目计划/实施方案", "stage": "00_项目管理",
     "kw": ["实施计划", "项目计划", "实施方案", "进度计划", "里程碑", "工作计划", "进度安排"]},
    {"code": "PM-WR", "name": "周报/日报", "stage": "00_项目管理", "series": True,
     "kw": ["周报", "日报", "月报", "本周工作", "下周计划", "工作汇报"]},
    {"code": "PM-MOM", "name": "会议纪要", "stage": "00_项目管理", "series": True,
     "kw": ["启动会纪要", "会议纪要", "会议记录", "参会人员", "纪要"]},
    {"code": "PM-CHG", "name": "变更单", "stage": "00_项目管理",
     "kw": ["变更申请", "变更单", "需求变更", "变更内容"]},
    {"code": "BIZ-REQ", "name": "需求/招标文件", "stage": "01_售前商务",
     "kw": ["招标文件", "采购需求", "招标公告", "需求说明", "技术要求", "磋商文件", "采购文件", "询价"]},
    {"code": "BIZ-SOL", "name": "技术方案/建议书", "stage": "01_售前商务",
     "kw": ["技术方案", "服务方案", "解决方案", "建议书", "方案建议"]},
    {"code": "BIZ-QT", "name": "报价单", "stage": "01_售前商务",
     "kw": ["报价单", "报价明细", "报价表", "报价"]},
    {"code": "BIZ-BID", "name": "投标/磋商响应文件", "stage": "01_售前商务",
     "kw": ["响应文件", "投标文件", "投标书", "应答文件", "磋商响应"]},
    {"code": "BIZ-CTR", "name": "合同/协议", "stage": "01_售前商务",
     "kw": ["服务合同", "采购合同", "技术服务合同", "合同", "框架协议", "服务协议", "甲方", "乙方"]},
    {"code": "KO-KICK", "name": "启动会材料", "stage": "02_项目启动",
     "kw": ["启动会", "项目启动", "开工会", "kickoff", "kick-off"]},
    {"code": "KO-AUTH", "name": "测试授权书", "stage": "02_项目启动",
     "kw": ["渗透测试授权", "测试授权", "授权书", "授权函", "委托书"]},
    {"code": "KO-NDA", "name": "保密协议", "stage": "02_项目启动",
     "kw": ["保密协议", "保密承诺", "保密条款", "NDA"]},
    {"code": "KO-STAFF", "name": "人员清单", "stage": "02_项目启动",
     "kw": ["人员清单", "人员名单", "驻场人员", "人员信息表", "项目组成员"]},
    {"code": "CLI-ASSET", "name": "资产清单", "stage": "06_客户资料",
     "kw": ["资产清单", "资产列表", "资产表", "IP清单", "系统清单", "域名清单", "IP地址"]},
    {"code": "CLI-DOC", "name": "客户提供资料", "stage": "06_客户资料", "series": True,
     "kw": ["管理制度", "网络拓扑", "拓扑图", "制度汇编", "客户提供", "问卷回复"]},
    {"code": "PRC-SURV", "name": "调研问卷", "stage": "03_过程文档",
     "kw": ["调研问卷", "调查表", "调研表", "问卷", "填写说明"]},
    {"code": "PRC-RCD", "name": "访谈/测评记录、工作底稿", "stage": "03_过程文档", "series": True,
     "kw": ["访谈记录", "测评记录", "核查记录", "现场记录", "工作底稿", "检查记录", "作业指导"]},
    {"code": "EVD-SCAN", "name": "扫描原始结果", "stage": EVIDENCE_DIR, "evidence": True,
     "kw": ["扫描结果", "漏扫结果", "nessus", "awvs", "appscan", "rsas", "xray", "nmap"]},
    {"code": "EVD-SHOT", "name": "截图证据", "stage": EVIDENCE_DIR, "evidence": True,
     "kw": ["截图", "复现截图", "证据截图"]},
    {"code": "RPT-PT", "name": "渗透测试报告", "stage": "04_交付成果",
     "kw": ["渗透测试报告", "渗透报告", "渗透测试", "漏洞详情", "攻击路径"]},
    {"code": "RPT-VS", "name": "漏洞扫描报告", "stage": "04_交付成果",
     "kw": ["漏洞扫描报告", "漏扫报告", "主机漏洞", "漏洞扫描"]},
    {"code": "RPT-DJ", "name": "等保测评报告", "stage": "04_交付成果",
     "kw": ["等级测评报告", "等保测评报告", "测评报告", "等级保护", "安全物理环境", "安全通信网络", "测评结论", "等保"]},
    {"code": "RPT-GAP", "name": "差距分析报告", "stage": "04_交付成果",
     "kw": ["差距分析", "差距评估", "差距报告", "不符合项", "符合项"]},
    {"code": "RPT-DSA", "name": "数据安全评估报告", "stage": "04_交付成果",
     "kw": ["数据安全风险评估", "数据安全评估", "数据出境", "个人信息保护影响评估", "数据分类分级", "个人信息"]},
    {"code": "RPT-REM", "name": "整改建议/整改方案", "stage": "04_交付成果",
     "kw": ["整改建议", "整改方案", "加固方案", "安全加固", "整改报告", "整改清单"]},
    {"code": "RPT-RCK", "name": "复测报告", "stage": "04_交付成果",
     "kw": ["复测报告", "整改验证", "回归测试", "复测"]},
    {"code": "RPT-DRL", "name": "演练报告", "stage": "04_交付成果",
     "kw": ["演练报告", "攻防演练", "红蓝对抗", "桌面演练", "应急演练", "护网"]},
    {"code": "RPT-AIRT", "name": "AI 红队测试报告", "stage": "04_交付成果",
     "kw": ["AI红队", "大模型安全", "提示注入", "越狱测试", "大模型"]},
    {"code": "ACC-SIGN", "name": "验收单/签字确认", "stage": "05_验收结项",
     "kw": ["验收单", "验收报告", "验收确认", "确认单", "签收单", "验收"]},
    {"code": "ACC-SUM", "name": "结项总结/满意度", "stage": "05_验收结项",
     "kw": ["结项报告", "项目总结", "满意度", "总结报告", "结项"]},
    {"code": "OTH-DOC", "name": "其他文件", "stage": "03_过程文档", "kw": []},
]

# 运行时的类型表 = 内置类型（可追加关键词）+ 自定义类型；由 apply_types() 根据数据库填充。
# 其他模块一律通过 S.TYPE_CODES / S.TYPE_MAP 访问，这里原地更新，引用始终有效。
TYPE_CODES: List[Dict] = []          # 启用中的类型（参与识别、出现在选择框里）
TYPE_MAP: Dict[str, Dict] = {}       # 全部类型（含已停用的自定义类型，老文件仍能显示名称）

TYPE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}-[A-Z0-9]{2,10}$")
# 新增类型可选的归档目录，以及类型码建议前缀
TYPE_STAGES: List[str] = ["00_项目管理", "01_售前商务", "02_项目启动", "03_过程文档", EVIDENCE_DIR,
                          "04_交付成果", "05_验收结项", "06_客户资料"]
STAGE_PREFIX: Dict[str, str] = {"00_项目管理": "PM", "01_售前商务": "BIZ", "02_项目启动": "KO", "03_过程文档": "PRC",
                                EVIDENCE_DIR: "EVD", "04_交付成果": "RPT", "05_验收结项": "ACC", "06_客户资料": "CLI"}


def apply_types(rows: List[Dict]) -> None:
    """rows = doc_types 表：builtin=1 的行只带追加关键词；builtin=0 的行是自定义类型。"""
    def kws(r: Dict) -> List[str]:
        v = r.get("kw")
        if isinstance(v, str):
            try:
                v = json.loads(v or "[]")
            except ValueError:
                v = []
        return [str(k) for k in (v or []) if str(k).strip()]

    extra = {r["code"]: kws(r) for r in rows if r.get("builtin")}
    enabled: List[Dict] = []
    every: Dict[str, Dict] = {}
    other = None
    for t in BUILTIN_TYPES:
        add = [k for k in extra.get(t["code"], []) if k not in t["kw"]]
        d = {**t, "kw": list(t["kw"]) + add, "extra_kw": add, "builtin": True, "enabled": True}
        every[t["code"]] = d
        if t["code"] == "OTH-DOC":
            other = d
        else:
            enabled.append(d)
    for r in sorted((r for r in rows if not r.get("builtin")), key=lambda r: (r.get("created_at") or "", r["code"])):
        if r["code"] in every:
            continue
        stage = r.get("stage") if r.get("stage") in TYPE_STAGES else "03_过程文档"
        d = {"code": r["code"], "name": r.get("name") or r["code"], "stage": stage, "kw": kws(r), "extra_kw": [],
             "series": bool(r.get("series")), "evidence": stage == EVIDENCE_DIR, "builtin": False,
             "enabled": bool(r.get("enabled", 1))}
        every[r["code"]] = d
        if d["enabled"]:
            enabled.append(d)
    if other:
        enabled.append(other)            # 「其他文件」始终放最后
    TYPE_CODES[:] = enabled
    TYPE_MAP.clear()
    TYPE_MAP.update(every)

# 业务线 → 关键词（用于同一客户多个项目时区分）
BIZ_LINES: Dict[str, List[str]] = {
    "等保": ["等保", "等级保护", "等级测评", "测评"],
    "渗透": ["渗透", "漏洞", "攻防"],
    "数据安全": ["数据安全", "数据出境", "个人信息", "分类分级", "数据"],
    "AI红队": ["AI", "大模型", "红队", "提示注入"],
    "演练": ["演练", "护网", "红蓝"],
    "售前": ["方案", "报价", "投标", "响应文件"],
    "安全运营": ["运营", "驻场", "值守", "巡检"],
}
# 类型码对业务线的提示
TYPE_BIZ_HINT: Dict[str, str] = {
    "RPT-DJ": "等保", "RPT-GAP": "等保", "RPT-PT": "渗透", "RPT-VS": "渗透", "KO-AUTH": "渗透",
    "RPT-DSA": "数据安全", "RPT-AIRT": "AI红队", "RPT-DRL": "演练",
}
SENSITIVE_TYPES = {"RPT-PT", "RPT-VS", "EVD-SCAN", "EVD-SHOT", "CLI-ASSET", "KO-STAFF"}

# 文件名中的噪声词（含义交给版本号和状态表达）
NOISE_WORDS = [
    "最终版", "最终稿", "最新版", "最新", "终稿", "定稿", "修改版", "修订版", "修改稿", "修改", "副本",
    "拷贝", "copy", "Copy", "final", "Final", "FINAL", "草稿", "初稿", "正式版", "签字版", "盖章版", "扫描件",
]
GARBAGE_TITLES = ["微信图片", "新建", "未命名", "untitled", "Untitled", "IMG_", "img_", "Scan", "scan",
                  "文档1", "文档2", "Document", "image", "屏幕截图", "截屏", "Screenshot",
                  "扫描全能王", "全能扫描王", "扫描件", "WechatIMG", "mmexport", "微信截图", "QQ截图", "企业微信截图",
                  "Snipaste", "Screen Shot", "PXL_", "DSC_", "DSC0", "Image_", "IMG"]

# 图片文件名里出现这些词，一定是截图证据（不当作文件照片）
SHOT_NAME_HINTS = ["截图", "截屏", "screenshot", "screen shot", "snipaste", "屏幕", "漏洞", "poc", "burp", "复现", "证据"]
# 图中文字出现这些特征，更像系统/漏洞截图（每类算一分）
SHOT_TEXT_PATTERNS = [
    r"https?://|www\.",
    r"HTTP/\d|\bHost:|Content-Type|Cookie:|User-Agent",
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    r"</?\w+[\s>/]|\{\s*\"",
    r"(?i)\b(select|union|alert\(|payload|token|admin|root@|sqlmap|nmap|burp)\b",
    r"用户名|密\s*码|登\s*录|验证码",
]
# 文件照片/扫描件的特征
DOC_TEXT_PATTERN = r"盖\s*章|签\s*字|签\s*章|签\s*署|授权方|甲\s*方|乙\s*方|特此|兹|日\s*期\s*[:：]"
# 拍照或扫描的这些类型，默认就是签字盖章版
SIGNED_TYPES = {"KO-AUTH", "ACC-SIGN", "BIZ-CTR", "KO-NDA", "PM-CHG"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff"}
SCAN_EXT = {".nessus"}
IGNORE_SUFFIX = {".crdownload", ".part", ".download", ".tmp", ".partial", ".icloud"}

NAME_FORMULA = "{项目编号}_{类型码}_{文档标题}_{版本}_{状态}_{日期}.{扩展名}"
MAX_TITLE = 30
MAX_NAME = 120

apply_types([])
