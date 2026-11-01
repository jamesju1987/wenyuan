"""生成产品网站：docs/index.html（中文）和 docs/en/index.html（英文），并按标题用字子集化中文衬线字体。

用法：python3 tools/site/build.py <版本号> <安装包大小KB> <更新日期YYYY-MM-DD>
"""
from __future__ import annotations

import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
VER = sys.argv[1] if len(sys.argv) > 1 else "1.6.1"
SIZE = sys.argv[2] if len(sys.argv) > 2 else "169"
DAY = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date.today()
ZIP = f"Wenyuan-{VER}.zip"
SITE = "https://jamesju1987.github.io/wenyuan/"
REPO = "https://github.com/jamesju1987/wenyuan"
GMW = "https://epaper.gmw.cn/gmrb/html/2015-04/29/nw.D110000gmrb_20150429_2-10.htm"

ZH = dict(
    lang="zh-CN", base="", other_href="en/", other_lang="en", other_label="EN", other_name="English",
    title="文渊：项目文件自动归档",
    desc="文渊自动认出文件属于哪个客户、哪个项目、是什么交付物，按统一规范改名，放进客户、项目、阶段三级目录。在你自己的电脑上运行，免费下载，Windows 与 macOS 通用。",
    og_title="文渊：每个项目，一座文渊阁", og_img="og.png",
    hero_alt="文渊的概览页：今日归档数、自动归档率、待复核和最近处理的文件",
    nav=("功能", "用法", "名字由来", "下载", "问答"), nav_dl="下载",
    h1=("每个项目，", "一座文渊阁。"),
    lede="把文件交给文渊：它认出文件属于哪个客户、哪个项目、是什么交付物，按统一规范改好名字，放进对应的阶段目录。拿不准的才来问你。整个过程都在你自己的电脑上完成。",
    cta=f"下载文渊 {VER}", cta2="看看怎么用",
    fine="免费。Windows 10/11 与 macOS 通用，需要 Python 3.9 或以上。",
    demo_label="演示：一份名字很乱的文件被识别、改名，放进项目的交付成果目录",
    demo_in="收件箱里来了一份文件", demo_out="归档结果", replay="再看一遍",
    steps=(("客户", "正文写着「青岚医疗集团有限公司」"),
           ("项目", "青岚医疗有两个在建项目，按「数据安全」选中 PRJ-2026-0118"),
           ("类型", "数据安全评估报告，类型码 RPT-DSA"),
           ("标题", "文件名太笼统，改用正文里的标题"),
           ("日期", "报告落款 2026 年 10 月 20 日")),
    landed="已归档",
    pillars_h=("文件交给它，", "后面的事不用管。"),
    pillars_p="每份文件经过同样的四道工序。依据都写在明处，哪一步拿不准，就停下来问你。",
    pillars=(("认", "认得出", "按项目编号、客户名称和别名、交付物关键词逐层判断。同一客户有几个在建项目，就看业务线和项目关键词。照片和扫描件先在本机识别文字。"),
             ("名", "起好名", "项目编号、类型码、标题、版本、状态、日期一次排好，去掉「最终版」「(2)」「改」这类字样。同一份文档再放进来，自动升版本，旧版移进「_历史版本」。"),
             ("收", "收得全", "拖进网页、放进收件箱、在资源管理器里右键「发送到」都行，也可以让它盯着微信和企业微信收到的文件。压缩包自动解压，逐个归档。"),
             ("找", "找得到", "按客户、项目、阶段分栏浏览，像翻书架。搜索允许中间隔字，「青岚评估」就能找到「青岚医疗数据安全风险评估报告」；选项目时打拼音首字母就行。")),
    naming_h=("一个文件名，", "把六件事说清楚。"),
    naming_p="谁来归档都是一个样。交付、审计、交接的时候，不用再逐个改名、对版本。",
    segs=(("项目编号", "来自 CRM，文件名里出现就直接锁定项目"),
          ("类型码", "内置 31 类交付物，也可以自己加"),
          ("标题", "客户简称加内容主题，不超过 30 字"),
          ("版本", "草稿是 V0.x，正式从 V1.0 起"),
          ("状态", "草稿、内审、送审、正式、签字"),
          ("日期", "取文件里的落款日期")),
    tree_note="每个项目都是同样的七个阶段目录。目录由导入的 CRM 项目表自动生成，客户改了简称，目录跟着改名。",
    tree_c=("客户简称_客户编码", "项目编号_项目简称", "被新版本替代的旧文件"),
    rows=(
        (("拿不准的，", "才来问你。"),
         ("每个判断都写着依据：在文件名还是正文里看到了什么。",
          "把握到九成就直接归档；其余进「待复核」，内容都已填好，按回车确认。",
          "同一个叫法你确认过两次，它就学会这条规则，第三次直接归档。"),
         "card_messy", "待复核卡片：一份叫「最终版(2)-评估报告-改.docx」的文件，被识别为青岚医疗数据安全评估项目的数据安全评估报告"),
        (("照片和扫描件，", "也按内容命名。"),
         ("在本机识别图中文字，图片不会上传到任何地方。",
          "拍下来的授权书、验收单按标题定类型，盖了章的默认算签字版。",
          "截图按图里的客户名找项目，保留原名，放进「证据」目录。"),
         "card_photo", "待复核卡片：手机拍的授权书照片，识别出图中文字，归为星衡能源大模型安全测试项目的测试授权书，状态为签字"),
        (("像翻书架", "一样找文件。"),
         ("按客户、项目、阶段分栏浏览，方向键翻页，空格快速查看。",
          "每份文件都有版本历史，旧版本一点就能打开。",
          "发给客户前复制「对外交付名」，自动去掉内部编号和类型码。"),
         "library", "归档库分栏浏览：澄湾科技、等保测评2026、04_交付成果，右侧是等保测评报告的版本历史"),
        (("项目从 CRM 来，", "目录自己长出来。"),
         ("导入 CRM 导出的 Excel 或 CSV；同一个项目编号再导入是更新，不会重复。",
          "客户写法不统一、出现两个文件夹时，「整理重复客户」一键合并。",
          "打拼音首字母就能筛选，qlyl 找到青岚医疗。"),
         "projects", "项目列表：项目编号、客户、项目、业务线、状态和文件数"),
    ),
    shot_note="",
    how_h=("三步，", "开始用。"),
    how=(("导入项目", "从 CRM 导出项目列表（Excel 或 CSV），在「项目」里导入。客户、项目、阶段三级目录自动建好。"),
         ("把文件交给它", "拖进网页，放进「_收件箱」文件夹，右键「发送到 → 文渊」，或者打开微信、企业微信自动收文件。"),
         ("确认拿不准的", "大部分文件自动归档。剩下的在「待复核」里看一眼，按回车确认。")),
    nums=("一", "二", "三"),
    local_h=("文件不出", "你的电脑。"),
    local=(("只在本机运行", "服务只监听 127.0.0.1，别的电脑和别的网页都连不上。"),
           ("不用注册", "没有账号，没有云端。归档库就是你硬盘上的普通文件夹，不用文渊也能打开。"),
           ("AI 可以不开", "不开也能靠关键词、规则和以前的归档记录工作。开了也只发送文件名和正文开头（默认 1500 字），原文件不上传。")),
    story_h=("外看两层，", "里面三层。"),
    story=("文渊阁建成于 1776 年，专为收藏《四库全书》。它「明二暗三」：外面看是两层，里面其实有三层；屋顶铺黑色琉璃瓦，取「以水压火」，护住满楼的书。",
           "四部书各用一种颜色的书衣，取书时一眼就知道在哪一架。文渊的标志就是这座阁，檐下四色书函；归档库也是三层：客户、项目、阶段，每份文件一看就知道该放在哪。"),
    swatches=(("经部", "青"), ("史部", "赤"), ("子部", "月白"), ("集部", "灰黑")),
    cite_pre="史料参考：", cite="《文渊阁与〈四库全书〉》，光明日报",
    dl_h=("把文渊", "装进你的电脑。"),
    dl_name=f"文渊 {VER}", dl_meta=f"ZIP 压缩包，{SIZE} KB，{DAY.year} 年 {DAY.month} 月 {DAY.day} 日更新",
    win=("先装 Python 3.9 或以上，安装时勾选「Add python.exe to PATH」。",
         "解压后双击「启动文渊.bat」。第一次会自动安装依赖，大约 1 分钟。",
         "浏览器打开后，在「项目」里导入 CRM 项目表。以后从开始菜单或托盘图标打开。"),
    mac=("把文件夹放到固定位置，例如 ~/workspace/文渊。",
         "双击「启动文渊.command」。提示「无法验证开发者」时，右键选「打开」。",
         "想登录后自动在后台运行，双击「设置开机自动运行.command」。"),
    upgrade=("用过「归档官」？", "把新的「文渊」文件夹解压到旧文件夹旁边，双击启动即可。设置、项目、归档记录和学会的规则都会接上，旧的右键菜单和开机启动项也会换成新名字。"),
    links=(("GitHub 上的源码", REPO), ("完整使用说明", REPO + "#readme")),
    faq_h="常见问题",
    faq=(("不配置 AI 能用吗？", "能。项目编号、客户名称和别名、交付物关键词、学会的规则和以前的归档记录已经能处理大部分文件。配置 Jev 后，关键词判断不了时让它在候选项目里做选择；配置 DeepSeek 后，它会读正文开头，生成更准确的标题和日期。"),
         ("会把我的文件传到网上吗？", "不会。文渊运行在你的电脑上，图片文字识别也在本机完成。只有你打开了 AI 功能，才会把文件名和正文开头（默认 1500 字）发给你自己配置的模型服务，原文件不上传。"),
         ("支持哪些文件？", "Word（docx）、Excel、PowerPoint、PDF（包括扫描版）、文本，以及 JPG、PNG、HEIC 等图片。zip、7z、tar 压缩包会自动解压；rar 需要电脑上装有 7-Zip 或 WinRAR。老的 .doc 在 Mac 上能读内容，在 Windows 上按文件名判断。"),
         ("归档错了怎么办？", "在「概览」或「处理记录」里点撤销，文件回到待复核，被替代的旧版本恢复原位。你改正之后，相关的自动规则会停用，不会一错再错。"),
         ("同一个客户出现了两个文件夹？", "一般是换过数据库，或者同一客户在 CRM 里有两种写法。在「项目」里点「整理重复客户」：按项目编号能确定的默认勾选，合并时文件只移动不删除，内容完全相同的只留一份。"),
         ("需要联网吗？", "第一次启动要联网安装依赖（默认从清华镜像下载）。之后除了 AI 功能，都可以离线使用。"),
         ("收费吗？", "免费。")),
    foot_tag="每个项目，一座文渊阁。", foot_links=("下载", "GitHub", "使用说明"), copy="© 2026 文渊",
    skip="跳到正文", nav_label="页面导航", home_label="文渊首页",
)

