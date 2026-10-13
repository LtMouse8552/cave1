---
name: report-writer
description: 撰写结构化的实验报告或技术调研报告并保存为 Markdown 文件。当用户要求“写报告”“写实验报告”“整理成文档”“生成调研总结”时使用。
---

# 报告撰写技能

## 何时使用
用户要求把某个主题、实验或调研结果整理成一份正式的 Markdown 报告时。

## 执行步骤
1. 用 `write_todos` 列出计划：收集资料、写初稿、审稿、定稿。
2. 用 `get_current_time` 获取今天的日期，写进报告抬头。
3. 收集资料（报告中的事实只能来自这些来源）：
   - 与课程实验有关的内容，调用 MCP 工具 `list_course_demos` / `get_course_demo`。
   - 写某个 demo 的报告时，用 `read_file` 阅读该目录下的 README.md 和主要源码（如 `/README.md`、`/agent.py`）。
   - 需要多方面资料时，用 `task` 工具委派给 `researcher` 子代理。
4. 用 `read_file` 读取同目录下的模板 `/skills/report-writer/template.md`，严格按模板结构写作。
5. 用 `write_file` 把初稿保存到 `/workspace/<主题英文短名>-report.md`。
6. 用 `task` 把初稿全文交给 `critic` 子代理审稿，根据意见用 `edit_file` 修改。
7. 可调用 MCP 工具 `text_stats` 检查篇幅，正文建议 800 到 1500 字。
8. 最后告诉用户文件路径，并用 3 句话概括报告内容。

## 写作规范
- 结论先行，每一节第一句话就是该节结论。
- 数字必须用 `calculator` 工具计算，不要心算。
- 不确定的信息标注“待核实”，严禁编造数据、百分比或未在资料中出现的结论。
- 审稿意见与源码矛盾时，以源码为准。
