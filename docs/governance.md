# 仓库治理配置

## 目标与当前规则

`main` 仅接收经过 PR 的改动。GitHub 当前要求：至少一项其他身份的批准、最新推送由他人批准、旧批准随新推送失效、`config-and-shell` 检查通过且分支保持最新；规则对管理员生效，禁止强制推送和删除分支。

根目录 [AGENTS.md](../AGENTS.md) 给 Codex 自动审查提供项目规则，重点检查代码对同类输入的通用性，以及是否通过静默 fallback、硬编码答案或跳过验证掩盖问题。生产者应在 PR 中说明适用的输入范围、跨样例验证及失败行为。审查发现阻断问题时先修复，再让 Codex 审查最新提交。

## 独立审查与 GitHub 批准

已启用的 ChatGPT/Codex GitHub 集成在 PR 开放审查时自动运行，以 `chatgpt-codex-connector[bot]` 身份留下可核查的审查状态。合并者应确认状态为 `Completed`，且记录的提交 SHA 与 PR 最新提交一致，并处理所有审查意见。

Codex 无发现时可能只留下 👍；这既不是 GitHub 的 `APPROVED` Review，也不是必需的状态检查。`AGENTS.md` 只能指导审查内容，不能改变 GitHub 对批准的判定。因此当前 Codex 自动审查**不能单独满足** `main` 的一项批准要求；另需具备权限且不同于 PR 作者及最新推送者的审核者在 GitHub 提交 `Approve`。不能为了合并而降低既定要求。

生产者自己启动的第二个 AI 会话或自己转贴的审查意见，不算独立审查。管理员凭据应由所有者保管；拥有管理员权限者仍可修改分支规则，是治理的信任根。

## 合并核对

1. Codex 自动审查完成，审查状态关联最新提交；发现的问题已解决。新推送后重新核对。
2. 独立批准者在 GitHub 提交批准，且满足 GitHub 对最新推送的要求。
3. `config-and-shell` 及其他必需检查通过；涉及 GPU 的验证附 Slurm 作业编号、结果及节点关机状态。
4. 合并者确认 PR 描述包含通用性证据、失败处理方式与残余风险，再从 GitHub PR 页面合并。

## 迁移到付费私有仓库

迁移到 GitHub Team 组织仓库后，重新核对私有仓库的分支规则、批准要求、CI 和 Codex 自动审查触发条件。公开期间的 Git 历史可能已被复制；改回私有无法撤回已公开内容。

参考：[OpenAI Codex GitHub 审查](https://learn.chatgpt.com/docs/third-party/github)、[GitHub 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)。
