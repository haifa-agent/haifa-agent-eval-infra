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

```bash
# 1. 请求配置校验：检查 Run Request YAML 结构、字段约束与仓库定义
evalctl request validate --file <request>

# 2. 主机信任建立：探测目标主机 SSH 公钥指纹，与声明校验一致后写入本地受控 known_hosts
evalctl host trust --file <request>

# 3. 主机只读预检：检查远端 OS 版本、CPU 架构、内核参数、tmpfs 挂载点与可用磁盘空间
evalctl host doctor --file <request>

# 4. 主机环境引导：幂等安装最小 APT 依赖包与物理路径 JDK 21，生成主机环境快照 (host_facts)
evalctl host bootstrap --file <request> [-v/--verbose]

# 5. 源码克隆与版本冻结：临时注入只读凭据，独立检出主仓/文档仓/配置仓精确 40 位 commit 后立即销毁凭据
evalctl source prepare --file <request> [-v/--verbose]

# 6. 两阶段门禁（第一阶段）：远端构建 runner 并生成执行计划与费用预算，产出 Plan Set Digest
evalctl plan --file <request>

# 7. 两阶段门禁（第二阶段）：携带人工核准的 Plan Set Digest 启动评测，注入内存级 API Key 并拉起 systemd 隔离单元
evalctl run --file <request> --approved-plan-set <digest> [-v/--verbose]

# 8. 任务状态查询：查看当前评测生命周期阶段（如 WAITING_APPROVAL、RUNNING、EVIDENCE_READY 等）
evalctl status --file <request>

# 9. 执行日志查看：读取评测各套件的远端 systemd journal 日志（支持 --follow 实时日志跟随）
evalctl logs --file <request> [--follow]

# 10. 证据产物收集：从远端拉取 Evidence Root 至本地，执行哈希清单比对与凭据防泄漏扫描
evalctl collect --file <request>

# 11. 评测报告生成：解析本地证据并生成标准化评测报告（支持 terminal 终端高亮、json、markdown 格式）
evalctl report --file <request> [--format terminal|json|markdown]

# 12. 远端环境清理：安全停止并清理远端瞬态单元与代码树（默认严格校验本地证据完整收据）
evalctl cleanup --file <request> [--include-evidence] [--force]
```

## 评测主机生命周期管理（阿里云 ROS 抢占式实例）

控制面在 `infra/ros/` 目录下提供了基于阿里云资源编排（ROS）的标准模板与生命周期管理工具，用于极速拉取超低成本的全新抢占式（Spot）Ubuntu 主机，并在评测结束后彻底销毁释放。

### 1. 配置参数准备
复制配置模板并配置本地实际的 VPC、交换机、安全组与 SSH 密钥对（`parameters.yaml` 已加入 `.gitignore`，防止敏感 ID 提交到代码仓）：
```bash
cp infra/ros/parameters.example.yaml infra/ros/parameters.yaml
# 根据实际网络与安全组配置编辑 parameters.yaml
```

### 2. 模板与参数合法性校验
```bash
python infra/ros/manager.py validate
```

### 3. 一键拉起抢占式主机（自动同步 IP 到 `.env`）
```bash
python infra/ros/manager.py up
```
- **自动同步**：等待实例创建成功后，会自动将公网 IP 写入本地 `.env` 的 `TARGET_HOST_IP` 项，可立即无缝对接后续 `evalctl` 命令。
- **参数选项**：
  - `--no-sync-env`：跳过写入 `.env` 文件。
  - `--no-wait`：发起创建请求后不阻塞等待（异步创建）。
  - `--timeout <seconds>`：等待创建完成的超时秒数（默认 300 秒）。

### 4. 查看当前活跃主机状态
```bash
python infra/ros/manager.py status
```

### 5. 评测完成一键销毁释放
```bash
python infra/ros/manager.py down
```
- 自动销毁由当前栈管理的所有 ECS 抢占式实例及关联系统盘，杜绝闲置费用产生。
