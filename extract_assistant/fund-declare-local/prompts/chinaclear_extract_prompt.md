# 中证登材料事件级抽取规则与字段解释表

## 一、核心处理逻辑

中证登材料进入 LLM 后，先判断材料类型，再决定抽取内容。

如果是“证券持有信息”：
  只抽取 holding_snapshot_records
  不抽取 business_events

如果是“证券持有变更信息”：
  只抽取 business_events
  不把“期末余额”当作完整持仓快照

如果同一文件中同时包含持仓表和变更表：
  按 section 拆开
  持仓部分抽取 holding_snapshot_records
  变更部分抽取 business_events

当前样本中：

《投资者证券持有变更信息（沪市）》 → 交易/变更事件文件
《投资者证券持有变更信息（深市）》 → 交易/变更事件文件
《投资者证券持有信息（深市B股）》 → 持仓快照文件

深市 B 股样本标题为“投资者证券持有信息”，字段为“持有日期、持有数量、其中冻结数量”，没有“过户日期、过户类型、过户数量”，因此应只抽持仓快照，不生成业务事件。

## 二、事件粒度原则

### 1. 交易事件

交易事件按流水行识别：

一次交易 = 一个事件
多次交易 = 多个事件

因此：

沪市：一行“交易过户” = 一个 security_trade 事件
深市：一行“买入” = 一个 security_trade 事件
深市：一行“卖出” = 一个 security_trade 事件

不得因为同一证券、同一日期、同一价格而合并交易事件。

### 2. 多阶段公司行为 / 权益事件

如果多行只是同一个业务事实的不同处理阶段，则合并为一个事件。

例如：

权益登记 + 权益挂牌 = 一个红利事件
权益登记 + 权益挂牌 = 一个兑息事件
权益登记 + 上市流通 + 冲销 = 一个送股/转增事件

这类合并不是因为“行数少”，而是因为它们本质上属于同一业务的不同阶段。

## 三、当前样本支持的事件枚举

当前只枚举样本中已经出现的事件类型：

[
  "security_trade",
  "security_registration",
  "cash_dividend",
  "bond_interest",
  "bonus_share",
  "unknown_event"
]

| event_type | 事件名称 | 事件粒度 | 当前样本表现 |
| --- | --- | --- | --- |
| security_trade | 证券交易事件 | 一行一个事件 | 沪市“交易过户”；深市“买入/卖出” |
| security_registration | 打新/证券登记入账事件 | 一行一个事件 | 深市“股份登记” |
| cash_dividend | 现金红利/分红/股息/派息事件 | 沪市多阶段合并；深市可一行一个事件 | 沪市“红利 + 权益登记/权益挂牌”；深市“分红” |
| bond_interest | 债券/可转债兑息事件 | 多阶段合并 | 沪市“兑息 + 权益登记/权益挂牌” |
| bonus_share | 送股/转增/红股事件 | 多阶段合并 | 沪市“送股 + 权益登记/上市流通” |
| unknown_event | 未知业务事件 | 视情况 | 疑似业务但无法判断 |

no_business_event 不是事件枚举，而是整份材料没有业务事件时的兜底结构。

## 四、字段解释表

### 1. 沪市字段解释表

