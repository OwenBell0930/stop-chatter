<p align="right">
  <a href="README.md">English</a> | <strong>简体中文</strong>
</p>

<div align="center">
  <a href="assets/hero.svg">
    <img src="assets/hero.svg" width="100%" alt="Stop Chatter — 让LLM只输出你要的最终结果，避免多余解释和过程留痕" />
  </a>
</div>

# stop-chatter

<div align="center">

**让LLM只输出你要的最终结果，避免多余解释和过程留痕！**

[![CI](https://github.com/OwenBell0930/stop-chatter/actions/workflows/ci.yml/badge.svg)](https://github.com/OwenBell0930/stop-chatter/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-0B1020.svg)](LICENSE)
[![Zero runtime dependencies](https://img.shields.io/badge/runtime_dependencies-0-19A974.svg)](#两种模式)
[![Cursor · Codex · Claude Code](https://img.shields.io/badge/Cursor_·_Codex_·_Claude_Code-ready-FF6B4A.svg)](#安装)

</div>

`stop-chatter` 是一个轻量、可移植的 Agent Skill，附带可选的零依赖确定性门禁。它不是单纯要求模型“少说点”，而是在用户纠正需求后，重新编译当前目标，并清掉已撤回想法在代码、测试、注释、UI、PR 文案和记忆中的衍生物。

适配 Cursor、OpenAI Codex 和 Claude Code。

## 痛点直击

> 我只要一盘番茄炒蛋，Agent 却擅自加了东坡肉。纠正后，PR 变成“番茄炒蛋（无东坡肉）”，注释和测试继续解释为什么没有东坡肉；任务写长了，东坡肘子又回来了。

<div align="center">
  <a href="assets/user-story.svg">
    <img src="assets/user-story.svg" width="100%" alt="普通 Agent 会把被否定内容写进交付物，Stop Chatter 只保留当前目标" />
  </a>
</div>

另一个常见版本是：你说“简洁高效就行”，交付物却被命名为“方案 2.0（简洁高效不啰嗦版）”，甚至把“用户不喜欢某个例子”写进长期记忆。

这不是普通的“话多”，而是 **dangling negation（悬空否定）**：对话里已经被否定的内容，没有从工作目标中真正删除，反而泄漏进了最终 artifact。

| 你做了什么 | 常见错误结果 | `stop-chatter` 的目标 |
|---|---|---|
| 删除一个擅自添加的功能 | 标题、注释和 PR 反复声明“无该功能” | 交付物只描述现在存在什么 |
| 要求简洁高效 | 生成“简洁高效版”标签和大段合规说明 | 约束执行方式，不变成产品内容 |
| 长任务中纠正方向 | 相近概念换个名字重新出现 | 连同依赖链和语义别名一起清理 |
| 纠正一次任务 | 被写成跨任务的永久偏好 | 默认只在当前任务生效 |

## 实测 v2：有帮助，但不是效果保证

2026-09-01，ChatterBench 在同一套 `gpt-5.6-luna` / Codex CLI 环境中运行了 **6 个中文纠错场景 × 3 个条件 × 3 次全新重复**，共 **54 次运行、108 个有效 Agent 回合**。其中 5 个场景要求清理；另有 1 个“保留对照”明确要求保留外部兼容性拒绝契约，防止工具靠无脑删除刷分。

<div align="center">
  <a href="assets/benchmark-v2.svg">
    <img src="assets/benchmark-v2.svg" width="100%" alt="ChatterBench v2 数据对比：Baseline 0%，Light 44.4%，Guarded 44.4%，并展示需求保留、残留、范围和成本指标" />
  </a>
</div>

| 模式 | 严格干净交付 | 有效需求保留 | artifact 无残留 | 回复无残留 | 范围干净 | 中位耗时 |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 0/18，0.0%（95% CI 0.0–17.6） | 83.3% | 16.7% | 11.1% | 16.7% | 68.6 秒 |
| Light | 8/18，44.4%（95% CI 24.6–66.3） | 77.8% | 88.9% | 55.6% | 88.9% | 77.2 秒 |
| Guarded | 8/18，44.4%（95% CI 24.6–66.3） | 94.4% | 94.4% | 55.6% | 94.4% | 88.0 秒 |

**数据能说明什么：**Light 与 Guarded 的严格端到端成功率相同。Guarded 更常保住有效需求，也更常做到 artifact 无残留、范围干净，但耗时和 token 成本更高。最终回复仍是主要短板：两种模式都只有 55.6% 的运行做到回复无残留。不同场景差异也很大——Light 在菜谱和 todo 场景为 3/3，Guarded 在三步方案为 3/3，而“看板 + 任务级记忆”场景三种条件都是 0/3。因此它是有用干预，不是可靠兜底。

“严格干净交付”采用两回合全有或全无判定：有效需求、隐藏行为、artifact 残留、回复残留、范围、临时状态和中性续写回归必须全部通过。正式运行从冻结的干净 commit `5f830b4` 启动；54 次运行全部有效，**v2 没有任何人工改分**。原始最终回复、逐项评分、耗时、token、补丁哈希和全部 54 份 patch 都已公开。

这仍是小规模、合成场景、单模型、单宿主评测，不能外推到 Cursor、Claude Code、其他模型、英文任务或真实生产分布。可查看[评测方法](evals/README.md)、[v2 汇总](evals/results/2026-09-01-chatterbench-v2-r3/summary.md)、[机器可读数据](evals/results/2026-09-01-chatterbench-v2-r3/summary.json)、[54 组原始记录](evals/results/2026-09-01-chatterbench-v2-r3/runs/)和[54 份 artifact patch](evals/results/2026-09-01-chatterbench-v2-r3/patches/)。早期[15 组先导实验](evals/results/2026-09-01-codex-luna-pilot/)继续归档，但不与 v2 合并，因为 v2 修正了两处过窄金标，并新增了保留对照。

确定性门禁另用 20 条标注样本评测：代码级 Precision **91.7%**、Recall **84.6%**、F1 **88.0%**。两次漏检来自未配置的语义别名，一次误报来自子串碰撞；这些数字只代表门禁脚本，不代表整个 Skill。

## 它怎么工作

1. **重编译当前目标**：把最新需求写成正向、当前态的目标；撤回项直接删除，不保留成“禁止清单”。
2. **修剪依赖链**：检查被撤回内容可能生成的计划、实现、配置、测试、注释、UI、PR 文案和记忆候选。
3. **追溯每个改动**：每个新增或修改的 artifact 都必须能映射到仍然有效的需求。
4. **隔离过程信息**：纠错史和执行约束留在工作上下文，不进入用户可见产品和长期记忆。

核心原则很简单：

```text
当前正向目标  →  必要实现  →  必要验证  →  用户要的结果
```

## 两种模式

| 模式 | 适用场景 | 增加的机制 |
|---|---|---|
| Light | 一次纠正、小输出、容易人工检查 | 只使用 `SKILL.md` |
| Guarded | 长任务、多文件、Git 改动、曾经反复复活 | 临时目标状态 + 确定性检查器 |

Light 模式保持 Skill 的轻量性。Guarded 模式才会创建任务内临时状态，并在交付前检查可观察的残留；两种模式都不会自动修改全局配置或长期记忆。

## 安装

```bash
git clone https://github.com/OwenBell0930/stop-chatter.git
cd stop-chatter
python3 scripts/install.py --host all --scope project --target /path/to/project
```

这会创建：

- Cursor / Codex：`.agents/skills/stop-chatter`
- Claude Code：`.claude/skills/stop-chatter`

安装器不会覆盖已有目录。按宿主显式调用：

| 宿主 | 调用方式 |
|---|---|
| Cursor | `/stop-chatter` |
| OpenAI Codex | `$stop-chatter` |
| Claude Code | `/stop-chatter` |

也可以只安装单个宿主或安装到用户级目录，详见 [host setup](references/host-setup.md)。

## Guarded 模式：30 秒上手

第一次发生实质性纠正后，初始化任务内状态：

```bash
STOP_CHATTER_SKILL_DIR=.agents/skills/stop-chatter
# Claude Code 项目级安装改为：.claude/skills/stop-chatter
# 用户级安装请使用 host setup 中对应的实际目录
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" init --root .
```

编辑 `.stop-chatter/state.json`：写入当前正向目标、有效需求对应的路径、已撤回概念及必要的语义别名，然后把 `ready` 改为 `true`。模板未填写时，检查器会拒绝产生无意义的通过结果。

```bash
python3 "$STOP_CHATTER_SKILL_DIR/scripts/stop_chatter.py" check --root .
```

默认检查 Git 工作区中已修改和未跟踪的文件。非 Git 流程可传入明确路径；检查暂存区用 `--mode staged`；有边界地扫描整个仓库用 `--mode all`。

完整状态结构与窄例外规则见 [target-state protocol](references/protocol.md)。

## 门禁会报告什么

| Code | 含义 |
|---|---|
| `STC001` | 已撤回词或配置的语义别名仍留在 artifact 中 |
| `STC002` | 改动文件无法映射到任何当前有效需求 |
| `STC003` | “简洁版”等执行约束或合规标签泄漏进 artifact |
| `STC004` | 文件无法被安全检查 |

检查器只负责确定性事实。语义别名由 Skill 根据当前任务提供；脚本不会假装理解任意语义。

## 边界

- 不会自动安装 Hook、修改宿主设置、写入长期记忆或访问网络。
- 不会为了证明“不存在错误扩展”而给业务项目堆一组否定测试；只有外部契约或安全属性明确要求时才保留。
- Light 模式依赖模型遵循 Skill；Guarded 模式只硬检查文件级可见事实，不能拦截所有自然语言输出。
- 门禁通过只证明 artifact 卫生条件通过，不等于业务实现一定正确。

## 验证仓库

```bash
python3 -m unittest discover -s tests -v
```

测试覆盖两类核心回归：被否定内容进入 artifact，以及“简洁高效”等元指令变成 artifact 标签。CI 使用 Python 3.11 运行同一组测试。

## License

[MIT](LICENSE)
