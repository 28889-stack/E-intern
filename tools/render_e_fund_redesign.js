const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");
const lucide = require("lucide");

const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, "output/imagegen/e-fund-redesign");
const HTML_DIR = path.join(ROOT, "tmp/slide-renderer/e-fund-redesign");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const W = 1920;
const H = 1080;

const ICONS = {
  background: "Workflow",
  rule: "BookOpenCheck",
  intro: "UploadCloud",
  issue: "TriangleAlert",
  solution: "Route",
  graph: "Network",
  risk: "ShieldAlert",
  trace: "GitBranch",
  time: "Timer",
  parallel: "SplitSquareHorizontal",
  demo: "MonitorPlay",
  expand: "Layers3",
  knowledge: "BrainCircuit",
  audit: "FolderSearch",
  file: "FileText",
  user: "UsersRound",
  search: "Search",
  shield: "ShieldCheck",
  link: "Link2",
  table: "Table2",
  check: "ListChecks",
  lock: "LockKeyhole",
  target: "Crosshair",
  stack: "Layers",
  box: "PackageCheck",
  arrow: "ArrowRight",
  database: "Database",
  alert: "CircleAlert",
  clock: "Clock3",
  spark: "Sparkles",
};

function icon(name, size = 36, stroke = 2.2) {
  const node = lucide[ICONS[name] || name] || lucide.Circle;
  const children = node
    .map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).map(([k, v]) => `${k}="${v}"`).join(" ")} />`)
    .join("");
  return `<svg class="svg-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${children}</svg>`;
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const slides = [
  {
    type: "hero-process",
    section: "项目背景",
    eyebrow: "背景一 | 合规流程链路",
    title: "证券投资行为合规管理流程",
    lead: "围绕员工及相关人员证券投资材料，形成从申报登记到复核判断的可追溯链路。",
    callout: { title: "项目目标", text: "结构化、可追溯、可编辑、可导出" },
    cards: [
      { icon: "rule", title: "合规需求", subtitle: "申报 / 登记 / 复核 / 留痕", bullets: ["基金公司员工及其利害关系人证券投资", "根据规定进行事前申报、定期申报等", "明确谁申报、何时申报、申报什么"] },
      { icon: "user", title: "复核判断", subtitle: "主体 / 交易 / 完整性 / 合规性", bullets: ["确定申报主体", "确定需申报的交易项目", "已申报交易是否有材料支撑"] },
      { icon: "issue", title: "人工痛点", subtitle: "翻阅 / 填写 / 异常", bullets: ["逐页翻阅材料", "手工填写字段", "人工判断异常，效率和一致性受限"] },
      { icon: "box", title: "项目目标", subtitle: "结构化 / 可追溯 / 可导出", bullets: ["把非结构化材料转为可复核结果", "形成证据链和问题清单", "支持导出与回传留痕"] },
    ],
    flow: ["合规需求", "复核判断", "人工痛点", "项目目标"],
  },
  {
    type: "three-cards-outcomes",
    section: "规则明确",
    eyebrow: "规则一 | 主体、流程与字段",
    title: "证券投资申报规则梳理",
    lead: "前期重点研究《基金从业人员证券投资管理指引（试行）》等规则，将大量法条压缩为项目需要落地的三个问题：谁要申报、何时申报、申报什么。",
    callout: { title: "规则前置理解", text: "把制度文本转化为抽取字段、人员范围和复核问题清单。" },
    cards: [
      { icon: "user", title: "申报主体", subtitle: "覆盖本人、配偶及相关账户", bullets: ["基金从业人员包括董监高和相关业务人员", "申报范围覆盖配偶、利害关系人及制度要求账户", "重点岗位适用更严格审批和交易限制"] },
      { icon: "workflow", title: "申报方式", subtitle: "覆盖入职、事前、定期和变更", bullets: ["贯穿入职申报、交易前申报或审批", "包含批准有效期、计划变更、定期报告", "不同岗位可差异化管理"] },
      { icon: "table", title: "申报内容", subtitle: "账户、持仓、交易、关系信息", bullets: ["账户类：身份、关系、证券/资金账户、券商", "持仓类：证券名称、代码、数量、市值、期限", "交易类：方向、金额、时间、理由及利益冲突"] },
    ],
    outcomes: [
      { icon: "user", title: "人员范围判断", text: "识别员工、配偶、利害关系人及需纳入管理的亲属账户" },
      { icon: "table", title: "字段抽取框架", text: "围绕账户、持仓、交易、关系四类字段设计抽取结构" },
      { icon: "check", title: "复核问题清单", text: "缺材料、缺字段、关系不明或交易异常进入人工复核" },
    ],
  },
  {
    type: "pipeline",
    section: "项目介绍",
    eyebrow: "流程一 | 核心业务链路",
    title: "智能申报合规助手",
    lead: "面向复核人员的核心链路：先批量上传材料，由系统完成识别与结构化，再由人工围绕问题项修改核对，最后回传系统或导出 Excel 留痕。",
    steps: [
      { icon: "intro", title: "上传材料", sub: "批量导入 PDF、图片、截图或压缩包", system: "文件归档、生成任务编号、记录上传人和时间", human: "选择申报对象，确认材料范围和补充说明" },
      { icon: "search", title: "识别抽取", sub: "OCR / PDF / 表格解析后生成候选结果", system: "识别身份、账户、持仓、交易与证明类材料", human: "查看识别状态，定位失败或需补充的文件" },
      { icon: "check", title: "修改核对", sub: "围绕合规结论、材料质量和证据链复核", system: "输出规则判断，识别材料模糊、缺页或证据不足", human: "人工核对结论与证据，修正字段并确认准确性" },
      { icon: "database", title: "回传 / 导出", sub: "形成最终申报结果和留痕文件", system: "生成最终表、完整表、持仓表、核对清单和问题清单", human: "确认后上传系统，或导出 Excel 用于归档与复核" },
    ],
    outcomes: ["可编辑申报结果", "可追溯证据链", "Excel 导出文件", "系统回传记录"],
    principle: "系统先把材料整理成可核对结果，人工只处理需要判断和确认的事项。",
  },
  {
    type: "source-quality",
    section: "项目问题与解决",
    eyebrow: "问题一 | 输入质量不可控",
    title: "来源复杂，格式不一，输入质量不可控",
    lead: "表格、分栏、流水记录和跨页信息直接交给 AI 容易出现识别不完整、字段错位和信息遗漏。",
    callout: { title: "风险 / 问题", text: "材料来源多、版式差异大，输入质量决定后续抽取上限。" },
    groups: [
      { title: "主要材料来源", icon: "file", items: ["广发证券对账单", "深市 / 沪市中证登材料", "持仓截图、交易截图", "身份证明材料"] },
      { title: "材料格式挑战", icon: "table", items: ["可解析 PDF", "扫描 PDF", "图片截图", "多页长表格"] },
    ],
    bottom: "表格形式的材料会导致结构化信息提取困难。",
  },
  {
    type: "solution-split",
    section: "项目问题与解决",
    eyebrow: "解决一 | 解析策略",
    title: "文件分流与多模态 + OCR 混合应用",
    lead: "系统不把不确定结果直接当成最终结论，而是将其转化为可处理的问题。",
    columns: [
      { icon: "file", title: "文件分流及信息结构化保存", tag: "文件格式不同，处理方式不同", bullets: ["尽可能结构化保存信息", "提升信息的可读性和可理解性", "保留项目原始字段并进行重标记", "为复核与校验链形成做准备"] },
      { icon: "spark", title: "多模态 + OCR 混合应用", tag: "速度提高，识别准确率提升", bullets: ["不直接使用多模态处理全部材料", "OCR 提供文本，模型识别结构", "OCR 识别困难时引入多模态", "密集表格场景降低幻觉风险"] },
    ],
  },
  {
    type: "event-grid",
    section: "项目问题与解决",
    eyebrow: "问题二 | 业务类型复杂",
    title: "同一材料中可能同时存在交易、持仓与多笔业务",
    lead: "系统不仅要抽取数据，还要理解数据背后的交易类型。",
    items: ["买入", "卖出", "派息", "利息归本", "银行转证", "股息", "打新", "送股", "非申报交易或流水", "资金流水", "费用扣划"],
    note: "不同业务类型会影响是否进入申报筛选、是否保留上下文、是否只作为证明材料。",
  },
  {
    type: "comparison",
    section: "项目问题与解决",
    eyebrow: "问题二 | 同类业务呈现不同",
    title: "同类业务在不同材料中的呈现不同",
    lead: "不同券商或登记结算材料对同一业务的表格结构、字段名称和展示顺序并不一致。",
    columns: [
      { icon: "table", title: "广发证券对账单", bullets: ["账户、证券、交易流水同页呈现", "日期与发生金额密集排列", "存在摘要和业务名称差异"] },
      { icon: "file", title: "中证登（沪市）", bullets: ["持仓、权益、变动记录分区展示", "部分字段跨行关联", "业务口径需结合上下文判断"] },
      { icon: "database", title: "中证登（深市）", bullets: ["证券代码、权益事件和流水混排", "表格行列关系更依赖版面", "需要保留页码和区域证据"] },
    ],
    bottom: "系统不仅要抽取数据，还要理解数据背后的交易类型。",
  },
  {
    type: "classification",
    section: "项目问题与解决",
    eyebrow: "解决二 | 事件分类规则",
    title: "建立事件分类和申报筛选规则",
    lead: "先完整抽取，再分类筛选，既避免漏报，也避免把资金流水误当成证券交易申报。",
    buckets: [
      { icon: "target", title: "重点申报事件", sub: "买入、卖出、配股、打新、送股等", tag: "进入申报筛选" },
      { icon: "stack", title: "保留观察事件", sub: "分红、派息、利息、资金变动等", tag: "保留原始证明与上下文" },
      { icon: "shield", title: "非申报流水", sub: "银证转账、利息归本等", tag: "不进入最终申报" },
    ],
    flow: ["完整抽取", "事件分类", "判断持仓影响", "生成最终表与完整表"],
  },
  {
    type: "graph-rag",
    section: "项目问题与解决",
    eyebrow: "解决二 | Graph RAG 上下文增强层",
    title: "Graph RAG：让 AI 理解业务字段之间的关联关系",
    lead: "使用 Graph RAG 让交易、持仓、分红、账户和证券代码在同一关系网络中被召回和解释。",
    process: ["OCR / 表格结果", "Chunk / 向量化", "相似度检索", "图关系扩展", "LLM 抽取"],
    graphNodes: ["账户", "证券代码", "交易事件", "持仓", "分红 / 利息事件"],
    advantages: [
      { title: "提高召回", normal: "普通 RAG：只按文本相似度找片段", graph: "Graph RAG：检索后沿实体关系补相关片段" },
      { title: "增强关联", normal: "普通 RAG：跨页信息容易断开", graph: "Graph RAG：把同账户、同证券、同事件连起来" },
      { title: "减少干扰", normal: "普通 RAG：Top-K 片段仍混入无关 OCR", graph: "Graph RAG：实体扩展后只保留相关局部上下文" },
    ],
    model: "Embedding：BAAI/bge-small-zh-v1.5；图结构在检索结果基础上，沿账户、证券代码、交易 / 分红 / 利息事件关系扩展上下文。",
  },
  {
    type: "risk-list",
    section: "项目问题与解决",
    eyebrow: "问题三 | AI 幻觉与误判",
    title: "AI 幻觉和误判风险必须可控",
    lead: "对于合规申报系统，AI 不能只追求“看起来完整”，结果必须可复核、可追溯、可纠错。",
    risks: ["把红利、利息误认为买入或卖出", "把银证转账误认为证券交易", "字段缺失时自行推断金额、价格或日期", "将相似业务类型混淆", "上下行表格信息错误关联", "对不确定内容给出过度确定结论"],
  },
  {
    type: "trace-rule",
    section: "项目问题与解决",
    eyebrow: "解决三 | 可追溯 / 可校验",
    title: "用链路追溯和代码规则，控制 AI 幻觉与误判",
    lead: "AI 只生成初步抽取结果；最终进入申报版前，必须同时通过证据链可追溯和代码规则可校验。",
    columns: [
      { icon: "trace", title: "链路追溯", subtitle: "每个字段都能回到原始材料", bullets: ["保留原始文件、页码、表格区域或截图位置", "记录 OCR / PDF / Table chunk 与抽取字段的对应关系", "关键字段必须有来源证据", "复核人员可从结果反查到证据"] },
      { icon: "rule", title: "规则校验", subtitle: "用代码规则约束 AI 输出", bullets: ["字段类型校验：日期、金额、证券代码、交易方向", "业务枚举归一：买入 / 卖出 / 分红 / 非申报流水", "不确定或冲突结果不进最终版", "异常进入问题清单"] },
    ],
    flow: ["AI 初抽取", "字段标准化", "规则校验", "证据挂接", "结果分流"],
    bottom: "AI 的不确定性不会被包装成结论，而是转化为可追溯证据、可执行规则和可复核问题项。",
  },
  {
    type: "two-problems",
    section: "项目问题与解决",
    eyebrow: "问题四 | 长材料处理复杂",
    title: "处理时间较长，长材料处理复杂",
    lead: "长材料既不能整份一次性交给 AI，也不能简单拆分后各自为政。",
    columns: [
      { icon: "time", title: "整份材料一次性交给 AI 的风险", bullets: ["超出上下文限制", "响应时间过长", "LLM 输出被截断", "信息密度太大，AI 幻觉率提升"] },
      { icon: "split", title: "简单拆分处理的新问题", bullets: ["跨页持仓关系丢失", "同一交易被重复识别", "文件结论无法统一", "最终结果难以合并"] },
    ],
  },
  {
    type: "parallel",
    section: "项目问题与解决",
    eyebrow: "解决四 | 并行处理",
    title: "长文件并行处理：材料拆分、去重、截断兜底",
    lead: "按页 / 表格区域切分成任务队列；OCR、表格解析、LLM 抽取并行执行，再由合并层去重、校验和补偿。",
    process: ["文件切分", "任务入队", "并发抽取", "统一合并", "去重兜底", "最终输出"],
    cards: [
      { icon: "parallel", title: "提速方式", bullets: ["OCR / PDF / Table 解析按页并发", "LLM 抽取按 chunk 并发，限制并发数", "已解析文件做缓存，重复上传不重新 OCR", "只把相关片段送入抽取"] },
      { icon: "route", title: "重叠区域设计", bullets: ["每个分块包含相邻区域的重叠部分", "保护同一笔交易不被截断", "预估输出长度，超限自动二次切分"] },
      { icon: "check", title: "去重合并", bullets: ["交易按账户 + 证券代码 + 日期 + 方向 + 金额近似匹配", "持仓按账户 + 证券代码 + 截止日期归并", "同一证据多次命中只保留一条", "冲突结果进入复核清单"] },
    ],
    metric: "长材料处理耗时降低约 50%，速度提升一倍以上。",
  },
  {
    type: "demo",
    section: "项目演示",
    eyebrow: "演示一 | 复核工作台",
    title: "智能申报合规助手演示",
    lead: "从材料上传到识别抽取、问题复核、导出留痕，演示核心工作流。",
    panes: [
      { icon: "intro", title: "材料接入", text: "批量上传 PDF、图片、截图或压缩包，系统自动生成任务并归档。" },
      { icon: "search", title: "识别抽取", text: "解析身份、账户、持仓、交易和证明类材料，生成候选结果。" },
      { icon: "check", title: "人工复核", text: "围绕问题项修正字段、确认合规结论，并回看证据位置。" },
      { icon: "database", title: "导出留痕", text: "输出最终表、完整表、持仓表、问题清单及系统回传记录。" },
    ],
  },
  {
    type: "expansion",
    section: "项目拓展性",
    eyebrow: "拓展一 | 泛化能力",
    title: "多来源材料识别能力拓展：泛化能力与识别准确率提高",
    lead: "增强 Graph RAG，并强化 LLM 与 PDF 解析、OCR、表格抽取结果之间的协同，支持更多券商材料接入。",
    columns: [
      { icon: "graph", title: "主线一：多券商材料泛化", accent: "cyan", bullets: ["建立多券商字段别名、交易类型表达、表格结构和证据位置关系", "识别不同券商材料中不同表达背后的同一业务含义", "新券商材料接入时，减少完全依赖人工重新适配", "Graph RAG 解决券商格式和业务表达不一致"] },
      { icon: "spark", title: "主线二：解析与模型协同", accent: "orange", bullets: ["PDF 解析、OCR、表格抽取先保留行列结构、页码、区域和上下文", "LLM 处理整理后的结构化输入，而不是混乱原始文件", "低置信 OCR、跨页表格、字段缺失、异常格式进入复核", "解析协同解决复杂材料输入质量不稳定"] },
    ],
    outcomes: [
      { title: "多券商接入更快", text: "复用业务语义关系，减少重复适配" },
      { title: "复杂材料识别更准", text: "减少 OCR 错漏、表格错位和跨页丢失" },
      { title: "抽取结果更可追溯", text: "字段回到页码、区域和原始证据" },
      { title: "泛化能力可持续沉淀", text: "新材料反哺图谱和解析策略" },
    ],
  },
  {
    type: "knowledge",
    section: "项目拓展性",
    eyebrow: "拓展二 | 规则知识化",
    title: "合规规则知识化拓展：支撑规则校验与“问小易”问答",
    lead: "建设可检索、可维护、可追溯的合规知识库，将制度条款、业务口径、材料要求、复核经验和常见问题沉淀为可调用知识资产。",
    columns: [
      { icon: "rule", title: "目标一：增强合规规则校验", bullets: ["抽取结果形成后，调用知识库中的制度条款、材料要求和校验口径", "辅助判断字段缺失、材料支撑不足、交易是否属于申报范围", "输出规则依据、适用口径和需要人工确认的问题项"] },
      { icon: "knowledge", title: "目标二：增强“问小易”合规问答", bullets: ["员工和复核人员可自然语言查询申报范围、材料要求和流程口径", "回答附带依据来源、适用范围和人工复核提示", "常见问题和复核经验持续沉淀，形成可维护知识资产"] },
    ],
    flow: ["规则口径结构化", "系统调用", "依据留痕"],
  },
  {
    type: "audit",
    section: "项目拓展性",
    eyebrow: "拓展三 | 内控审计复核",
    title: "合规材料复核场景拓展：面向内控与审计材料的初筛归类",
    lead: "将材料理解、规则判断、证据链管理能力迁移到内控检查、审计支持、稽核材料整理等复核环节。",
    process: [
      { icon: "file", title: "材料接入", text: "制度 / 附件 / 底稿按项目和流程进入系统" },
      { icon: "search", title: "内控初筛", text: "识别材料类型和关键字段，提示缺失、版本、签章异常" },
      { icon: "audit", title: "审计归类", text: "按期间、机构、业务类型归档，抽取事实和证据位置" },
      { icon: "check", title: "人工确认", text: "高风险和冲突事项入清单，复核结论反向沉淀" },
    ],
    boundary: "适合材料密集、规则明确、需要证据索引的复核环节；系统负责初筛、归类、提示和索引，不替代内控或审计人员作出最终判断。",
    outcomes: ["降低整理成本", "提高初筛一致性", "强化证据管理", "形成可迁移能力底座"],
  },
];