| 市场 | 一级字段 | 一级字段释义 | 子字段 / 取值 | 子字段释义 | 是否在材料中出现 |
| --- | --- | --- | --- | --- | --- |
| 沪市 | 证券类别 | 中国结算在沪市凭证中对证券或持有份额性质的类别标识。 | 无限售流通股 | 普通股票中没有限售条件、可在交易所流通的股份类别。 | 是 |
| 沪市 | 证券类别 | 中国结算在沪市凭证中对证券或持有份额性质的类别标识。 | 固定收益类 | 债券、可转债等固定收益类证券；样本中主要对应可转债兑息。 | 是 |
| 沪市 | 证券类别 | 中国结算在沪市凭证中对证券或持有份额性质的类别标识。 | 固定收益类（流通） | 固定收益类证券的流通状态，样本中对应可转债交易过户流水。 | 是 |
| 沪市 | 证券类别 | 中国结算在沪市凭证中对证券或持有份额性质的类别标识。 | 基金（无限售流通） | 场内基金份额，且不存在限售流通限制。 | 是 |
| 沪市 | 权益类别 | 标识该笔持有变更对应的权益分派或债券权益事项。 | 现金红利 / 红利 / 股息 / 派息 / 分红 | 上市公司派发现金红利或股息形成的权益类别。 | 是 |
| 沪市 | 权益类别 | 标识该笔持有变更对应的权益分派或债券权益事项。 | 股票红利 / 送股 / 转增 / 红股 | 派发股票红利、送股或转增形成的权益类别。 | 是 |
| 沪市 | 权益类别 | 标识该笔持有变更对应的权益分派或债券权益事项。 | 兑息 / 债券兑付 / 付息 | 债券或可转债兑息、兑付相关权益事项。 | 是 |
| 沪市 | 过户日期 | 该笔持有变更在中国结算记录中的发生日期。 | 日期 | 作为业务事件的发生时间 event_date。 | 是 |
| 沪市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 交易过户 | 交易导致证券过入或过出。一行交易过户就是一个交易事件。 | 是 |
| 沪市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 权益登记 | 权益业务的登记阶段，例如红利登记、兑息登记、送股登记。不是买入。 | 是 |
| 沪市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 权益挂牌 | 权益业务的处理阶段，例如红利挂牌、兑息挂牌。不是卖出。 | 是 |
| 沪市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 上市流通 | 证券或权益进入可流通状态。送股/转增事件中常作为新增股份流通和冲销阶段。 | 是 |
| 沪市 | 过户数量 | 本笔持有变更的数量。 | 正数 | 表示过入、登记增加或权益数量增加；具体含义要结合过户类型判断。 | 是 |
| 沪市 | 过户数量 | 本笔持有变更的数量。 | 负数 | 表示过出或冲减；在权益挂牌、上市流通负数行中，通常是权益处理方向或临时权益冲销，不等于卖出。 | 是 |
| 沪市 | 期末余额 | 本笔流水处理后的余额。 | 数值 | 记录该行处理后的余额，必须原样保存；不等同于完整持仓快照。 | 是 |
| 沪市 | 成交价格 | 原始价格字段。 | 交易价格 | 交易过户行中通常表示该笔交易价格。 | 是 |
| 沪市 | 成交价格 | 原始价格字段。 | 权益处理价格 / 单位权益字段 | 红利、兑息等权益挂牌行中可能出现数值，但本阶段只原样记录，不计算总金额。 | 是 |
| 沪市 | 交易单元号 | 沪市交易或登记相关的交易单元编号。 | 交易单元代码 | 如 23206、29344。 | 是 |
| 沪市 | 结算参与人简称 | 对应结算参与人的简称。 | 参与人简称 | 如广发证券公司客户、兴业证券公司客户。 | 是 |

### 2. 深市字段解释表

| 市场 | 一级字段 | 一级字段释义 | 子字段 / 取值 | 子字段释义 | 是否在材料中出现 |
| --- | --- | --- | --- | --- | --- |
| 深市 | 证券代码 | 证券在深市的代码。 | 000xxx、002xxx、300xxx、301xxx | 深市股票代码。 | 是 |
| 深市 | 证券代码 | 证券在深市的代码。 | 123xxx、127xxx、128xxx | 深市新债、可转债等债券类证券代码。 | 是 |
| 深市 | 证券简称 | 证券名称简称。 | 股票简称 | 如秦川机床、东方锆业、深南电路等。 | 是 |
| 深市 | 证券简称 | 证券名称简称。 | 转债简称 / 新债简称 | 如亿纬转债、太能转债等。 | 是 |
| 深市 | 股份性质 | 深市凭证中用于说明股票或份额在股本结构中的性质。 | 无限售流通股 | 深市凭证中的股份性质，表示该股份无特殊限售条件、可流通。 | 是 |
| 深市 | 流通类型 | 在股份性质基础上进一步描述是否存在特殊流通限制或细分类别。 | 无特殊限制条件 | 未被标识为特殊限售、非流通或其他限制流通细分类别。 | 是 |
| 深市 | 过户日期 | 该笔持有变更在中国结算记录中的发生日期。 | 日期 | 作为业务事件的发生时间 event_date。 | 是 |
| 深市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 买入 | 投资者买入证券后，经撮合成交和清算交收，在中国结算持有变更凭证中表现为证券数量过入。 | 是 |
| 深市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 卖出 | 投资者卖出证券后，经撮合成交和清算交收，在中国结算持有变更凭证中表现为证券数量过出。 | 是 |
| 深市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 股份登记 | 打新/证券登记入账。表示证券发行、网上认购中签、配售、初始登记或其他登记入账场景下，中国结算将证券登记到持有人名下。包括新股、新债、可转债等，不局限于可转债。 | 是 |
| 深市 | 过户类型 | 说明持有数量发生变化的业务原因或登记环节。 | 分红 | 权益分派导致的红利、股息、派息或分红相关权益记录。 | 是 |
| 深市 | 过户数量 | 本笔持有变更的数量。 | 正数 | 表示过入、登记增加或权益数量增加。 | 是 |
| 深市 | 过户数量 | 本笔持有变更的数量。 | 负数 | 表示过出或冲减。若过户类型是卖出，表示卖出导致证券过出。 | 是 |
| 深市 | 期末余额 | 本笔流水处理后的余额。 | 数值 | 记录该行处理后的余额，必须原样保存；不等同于完整持仓快照。 | 是 |
| 深市 | 成交价格 | 原始价格字段。 | 价格值或空值 | 深市样本中该字段可能为空或未明显展示；本阶段只原样记录，不强制补全。 | 是 |
| 深市 | 托管单元 | 深市证券托管单元编号。 | 托管单元代码 | 如 007055、390537。 | 是 |
| 深市 | 托管单元名称 | 深市证券托管单元名称。 | 托管单元名称 | 如平安证券六十三交易单元、华泰证券四十七交易单元。 | 是 |

