# Haifa Agent 全新主机评测控制面：可执行开发任务分解与实施指南

- 文档版本：v1.0.0
- 基准设计：`docs/01-ssh-fresh-machine-evaluation-control-plane.md`
- 适用项目：`haifa-agent-eval-infra`
- 目标产物：本地控制 CLI 工具 `evalctl`、远端引导脚本、可信执行器及全套自动化测试

---

## 1. 任务体系与工程结构规划

### 1.1 技术栈选型
- **开发语言**：Python 3.11+
- **包管理与工程编排**：`uv` (`pyproject.toml`)
- **核心依赖**：
  - `pyyaml`：YAML 配置与 Run Request 解析
  - `pydantic>=2.0`：Strict Schema 强类型校验与规范化 JSON 序列化
  - Python 标准库：`subprocess`、`hashlib`、`argparse`、`pathlib`、`tempfile`、`shutil`、`socket`
- **测试框架**：`pytest`、`pytest-mock`、`pytest-cov`
- **代码规范**：`ruff` (format & lint)

### 1.2 仓库工程目录结构
```text
haifa-agent-eval-infra/
├── pyproject.toml                         # uv 项目与依赖声明
├── README.md                              # 快速入门与架构说明
├── docs/
│   ├── 01-ssh-fresh-machine-evaluation-control-plane.md  # 顶层架构设计方案
│   └── 02-executable-development-tasks.md               # 本任务分解文档
├── lockfiles/
│   └── bootstrap-ubuntu-26.04.json        # 工具链最低/推荐版本与包锁定
├── remote/                                # 部署在远端主机 /opt/haifa-eval/ 的受控脚本
│   ├── doctor.sh                          # 只读主机环境检查
│   ├── bootstrap.sh                       # 幂等 APT 软件安装与用户环境配置
│   ├── source-prepare.sh                  # 独立 Git 源码检出与 SHA 校验
│   ├── supervisor.sh                      # systemd transient unit 包装与退出码捕获
│   └── cleanup.sh                         # 精确 runId 级受控清理
├── src/
│   └── evalctl/
│       ├── __init__.py
│       ├── cli.py                         # 顶层 CLI 子命令分发入口
│       ├── config/
│       │   ├── __init__.py
│       │   ├── schema.py                  # Run Request V1 规范与 Pydantic 模型
│       │   └── loader.py                  # YAML 加载、规范化 JSON 转换与 SHA-256 计算
│       ├── core/
│       │   ├── __init__.py
│       │   ├── lifecycle.py               # 本地/远端 lifecycle.jsonl 事件记录器
│       │   ├── errors.py                  # 强类型异常定义 (Fail-closed)
│       │   └── models.py                  # 运行态数据结构定义
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── ssh.py                     # OpenSSH 命令安全封装 (严禁 StrictHostKeyChecking=no)
│       │   └── sftp.py                    # 文件传输与清单拉取验证
│       ├── host/
│       │   ├── __init__.py
│       │   ├── trust.py                   # SSH Host Key 指纹提取、比对与固化
│       │   ├── doctor.py                  # 远端 OS、Arch、Sudo、网络只读预检
│       │   └── bootstrap.py               # APT 引导动作生成、执行与事实采集
│       ├── source/
│       │   ├── __init__.py
│       │   └── manager.py                 # 三仓只读临时 Key 注入、检出、SHA 校验与清理
│       ├── admission/
│       │   ├── __init__.py
│       │   └── validator.py               # Profile、Provider、Model 交叉验证与本地 Secret 存在性检查
│       ├── harness/
│       │   ├── __init__.py
│       │   ├── plan.py                    # Harness plan 执行、原始 Plan 收集与 Plan Set 组装
│       │   ├── approval.py                # 预算与 Plan Set 摘要比对与人工审阅门禁
│       │   ├── secret.py                  # tmpfs stdin 安全注入 secrets.env
│       │   └── supervisor.py              # systemd 任务投递、心跳与安全进度过滤流式转发
│       ├── evidence/
│       │   ├── __init__.py
│       │   ├── verifier.py                # Manifest SHA 校验与 Secret Scan 结果裁决
│       │   └── puller.py                  # 远端证据拉取与本地一致性二次验证
│       └── report/
│           ├── __init__.py
│           ├── builder.py                 # 确定性报告生成器入口
│           ├── critical_path.py           # CP Smoke 与 Formal CP-01~11 统计投影
│           ├── autonomous_delivery.py     # AD Phase 1~3 (26 Case) 统计投影
│           └── renderers.py               # Terminal ANSI / Markdown / JSON 渲染器
└── tests/
    ├── __init__.py
    ├── conftest.py                        # 测试桩、Fixtures、临时目录配置
    ├── unit/
    │   ├── test_request_schema.py
    │   ├── test_lifecycle.py
    │   ├── test_ssh_transport.py
    │   ├── test_host_doctor.py
    │   ├── test_bootstrap.py
    │   ├── test_source_manager.py
    │   ├── test_admission.py
    │   ├── test_plan_approval.py
    │   ├── test_progress_parser.py
    │   ├── test_evidence_verifier.py
    │   └── test_report_builder.py
    └── integration/
        ├── test_cli_dispatch.py
        └── test_offline_workflow_mock.py
```

