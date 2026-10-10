# Terminal-Bench (TB2 × GLM) 远程评测 Runbook

前置状态（一次性，已完成，无需重复）：
- 东京专用网络：VPC `vpc-6wecv5kp71b0qxf8pmy6n` / vSwitch `vsw-6weunpwzl72m9u7dszaoi` / SG `sg-6wehuu8odfmelya5pfr2`（仅 22 入站）/ KeyPair `haifa-agent-tokyo`（pem: `D:\workspace\haifa-remote\haifa-agent-tokyo.pem`）
- 参数文件：`infra/ros/parameters-tokyo.yaml`（`ecs.e-c1m2.xlarge` 4vCPU/8G，spot ≈¥0.084/h）
- 评测配置：haifa-agent-evals `evals/coding-terminal-bench2-glm53-full89-v1`（89 任务，agent 90min / setup 30 / verifier 30，concurrency 2，已 ADMITTED）
- 凭据：`D:\workspace\haifa-agent-eval-infra\.env`（BIGMODEL_API_KEY 无引号写入）

---

## 1. 拉实例（约 2 分钟，自动写 .env 的 TARGET_HOST_IP）

```powershell
cd D:\workspace\haifa-agent-eval-infra
uv run python infra\ros\manager.py up --parameters infra\ros\parameters-tokyo.yaml --timeout 600
```

## 2. 固定指纹 → 装环境 → 冻结源码（约 6–10 分钟）

```powershell
# 首次必须：把 trust 输出的 Discovered 第一个指纹回填到
# run-request-evals-tb2.yaml 与 run-request-evals-tb2-warm10.yaml 的 hostKeySha256
uv run evalctl host trust --file run-request-evals-tb2.yaml
uv run evalctl host bootstrap --file run-request-evals-tb2.yaml      # docker + uv（内置阿里镜像 fallback）
uv run evalctl host doctor --file run-request-evals-tb2.yaml        # 必须输出 PASSED
uv run evalctl source prepare --file run-request-evals-tb2.yaml      # 冻结 evals 仓 main
```

> 会话中断的话换 runId 就每次重做 `host trust`（known_hosts 按 runId 存放）。

## 3. 零费预检 → 正式跑（systemd 单元，断连不中断）

```powershell
uv run evalctl check --file run-request-evals-tb2.yaml     # admission + doctor，不调模型
uv run evalctl run --file run-request-evals-tb2.yaml       # full89 ×1，18–24h
```

- 本地只打印安全心跳（[supervisor-harbor]/[driver] 标记），全量 journal 落 `localResultRoot\<runId>\control\evals.journal`
- ssh 中断可以：远端 unit 继续跑，把 yaml 里 runId 改新号重新 `trust/prepare` 不换实例也行；或直接重开 `evalctl run`

## 4. 回拉证据 + 报告 → 释放实例

```powershell
uv run evalctl collect --file run-request-evals-tb2.yaml
uv run evalctl report --file run-request-evals-tb2.yaml --format markdown
uv run python infra\ros\manager.py down          # 证据已在本地，放心删栈
```

---

## 关键口径（勿改）

- 凭据命名：本地只有 `BIGMODEL_API_KEY`（可选 `BIGMODEL_API_BASE`，默认 open.bigmodel.cn）；`ZAI_*` 是容器/宿主 litellm 内部映射，由 supervisor 派生，永不手填
- uv 索引：evals `uv.toml` 钉 `mirrors.aliyun.com/pypi/simple`（本地/远端一致），勿回 pypi.org
- Docker Hub 走远端 `registry-mirrors`（1ms.run / daocloud），bootstrap 幂等重跑即可
- attempts 门禁 =1：官方 5 repeats 需拆 5 个 run（同 eval 配置不同 runId 分批）
- 新增/修改 eval 配置后：先本地 `uv run evals admit ...` 验 ADMITTED，再 commit + push，远端 `source prepare` 重新冻结才能用到

## 故障速查

| 症状 | 处置 |
|---|---|
| `host trust` Host key mismatch | 回填最新 Discovered 指纹（换实例必得重新钉） |
| bootstrap 600s 超时 | 直接重跑（幂等，docker 已在则秒过）|
| run 报 Eval config not found | evals 配置未 push，先 push 再 `source prepare` |
| EnvironmentStartTimeoutError | 大镜像拉取慢：重跑该 runId（镜像层已缓存则过关），或带宽升配 |
| AgentTimeoutError 大量 | eval 配置调大 timeoutMinutes（thinking 模型 60–90min） |
