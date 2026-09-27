# 仓库治理配置

## 目标

`main` 仅接收经过 PR 的改动。每次合并都要有独立 AI 对 PR 最新提交的 Review，并留下 GitHub 可核查的记录。

## 独立性边界

- **生产者**：编写代码并创建 PR；使用单独的非管理员 GitHub 身份或 GitHub App 凭据，只授予所需的内容和 PR 写权限。
- **Reviewer**：由 GitHub 在 PR 创建或更新时自动触发的独立 AI 服务。Review 以 Reviewer 自己的 GitHub 身份提交，或由受保护的工作流发布状态检查。Review 必须绑定 PR 最新提交 SHA；新提交需要重新 Review。
- **所有者**：保管仓库管理员权限，设置分支保护，不把管理员令牌交给生产者。管理员仍是信任根；拥有管理员权限的人可以改变规则，因此不能把管理员凭据交给需要被规则约束的 AI。

生产者自己启动一个“第二个 AI 对话”并贴出结果，不能证明独立性；GitHub 上 Reviewer 的独立身份、自动触发记录和必需的合并检查才能提供可核查的证据。

## GitHub 服务器端规则

私有仓库需要支持分支保护的 GitHub 套餐。对 `main` 配置：

1. 要求 Pull Request，至少一项独立 Review 或独立 AI 状态检查。
2. 推送新提交后撤销旧批准，并要求最新提交重新审核。
3. 将 `config-and-shell` 和 AI Review 检查设为必需；若使用 GitHub App 检查，指定该 App 为检查来源。
4. 禁止管理员绕过、强制推送和删除分支。
5. 涉及 Review 工作流、凭据或分支规则的改动，由所有者另行审核。

可选实现是 GitHub Copilot 自动代码审查。只有在仓库启用 Copilot 自动审查与“Copilot 批准计入合并要求”、并且分支保护要求批准时，它才可充当必需的 AI Review。另一种实现是独立 GitHub App/受保护检查任务。两者都应验证提交更新后会重新运行或撤销旧批准。

## 当前状态

截至 2026-09-27，GitHub API 对本私有仓库的分支保护和规则集返回 HTTP 403，提示需要 GitHub Pro 或将仓库公开。项目保持私有，因此目前**尚无服务器端强制门禁**。升级并完成规则配置之前，禁止把本文件或 PR 模板视为已实施的保护。

参考：[GitHub 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)、[GitHub Copilot 自动审查](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-code-review)。