EN = dict(
    lang="en", base="../", other_href="../", other_lang="zh-CN", other_label="中文", other_name="简体中文",
    title="Wenyuan: project files, filed for you",
    desc="Wenyuan works out which client, project and deliverable each file belongs to, renames it to one standard and files it into client, project and stage folders. Runs on your own computer. Free for Windows and macOS.",
    og_title="Wenyuan: every project, its own library", og_img="og-en.png",
    hero_alt="Wenyuan’s overview screen: files filed today, auto-filing rate, items waiting for review and recent activity",
    nav=("Features", "How it works", "The name", "Download", "FAQ"), nav_dl="Download",
    h1=("Every project,", "its own library."),
    lede="Hand Wenyuan a file. It works out which client, project and deliverable it belongs to, renames it to one consistent standard, and files it into the right stage folder. It only asks when it isn’t sure, and it all happens on your own computer.",
    cta=f"Download Wenyuan {VER}", cta2="See how it works",
    fine="Free. Windows 10/11 and macOS, with Python 3.9 or later. The app’s interface is in Simplified Chinese.",
    demo_label="Demo: a badly named file is recognised, renamed and filed into the project’s deliverables folder",
    demo_in="A file just landed in the inbox", demo_out="Filed as", replay="Play again",
    steps=(("Client", "The text names 青岚医疗集团有限公司"),
           ("Project", "Two active projects for this client; the data-security one fits: PRJ-2026-0118"),
           ("Type", "Data security assessment report, type code RPT-DSA"),
           ("Title", "The file name is too vague, so the document’s own heading is used"),
           ("Date", "Signed off on 20 October 2026")),
    landed="Filed",
    pillars_h=("Hand it the file.", "It does the rest."),
    pillars_p="Every file goes through the same four steps. The reasoning is always on show, and whenever a step is uncertain, it stops and asks.",
    pillars=(("认", "Recognise", "Project numbers first, then client names and aliases, then deliverable keywords. When a client has several active projects, business line and project keywords decide. Photos and scans are read on your machine first."),
             ("名", "Name", "Project number, type code, title, version, status and date, in that order, every time. Noise like “final”, “(2)” or “edited” is stripped. Drop in a newer copy and the version goes up; the old one moves to the history folder."),
             ("收", "Collect", "Drag files into the page, drop them in the inbox folder, use right-click Send to on Windows, or let it pick up files you receive in WeChat and WeCom. Archives are unpacked and filed one by one."),
             ("找", "Find", "Browse client, project and stage in columns, like a bookshelf. Search tolerates gaps between characters, and project pickers accept pinyin initials.")),
    naming_h=("One file name.", "Six facts."),
    naming_p="Whoever files it, it comes out the same. No more renaming or reconciling versions at hand-over or audit time.",
    segs=(("Project number", "From your CRM; a match locks the project"),
          ("Type code", "31 built-in deliverable types, and your own"),
          ("Title", "Client short name plus subject, 30 characters at most"),
          ("Version", "Drafts are V0.x; the first formal release is V1.0"),
          ("Status", "Draft, internal review, client review, final, signed"),
          ("Date", "The document’s own sign-off date")),
    tree_note="Every project gets the same seven stage folders, generated from your CRM project list. Rename a client and its folder follows.",
    tree_c=("client short name_client code", "project number_project short name", "older versions, replaced by newer ones"),
    rows=(
        (("It only asks", "when it isn’t sure."),
         ("Every decision shows its evidence: what it saw, and whether in the file name or the body.",
          "At 90% confidence it files straight away. Everything else waits in Review, filled in, ready for you to press Enter.",
          "Confirm the same wording twice and it learns a rule. The third time, it just files."),
         "card_messy", "Review card: a file called 最终版(2)-评估报告-改.docx is recognised as a data security assessment report for the Qinglan Medical data-security project"),
        (("Photos and scans,", "named by what they say."),
         ("Text in images is recognised on your machine. Images never leave it.",
          "Photographed authorisation letters and sign-off sheets are typed by their heading; stamped ones count as signed.",
          "Screenshots are matched to a project by the client name inside them, keep their original names and go to the evidence folder."),
         "card_photo", "Review card: a phone photo of an authorisation letter, its text recognised and filed as a signed test authorisation for the Xingheng Energy project"),
        (("Browse it like", "a bookshelf."),
         ("Client, project and stage in columns. Arrow keys to move, space to preview.",
          "Every file keeps its version history; older versions open in one click.",
          "Before sending a file out, copy a client-facing name without internal codes."),
         "library", "Archive browser with columns for client, project and stage, and the version history of an assessment report"),
        (("Projects come from your CRM.", "Folders follow."),
         ("Import an Excel or CSV export. Importing the same project number again updates it instead of duplicating it.",
          "If one client ends up with two folders, Tidy Duplicates merges them.",
          "Filter projects by pinyin initials: qlyl finds 青岚医疗."),
         "projects", "Project list with project number, client, project, business line, status and file count"),
    ),
    shot_note="Screenshots show the app’s Simplified Chinese interface.",
    how_h=("Three steps", "to get going."),
    how=(("Import your projects", "Export the project list from your CRM as Excel or CSV and import it. Client, project and stage folders are created for you."),
         ("Hand over your files", "Drag them into the page, drop them in the inbox folder, right-click Send to on Windows, or switch on WeChat and WeCom collection."),
         ("Confirm the unsure ones", "Most files are filed automatically. Glance over the rest in Review and press Enter.")),
    nums=("1", "2", "3"),
    local_h=("Your files never", "leave your computer."),
    local=(("Runs only on this machine", "The service listens on 127.0.0.1 only. Other computers and other web pages can’t reach it."),
           ("No sign-up", "No account, no cloud. Your archive is an ordinary folder on your disk, readable without Wenyuan."),
           ("AI is optional", "Without it, keywords, rules and your filing history do the work. With it, only the file name and opening text (1,500 characters by default) are sent, never the file itself.")),
    story_h=("Two storeys outside.", "Three inside."),
    story=("The Wenyuan Pavilion (文渊阁) in the Forbidden City was completed in 1776 to house the Siku Quanshu, the great imperial collection of Chinese books. From outside it looks two storeys high, but it holds three; its roof is laid with black glazed tiles, black standing for water, to keep fire away from the books.",
           "Each of the four sections was bound in its own colour, so the right shelf could be found at a glance. Our mark is that pavilion, with four coloured cases under its eaves. Your archive has three levels too, client, project and stage, so every file has an obvious place."),
    swatches=(("Classics", "green"), ("Histories", "red"), ("Masters", "moon-white"), ("Collections", "grey-black")),
    cite_pre="Historical source: ", cite="文渊阁与《四库全书》, Guangming Daily (in Chinese)",
    dl_h=("Put Wenyuan", "on your computer."),
    dl_name=f"Wenyuan {VER}", dl_meta=f"ZIP, {SIZE} KB, updated {DAY.day} {DAY.strftime('%B')} {DAY.year}",
    win=("Install Python 3.9 or later and tick “Add python.exe to PATH”.",
         "Unzip and double-click 启动文渊.bat. The first run installs dependencies, which takes about a minute.",
         "When the browser opens, import your CRM project list under 项目 (Projects). Next time, open it from the Start menu or the tray icon."),
    mac=("Put the folder somewhere permanent, such as ~/workspace/文渊.",
         "Double-click 启动文渊.command. If macOS can’t verify the developer, right-click it and choose Open.",
         "To keep it running in the background after login, double-click 设置开机自动运行.command."),
    upgrade=("Used 归档官 before?", "That was Wenyuan’s previous name. Unzip the new 文渊 folder next to the old one and start it: settings, projects, history and learned rules carry over, and the old right-click and startup entries are renamed."),
    links=(("Source code on GitHub", REPO), ("Full guide (in Chinese)", REPO + "#readme")),
    faq_h="Questions",
    faq=(("Does it work without AI?", "Yes. Project numbers, client names and aliases, deliverable keywords, learned rules and your filing history handle most files. With Jev configured, it chooses among candidate projects when keywords can’t decide; with DeepSeek, it reads the opening text to produce better titles and dates."),
         ("Are my files uploaded anywhere?", "No. Wenyuan runs on your computer, and text in images is recognised locally. Only if you switch on AI are the file name and opening text (1,500 characters by default) sent to the model service you configured. Files themselves are never uploaded."),
         ("Which files does it handle?", "Word (docx), Excel, PowerPoint, PDF (including scans), plain text, and images such as JPG, PNG and HEIC. zip, 7z and tar archives are unpacked automatically; rar needs 7-Zip or WinRAR installed. The content of legacy .doc files is read on macOS; on Windows they are judged by file name."),
         ("What if something is filed wrong?", "Undo it from Overview or Activity. The file goes back to Review and any version it replaced is restored. Once you correct it, the automatic rule behind the mistake is switched off."),
         ("One client ended up with two folders?", "Usually after a database reset, or when a client is spelled two ways in your CRM. Open Projects and choose Tidy Duplicates: folders matched by project number are pre-selected, files are only moved, never deleted, and identical copies are kept once."),
         ("Does it need the internet?", "Only the first time, to install dependencies (from a mirror in mainland China by default). After that, everything except the AI features works offline."),
         ("Is it free?", "Yes.")),
    foot_tag="Every project, its own library.", foot_links=("Download", "GitHub", "Guide (Chinese)"), copy="© 2026 Wenyuan",
    skip="Skip to content", nav_label="Page sections", home_label="Wenyuan home",
)

