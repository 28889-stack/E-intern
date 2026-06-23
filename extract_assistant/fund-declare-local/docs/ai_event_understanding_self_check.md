# AI 事件理解链路自查报告

检查日期：2026-06-23  
分支：`feature/ai-chain-redesign`

## 结论先行

当前问题不是单纯的 OCR 识别失败，也不是某一个 case 的字段映射没补够。OCR 之后已经有一定结构信息，但这套结构在进入抽取、归一化和 final 层时被多次降维、重判和重包装，导致后续链路效果不稳定。

最核心的三个问题：

1. OCR 结构信息有，但不是“可直接理解事件”的结构。
   当前 `document_structure.json` 保留了行、bbox、confidence，但主要是基于 OCR 行框按 y 轴聚合出来的布局行，不等于稳定的业务表格、列语义、事件边界。

2. 结构在抽取分批边界曾经被丢掉一部分，本轮已修复关键透传。
   `document_structure_to_tables_payload()` 现在仍保留兼容的 `rows: [[cell_text...]]`，同时增加 `row_metadata` 和 `cell_metadata`，包含 `row_id`、`cell_id`、`bbox`、`source_line_id` 等追溯信息；Guangfa / Chinaclear batch 文本会带上 `row_id`、`bbox`、`source_line_ids`。

3. normalizer、final_result_builder、case_event_resolver 曾存在最终表筛选职责重叠，本轮已收掉 normalizer 预筛。
   LLM 输出里仍可能有 `include_in_final_declaration` / `affects_holding` 这类字段，但后端不再把它们当最终筛选控制字段；normalizer 的 `final_declaration_rows` 保持兼容字段但固定为空，最终是否进入申报表统一由 `case_event_resolver` 判定。

因此，继续 case-by-case 往 normalizer 或 final 层加规则，短期能压住某个样本，长期会继续产生新冲突。

## 当前链路

现有主链路大致是：

```text
上传文件
-> document_processor
-> file_router / PDF 文本 / PDF 表格 / PaddleOCR
-> document_structure.json
-> extraction_input_builder
-> ChinaclearExtractor / GuangfaExtractor
-> extract_result.json
-> source normalizer
-> case_event_resolver
-> final_result_builder
-> final_result.json
-> 人工复核 / Excel
```

关键代码位置：

- `apps/api/app/pipeline/document_processor.py:35-72`：直读 PDF 走文本和表格，再生成 `document_structure.json`。
- `apps/api/app/pipeline/document_processor.py:74-123`：扫描件/图片走 OCR，再生成 `document_structure.json`。
- `apps/api/app/pipeline/document_structure.py:13-50`：汇总 `raw_text.json`、`tables.json`、`ocr_result.json` 为统一结构。
- `apps/api/app/pipeline/extraction_input_builder.py:17-35`：优先读取 `document_structure.json` 作为抽取输入。
- `apps/api/app/pipeline/guangfa_extractor.py:52-113`、`apps/api/app/pipeline/chinaclear_extractor.py:45-107`：调用 LLM 抽取。
- `apps/api/app/pipeline/final_result_builder.py:224-255`：先 normalizer，再 `resolve_case_events()`。
- `apps/api/app/pipeline/case_event_resolver.py:146-215`：合并、校验、复核问题、最终表拆分都在这里做。

## OCR 输出是否有结构信息

有，但它目前是“布局结构”，不是完整的业务结构。

已经保留的信息：

- OCR page/block text；
- bbox；
- confidence；
- line_id；
- 根据 bbox 聚合出来的行；
- row_id；
- cell_id；
- source_line_id；
- page/table 信息。

证据：

- `document_structure.py:216-234` 从 OCR block 生成带 `line_id`、`bbox`、`confidence` 的行。
- `document_structure.py:237-302` 根据 OCR 行 bbox 的 y 轴位置聚合出 `ocr_layout_rows`。
- `extraction_input_builder.py:158-175` 在文本输入中可以带上 `row_id` 和 bbox。

但是这个结构仍有明显限制：

1. 行聚合是启发式的。
   `document_structure.py:249-260` 通过行高 median 和 y 轴阈值聚合行。它能恢复很多表格行，但不能保证复杂扫描件、盖章、跨页续表、错位文字都正确。

2. 没有稳定列语义。
   OCR 聚合后的 cell 只有 `column_index`，`column_name` 为空。列含义仍要靠上游 prompt 或后处理推断。

