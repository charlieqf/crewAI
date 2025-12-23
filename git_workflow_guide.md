# Git 多远程仓库与开发同步指南

本指南详细说明了如何在使用 CrewAI 官方代码的基础上，进行公司内部定制化开发并保持与上游同步。

## 1. 当前仓库配置

您的本地仓库已配置为“双远程”模式：

- **`origin`** (您的私有库): `https://github.com/charlieqf/crewAI.git`
  - 这是您的主开发库，拥有完全读写权限。
  - 所有的业务逻辑、文档和私有定制都应提交到这里。
- **`upstream`** (官方仓库): `https://github.com/crewAIInc/crewAI.git`
  - 这是 CrewAI 官方维护的库。
  - 仅用于“只读”同步，获取最新的功能和 Bug 修复。

---

## 2. 日常开发：如何提交代码

当您完成了代码修改或写了新的文档后，请将代码推送到您的私有库。

```bash
# 1. 查看改动状态
git status

# 2. 暂存所有改动
git add .

# 3. 提交到本地记录
git commit -m "feat: 增加了企业微信集成的设计文档"

# 4. 推送到您的个人 GitHub 仓库
git push origin main
```

---

## 3. 同步上游：如何获取官方新功能

CrewAI 更新非常频繁，建议每周执行一次以下操作，以保持您的代码库不过时。

```bash
# 1. 获取官方 (upstream) 的最新变动，但这不会修改您的代码
git fetch upstream

# 2. 确保您在自己的 main 分支上
git checkout main

# 3. 将官方的更新合并到您的分支
git merge upstream/main

# 4. 如果出现冲突
#    - 打开冲突文件手动解决
#    - git add <冲突文件>
#    - git commit -m "chore: 合并上游更新并解决冲突"

# 5. 最后将合并后的代码推送到您的私有库
git push origin main
```

---

## 4. 注意事项（安全第一）

- **`.env` 文件**：如果您在本地创建了 `.env` 文件来存储 OpenAI API Key 或 GitLab API Token，**千万不要将其提交到仓库**。系统已经配置了 `.gitignore` 来忽略此类文件。
- **冲突处理**：在执行 `git merge upstream/main` 之前，请务必保证您的本地工作区是干净的（已 commit 完毕）。

---

## 💡 进阶：分支策略建议

如果您需要进行大型的功能开发，建议创建一个功能分支，而不是直接在 `main` 上修改：
```bash
git checkout -b feat/wecom-integration
# ... 开发完成后 ...
git pull origin main  # 先拉取最新 main
git push origin feat/wecom-integration
```