SEG_CODES = ("PRJ-2026-0118", "RPT-DSA", "青岚医疗数据安全风险评估报告", "V1.0", "正式", "20261020")
CASE_CLASS = ("c-qing", "c-chi", "c-yuebai", "c-huihei")
ROW_TINT = ("t-qing", "t-chi", "t-huihei", "t-yuebai")
SHOT_SIZE = {"card_messy": (1616, 728), "card_photo": (1616, 818), "library": (2000, 1265), "projects": (2000, 1265)}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def lines(pair, cls="ln") -> str:
    return "".join(f'<span class="{cls}">{esc(x)}</span>' for x in pair)


def _hash(name: str) -> str:
    import hashlib
    return hashlib.sha1((DOCS / "assets" / name).read_bytes()).hexdigest()[:10]


def page(L: dict) -> str:
    b = L["base"]
    css_v, js_v = _hash("site.css"), _hash("site.js")       # 内容变了链接就变，浏览器不会用旧缓存
    a = b + "assets/"
    zh = L["lang"] == "zh-CN"
    nav_ids = ("features", "how", "story", "download", "faq")
    nav = "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in zip(nav_ids, L["nav"]))
    steps = "".join(f'<li class="s{i + 1}"><b>{esc(k)}</b><span>{esc(v)}</span></li>' for i, (k, v) in enumerate(L["steps"]))
    cases = "".join(
        f'<article class="case {CASE_CLASS[i]}"><div class="case-box" aria-hidden="true"><span class="slip">{ch}</span></div>'
        f'<h3>{esc(t)}</h3><p>{esc(p)}</p></article>' for i, (ch, t, p) in enumerate(L["pillars"]))
    segs = []
    for i, ((label, note), code) in enumerate(zip(L["segs"], SEG_CODES)):
        ext = '<span class="ext">.docx</span>' if i == len(SEG_CODES) - 1 else ""
        wide = " seg-wide" if i == 2 else ""
        segs.append(f'<span class="seg{wide}" role="listitem"><code>{code}{ext}</code><small><b>{esc(label)}</b>{esc(note)}</small></span>')
    anatomy = '<span class="us" aria-hidden="true">_</span>'.join(segs)
    rows = []
    for i, (h, ticks, img, alt) in enumerate(L["rows"]):
        w, hh = SHOT_SIZE[img]
        flip = " flip" if i % 2 else ""
        lis = "".join(f"<li>{esc(t)}</li>" for t in ticks)
        rows.append(f'''      <article class="row{flip}">
        <div class="row-text"><h2 class="display">{lines(h)}</h2><ul class="ticks">{lis}</ul></div>
        <figure class="panel {ROW_TINT[i]}"><img src="{a}img/{img}.webp" width="{w}" height="{hh}" loading="lazy" alt="{esc(alt)}"></figure>
      </article>''')
    how = "".join(f'<li><span class="num">{n}</span><h3>{esc(t)}</h3><p>{esc(p)}</p></li>' for n, (t, p) in zip(L["nums"], L["how"]))
    local = "".join(f"<div><dt>{esc(t)}</dt><dd>{esc(d)}</dd></div>" for t, d in L["local"])
    sw = "".join(f'<li class="{CASE_CLASS[i]}"><i aria-hidden="true"></i><b>{esc(k)}</b><span>{esc(v)}</span></li>'
                 for i, (k, v) in enumerate(L["swatches"]))
    win = "".join(f"<li>{esc(x)}</li>" for x in L["win"])
    mac = "".join(f"<li>{esc(x)}</li>" for x in L["mac"])
    faq = "".join(f"<details><summary>{esc(q)}</summary><p>{esc(ans)}</p></details>" for q, ans in L["faq"])
    links = "".join(f'<a href="{u}">{esc(t)}</a>' for t, u in L["links"])
    dl = f"{b}download/{ZIP}"
    fl = L["foot_links"]
    shot_note = f'<p class="shot-note">{esc(L["shot_note"])}</p>' if L["shot_note"] else ""
    brand_name = "文渊" if zh else "Wenyuan"
    brand_sub = "Wenyuan" if zh else "文渊"
    return f'''<!doctype html>
<html lang="{L["lang"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(L["title"])}</title>
<meta name="description" content="{esc(L["desc"])}">
<meta name="theme-color" content="#0E1419">
<link rel="canonical" href="{SITE}{"" if zh else "en/"}">
<link rel="alternate" hreflang="zh-CN" href="{SITE}">
<link rel="alternate" hreflang="en" href="{SITE}en/">
<link rel="icon" href="{a}logo.svg" type="image/svg+xml">
<link rel="icon" href="{a}favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{a}apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(L["og_title"])}">
<meta property="og:description" content="{esc(L["desc"])}">
<meta property="og:image" content="{SITE}assets/{L["og_img"]}">
<meta property="og:url" content="{SITE}{"" if zh else "en/"}">
<link rel="preload" href="{a}fonts/{"wy-serif-600.woff2" if zh else "wy-latin-600.woff2"}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{a}site.css?v={css_v}">
<script>document.documentElement.classList.add("js")</script>
</head>
<body class="{"zh" if zh else "en"}">
<a class="skip" href="#main">{esc(L["skip"])}</a>

<header class="nav" id="nav">
  <div class="wrap nav-in">
    <a class="brand" href="#top" aria-label="{esc(L["home_label"])}"><img src="{a}logo.svg" width="28" height="28" alt=""><span class="bn">{brand_name}</span><span class="bs">{brand_sub}</span></a>
    <nav class="nav-links" aria-label="{esc(L["nav_label"])}">{nav}</nav>
    <a class="lang" href="{L["other_href"]}" hreflang="{L["other_lang"]}" lang="{L["other_lang"]}" title="{esc(L["other_name"])}">{esc(L["other_label"])}</a>
    <a class="btn btn-sm nav-dl" href="#download">{esc(L["nav_dl"])}</a>
  </div>
</header>

<main id="main">

<section class="hero" id="top">
  <div class="tiles" aria-hidden="true"></div>
  <div class="wrap hero-in">
    <div class="hero-copy">
      <img class="emblem" src="{a}mark-mono.svg" width="64" height="52" alt="">
      <h1 class="display">{lines(L["h1"])}</h1>
      <p class="lede">{esc(L["lede"])}</p>
      <div class="cta">
        <a class="btn btn-paper" href="{dl}" download>{esc(L["cta"])}</a>
        <a class="btn btn-ghost" href="#how">{esc(L["cta2"])}</a>
      </div>
      <p class="fine">{esc(L["fine"])}</p>
    </div>
  </div>
  <figure class="stage">
    <div class="win"><img src="{a}img/hero.webp" width="1800" height="1138" alt="{esc(L["hero_alt"])}" fetchpriority="high"></div>
  </figure>
</section>

<section class="flow" aria-label="{esc(L["demo_label"])}">
  <div class="wrap">
    <figure class="demo" id="demo" aria-label="{esc(L["demo_label"])}">
      <div class="demo-col">
        <div class="demo-head"><span>{esc(L["demo_in"])}</span><button type="button" class="replay" id="replay" hidden>{esc(L["replay"])}</button></div>
        <div class="d-file d-in"><span class="ftag">DOC</span><span class="fn">最终版(2)-评估报告-改.docx</span></div>
        <ul class="d-steps">{steps}</ul>
      </div>
      <div class="demo-col demo-right">
        <div class="demo-head"><span>{esc(L["demo_out"])}</span></div>
        <div class="d-file d-out"><span class="ftag">DOC</span><span class="fn mono">PRJ-2026-0118_RPT-DSA_青岚医疗数据安全风险评估报告_V1.0_正式_20261020.docx</span></div>
        <div class="d-tree">
          <div class="t t0">项目归档库</div>
          <div class="t t1">青岚医疗_C0002</div>
          <div class="t t2">PRJ-2026-0118_数据安全评估</div>
          <div class="t t3"><span>04_交付成果</span><em class="land">{esc(L["landed"])}</em></div>
        </div>
      </div>
    </figure>
  </div>
</section>

<section class="pillars" id="features" aria-labelledby="pillars-h">
  <div class="wrap">
    <header class="sec-head"><h2 class="display" id="pillars-h">{lines(L["pillars_h"])}</h2><p>{esc(L["pillars_p"])}</p></header>
    <div class="cases">{cases}</div>
  </div>
</section>

<section class="anatomy" id="naming" aria-labelledby="naming-h">
  <div class="wrap">
    <header class="sec-head"><h2 class="display" id="naming-h">{lines(L["naming_h"])}</h2><p>{esc(L["naming_p"])}</p></header>
    <div class="fname-anatomy" role="list">{anatomy}</div>
    <div class="tree-wrap">
      <div class="tree">
        <div class="tr d0"><span class="tn">项目归档库</span></div>
        <div class="tr d1"><span class="tn">青岚医疗_C0002</span><span class="tc">{esc(L["tree_c"][0])}</span></div>
        <div class="tr d2"><span class="tn">PRJ-2026-0118_数据安全评估</span><span class="tc">{esc(L["tree_c"][1])}</span></div>
        <div class="tr d3 stages"><span class="tn">00_项目管理</span><span class="tn">01_售前商务</span><span class="tn">02_项目启动</span><span class="tn">03_过程文档</span><span class="tn on">04_交付成果</span><span class="tn">05_验收结项</span><span class="tn">06_客户资料</span></div>
        <div class="tr d3"><span class="tn">_历史版本</span><span class="tc">{esc(L["tree_c"][2])}</span></div>
      </div>
      <p class="tree-note">{esc(L["tree_note"])}</p>
    </div>
  </div>
</section>

<section class="rows" aria-label="{esc(L["nav"][0])}">
  <div class="wrap">
{chr(10).join(rows)}
    {shot_note}
  </div>
</section>

<section class="how" id="how" aria-labelledby="how-h">
  <div class="wrap">
    <header class="sec-head"><h2 class="display" id="how-h">{lines(L["how_h"])}</h2></header>
    <ol class="steps">{how}</ol>
  </div>
</section>

<section class="local" aria-labelledby="local-h">
  <div class="tiles" aria-hidden="true"></div>
  <div class="wrap local-in">
    <h2 class="display" id="local-h">{lines(L["local_h"])}</h2>
    <dl class="local-list">{local}</dl>
  </div>
</section>

<section class="story" id="story" aria-labelledby="story-h">
  <div class="wrap story-in">
    <h2 class="display" id="story-h">{lines(L["story_h"])}</h2>
    <div class="story-text">
      <p>{esc(L["story"][0])}</p>
      <ul class="swatches">{sw}</ul>
      <p>{esc(L["story"][1])}</p>
      <p class="cite">{esc(L["cite_pre"])}<a href="{GMW}" rel="noopener">{esc(L["cite"])}</a></p>
    </div>
  </div>
</section>

<section class="download" id="download" aria-labelledby="dl-h">
  <div class="wrap">
    <div class="dl-top">
      <img src="{a}logo.svg" width="88" height="88" alt="">
      <h2 class="display" id="dl-h">{lines(L["dl_h"])}</h2>
      <p class="dl-meta"><b>{esc(L["dl_name"])}</b><span>{esc(L["dl_meta"])}</span></p>
      <a class="btn btn-paper btn-lg" href="{dl}" download>{esc(L["cta"])}</a>
    </div>
    <div class="dl-os">
      <div><h3>Windows 10 / 11</h3><ol>{win}</ol></div>
      <div><h3>macOS</h3><ol>{mac}</ol></div>
    </div>
    <p class="dl-upgrade"><b>{esc(L["upgrade"][0])}</b>{esc(L["upgrade"][1])}</p>
    <p class="dl-links">{links}</p>
  </div>
</section>

<section class="faq" id="faq" aria-labelledby="faq-h">
  <div class="wrap faq-in">
    <h2 class="display" id="faq-h">{esc(L["faq_h"])}</h2>
    <div class="faq-list">{faq}</div>
  </div>
</section>

</main>

<footer class="foot">
  <div class="wrap foot-in">
    <a class="brand" href="#top"><img src="{a}logo.svg" width="28" height="28" alt=""><span class="bn">{brand_name}</span><span class="bs">{brand_sub}</span></a>
    <p class="foot-tag">{esc(L["foot_tag"])}</p>
    <nav class="foot-links" aria-label="footer"><a href="#download">{esc(fl[0])}</a><a href="{REPO}">{esc(fl[1])}</a><a href="{REPO}#readme">{esc(fl[2])}</a><a href="{L["other_href"]}" hreflang="{L["other_lang"]}" lang="{L["other_lang"]}">{esc(L["other_name"])}</a></nav>
    <p class="foot-copy">{esc(L["copy"])}</p>
  </div>
</footer>

<script src="{a}site.js?v={js_v}" defer></script>
</body>
</html>
'''