3. OCR confidence 容易被误解。
   `case_103` 的 OCR page confidence 很高：第一页约 0.988，第二页约 0.965，但仍存在姓名/证券名称识别错误或被截断。confidence 是识别置信度，不是“表格行、列、事件理解正确”的置信度。

4. 结构追溯已能进入抽取分批，但还不是强约束。
   `document_structure_to_tables_payload()` 已保留 `row_metadata` / `cell_metadata`；`guangfa_extractor.py` 和 `chinaclear_extractor.py` 在 batch 文本中透传 `row_id`、`bbox`、`source_line_ids`。这解决了“结构生成后在 table batch 边界被吞掉”的问题。

   本轮进一步做了精简写回：不要求 LLM 输出完整 cell trace，而是由后端根据 LLM 已输出的 `page/row_no` 匹配 batch 内 trace，并写回精简 `source_trace` / `source_traces`。这样能避免输出 token 被 trace 打满。

## 为什么可能不如直接喂扫描件

直接把扫描件喂给多模态模型时，模型能看到：

- 原始页面视觉布局；
- 表头和表体的空间关系；
- 跨行、跨页、盖章、边界线；
- 单元格视觉位置；
- OCR 文字与图像之间的冲突。

当前链路主要是：

```text
图像/PDF -> OCR 文本/框 -> 文本化 table rows -> LLM JSON
```

图像证据只作为旁路复核：

- `single_file_extractor.py:14-36` 先运行可选 multimodal review，然后把结果附加到 `extract_result["multimodal_review"]`。
- `multimodal_review_sidecar.py:67-104` 会对疑难块抽取 hints。
- 但这些 hints 当前没有成为主抽取输入，也不会直接修正 LLM 的事件抽取。

所以现在的多模态能力更像“旁路提示”，不是“主抽取证据”。这解释了为什么视觉直接喂模型有时更强：当前主链路已经把视觉结构压成了文本行。

## 职责冲突

### 1. LLM、normalizer、resolver 曾都在判断是否进入最终申报表

Guangfa 抽取约束中仍可能要求模型输出 `include_in_final_declaration=false`、`affects_holding=false` 等业务判断，但这些字段现在只应视为来源提示，不应控制最终申报。

本轮已修复：

- Guangfa normalizer 不再因为 LLM 的最终申报判断和脚本判断不一致而制造复核项。
- `normalizers/common.py` 的 `build_normalized_result()` 不再调用 `is_final_declaration_row()` 预生成正式最终表。
- normalizer 返回的 `final_declaration_rows` 仅为兼容字段，固定为空。
- `case_event_resolver.py` 是当前唯一正式最终表筛选层。

这让“字段映射”和“最终筛选”先解耦：normalizer 只负责把来源字段映射成统一事件行，resolver 再根据统一行做完整表/最终表/待复核分流。

### 2. normalizer 输出的 final_declaration_rows 实际被 final 层绕过

`normalize_guangfa()` / `normalize_chinaclear()` 返回：

```text
full_transaction_rows
final_declaration_rows
holding_rows
review_items
```

但 `final_result_builder.py:224-255` 只拿了：

```python
complete_rows.extend(normalized["full_transaction_rows"])
holding_rows.extend(normalized["holding_rows"])
review_items.extend(normalized["review_items"])
...
resolved = resolve_case_events(complete_rows, ...)
final_rows = resolved["final_declaration_rows"]
```

本轮已把这个暧昧点收掉：normalizer 不再生成正式最终表，`final_declaration_rows` 保持为空用于兼容旧调用。真正决定最终申报表的是 `case_event_resolver`。

### 3. case_event_resolver 不是单纯 resolver，而是第二个 normalizer + 质量审查器

`case_event_resolver.py:146-215` 同时做了：

- 证券代码/名称引用补齐；
- 精确重复合并；
- 同文件部分重复合并；
- 跨文件互补合并；
- 0 数量普通交易丢弃；
- 冲突标记；
- 事件必填字段校验；
- 持仓字段校验；
- review_items 转 review_issues；
- 完整表/最终申报表拆分。

这导致它事实上承担了 normalizer、deduper、validator、policy engine、review issue builder 五个职责。后续任何一层加规则，都很容易和这里冲突。

### 4. review_items、review_issues、file_issues 语义混杂

目前有至少三套复核信息：

- normalizer 产生 `review_items`；
- resolver 产生 `review_issues`；
- file_issue_collector 再根据文件状态和 review issues 产生 `file_issues`。

`final_result_builder.py:350-360` 里最终 `manual_review_required` 是：

