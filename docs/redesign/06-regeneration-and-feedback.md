# Regeneration And Feedback

## Problem
- 旧实现只做“整篇 markdown + 单句 instruction”的粗暴改写。
- 结果是案例经常不变、逐字稿劣化、负反馈失效。

## V2 Strategy
- 再生成输入必须显式包含：
  - `base_version`
  - `instruction`
  - 活动约束摘要
  - 已采纳反馈
  - 目标差异说明
- 输出必须：
  - 生成新版本
  - 记录 `source_version`
  - 记录 `revision_goal`
  - 进入新的 review batch

## Acceptance Rules
- 用户说“不要咖啡馆案例”后，后续版本不得再出现该案例类型。
- 新版本必须能和旧版本做 diff。
- 新版本不应无理由整体劣化。