class _Chars(HTMLParser):
    """收集中文页里用衬线体显示的字：标题、品牌、题签、编号。"""
    SERIF = ("display", "brand", "slip", "num", "bn", "dl-meta")

    def __init__(self):
        super().__init__()
        self.stack, self.chars = [], set()

    def handle_starttag(self, tag, attrs):
        cls = (dict(attrs).get("class") or "").split()
        self.stack.append((tag, tag in ("h1", "h2") or any(c in self.SERIF for c in cls)))

    def handle_endtag(self, tag):
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        if any(s for _, s in self.stack):
            self.chars.update(c for c in data if not c.isspace())


def subset_zh(html: str) -> None:
    from fontTools import subset
    from fontTools.ttLib import TTCollection
    p = _Chars()
    p.feed(html)
    text = "".join(sorted(p.chars | set("认名收找一二三文渊0123456789.，。、「」《》（）-")))
    src = "/usr/share/fonts/opentype/noto/NotoSerifCJK-SemiBold.ttc"
    idx = next(i for i, f in enumerate(TTCollection(src).fonts) if "Noto Serif CJK SC" in (f["name"].getDebugName(1) or ""))
    o = subset.Options()
    o.flavor, o.font_number, o.layout_features, o.hinting, o.desubroutinize = "woff2", idx, ["*"], False, True
    font = subset.load_font(src, o)
    s = subset.Subsetter(o)
    s.populate(text=text)
    s.subset(font)
    out = DOCS / "assets" / "fonts" / "wy-serif-600.woff2"
    subset.save_font(font, str(out), o)
    print(f"中文标题字体：{len(text)} 字，{out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    zh_html, en_html = page(ZH), page(EN)
    (DOCS / "index.html").write_text(zh_html, "utf-8")
    (DOCS / "en").mkdir(exist_ok=True)
    (DOCS / "en" / "index.html").write_text(en_html, "utf-8")
    subset_zh(zh_html)
    print("已生成 docs/index.html、docs/en/index.html")