### 3. 持仓信息字段解释表

当文件标题为“证券持有信息”而不是“证券持有变更信息”时，按持仓快照处理。

| 材料类型 | 一级字段 | 字段释义 | 是否抽取 | 输出位置 |
| --- | --- | --- | --- | --- |
| 持仓信息 | 持有日期 | 该持仓快照对应的日期。 | 是 | holding_snapshot_records.holding_date |
| 持仓信息 | 证券代码 | 持有证券代码。 | 是 | holding_snapshot_records.security_code |
| 持仓信息 | 证券简称 | 持有证券简称。 | 是 | holding_snapshot_records.security_name |
| 持仓信息 | 股份性质 | 持有证券的股份性质。 | 是 | holding_snapshot_records.share_property |
| 持仓信息 | 流通类型 | 持有证券的流通限制类别。 | 是 | holding_snapshot_records.circulation_type |
| 持仓信息 | 持有数量 | 该持有日期日终完成清算交收后的持有余额。 | 是 | holding_snapshot_records.holding_quantity_raw |
| 持仓信息 | 其中冻结数量 | 持仓中被冻结的数量。 | 是 | holding_snapshot_records.frozen_quantity_raw |
| 持仓信息 | 托管单元 | 深市托管单元编号。 | 是 | holding_snapshot_records.custody_unit |
| 持仓信息 | 托管单元名称 | 深市托管单元名称。 | 是 | holding_snapshot_records.custody_unit_name |

持仓信息文件不生成 business_events。

## 五、事件规则：沪市

### 1. 沪市证券交易事件：security_trade

表中表现

过户类型 = 交易过户
权益类别为空，或权益类别与红利、兑息、送股无关

事件本质

一行交易过户 = 一个证券交易事件
多行交易过户 = 多个证券交易事件
不得合并

方向

过户数量为正 → trade_direction = transfer_in
过户数量为负 → trade_direction = transfer_out

事件输出要求

每个事件必须记录：

event_date
security_code
security_name
transfer_types
transfer_quantities_raw
transaction_prices_raw
balances_after_raw
related_rows

### 2. 沪市现金红利事件：cash_dividend

表中表现

权益类别包含：红利、现金红利、分红、股息、派息
过户类型通常包括：权益登记、权益挂牌

事件本质

权益登记 + 权益挂牌 = 同一个现金红利事件的两个阶段

合并规则

满足以下条件时合并为一个事件：

同一市场
同一证券代码
同一证券名称
同一过户日期
同一权益类别
过户类型包含 权益登记 和 权益挂牌

禁止误判

权益登记不是买入
权益挂牌不是卖出
权益挂牌中的负数不是证券卖出
不得计算红利金额

### 3. 沪市债券兑息事件：bond_interest

表中表现

证券类别 = 固定收益类
或证券简称包含“债”“转债”
权益类别包含：兑息、债券兑付、付息、派息
过户类型通常包括：权益登记、权益挂牌

事件本质

权益登记 + 权益挂牌 = 同一个债券兑息事件的两个阶段

禁止误判

兑息权益登记不是买入
兑息权益挂牌不是卖出
权益挂牌中的负数不是债券卖出
不得计算兑息金额