```python
bool(review_items or review_issues or file_issues)
```

这会导致一种现象：即使 `待复核问题` sheet 为 0，`manual_review_required` 仍可能为 true，因为 checklist 或其他 review_items 还存在。这个状态本身未必错，但语义不清晰：用户看到的是“无待复核问题”，系统状态却说“需要人工复核”。

## 证券名称不全、证券代码消失、无关复核的来源

这三个症状不是同一种 bug，但根源都和“结构降维 + 多层重判”有关。

### 证券名称不全

可能来源：

1. OCR 原文已经识别错或切碎。
   例如 case_103 中存在 `卵捷配号` 这类明显 OCR 错字，但 page confidence 仍很高。

2. 表格结构没有列语义。
   OCR 行里有很多 cell，但没有“这一列是证券名称”的稳定 schema。LLM 或脚本只能根据位置和表头猜。

3. 归一化阶段会尝试用持仓补名称。
   这能补一些结果，例如 `688262 -> 国芯科技`，但这属于后处理纠错，不应该成为主路径。

### 证券代码消失

可能来源：

1. LLM 对配号、股息、资金流水等事件主动省略代码，因为 prompt 同时要求它做业务判断。

2. normalizer 对 full-only 事件降低必填要求，避免无关复核；这对股息/配号是合理的，但如果事件被错误归类为 full-only，就会让代码缺失被放过。

3. `case_event_resolver` 对 full-only 事件直接跳过部分校验：

   - `case_event_resolver.py:661-669` 遇到 full-only row 直接 return。

   这个规则本身是为了减少无关复核，但如果上游事件类型错了，就会掩盖关键字段缺失。

### 无关复核

主要来源：

1. normalizer 先写 review_items。
2. resolver 把 review_items 再转换成 review_issues。
3. file_issue_collector 又把 review_issues 和 pending rows 汇总成 file_issues。
4. checklist 的“材料不足需人工复核”也会写入 review_items。

这会把“抽取字段缺失”“业务判断不一致”“文件级问题”“checklist 无法校验”混在一个人工复核状态里。用户体验上就像无关复核很多。

## case_103 探针结果

这里不是做 case-by-case 修复，只把 case_103 当作链路探针。

观察结果：

- OCR 成功，2 页，PaddleOCR 请求配置已生效。
- `document_structure.json` 成功生成，第一页 517 个 OCR lines，1 个 layout table；第二页 443 个 OCR lines，1 个 layout table。
- 结构行能恢复类似：

```text
2022-01-05  160000  802777974  15685657  688262  688262  新股入账  500.0000  41.9800 ...
```

- 持仓行里能看到：

```text
2022-12-30  688262  国芯科技  500.0000 ...
```

- 当前 final 结果中，完整表 36 行，最终申报表 1 行，持仓 6 行，待复核问题 0 行。

这说明结构化链路不是完全无效；它能恢复行，也能做部分补齐。但它仍然靠后处理把 `688262` 的名称从持仓里补回来，这不是最理想的主抽取能力。

## 根因归纳

### 根因 1：当前 document_structure 还不是事件理解层的 canonical evidence

它保存了结构，本轮也已经把 `row_id/bbox/source_line_id` 透传到 table batch，并由后端把匹配到的精简行级 trace 写回 `extract_result.json`。当前不是让 LLM 输出完整 trace，而是用脚本补写，降低输出 token 压力。

### 根因 2：抽取 prompt 让 LLM 同时做“事实抽取”和“最终业务裁判”

LLM 应该优先抽事实：日期、账号、代码、名称、变动类型、数量、金额、来源行。是否进入最终申报表应该由稳定脚本规则做。

现在如果继续让 LLM 输出 `include_in_final_declaration` 和 `affects_holding`，这些字段只能作为 hint，不能再驱动 normalizer 或 resolver 的正式规则。

### 根因 3：normalizer 和 case_event_resolver 的边界没有收敛

normalizer 应该只做“来源 schema -> 统一事件 schema”。  
case_event_resolver 如果保留，应只做跨来源合并和统一校验。  
最终申报表过滤应该只有一个 owner。

当前三者都有过滤、校验或复核职责，导致系统呈现出“越补越乱”的趋势。

### 根因 4：多模态证据没有进入主抽取闭环

当前视觉链路是 sidecar。它能产出 hints，但主 LLM 抽取仍主要基于 OCR 文本/表格。对于扫描件表格，视觉布局恰恰是关键证据。

### 根因 5：复核体系没有分层

现在 review_items/review_issues/file_issues/checklist review 混在一起。需要区分：