---

## 2. 细分开发任务工作分解结构 (WBS)

### Phase 0: 工程基础设施与规范初始化

#### Task 0.1: 基础工程构建与配置
- **目标**：建立 Python 现代工程结构、依赖清单与静态检查配置。
- **具体实施**：
  1. 创建 `pyproject.toml`，配置项目元数据、Python `>=3.11`、依赖项（`pyyaml>=6.0`, `pydantic>=2.0`）、测试依赖（`pytest>=8.0`, `pytest-mock`）与代码工具配置（`ruff`）。
  2. 配置入口点脚本 `evalctl = "evalctl.cli:main"`。
  3. 创建基础目录结构与初始 `README.md`。
- **交付物**：`pyproject.toml`, 完整目录树, `ruff` 检查通过。
- **验收标准**：`uv sync` 成功完成，`pytest` 可正常执行，`evalctl --help` 骨架命令可响应。

---

### Phase 1A: 核心架构模型与离线校验控制面 (Read-Only & Offline)

#### Task 1.1: Run Request V1 规范与模式校验器
- **对应设计文档**：第 5 节（Run Request 契约）
- **具体实施**：
  1. 在 `src/evalctl/config/schema.py` 中使用 Pydantic 定义严谨的类型：
     - `TargetConfig`: `address`, `port` (默认 22), `user`, `hostKeySha256`, `sshPrivateKeyFileEnv`, `requirePasswordlessSudo: bool`
     - `RepoSpec`: `url`, `commit` (精确 40 位小写十六进制 SHA)
     - `SourceConfig`: `githubPrivateKeyFileEnv`, `repositories: {product: RepoSpec, docs: RepoSpec, testConfig: RepoSpec}`
     - `SuiteRunSpec`: `id`, `suite`, `platform`, `approveBudget: str`, `reportRole` (`admission` | `formal`)
     - `EvaluationConfig`: `kind` (字面量 `"haifa-harness"`), `providerId`, `modelId`, `agentProfileRef`, `requiredSecretEnvironmentNames: list[str]`, `runs: list[SuiteRunSpec]`
     - `OutputConfig`: `remoteEvidenceRoot`, `localResultRoot`, `retainRemoteEvidenceAfterPull: bool`
     - `RunRequest`: `schemaVersion: 1`, `runId`, `target`, `source`, `evaluation`, `output`
  2. 实现校验规则：
     - 禁止通配符、HEAD、分支名作为 commit，必须是 40 位 SHA；
     - 验证 `runId` 符合 `^[a-z0-9-]+$`；
     - 验证 `localResultRoot` 不在任何已知的 Git 源码仓库根路径内；
     - 验证 `sshPrivateKeyFileEnv` 与 `githubPrivateKeyFileEnv` 环境变量名不同。
  3. 实现 `src/evalctl/config/loader.py`：
     - 加载 YAML 文件；
     - 计算其 Canonical JSON 字符串及 SHA-256 摘要（用于全流程审计）；
     - 检查本地引用的私钥环境变量是否存在，并验证文件存在性及权限（POSIX 0600 或 Windows 专有读取）。
  4. 暴露 CLI 命令：`evalctl request validate --file <request.yaml>`。