### 4. 沪市送股 / 转增事件：bonus_share

表中表现

权益类别包含：送股、转增、股票红利、红股
过户类型通常包括：权益登记、上市流通

可能还会出现：

权益类别为空
过户类型 = 上市流通
过户数量为正

如果该行与同一证券、同一日期的送股/转增权益行构成同一个业务流程，应合并进同一个 bonus_share 事件。

事件本质

送股/转增不是普通买入
它是一个公司权益事件
权益登记、上市流通正数、上市流通负数冲销是同一事件的不同阶段

禁止误判

送股权益登记不是买入
上市流通正数不是普通买入
上市流通负数不是卖出

## 六、事件规则：深市

### 1. 深市证券交易事件：security_trade

表中表现

过户类型 = 买入
或
过户类型 = 卖出

事件本质

一行买入 = 一个证券交易事件
一行卖出 = 一个证券交易事件
多行买入/卖出 = 多个证券交易事件
不得合并

方向

过户类型 = 买入 → trade_direction = buy
过户类型 = 卖出 → trade_direction = sell

### 2. 深市打新 / 证券登记入账事件：security_registration

表中表现

过户类型 = 股份登记
证券代码为正式证券代码

事件本质

深市“股份登记”应理解为：

打新/证券登记入账事件

它表示证券发行、网上认购中签、配售、初始登记或其他登记入账场景下，中国结算将证券登记到持有人名下。

它包括：

新股登记入账
新债登记入账
可转债登记入账
其他正式证券登记入账

不局限于可转债。

处理规则

一行股份登记 = 一个 security_registration 事件

禁止误判

股份登记不是普通买入
股份登记不是配号
股份登记应作为有效证券入账事件记录

### 3. 深市现金红利 / 分红事件：cash_dividend

表中表现

过户类型 = 分红
或业务描述包含：红利、分红、股息、派息

事件本质

深市样本中分红可一行构成一个完整分红事件。

一行分红 = 一个 cash_dividend 事件

禁止误判

分红不是买入
分红不是卖出
不得计算分红金额

## 七、事件级 JSON Schema

### 1. 顶层结构

{
  "schema_version": "china_clear_event_extract_v5",
  "source_type": "china_clear",
  "document_extract_mode": "holding_snapshot | transaction_event | mixed | unknown",
  "input_file": {
    "file_id": "",
    "original_file_name": "",
    "file_type": "",
    "page_count": null
  },
  "material_info": {
    "material_id": "",
    "material_type": "",
    "material_type_label": "",
    "document_title": "",
    "market": "",
    "market_label": "",
    "query_period_start": "",
    "query_period_end": "",
    "holding_date": "",
    "business_serial_no": "",
    "verification_code": "",
    "field_dictionary_version": "china_clear_field_dictionary_v1"
  },
  "account_context": {
    "holder_name": "",
    "one_code_account_no": "",
    "securities_account_no": "",
    "securities_account_no_raw": "",
    "account_type_raw": "",
    "account_status": "",
    "current_trading_unit": "",
    "settlement_participant": "",
    "custody_unit": "",
    "custody_unit_name": ""
  },
  "extract_summary": {
    "has_holding_snapshot": false,
    "holding_record_count": 0,
    "has_business_event": false,
    "business_event_count": 0,
    "unknown_event_count": 0,
    "event_types_detected": []
  },
  "holding_snapshot_records": [],
  "business_events": [],
  "unknown_events": [],
  "no_business_event": null,
  "quality": {
    "manual_review_required": false,
    "review_reasons": []
  }
}

### 2. business_events Schema

每个事件顶层必须直接出现：

发生时间
证券代码
证券名称
过户数量
成交价格
期末余额

不能只放在 related_rows 里面。