- OCR/结构质量问题；
- 抽取字段缺失；
- 来源间冲突；
- 最终申报规则不确定；
- checklist 材料不足；
- 文件级流程问题。

否则“需复核”会变成一个大箩筐。

## 不建议继续做的方向

不建议继续：

1. 针对某个证券名称加特殊映射。
2. 针对某个配号/股息样例继续补关键词。
3. 在 normalizer 和 resolver 两边同时加最终表规则。
4. 让 prompt、normalizer、resolver 都输出或解释 `include_in_final_declaration`。
5. 用 file_issue 再去掩盖 review_items 的语义问题。

这些都会继续放大职责冲突。

## 建议的架构收敛方向

建议把链路改成五个明确契约：

### 1. Evidence Layer：文档证据层

`document_structure.json` 成为唯一结构证据源，至少保留：

```text
page_id
table_id
row_id
cell_id
bbox
text
confidence
column_key
column_name
row_type
visual_ref
```

重点是：进入 LLM 的 batch 不能再丢掉 `row_id/bbox/cell_id`。

### 2. Source Extract Layer：来源事实抽取层

Chinaclear / Guangfa prompt 只抽来源事实：

```text
source_event_rows
source_holding_rows
source_identity_rows
source_negative_proofs
evidence_refs
```

不要让 LLM 决定最终是否申报。`include_in_final_declaration` / `affects_holding` 如果保留，也只能作为 hint，不作为规则输入。

### 3. Source Normalizer：来源归一化层

只负责：

```text
来源字段 -> 统一事件字段
来源持仓 -> 统一持仓字段
来源证据 -> source_trace
```

不负责：

- 最终申报表过滤；
- checklist；
- 文件级复核；
- 跨文件合并。

### 4. Event Preprocessor：事件预处理层

先处理来源内部和 overlap 造成的重复：

```text
canonical_event_rows -> deduped_event_rows
```

这层可以做：

- 同一来源 overlap 重复清理；
- trade_group / business_events 双路径重复清理；
- 明确可解释的跨来源同一事实合并；
- source_trace 合并审计。

这层不做最终申报表过滤，不生成待复核/最终表/完整表。

### 5. Event Resolver / Policy Engine：统一事件决策层

只保留一个最终申报表 owner：

```text
deduped_event_rows -> full_transaction_rows
deduped_event_rows -> final_declaration_rows
canonical_holding_rows
```

这层可以做：

- 持仓影响分类；
- 最终申报过滤；
- 规则审计。

不要再由 normalizer 预先生成正式 `final_declaration_rows`。

### 6. Review Engine：复核问题层

统一生成复核问题，并按类型分层：

```text
data_quality_issues
extraction_issues
source_conflict_issues
final_policy_issues
checklist_issues
file_process_issues
```

最终 UI 可以聚合展示，但底层不要混成一个 `manual_review_required` 布尔值。

## 推荐的下一步

短期不建议继续补 case 规则。建议按下面顺序做：

1. 已完成：保留 `document_structure` 的 row/cell/bbox/source_line 信息到 extractor batch。
2. 已完成：normalizer 不再生成正式 `final_declaration_rows`，最终筛选统一由 resolver 做。
3. 已完成：抽取结果写回精简 `source_trace`，字段控制在 `page/table/row_no/row_id/bbox/line_ids`，不写完整 cell 大对象。
4. 下一步：从 prompt 中弱化“最终是否申报”的强判断，只保留事实抽取或明确标注为 hint。
5. 下一步：把 `case_event_resolver` 中的 dedupe / merge 逻辑拆成前置 `event_preprocessor`，让 resolver 更接近 final-policy owner。
6. 下一步：把 `review_items`、`review_issues`、`file_issues` 统一成分层 review schema。
7. 下一步：对扫描件疑难表格，把 page/cell crop 或 visual_ref 引入主抽取，而不是只做 sidecar。
8. 下一步：建立固定 golden samples，验收指标不是某个 case 通过，而是字段完整率、无关复核率、最终申报过滤准确率、source trace 覆盖率。

## 当前分支风险

当前分支中已经有不少链路调整和未跟踪文件，包括：

- `document_structure.py`
- `document_blocks.py`
- `visual_evidence.py`
- `multimodal_review_sidecar.py`
- `difficult_block_detector.py`
- 多个 normalizer / resolver / final builder 修改