- **单测/自测**：
  - 测试非法 commit、非法 runId、相同 key env、缺少字段时的 Fail-closed 行为；
  - 测试标准契约 YAML 解析与 SHA-256 计算的一致性。

#### Task 1.2: 本地与远端生命周期事件管理器 (Lifecycle Journal)
- **对应设计文档**：第 9 节（生命周期与动作）
- **具体实施**：
  1. 在 `src/evalctl/core/lifecycle.py` 实现 `LifecycleManager`：
     - 状态集枚举：`REQUEST_VALIDATED`, `HOST_TRUSTED`, `HOST_PREFLIGHTED`, `BOOTSTRAPPED`, `SOURCE_PINNED`, `MODEL_PROFILE_VERIFIED`, `PLAN_CREATED`, `WAITING_APPROVAL`, `RUNNING`, `EVIDENCE_READY`, `EVIDENCE_PULLED`, `REPORT_READY`, `COMPLETE`, 以及各阶段对应的 `FAILED_<STAGE>`, `CANCELLED`。
     - 事件记录结构：`timestamp` (ISO 8601), `runId`, `stage`, `status` (`SUCCESS` | `FAILURE` | `IN_PROGRESS`), `exitCode`, `reasonCode`, `artifacts: dict`, `extra: dict`。
     - 行为：追加写入本地 `<localResultRoot>/<runId>/control/lifecycle.jsonl`，并支持远端同步。
     - 状态转移校验：禁止非法状态跃迁（例如未经 `WAITING_APPROVAL` 直接进入 `RUNNING`）。
- **单测/自测**：
  - 测试生命周期顺序写入与重放；测试非法跃迁抛出异常。

#### Task 1.3: SSH 安全传输与 Host Key 可信锚定
- **对应设计文档**：第 6 节（凭据与信任边界）、第 6.3 节（SSH 安全）
- **具体实施**：
  1. 在 `src/evalctl/transport/ssh.py` 实现基于底层 OpenSSH (`ssh`, `scp`) 的子进程封装：
     - **安全底线**：严禁 `StrictHostKeyChecking=no`；严禁拼接未转义的 shell 命令；
     - 必须显式指定：`-o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=15`；
     - 统一通过参数列表传参，远程命令使用标准参数数组调用，避免 Shell Injection。
  2. 在 `src/evalctl/host/trust.py` 实现：
     - `discover_host_key(address, port)`：使用 `ssh-keyscan` 获取远端公钥并计算 `SHA256:...` 指纹；
     - `verify_or_trust_host_key(request, auto_trust=False)`：对比 Request 中的 `hostKeySha256`。若 Request 为空，仅输出指纹并提示操作者人工确认固化，中断后续流程；若不匹配，坚决阻断；若匹配，追加至 Run 专用的临时 `known_hosts`。
  3. 暴露 CLI 命令：`evalctl host trust --file <request.yaml>`。
- **单测/自测**：
  - Mock `ssh-keyscan` 与 `ssh`，验证指纹比对逻辑、不匹配阻断逻辑、known_hosts 隔离配置。

#### Task 1.4: 主机只读预检机制 (Host Doctor)
- **对应设计文档**：第 8 节（主机引导与可重现性）、第 10.1 节
- **具体实施**：
  1. 编写受控只读脚本 `remote/doctor.sh`：
     - 检查 `/etc/os-release` 是否为 Ubuntu 26.04 (或支持的版本)；
     - 检查 `dpkg --print-architecture` (`amd64` 或 `arm64`)；
     - 检查当前用户非交互 `sudo -n true` 权限；
     - 检查可用磁盘空间（根目录与 `/var/lib` 至少 20GB 空闲）；
     - 检查 `/run` 挂载点类型必须为 `tmpfs`；
     - 检查对外网络连通性（GitHub HTTPS/SSH、Maven 仓库、DNS 解析）；
     - 检查系统时间与 NTP 同步状态。
  2. 在 `src/evalctl/host/doctor.py` 实现调度执行与结果解析：
     - 通过 SSH 调用远端 doctor 检查，不产生主机副作用；
     - 输出结构化 `doctor_report.json`。
  3. 暴露 CLI 命令：`evalctl host doctor --file <request.yaml>`。
