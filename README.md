# Haifa Agent Evaluation Control Plane (`haifa-agent-eval-infra`)

独立于产品代码和评测语义的评测基础设施控制面 CLI (`evalctl`)。

## 概述

本项目用于通过本地控制端接管全新的 Ubuntu 评测主机，并在严格的信任边界与物理安全约束下完成：
1. **主机预检与引导**：只读检查环境、幂等 APT 最小软件包安装、无架构假设的 JDK 21 物理路径校验；
2. **源码冻结**：只读凭据临时注入远端，完成主仓、`docs` 仓、`test-config` 仓精确 40 位 commit 独立检出后立即销毁凭据；
3. **两阶段评测门禁**：执行 `plan` 并生成标准 `plan-set.json`，经由人工审阅预算与 Runner 签名确认后方可调用 `run`；
4. **安全凭据注入**：Provider API Key 仅经 SSH stdin 进入远端 tmpfs `/run/haifa-eval/<runId>/secrets.env` (0600)，绝不落地长期介质；
5. **实时安全进度转发**：脱敏转发 `[delivery-progress]` 安全心跳行，断线后任务继续在远端 systemd supervisor 执行；
6. **双端证据校验与确定性报告**：基于清单与 Secret Scan 严格校验拉取的 Evidence Root，由确定性程序生成终端 ANSI、JSON 和 Markdown 报告。

## 架构参考
- 架构设计方案：[`docs/01-ssh-fresh-machine-evaluation-control-plane.md`](docs/01-ssh-fresh-machine-evaluation-control-plane.md)
- 详细任务分解：[`docs/02-executable-development-tasks.md`](docs/02-executable-development-tasks.md)

## CLI 子命令体系

```text
evalctl request validate --file <request>
evalctl host trust --file <request>
evalctl host doctor --file <request>
evalctl host bootstrap --file <request>
evalctl source prepare --file <request>
evalctl plan --file <request>
evalctl run --file <request> --approved-plan-set <digest>
evalctl status --run-id <id>
evalctl logs --run-id <id> [--follow]
evalctl collect --run-id <id>
evalctl report --run-id <id> [--format terminal|json|markdown]
evalctl cleanup --run-id <id>
```