这些变化说明链路正在往“结构化 + 视觉旁路 + final 审计”方向演进，但还没有完成职责收敛。继续在这个状态下做局部修补，容易把问题从抽取层转移到 final 层，或者从 final 层转移到复核层。

## 验证建议

完成架构收敛前，每次改动至少跑：

```bash
PYTHONPATH=apps/api python -m unittest discover apps/api/tests
```

同时建议新增链路级审计脚本，对每个 case 输出：

```text
OCR confidence summary
document_structure row/cell count
extract source_event count
normalizer canonical_event count
resolver full/final count
review issue type summary
source_trace coverage
```

这样才能判断问题发生在哪一层，而不是继续凭最终 Excel 的坏结果倒推。

## 2026-06-23 脚本职责收敛记录

本轮已先处理脚本冲突问题，暂不继续追抽取模型质量。

收敛后的职责边界：

1. LLM 仍然负责事件级事实抽取。
   如果 LLM 输出 `include_in_final_declaration` 或 `affects_holding`，后端只把它们视为来源提示，不再作为最终筛选控制字段。

2. normalizer 只做来源字段归一化和来源内部清理。
   Guangfa / Chinaclear 可以继续保留各自来源 schema，normalizer 负责把来源字段映射为统一事件行、持仓行和来源证据；如果同一来源内因为 overlap 或 trade_group/business_events 双路径产生重复事件，先在来源归一化侧清理，不交给 resolver。normalizer 不再因为 LLM 的最终申报判断和脚本规则不一致而制造复核项。

3. `case_event_resolver` 是完整表、最终表、复核问题的统一脚本兜底层。
   配号、股息、分红、利息、资金流水等规则统一在这里或公共 final-policy 函数兜底处理。

4. 完整表保留待复核事件。
   事件即使字段缺失或类型不确定，也会保留在完整表；但不会进入最终申报表，并会产生待复核问题。

5. 最终申报表只从非待复核事件中筛选。
   这样既不会丢事实，也不会让不确定事件污染正式申报表。

6. 来源重复不放在 resolver。
   对 `security_registration`、`bonus_share` 这类非普通成交事件，如果同一 Guangfa extract_result 内出现 trade_group/business_events 双路径重复，先在 Guangfa normalizer 内合并来源证据。resolver 不处理这类 overlap/source-path 重复，只做业务规则兜底和完整表/最终表/待复核分流。

7. `document_structure` trace 已进入 table batch。
   `document_structure_to_tables_payload()` 现在输出 `row_metadata` 和 `cell_metadata`；Guangfa / Chinaclear 的 batch 文本包含 `row_id`、`bbox`、`source_line_ids`，避免结构证据在抽取入口被降维丢失。

8. 精简 trace 已写回 `extract_result.json`。
   Guangfa / Chinaclear 的批次抽取结果会根据 `source_page/page + row_no` 匹配 batch 行级 trace。dict 事件写入 `source_trace`；compact `trade_group.trades` 不增加列，而是在根节点写入去重后的 `source_traces`。

验证结果：

```bash
PYTHONPATH=apps/api python -m unittest discover apps/api/tests
```

当前结果：`125 tests OK`。

实际 case 快速检查：

- `case_103`：完整表 35 行，最终申报表 1 行，持仓 6 行，review_items 1 条；配号/股息进入完整表但不进入最终表，重复的新股入账已合并。`document_structure` 转换出的 table payload 有 47 行、47 条 row metadata、47 条 cell metadata。
- `case_008`：完整表 62 行，最终申报表 62 行；仍保留 warning，提示需确认是否确实不存在非持仓影响事件。
- `case_015`：完整表 10 行，最终申报表 2 行；8 条权益登记/权益挂牌被排除出最终申报表。

本轮自查结论：

- 已修复：normalizer 生成后又被 final 绕过的 `final_declaration_rows`。
- 已修复：`document_structure` 到 extractor table batch 的 row/cell trace 丢失。
- 已修复：trace 进入 LLM 输入但没有写回 `extract_result.json` 的问题；现在以后端精简补写为主，避免输出 token 膨胀。
- 仍存在：`case_event_resolver` 里还有历史 merge / dedupe / conflict 标记逻辑；严格按边界设计，后续应抽到 `event_preprocessor`，让 resolver 只做业务兜底和完整表/最终表/待复核分流。
- 仍存在：`review_items`、`review_issues`、`file_issues` 还没有统一成分层 review schema。
- 仍存在：当前 trace 是行级精简追溯，不是完整 cell 级证据；如需点击定位到具体单元格，后续再扩展，不建议现在塞进 LLM 输出。