- **单测/自测**：
  - 测试各种 Doctor 检查输出解析（Ubuntu 版本不对、无 sudo、无 tmpfs、磁盘不足时的结构化阻断原因）。

#### Task 1.5: 软件包锁定规范与 Bootstrap Dry-Run
- **对应设计文档**：第 8.2 节、第 8.3 节
- **具体实施**：
  1. 建立 `lockfiles/bootstrap-ubuntu-26.04.json`，声明所需 APT 包及最低工具版本要求：
     - APT 清单：`ca-certificates`, `curl`, `wget`, `git`, `openssh-client`, `jq`, `tar`, `unzip`, `zip`, `xz-utils`, `rsync`, `openjdk-21-jdk-headless`, `build-essential`, `python3`, `python3-venv`, `python3-pip`, `nodejs`, `npm`, `golang-go`, `procps`, `psmisc`, `lsof`, `acl`, `util-linux`, `locales`, `tzdata`。
     - 最低版本约束：Java 21, Python 3.11+, Node 18+, Go 1.20+, Git 2.30+。
  2. 在 `src/evalctl/host/bootstrap.py` 实现 `generate_bootstrap_plan()`：
     - 比对锁定清单与当前主机已安装包状态，生成待执行变更计划（Packages to install/upgrade）；
     - 支持 dry-run 输出，不执行安装。
- **单测/自测**：
  - 测试清单解析与差异比对算法。

---

### Phase 1B: 远端主机引导与执行编排实现 (Remote Execution & Harness)

#### Task 2.1: 幂等的主机引导程序 (Host Bootstrap)
- **对应设计文档**：第 8.2 节（软件包安装与架构无关 Java 解析）
- **具体实施**：
  1. 编写远端初始化脚本 `remote/bootstrap.sh`：
     - 校验 root/sudo 权限；
     - 设置 `DEBIAN_FRONTEND=noninteractive`，执行受控 APT 更新与安装；
     - 严格按架构无关物理路径解析 Java/Javac，验证两者指向同一 `JAVA_HOME` 且版本为 21：
       ```bash
       eval_java="$(readlink -f "$(command -v java)")"
       eval_javac="$(readlink -f "$(command -v javac)")"
       eval_java_home="$(dirname "$(dirname "$eval_java")")"
       test "$eval_java_home" = "$(dirname "$(dirname "$eval_javac")")"
       ```
     - 逐项验收工具版本，输出 `toolchain.json`；
     - 创建专用受限系统账号 `haifa-eval` 及组；
     - 创建标准化目录结构：
       `/opt/haifa-eval/`
       `/var/lib/haifa-eval/{runs,worktrees,plans,evidence}`
       `/run/haifa-eval/` (权限 0700，归属 `haifa-eval`)；
     - 提取并记录 `installed-packages.tsv`、`os-release.json`、`apt-sources.sha256`。
  2. 在 `src/evalctl/host/bootstrap.py` 中调度：
     - 上传固定脚本至 `/opt/haifa-eval/`；
     - 触发执行并拉取 Host Facts 至本地 `<localResultRoot>/<runId>/control/host_facts/`；
     - 更新生命周期为 `BOOTSTRAPPED`。
  3. 暴露 CLI 命令：`evalctl host bootstrap --file <request.yaml>`。
- **单测/自测**：
  - 测试 Java 解析逻辑与各工具版本比对逻辑（Mock 输出）。