{
  "event_id": "",
  "event_type": "",
  "event_name": "",
  "event_granularity": "single_row | multi_stage",
  "market": "",
  "market_label": "",

  "event_date": "",
  "event_date_source": "transfer_date",
  "security_code": "",
  "security_name": "",
  "security_category": "",
  "security_type": "",
  "security_type_label": "",
  "rights_category": "",

  "transfer_types": [],
  "transfer_quantities_raw": [],
  "transaction_prices_raw": [],
  "balances_after_raw": [],

  "trade_direction": null,
  "event_stage_summary": "",

  "related_rows": [
    {
      "row_no": "",
      "page_no": null,
      "transfer_date": "",
      "security_code": "",
      "security_name": "",
      "security_category": "",
      "rights_category": "",
      "transfer_type": "",
      "transfer_quantity_raw": "",
      "balance_after_raw": "",
      "transaction_price_raw": "",
      "trading_unit_no": "",
      "settlement_participant_short_name": "",
      "custody_unit": "",
      "custody_unit_name": "",
      "raw_text": ""
    }
  ],

  "classification": {
    "is_real_trade": false,
    "is_position_change": false,
    "is_cash_income_related": false,
    "is_rights_related": false,
    "is_registration_event": false,
    "requires_manual_review": false
  },

  "business_interpretation": {
    "summary": "",
    "event_essence": "",
    "why_this_is_one_event": "",
    "why_not_buy_or_sell": "",
    "rule_hit": "",
    "manual_review_required": false,
    "review_reason": ""
  },

  "calculation_policy": {
    "do_not_calculate_amount": true,
    "do_not_infer_tax": true,
    "do_not_infer_profit_or_loss": true
  },

  "source_trace": {
    "source_file_id": "",
    "page_numbers": [],
    "row_numbers": []
  }
}

### 3. holding_snapshot_records Schema

{
  "holding_record_id": "",
  "record_type": "holding_snapshot",
  "market": "",
  "market_label": "",
  "holding_date": "",
  "security_code": "",
  "security_name": "",
  "security_category": "",
  "share_property": "",
  "circulation_type": "",
  "security_type": "",
  "security_type_label": "",
  "holding_quantity_raw": "",
  "frozen_quantity_raw": "",
  "quantity_unit_raw": "",
  "custody_unit": "",
  "custody_unit_name": "",
  "source_trace": {
    "source_file_id": "",
    "page_no": null,
    "row_no": "",
    "raw_text": ""
  },
  "quality": {
    "confidence": null,
    "manual_review_required": false,
    "review_reasons": []
  }
}

## 八、示例：沪市红利事件

原始行：

13 600794 保税科技 无限售流通股 2024 第二次 红利 2025-05-15 权益登记 16,400 16,400 0
14 600794 保税科技 无限售流通股 2024 第二次 红利 2025-05-15 权益挂牌 -16,400 0 0.03

输出一个事件：

{
  "event_id": "evt_001",
  "event_type": "cash_dividend",
  "event_name": "现金红利/分红/股息/派息事件",
  "event_granularity": "multi_stage",
  "market": "SH",
  "market_label": "沪市",

  "event_date": "2025-05-15",
  "event_date_source": "transfer_date",
  "security_code": "600794",
  "security_name": "保税科技",
  "security_category": "无限售流通股",
  "security_type": "stock",
  "security_type_label": "股票",
  "rights_category": "2024 第二次 红利",

  "transfer_types": ["权益登记", "权益挂牌"],
  "transfer_quantities_raw": ["16,400", "-16,400"],
  "transaction_prices_raw": ["0", "0.03"],
  "balances_after_raw": ["16,400", "0"],

  "trade_direction": null,
  "event_stage_summary": "rights_register_and_rights_listing",

  "related_rows": [
    {
      "row_no": "13",
      "page_no": 1,
      "transfer_date": "2025-05-15",
      "security_code": "600794",
      "security_name": "保税科技",
      "security_category": "无限售流通股",
      "rights_category": "2024 第二次 红利",
      "transfer_type": "权益登记",
      "transfer_quantity_raw": "16,400",
      "balance_after_raw": "16,400",
      "transaction_price_raw": "0",
      "trading_unit_no": "23206",
      "settlement_participant_short_name": "广发证券公司客户",
      "raw_text": ""
    },
    {
      "row_no": "14",
      "page_no": 1,
      "transfer_date": "2025-05-15",
      "security_code": "600794",
      "security_name": "保税科技",
      "security_category": "无限售流通股",
      "rights_category": "2024 第二次 红利",
      "transfer_type": "权益挂牌",
      "transfer_quantity_raw": "-16,400",
      "balance_after_raw": "0",
      "transaction_price_raw": "0.03",
      "trading_unit_no": "23206",
      "settlement_participant_short_name": "广发证券公司客户",
      "raw_text": ""
    }
  ],

  "classification": {
    "is_real_trade": false,
    "is_position_change": false,
    "is_cash_income_related": true,
    "is_rights_related": true,
    "is_registration_event": false,
    "requires_manual_review": false
  },

  "business_interpretation": {
    "summary": "该事件为沪市现金红利/分红事件。",
    "event_essence": "同一个红利业务的两个阶段：权益登记和权益挂牌。",
    "why_this_is_one_event": "两行证券代码、证券名称、过户日期、权益类别一致，且过户类型分别为权益登记和权益挂牌，构成同一个红利业务流程。",
    "why_not_buy_or_sell": "权益类别为红利，过户类型不是交易过户，权益挂牌中的负数是权益处理方向，不是证券卖出。",
    "rule_hit": "SH_CASH_DIVIDEND_MULTI_STAGE",
    "manual_review_required": false,
    "review_reason": ""
  },

  "calculation_policy": {
    "do_not_calculate_amount": true,
    "do_not_infer_tax": true,
    "do_not_infer_profit_or_loss": true
  },

  "source_trace": {
    "source_file_id": "",
    "page_numbers": [1],
    "row_numbers": ["13", "14"]
  }
}

