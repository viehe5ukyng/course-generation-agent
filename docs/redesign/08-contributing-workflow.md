# Contributing Workflow

## Fork / Sync / Branch
1. 从主仓库 fork 到个人空间。
2. 定期同步 upstream，避免在过旧基线开发。
3. 分支名建议用 `feature/...`、`fix/...`、`docs/...`。

## PR Expectations
- 标题说明行为变化，不写模糊标题。
- 描述固定包含：
  - 背景
  - 改动点
  - 风险
  - 验证方式
  - 截图或接口示例

## Review Checklist
- 是否保持负约束生效。
- 是否保留版本来源与 diff 能力。
- 是否新增了用户可读时间线。
- 是否让模型切换继续通过配置完成。