#### Task 2.2: 精确源码准备与三仓拓扑维护 (Source Prepare)
- **对应设计文档**：第 6.2 节、第 7 节、第 10.3 节
- **具体实施**：
  1. 编写远端源码拉取脚本 `remote/source-prepare.sh`：
     - 接收临时注入的 GitHub Read-Only SSH Key（存放在独立临时目录，权限 `0600`，通过 `GIT_SSH_COMMAND` 使用）；
     - 为该 `runId` 在 `/var/lib/haifa-eval/worktrees/<runId>/haifa-agent` 建立工作区；
     - 克隆/拉取 `product` 仓并 checkout 到精确 40 位 SHA；
     - 在其子路径分别拉取独立的 `docs` 和 `test-config` 仓并 checkout 到各自精确 40 位 SHA；
     - 检查三仓状态必须为完全 clean (无 untracked 文件，无未提交修改)；
     - 生成并写入三仓的 `source-manifest.json` 与 SHA-256；
     - **立即彻底安全删除远端临时 GitHub Key**。
  2. 在 `src/evalctl/source/manager.py` 实现：
     - 本地读取 GitHub Key 内容，经由 SSH 临时受限通道传至远端；
     - 监控检出过程，确保无论成功或失败，远端 Key 都被完全销毁（Trap 清理）；
     - 抓取 `source-manifest.json`，在本地验证三个 commit 与 Request 完全一致。
  3. 暴露 CLI 命令：`evalctl source prepare --file <request.yaml>`。
- **单测/自测**：
  - 测试 Key 注入后必定清理的异常保障机制；
  - 测试 commit 不一致、未提交脏文件的检测拒绝机制。

#### Task 2.3: Profile、Provider 准入与本地凭据交叉校验 (Admission)
- **对应设计文档**：第 3 节、第 5 节、第 10.4 节
- **具体实施**：
  1. 在 `src/evalctl/admission/validator.py` 实现：
     - 读取已检出的 `test-config/profiles/<agentProfileRef>.json` (或 yaml)；
     - 交叉比对 Request 中的 `providerId` 和 `modelId` 与 Profile 中声明的精确身份是否完全吻合；
     - 校验 Profile 配置内容的 SHA-256；
     - 检查 `requiredSecretEnvironmentNames`：遍历所有必需的 Secret 变量名，验证本地环境变量中均存在且非空；
     - **安全底线**：严禁在日志、异常或控制台输出 Secret 的值、长度、字符前后缀或哈希；
     - 验证 Profile 声明的 baseline commit 是否为主仓检出 commit 的历史祖先。
- **单测/自测**：
  - 测试 Provider/Model ID 不匹配、Secret 缺失、Profile 损坏时的 fail-closed 拦截。

#### Task 2.4: Plan Set 生成与人工批准门禁 (Plan & Approval Gate)
- **对应设计文档**：第 10.5 节、第 9 节
- **具体实施**：
  1. 在 `src/evalctl/harness/plan.py` 实现：
     - 针对 Request 中的每个 Suite 条目，以 `haifa-eval` 用户在远端调用：
       `test-config/scripts/run-suite.sh plan --suite <suite> --profile <profile> --platform <platform> --mode live --output /var/lib/haifa-eval/plans/<runId>/<suite-id>.json`；
     - 收集各 Suite 生成的 Plan JSON，验证 runner JAR SHA-256 与类名；
     - 汇总计算各 Suite 的预算并生成标准 `plan-set.json`：
       包含 `runId`, `requestSha256`, 各 Plan 的 `planSha256`, `budgetUnit`, `budget`, 以及整个 Plan Set 的 `planSetSha256`；
     - 将生命周期置为 `WAITING_APPROVAL`，命令结束并退出。
  2. 在 `src/evalctl/harness/approval.py` 实现：
     - 比较操作者输入的 `--approved-plan-set <digest>` 与本地生成的 `planSetSha256`；
     - 校验操作者批准的每项预算与 Request/Plan 一致；
     - 生成审计记录 `approval.json` (记录批准时间、操作者标识、Digest)。
  3. 暴露 CLI 命令：
     - `evalctl plan --file <request.yaml>`
     - `evalctl run --file <request.yaml> --approved-plan-set <digest>`