## 九、示例：深市打新 / 证券登记入账事件

原始行：

41 123254 亿纬转债 无限售流通股 无特殊限制条件 2025-03-31 股份登记 1,000.00 1,000.00

输出一个事件：

{
  "event_id": "evt_002",
  "event_type": "security_registration",
  "event_name": "打新/证券登记入账事件",
  "event_granularity": "single_row",
  "market": "SZ",
  "market_label": "深市",

  "event_date": "2025-03-31",
  "event_date_source": "transfer_date",
  "security_code": "123254",
  "security_name": "亿纬转债",
  "security_category": "无限售流通股",
  "security_type": "convertible_bond",
  "security_type_label": "可转债",
  "rights_category": "",

  "transfer_types": ["股份登记"],
  "transfer_quantities_raw": ["1,000.00"],
  "transaction_prices_raw": [""],
  "balances_after_raw": ["1,000.00"],

  "trade_direction": null,
  "event_stage_summary": "registration_in",

  "related_rows": [
    {
      "row_no": "41",
      "page_no": 3,
      "transfer_date": "2025-03-31",
      "security_code": "123254",
      "security_name": "亿纬转债",
      "security_category": "无限售流通股",
      "rights_category": "",
      "transfer_type": "股份登记",
      "transfer_quantity_raw": "1,000.00",
      "balance_after_raw": "1,000.00",
      "transaction_price_raw": "",
      "custody_unit": "007055",
      "custody_unit_name": "平安证券六十三交易单元",
      "raw_text": ""
    }
  ],

  "classification": {
    "is_real_trade": false,
    "is_position_change": true,
    "is_cash_income_related": false,
    "is_rights_related": false,
    "is_registration_event": true,
    "requires_manual_review": false
  },

  "business_interpretation": {
    "summary": "该事件为深市打新/证券登记入账事件。",
    "event_essence": "证券发行、网上认购中签、配售、初始登记或其他登记入账场景下形成的证券到账。",
    "why_this_is_one_event": "该行股份登记本身构成一个完整证券登记入账事件。",
    "why_not_buy_or_sell": "过户类型为股份登记，不是买入或卖出。",
    "rule_hit": "SZ_SECURITY_REGISTRATION_SINGLE_ROW",
    "manual_review_required": false,
    "review_reason": ""
  },

  "calculation_policy": {
    "do_not_calculate_amount": true,
    "do_not_infer_tax": true,
    "do_not_infer_profit_or_loss": true
  },

  "source_trace": {
    "source_file_id": "",
    "page_numbers": [3],
    "row_numbers": ["41"]
  }
}

## 十、最终硬规则

LLM 必须遵守：

1. 先识别文件是持仓信息还是持有变更信息。
2. 持仓信息只抽 holding_snapshot_records。
3. 持有变更信息只抽 business_events。
4. 交易类事件一行一个事件，不合并。
5. 红利、兑息、送股等多阶段业务按业务本质合并为一个事件。
6. 每个事件顶层必须记录：
   - event_date
   - security_code
   - security_name
   - transfer_quantities_raw
   - transaction_prices_raw
   - balances_after_raw
7. 每个事件的 related_rows 必须逐行保存原始字段。
8. 深市“股份登记”识别为打新/证券登记入账，不局限于可转债。
9. 不计算金额。
10. 不推导税额。
11. 不推导盈亏。
12. 不把权益挂牌负数识别为卖出。
13. 不把上市流通负数识别为卖出。
14. 不把送股、红利、兑息误判为普通交易。
