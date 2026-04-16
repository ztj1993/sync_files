# Project Agents Instructions

## 沟通规范

- 回复简洁，通常 1-3 句或短段落，避免不必要的开场白和总结
- 直接回答用户问题，不绕弯子
- 代码引用包含文件路径和行号，便于导航

## 代码规范

- 代码风格与现有代码保持一致
- 使用现有库和工具，遵循项目惯例

## Git Commit

### 格式
- `type(scope): subject`
- body 使用 `- ` 列表
- type: feat, fix, refactor, docs, style, perf, test, chore, ci

### 类型
- feat: 新增功能
- fix: 修复问题
- docs: 文档变更
- style: 代码格式（不影响逻辑）
- refactor: 重构
- perf: 性能优化
- test: 测试相关
- chore: 构建工具/依赖变更
- ci: CI/CD 相关

### 提交流程

1. 生成 commit message
2. 向用户展示完整内容
3. 等待确认
4. 确认后才执行 commit

### 强制规则
- ❌ 不允许跳过用户确认直接 commit
- ❌ 不允许使用不规范 commit message
- ✅ 必须符合 Conventional Commits

### 推荐实践
- 一个 commit 只做一件事
- 保持历史可读性与可回滚性