- **单测/自测**：
  - 测试未批准、Digest 错误、预算篡改时的拦截；测试合规 Plan Set 生成。

#### Task 2.5: 远端 Supervisor、tmpfs Secret 注入与安全进度流 (Run & Supervise)
- **对应设计文档**：第 4.2 节、第 6.2 节、第 10.6 节
- **具体实施**：
  1. 在 `src/evalctl/harness/secret.py` 实现：
     - 仅在 `run` 开始时，将必需的 API Key 通过 SSH stdin 写入远端 `/run/haifa-eval/<runId>/secrets.env`；
     - 文件权限严格为 `0600`，归属 `haifa-eval:haifa-eval`；
     - 确认宿主挂载为 tmpfs，否则拒绝运行。
  2. 编写 `remote/supervisor.sh` 与 systemd transient unit 配置：
     - 使用 `systemd-run --unit=haifa-eval-<runId>-<suiteId> --property=EnvironmentFile=/run/haifa-eval/<runId>/secrets.env --property=LimitNOFILE=65536 --uid=haifa-eval ...`；
     - 执行 `run-suite.sh run --plan ... --approve-budget ...`；
     - 保证 SSH 断开后进程仍持续执行并在结束时捕获退出码；
     - 在运行结束（无论成功或异常）的 `ExecStopPost` 中立即销毁 `secrets.env`。
  3. 在 `src/evalctl/harness/supervisor.py` 实现安全日志转发：
     - 正则匹配安全进度模式：`^\[delivery-progress\] phase=(\S+) evaluated=(\d+)/(\d+) passed=(\d+)/(\d+) currentCase=(\S+) currentRepetition=(\S+)$`；
     - 仅向终端或 status 接口输出脱敏的安全心跳进度；
     - 严禁输出 Prompt、LLM 思考内容、Tool 参数或系统环境变量；
     - 维护本地 journal 日志副本。
  4. 暴露 CLI 命令：
     - `evalctl status --run-id <id>`
     - `evalctl logs --run-id <id> [--follow]`
- **单测/自测**：
  - 测试进度模式过滤器的脱敏效果（确保含有 API key、prompt 的行被完全过滤或不被暴露）；
  - 测试断线恢复后的状态查询逻辑。

#### Task 2.6: 证据收集与远端/本地双重校验 (Evidence Collect)
- **对应设计文档**：第 10.7 节
- **具体实施**：
  1. 在 `src/evalctl/evidence/verifier.py` 实现：
     - 检查 Harness 输出的权威 Evidence Root；
     - 校验必须存在：`run-result.json`, `secret-scan.json`, `manifest.sha256`；
     - 检查 `secret-scan.json` 判定：若存在未放行 Secret 泄漏，判定为 `INVALID_EVIDENCE`；
     - 根据 `manifest.sha256` 逐项验证文件大小与 SHA-256。
  2. 在 `src/evalctl/evidence/puller.py` 实现：
     - 在远端先执行一次清单核验；
     - 通过 SFTP/rsync 拉取整个 Evidence Root 至 `<localResultRoot>/<runId>/evidence/`；
     - 在本地再次执行全量清单核验（二次校验）；
     - 生成传输记录 `transfer-receipt.json`；
     - 标记生命周期为 `EVIDENCE_READY` -> `EVIDENCE_PULLED`。
  3. 暴露 CLI 命令：`evalctl collect --run-id <id>`。
- **单测/自测**：
  - 测试文件大小篡改、哈希不匹配、Secret Scan 报警时的 `INVALID_EVIDENCE` 判定。

---

### Phase 1C: 确定性报告生成与生命周期收敛 (Deterministic Report & Cleanup)

