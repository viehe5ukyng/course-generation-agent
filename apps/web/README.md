# apps/web

该目录当前不作为运行中的前端入口。

当前唯一有效的前端工程目录是项目根下的 `frontend/`：

- `frontend/package.json`
- `frontend/src/*`
- `frontend/src/generated/api.d.ts`

保留 `apps/web/` 仅用于后续真正迁移到 monorepo 结构时承接 Web 应用；在迁移完成前，不应把新前端代码继续分散到这里。