function header(slide, index) {
  const page = String(index + 1).padStart(2, "0");
  return `
    <div class="topbar">
      <div class="brand"><div class="mark">E</div><div><b>E FUND</b><span>易方达</span></div></div>
      <div class="tagline">${esc(slide.section)} · 提升价值</div>
    </div>
    <div class="footer"><span>易方达基金 · 内部交流，请勿外传</span><span>${page} / 17</span></div>
  `;
}

function titleBlock(slide) {
  return `
    <div class="eyebrow">${esc(slide.eyebrow || slide.section)}</div>
    <div class="title-row">
      <h1>${esc(slide.title)}</h1>
      ${slide.callout ? `<div class="mini-callout">${icon("spark", 28)}<div><b>${esc(slide.callout.title)}</b><span>${esc(slide.callout.text)}</span></div></div>` : ""}
    </div>
    ${slide.lead ? `<div class="lead"><div class="lead-icon">${icon("search", 30)}</div><p>${esc(slide.lead)}</p></div>` : ""}
  `;
}

function card(c, cls = "") {
  return `<div class="card ${cls}">
    <div class="card-head"><div class="round-icon">${icon(c.icon || "file")}</div><div><h3>${esc(c.title)}</h3>${c.subtitle || c.sub ? `<p>${esc(c.subtitle || c.sub)}</p>` : ""}</div></div>
    ${c.tag ? `<div class="tag">${esc(c.tag)}</div>` : ""}
    ${c.text ? `<p class="card-text">${esc(c.text)}</p>` : ""}
    ${c.bullets ? `<ul>${c.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
  </div>`;
}

function flow(items, cls = "") {
  return `<div class="flow ${cls}">${items.map((item, i) => `
    <div class="flow-item"><span>${typeof item === "string" ? esc(item) : esc(item.title)}</span></div>
    ${i < items.length - 1 ? `<div class="flow-arrow">${icon("arrow", 34, 1.7)}</div>` : ""}
  `).join("")}</div>`;
}

function outcomes(items) {
  const countClass = items.length === 4 ? "four-cols" : "";
  return `<div class="outcomes ${countClass}">${items.map((o) => `
    <div class="outcome"><div class="round-icon muted">${icon(o.icon || "check", 32)}</div><div><b>${esc(o.title || o)}</b>${o.text ? `<span>${esc(o.text)}</span>` : ""}</div></div>
  `).join("")}</div>`;
}

function renderBody(slide) {
  if (slide.type === "hero-process") {
    return `
      <div class="grid four">${slide.cards.map((c) => card(c)).join("")}</div>
      ${flow(slide.flow, "wide-flow")}
    `;
  }
  if (slide.type === "three-cards-outcomes") {
    return `<div class="grid three">${slide.cards.map((c) => card(c)).join("")}</div><h2>对项目设计的转化</h2>${outcomes(slide.outcomes)}`;
  }
  if (slide.type === "pipeline") {
    return `
      <div class="pipeline">${slide.steps.map((s, i) => `
        <div class="step-card">
          <div class="step-no">${String(i + 1).padStart(2, "0")}</div>
          <div class="round-icon">${icon(s.icon)}</div>
          <h3>${esc(s.title)}</h3><p>${esc(s.sub)}</p>
          <div class="mini-section"><b>系统处理</b><span>${esc(s.system)}</span></div>
          <div class="mini-section human"><b>人工动作</b><span>${esc(s.human)}</span></div>
        </div>`).join("")}
      </div>
      <div class="result-strip"><b>最终输出</b>${slide.outcomes.map((o) => `<span>${esc(o)}</span>`).join("")}</div>
      <div class="principle">${esc(slide.principle)}</div>
    `;
  }
  if (slide.type === "source-quality") {
    return `
      <div class="split">${slide.groups.map((g) => card({ ...g, bullets: g.items })).join("")}</div>
      <div class="large-note">${icon("alert", 42)}<span>${esc(slide.bottom)}</span></div>
    `;
  }
  if (slide.type === "solution-split") {
    return `<div class="split tall">${slide.columns.map((c) => card(c)).join("")}</div>`;
  }
  if (slide.type === "event-grid") {
    return `
      <div class="event-grid">${slide.items.map((x, i) => `<div class="event-pill ${i % 3 === 0 ? "hot" : i % 3 === 1 ? "cool" : ""}">${esc(x)}</div>`).join("")}</div>
      <div class="large-note">${icon("shield", 42)}<span>${esc(slide.note)}</span></div>
    `;
  }
  if (slide.type === "comparison") {
    return `<div class="grid three">${slide.columns.map((c) => card(c)).join("")}</div><div class="large-note">${icon("knowledge", 42)}<span>${esc(slide.bottom)}</span></div>`;
  }
  if (slide.type === "classification") {
    return `<div class="grid three bucket-row">${slide.buckets.map((b) => card(b)).join("")}</div>${flow(slide.flow, "wide-flow")}`;
  }
  if (slide.type === "graph-rag") {
    return `
      ${flow(slide.process, "compact-flow")}
      <div class="graph-layout">
        <div class="graph-box">
          <h2>图结构扩展的实体关系</h2>
          <div class="node-map">${slide.graphNodes.map((n, i) => `<div class="node n${i}">${esc(n)}</div>`).join("")}<div class="line l1"></div><div class="line l2"></div><div class="line l3"></div><div class="line l4"></div></div>
          <div class="model-note">${esc(slide.model)}</div>
        </div>
        <div class="adv-box"><h2>相比普通 RAG 的项目优势</h2>${slide.advantages.map((a) => `
          <div class="adv"><b>${esc(a.title)}</b><p>${esc(a.normal)}</p><p class="graph-line">${esc(a.graph)}</p></div>
        `).join("")}</div>
      </div>
    `;
  }
  if (slide.type === "risk-list") {
    return `<div class="risk-grid">${slide.risks.map((r, i) => `<div class="risk"><span>${String(i + 1).padStart(2, "0")}</span>${icon("alert", 34)}<b>${esc(r)}</b></div>`).join("")}</div>`;
  }
  if (slide.type === "trace-rule") {
    return `<div class="split compact">${slide.columns.map((c) => card(c)).join("")}</div>${flow(slide.flow, "wide-flow")}<div class="principle">${esc(slide.bottom)}</div>`;
  }
  if (slide.type === "two-problems") {
    return `<div class="split tall">${slide.columns.map((c) => card(c)).join("")}</div>`;
  }
  if (slide.type === "parallel") {
    return `${flow(slide.process, "compact-flow six")}<div class="grid three dense">${slide.cards.map((c) => card(c)).join("")}</div><div class="metric">${esc(slide.metric)}</div>`;
  }
  if (slide.type === "demo") {
    return `<div class="demo-screen"><div class="screen-bar"><span></span><span></span><span></span></div><div class="demo-grid">${slide.panes.map((p) => card({ ...p, bullets: null })).join("")}</div></div>`;
  }
  if (slide.type === "expansion") {
    return `<div class="split compact">${slide.columns.map((c) => card(c, c.accent || "")).join("")}</div><h2>目标效果</h2>${outcomes(slide.outcomes)}`;
  }
  if (slide.type === "knowledge") {
    return `<div class="split tall">${slide.columns.map((c) => card(c)).join("")}</div>${flow(slide.flow, "wide-flow")}`;
  }
  if (slide.type === "audit") {
    return `<div class="audit-flow">${slide.process.map((p, i) => `<div class="audit-card">${icon(p.icon, 42)}<b>${esc(p.title)}</b><span>${esc(p.text)}</span></div>${i < slide.process.length - 1 ? `<div class="flow-arrow">${icon("arrow", 34, 1.7)}</div>` : ""}`).join("")}</div><div class="large-note">${icon("shield", 42)}<span>${esc(slide.boundary)}</span></div><div class="simple-outcomes">${slide.outcomes.map((o) => `<span>${esc(o)}</span>`).join("")}</div>`;
  }
  return "";
}

function slideHtml(slide, index) {
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css()}</style></head><body><main class="slide">${header(slide, index)}<section class="content">${titleBlock(slide)}${renderBody(slide)}</section></main></body></html>`;
}

function css() {
  return `
    * { box-sizing: border-box; }
    html, body { width:${W}px; height:${H}px; margin:0; background:#eef3f8; font-family:"Hiragino Sans GB","STHeiti","PingFang SC","Microsoft YaHei",Arial,sans-serif; color:#092b56; }
    .slide { position:relative; width:${W}px; height:${H}px; overflow:hidden; background:radial-gradient(circle at 72% 20%, rgba(44,84,130,.13), transparent 34%), linear-gradient(180deg,#fbfdff 0%,#f4f7fb 100%); }
    .topbar { position:absolute; inset:0 0 auto 0; height:88px; background:linear-gradient(90deg,#061f44 0%,#002b5e 58%,#052348 100%); color:#fff; display:flex; align-items:center; justify-content:space-between; padding:0 54px; box-shadow:0 7px 28px rgba(3,31,67,.18); }
    .brand { display:flex; align-items:center; gap:18px; font-size:26px; letter-spacing:0; }
    .brand .mark { width:58px; height:43px; font-size:52px; line-height:40px; font-weight:900; transform:scaleX(1.22); }
    .brand b { display:inline-block; margin-right:12px; font-size:28px; }
    .brand span { font-weight:800; font-size:25px; }
    .tagline { color:#dbe7f4; font-size:20px; font-weight:600; }
    .content { position:absolute; inset:134px 96px 82px 96px; }
    .eyebrow { font-size:22px; font-weight:800; color:#063470; margin-bottom:18px; }
    .title-row { display:flex; gap:22px; align-items:flex-start; justify-content:space-between; }
    h1 { margin:0; font-size:48px; line-height:1.15; letter-spacing:0; font-weight:900; color:#082b57; max-width:1320px; }
    h2 { margin:24px 0 14px; font-size:27px; line-height:1.2; color:#092f60; font-weight:900; border-left:5px solid #004f9e; padding-left:14px; }
    .mini-callout { flex:0 0 330px; min-height:84px; display:flex; gap:18px; align-items:center; padding:17px 22px; border-radius:18px; background:rgba(255,255,255,.82); border:1px solid #dce6f0; box-shadow:0 14px 36px rgba(22,43,74,.12); }
    .mini-callout b { display:block; font-size:21px; margin-bottom:5px; }
    .mini-callout span { color:#51677f; font-size:16px; }
    .lead { margin:26px 0 30px; display:flex; align-items:center; gap:24px; min-height:96px; padding:20px 30px; border-radius:16px; background:rgba(255,255,255,.74); border:1px solid #d8e3ef; box-shadow:0 14px 42px rgba(27,56,90,.08); }
    .lead p { margin:0; font-size:22px; line-height:1.55; font-weight:700; color:#163963; }
    .lead-icon, .round-icon { width:70px; height:70px; border-radius:50%; background:#edf2f8; display:grid; place-items:center; color:#06488d; flex:0 0 auto; }
    .round-icon { width:68px; height:68px; }
    .round-icon.muted { background:#eef2f7; color:#082f60; }
    .svg-icon { display:block; }
    .grid { display:grid; gap:26px; }
    .grid.four { grid-template-columns:repeat(4,1fr); }
    .grid.three { grid-template-columns:repeat(3,1fr); }
    .card { min-height:210px; padding:26px 30px; border-radius:14px; background:rgba(255,255,255,.78); border:1px solid #d9e3ed; box-shadow:0 13px 36px rgba(28,57,90,.08); position:relative; overflow:hidden; }
    .card:before { content:""; position:absolute; inset:0 auto auto 0; height:5px; width:100%; background:linear-gradient(90deg,#06488d,#c7d6e8); opacity:.45; }
    .card.orange:before { background:linear-gradient(90deg,#ea7b1a,#f4d2aa); opacity:.8; }
    .card.cyan:before { background:linear-gradient(90deg,#00a9c9,#9bdde9); opacity:.85; }
    .card-head { display:flex; align-items:center; gap:18px; margin-bottom:20px; }
    .card h3 { margin:0; font-size:25px; line-height:1.18; font-weight:900; color:#092f60; }
    .card-head p { margin:8px 0 0; font-size:18px; color:#21466f; font-weight:700; }
    .tag { display:inline-block; padding:8px 12px; margin:-4px 0 14px; border-radius:8px; color:#004f9e; background:#eaf4fb; font-weight:800; font-size:16px; }
    .card-text { margin:0; font-size:19px; line-height:1.5; color:#314a66; }
    ul { margin:0; padding-left:22px; }
    li { margin:9px 0; font-size:18px; line-height:1.38; color:#173b64; font-weight:600; }
    .flow { display:flex; align-items:center; gap:18px; border-radius:14px; background:rgba(255,255,255,.78); border:1px solid #d7e2ee; box-shadow:0 12px 32px rgba(25,53,84,.08); padding:20px 28px; }
    .wide-flow { margin-top:28px; justify-content:space-between; }
    .compact-flow { margin:4px 0 22px; padding:18px 24px; }
    .flow-item { min-width:0; flex:1; display:flex; justify-content:center; align-items:center; height:62px; border-radius:31px; background:#083b76; color:#fff; font-size:19px; font-weight:900; text-align:center; padding:0 18px; }
    .compact-flow .flow-item { height:70px; background:#fff; color:#092f60; border:1px solid #cfddea; border-top:5px solid #00a9c9; border-radius:4px; }
    .flow-arrow { color:#7389a5; flex:0 0 auto; }
    .outcomes { display:grid; grid-template-columns:repeat(3,1fr); gap:18px; padding:20px 0 0; border-top:2px solid #d2dfeb; }
    .outcomes.four-cols { grid-template-columns:repeat(4,1fr); }
    .outcome { display:flex; align-items:center; gap:18px; padding:10px 18px; border-right:1px solid #cbd9e7; min-height:84px; }
    .outcome:last-child { border-right:none; }
    .outcome b { display:block; font-size:22px; color:#092f60; margin-bottom:6px; }
    .outcome span { display:block; font-size:17px; line-height:1.38; color:#48617a; font-weight:650; }
    .pipeline { display:grid; grid-template-columns:repeat(4,1fr); gap:20px; }
    .step-card { position:relative; min-height:420px; padding:24px 24px; border-radius:14px; background:#fff; border:1px solid #d9e4ef; box-shadow:0 14px 38px rgba(28,57,90,.08); }
    .step-no { position:absolute; top:20px; right:22px; color:#9aacbf; font-size:22px; font-weight:900; }
    .step-card h3 { margin:16px 0 6px; font-size:26px; }
    .step-card p { margin:0 0 18px; color:#244a73; font-size:17px; line-height:1.4; font-weight:700; }
    .mini-section { padding:13px 14px; border-radius:10px; background:#edf6fb; margin-top:12px; }
    .mini-section.human { background:#f5f7fa; }
    .mini-section b, .mini-section span { display:block; }
    .mini-section b { margin-bottom:7px; color:#004f9e; font-size:16px; }
    .mini-section span { color:#2d4c6e; font-size:15px; line-height:1.38; font-weight:650; }
    .result-strip { margin-top:16px; padding:15px 24px; border-radius:13px; background:#082f60; color:#fff; display:flex; align-items:center; gap:22px; font-size:18px; }
    .result-strip b { margin-right:12px; }
    .result-strip span { padding:8px 15px; border-radius:999px; background:rgba(255,255,255,.12); }
    .principle, .metric { margin-top:14px; padding:14px 24px; border-left:5px solid #00a9c9; background:#eaf6fb; color:#0a376a; font-size:20px; line-height:1.38; font-weight:850; }
    .split { display:grid; grid-template-columns:repeat(2,1fr); gap:28px; }
    .split.tall .card { min-height:390px; }
    .split.compact .card { min-height:300px; }
    .large-note { margin-top:28px; min-height:104px; border-radius:14px; border:1px solid #d9e3ee; background:#fff; box-shadow:0 12px 32px rgba(28,57,90,.08); display:flex; align-items:center; gap:22px; padding:24px 30px; color:#092f60; font-size:26px; font-weight:900; }
    .large-note .svg-icon { color:#06488d; flex:0 0 auto; }
    .event-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:22px; margin-top:12px; }
    .event-pill { min-height:88px; border-radius:14px; display:grid; place-items:center; background:#fff; border:1px solid #d8e3ed; color:#0b3768; font-size:26px; font-weight:900; box-shadow:0 11px 30px rgba(25,54,89,.08); }
    .event-pill.hot { border-top:5px solid #004f9e; }
    .event-pill.cool { border-top:5px solid #00a9c9; }
    .bucket-row .card { min-height:250px; }
    .graph-layout { display:grid; grid-template-columns:1.05fr 1fr; gap:28px; }
    .graph-box, .adv-box, .demo-screen { border-radius:14px; background:rgba(255,255,255,.82); border:1px solid #d9e4ef; box-shadow:0 13px 36px rgba(28,57,90,.08); padding:24px 30px; }
    .node-map { height:228px; position:relative; margin-top:8px; background:#f3f8fc; border-radius:12px; overflow:hidden; }
    .node { position:absolute; min-width:130px; height:48px; border-radius:8px; background:#dff3f8; border-left:5px solid #00a9c9; color:#053568; font-size:18px; font-weight:900; display:grid; place-items:center; z-index:2; }
    .n0 { left:56px; top:48px; } .n1 { left:260px; top:48px; } .n2 { right:70px; top:48px; background:#fff2df; border-left-color:#e77b17; } .n3 { left:190px; bottom:46px; } .n4 { right:92px; bottom:46px; background:#fff2df; border-left-color:#e77b17; }
    .line { position:absolute; height:3px; background:#9cb2c8; transform-origin:left center; z-index:1; }
    .l1 { left:188px; top:73px; width:82px; } .l2 { left:390px; top:73px; width:335px; } .l3 { left:255px; top:115px; width:160px; transform:rotate(37deg); } .l4 { left:470px; top:145px; width:260px; transform:rotate(-16deg); }
    .model-note { margin-top:18px; padding:18px; border-radius:10px; background:#082f60; color:#fff; font-size:17px; line-height:1.45; font-weight:750; }
    .adv { display:grid; grid-template-columns:130px 1fr; gap:10px 18px; align-items:start; padding:16px 0; border-bottom:1px solid #d9e4ef; }
    .adv:last-child { border-bottom:none; }
    .adv b { grid-row:span 2; font-size:24px; color:#082f60; }
    .adv p { margin:0; font-size:17px; line-height:1.35; color:#60758c; font-weight:800; }
    .adv .graph-line { color:#063b76; background:#eaf6fb; display:inline-block; padding:4px 8px; border-radius:4px; }
    .risk-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:24px; }
    .risk { min-height:164px; padding:28px; border-radius:14px; background:#fff; border:1px solid #d9e4ef; border-top:5px solid #e77b17; box-shadow:0 13px 36px rgba(28,57,90,.08); color:#092f60; position:relative; display:flex; flex-direction:column; gap:14px; }
    .risk span { position:absolute; top:18px; right:22px; color:#a8b8c8; font-size:24px; font-weight:900; }
    .risk b { font-size:23px; line-height:1.35; }
    .grid.dense .card { min-height:285px; padding:24px 26px; }
    .grid.dense li { font-size:16px; margin:7px 0; }
    .metric { text-align:center; border-left:none; border-top:5px solid #00a9c9; }
    .screen-bar { height:42px; background:#082f60; margin:-24px -30px 28px; border-radius:14px 14px 0 0; display:flex; align-items:center; gap:10px; padding-left:22px; }
    .screen-bar span { width:13px; height:13px; border-radius:50%; background:#d7e4f1; opacity:.85; }
    .demo-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:22px; }
    .demo-grid .card { min-height:430px; }
    .audit-flow { display:flex; align-items:stretch; gap:16px; margin-top:8px; }
    .audit-card { flex:1; min-height:250px; border-radius:14px; background:#fff; border:1px solid #d9e4ef; box-shadow:0 13px 36px rgba(28,57,90,.08); padding:30px 24px; display:flex; flex-direction:column; align-items:flex-start; gap:18px; }
    .audit-card .svg-icon { color:#06488d; }
    .audit-card b { font-size:25px; color:#092f60; }
    .audit-card span { font-size:17px; line-height:1.45; color:#425d77; font-weight:700; }
    .simple-outcomes { margin-top:24px; display:grid; grid-template-columns:repeat(4,1fr); gap:18px; }
    .simple-outcomes span { min-height:80px; border-left:5px solid #00a9c9; background:#fff; border-radius:8px; display:flex; align-items:center; padding:0 22px; font-size:22px; font-weight:900; color:#092f60; box-shadow:0 10px 28px rgba(28,57,90,.07); }
    .footer { position:absolute; left:96px; right:96px; bottom:25px; padding-top:16px; border-top:1px solid #cbd8e5; display:flex; justify-content:space-between; color:#7d8fa3; font-size:16px; font-weight:700; }
  `;
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.mkdirSync(HTML_DIR, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    executablePath: fs.existsSync(CHROME) ? CHROME : undefined,
  });

  for (let i = 0; i < slides.length; i += 1) {
    const html = slideHtml(slides[i], i);
    const htmlPath = path.join(HTML_DIR, `slide-${String(i + 1).padStart(2, "0")}.html`);
    fs.writeFileSync(htmlPath, html, "utf8");
    const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
    await page.goto(`file://${htmlPath}`, { waitUntil: "load" });
    await page.screenshot({ path: path.join(OUT_DIR, `slide-${String(i + 1).padStart(2, "0")}.png`), fullPage: false });
    await page.close();
  }

  await browser.close();
  console.log(`Rendered ${slides.length} slides to ${OUT_DIR}`);
}

module.exports = { slides, ICONS };

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