#### Task 3.1: 确定性多端报告生成器 (Report Generator)
- **对应设计文档**：第 11 节（确定性报告）
- **具体实施**：
  1. 在 `src/evalctl/report/` 模块实现纯程序确定性汇总（不调用任何 LLM）：
     - 顶层权威状态定义：`COMPLETE_PASS`, `COMPLETE_WITH_FAILURES`, `INCOMPLETE`, `INVALID_EVIDENCE`, `INFRA_FAILED`；
     - `critical_path.py`：
       - 单独投影 Smoke 准入结果；
       - 投影正式 CP-01~11 每个 Case、repetition、状态、失败原因；
       - 计算 `PASS/11` 覆盖率与结果；
       - 记录 `processTreeNaturalExit`, `repositoryStateStable`, Secret Scan 状态；
     - `autonomous_delivery.py`：
       - Phase 1/2/3 分别统计，逐项列出 26 个 Case 实例明细；
       - 仅当三 Phase 均具备完整有效证据时，生成 `PASS/26`；
       - 统计 Token 消耗、工具调用次数、耗时与估算成本（标记 `providerReportedCostKnown`）；
     - 记录每一个数值的来源文件与 SHA-256。
  2. 实现三类渲染器 `renderers.py`：
     - 终端 ANSI 彩色摘要表格；
     - 机器可读 `report.json`（稳定 Schema）；
     - 人类可读 `report.md`（完整归档）。
  3. 暴露 CLI 命令：`evalctl report --run-id <id> [--format terminal|json|markdown]`。
- **单测/自测**：
  - 基于模拟的 CP 和 AD 真实 Harness 输出数据，验证报告计算与 Markdown/JSON 输出的精确性。

#### Task 3.2: 运行清理与受控回收 (Cleanup)
- **对应设计文档**：第 12 节（失败、恢复与清理）
- **具体实施**：
  1. 在 `remote/cleanup.sh` 与 `src/evalctl/core/cleanup.py` 实现：
     - 严格限定删除目标为指定 `runId` 对应的精确目录与 systemd unit；
     - 严禁接受通配符、根目录、Home 或 `/var/lib/haifa-eval` 根作为参数；
     - 本地检查：确认该 Run 的 Evidence 已经完整拉取并本地通过校验；
     - 人工确认机制：打印待清理目标路径与本地证据摘要，要求确认；
     - 清理远端 `/run/haifa-eval/<runId>`、`/var/lib/haifa-eval/{runs,worktrees,plans}/<runId>`。
  2. 暴露 CLI 命令：`evalctl cleanup --run-id <id>`。
- **单测/自测**：
  - 测试非法目标路径（如 `/`, `/var/lib/haifa-eval`）的防护拦截；
  - 测试本地证据未拉取时的清理告警/阻断。

#### Task 3.3: 异常边界、断线重连与全流程离线端到端测试
- **对应设计文档**：第 14 节 (Phase 1C)、第 15 节 (验收标准)
- **具体实施**：
  1. 异常恢复策略：
     - SSH 连接意外断开时的重连探查与 status 恢复；
     - 传输中断时的断点重试与 Manifest 校验；
  2. 编写离线端到端模拟测试 `tests/integration/test_offline_workflow_mock.py`：
     - 使用 Mock SSH/Remote Server 模拟整个流程：
       `validate -> trust -> doctor -> bootstrap -> source prepare -> plan -> approve & run -> collect -> report`；
     - 验证所有关键状态机转移、脱敏日志与确定性报告输出。
- **单测/自测**：
  - 运行全套测试集，达到 85%+ 测试覆盖率。

---

## 3. 实施进度规划与里程碑 (Milestones)

| 里程碑 | 周期目标 | 核心输出 | 准出条件 (Gate) |
|---|---|---|---|
| **M0: 工程与契约基线** | 搭建工程骨架与 Schema 引擎 | `pyproject.toml`, CLI 入口, `schema.py`, 单测 | `evalctl request validate` 对合法/非法 YAML 判定 100% 正确 |
| **M1: 主机受控连接与预检** | 完成安全 SSH、Host Trust 与 Doctor | `ssh.py`, `trust.py`, `doctor.py`, `remote/doctor.sh` | 严禁 StrictHostKeyChecking=no，Doctor 可准确定位主机缺失项 |
| **M2: 主机引导与三仓准备** | 实现幂等 Bootstrap 与源码精确检出 | `bootstrap.sh`, `source-prepare.sh`, `manager.py` | 成功安装 JDK21/Node/Python 等，临时 Key 检出后彻底自毁 |
| **M3: Harness 编排与两阶段门禁**| 实现 Plan Set、人工审批、Supervisor 与日志安全转发 | `plan.py`, `approval.py`, `supervisor.py`, `secret.py` | 未经人工批准绝对不执行 Run，tmpfs secrets.env 退出必删，无 Secret 泄漏 |
| **M4: 证据拉取与确定性报告** | 双端清单校验、CP 与 AD 报告生成 | `collector.py`, `report/*.py` | 报告输出 terminal/json/markdown，Secret Scan 失败时标红 INVALID_EVIDENCE |
| **M5: 交付收敛与集成自测** | 可靠性恢复、Cleanup 与离线集成测试 | `cleanup.py`, `test_offline_workflow_mock.py` | 全流程通过 Mock 集成验证，符合文档第 15 节所有验收标准 |

