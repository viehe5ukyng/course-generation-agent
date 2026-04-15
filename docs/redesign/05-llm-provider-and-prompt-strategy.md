# LLM Provider And Prompt Strategy

## Summary
- 运行默认仍是 DeepSeek。
- 模型切换通过 `config/llm.yaml` 完成，而不是改业务代码。

## Config Shape
```yaml
default_provider: deepseek
providers:
  deepseek:
    api_base_env: DEEPSEEK_BASE_URL
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com
profiles:
  chat:
    provider: deepseek
    model: deepseek-chat
    temperature: 0.4
  review:
    provider: deepseek
    model: deepseek-chat
    temperature: 0.1
```

## Prompt Rules
- 澄清 prompt 一次只问一个槽位。
- 生成 prompt 必须带 `constraint_summary`。
- 修订 prompt 必须带 `source_version`、`revision_goal`、`constraint_summary`。
- 用户可见层不直接暴露结构化输出里的空值。
