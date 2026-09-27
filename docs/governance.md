# 仓库治理配置

## 目标

`main` 仅接收经过 PR 的改动。每次合并都要有独立 AI 对 PR 最新提交的 Review，并留下 GitHub 可核查的记录。

## 当前公开仓库阶段

仓库目前公开。GitHub 已对 `main` 启用分支保护：要求 PR、至少一项其他 GitHub 身份的批准、最新推送由他人批准、推送后撤销旧批准、`config-and-shell` 检查通过且分支保持最新、对管理员执行规则、禁止强制推送和删除分支。

独立 AI 审查服务仍待接入。因此当前已有 PR 与 CI 门禁，独立 AI 审查尚未成为可验证的合并门禁。在接入前，不应为了合并而降低审查要求。

## 独立审查的信任边界

- **生产者**：编写代码并创建 PR；常规开发应使用非管理员 GitHub 身份，不得掌握管理员令牌或审查服务凭据。
- **Reviewer**：由 GitHub 在 PR 创建或更新时自动触发的独立 AI 服务。Review 以 Reviewer 自己的 GitHub 身份提交，或由受保护的工作流发布状态检查。Review 必须绑定 PR 最新提交 SHA；新提交需要重新 Review。
- **所有者**：保管仓库管理员权限，设置分支保护，不把管理员令牌交给生产者。管理员仍是信任根；拥有管理员权限的人可以改变规则，因此不能把管理员凭据交给需要被规则约束的 AI。

生产者自己启动一个“第二个 AI 对话”并贴出结果，只能提供参考，不能证明审查服务独立。仓库应要求独立 GitHub App 的检查，并尽可能将必需检查限定到该 App。若审查 App 不提交 GitHub 批准，还需要单独的批准者；评论不等于批准。

## 接入独立 AI 后的验收

1. 安装独立审查 App，仅授权本仓库，并确认由 PR 事件自动触发。
2. 在测试 PR 上观察 Reviewer 身份、最新提交 SHA、审查结论与状态检查的实际名称。
3. 将 AI 状态检查设为 `main` 的必需检查，限定检查来源到该 App；保留 CI 和 PR 门禁。若 App 提交可计入规则的批准，验证其批准行为；否则保留另一独立批准者。
4. 推送一个新提交，验证旧审查无法直接用于合并，新提交触发新的审查。
5. 涉及 Review 工作流、凭据或分支规则的改动，由所有者另行审核。

## 转为付费私有仓库前

先确认 GitHub Team 组织仓库已具备所需保护能力，并确认独立 AI 服务的私有仓库套餐与授权。迁移后重新核对分支规则、必需检查来源、审查 App 安装范围和 PR 触发行为。公开期间的 Git 历史已经公开；改回私有也不能撤回已复制的内容。

参考：[GitHub 分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches)、[GitHub REST 分支保护 API](https://docs.github.com/en/rest/branches/branch-protection)、[CodeRabbit 公开仓库方案](https://www.coderabbit.ai/oss)。