---

## 4. 任务执行跟踪清单 (Task Checklist)

- [ ] **M0: 工程初始化**
  - [ ] 0.1 初始化 git 与 uv 工程 (`pyproject.toml`, `ruff`, `pytest`)
  - [ ] 0.2 实现 CLI 骨架与帮助文档 (`src/evalctl/cli.py`)
- [ ] **M1: 配置契约与只读检查 (Phase 1A)**
  - [ ] 1.1 实现 Run Request V1 Pydantic 模型与 Schema 验证 (`schema.py`, `loader.py`)
  - [ ] 1.2 实现 `lifecycle.jsonl` 事件追加记录器 (`lifecycle.py`)
  - [ ] 1.3 实现安全 SSH 客户端与 Host Key 指纹可信验证 (`ssh.py`, `trust.py`)
  - [ ] 1.4 实现只读主机预检脚本与解析器 (`remote/doctor.sh`, `doctor.py`)
  - [ ] 1.5 实现软件包锁定规范与 dry-run 比对 (`bootstrap-ubuntu-26.04.json`)
- [ ] **M2: 远端主机引导与源码管理 (Phase 1B 前半)**
  - [ ] 2.1 实现幂等 APT Bootstrap 脚本与 Java 物理路径解析 (`bootstrap.sh`, `bootstrap.py`)
  - [ ] 2.2 实现三仓拓扑拉取、精确 40 位 SHA 校验与临时 Key 销毁 (`source-prepare.sh`, `manager.py`)
  - [ ] 2.3 实现 Profile/Provider 交叉校验与本地环境变量存在性检查 (`admission/validator.py`)
- [ ] **M3: Harness 两阶段编排与安全执行 (Phase 1B 后半)**
  - [ ] 3.1 实现 Plan 生成、Plan Set 汇总与 `WAITING_APPROVAL` 门禁 (`plan.py`)
  - [ ] 3.2 实现人工审批摘要核对与批准记录生成 (`approval.py`)
  - [ ] 3.3 实现 tmpfs `secrets.env` 安全注入与生命周期删除 (`secret.py`)
  - [ ] 3.4 实现 systemd transient unit 调度与脱敏安全进度流转发 (`supervisor.py`)
- [ ] **M4: 证据校验与确定性报告 (Phase 1C)**
  - [ ] 4.1 实现权威 Evidence 远端/本地双端 Manifest 与 Secret Scan 校验 (`verifier.py`, `puller.py`)
  - [ ] 4.2 实现 Critical Path 结果确定性汇总投影 (`critical_path.py`)
  - [ ] 4.3 实现 Autonomous Delivery 26 Case 结果确定性汇总投影 (`autonomous_delivery.py`)
  - [ ] 4.4 实现 Terminal / JSON / Markdown 多格式报告渲染器 (`renderers.py`)
- [ ] **M5: 清理与集成验收**
  - [ ] 5.1 实现精确 `runId` 范围确认与安全清理程序 (`cleanup.sh`, `cleanup.py`)
  - [ ] 5.2 编写全流程 Mock 离线端到端集成测试 (`test_offline_workflow_mock.py`)
  - [ ] 5.3 运行全量单元测试与 Lint 检查，输出交付总结报告
