> **⚠️ Merged into [architecture.md](architecture.md)**  
> This glossary was a temporary standalone reference. As of 2026-04-10, all terminology definitions have been merged into the §9 术语速查 section of `architecture.md`. Use `architecture.md` as the single reference for both architecture and terminology. Do not use this file for new implementation.

---

*Original content preserved below for historical reference.*

---

# Yoitsu 术语表

**Status:** Superseded · Merged into architecture.md · **Date:** 2026-04-10
**Original Anchor ADR:** [ADR-0015](adr/0015-bundle-as-repo.md)

本术语表的内容已合并入 [architecture.md](architecture.md) §9。以下是归档时的原始内容。

---

## 1. Bundle

**是什么**：一组为某一类任务服务的可复用资产的**逻辑身份**，以一个稳定的字符串名称标识（例如 `"factorio"`、`"webdev"`）。Bundle 是配置、调度、观测、并发控制的基本单位。

**不是什么**：bundle **不是** URL，**不是**目录，**不是** git 仓库。URL / 目录 / 仓库是 bundle 的"物理化"，可以更换；bundle 名称本身是稳定的逻辑锚点。

## 2. Bundle Repo

**是什么**：承载某个 bundle 的 code-like 内容（roles、tools、contexts、prompts、scripts、lib）的**独立 git 仓库**，是该 bundle 内容的权威来源。每个 bundle 有且仅有一个 bundle repo。

**不是什么**：不是 monorepo 的子目录，不是 submodule，不是 palimpsest 仓库的一部分。Bundle repo 的演化历史完全由它自己承担。

## 3. Bundle Source

**是什么**：一次 job 执行时对 "本次使用的 bundle 是哪个、来自哪、在哪物化" 的运行时描述，形如 `{name, repo_uri, selector, resolved_ref, workspace}`。由 trenni 在派发 job 前生成并通过 JobConfig 传入 palimpsest。`selector` 是配置中声明的分支名或 tag 名；`resolved_ref` 是 trenni 解析出的 commit sha（保证可复现）。

**不是什么**：不是静态配置项。Bundle Source 是 per-job 的运行时产物，每次 job 都会重新生成一个。`resolved_ref` 不是 registry 配置字段——它由 trenni 动态解析。

## 4. Bundle Registry

**是什么**：trenni 配置中按 bundle 名键控的映射，声明每个已知 bundle 的 `source`（repo + selector）、`runtime`、`scheduling` 配置。形如 `bundles: {factorio: {source: {url, selector}, runtime: {...}, scheduling: {...}}}`。`selector` 是分支名或 tag 名（如 `evolve`、`main`）。

**不是什么**：不是一个中央 base 仓库，不是 bundle 内容的任何形式的"发现服务"。Registry 只记录"这个名字对应哪个仓库和哪条分支/tag"。Registry **不**存储 commit sha——那是 per-job 的 resolved_ref。

## 5. Workspace

**是什么**：trenni 为每次 job 准备的 **ephemeral** bundle 仓库 clone，agent 在其中读写文件。Publication 时 commit + push 回 bundle repo，随后 workspace 整体丢弃。

**不是什么**：workspace **永远不是权威**。把 workspace 当长期存储的任何做法（包括曾经的 `workspace_override` 直接 bind mount live 树）都是 bug。Workspace 也不跨 job 复用——per-job 重新 clone 是默认。

## 6. Event Store

**是什么**：系统的**时序 / 因果**权威。它以 append-only 方式记录 "时刻 t 发生了事件 E，事件声明了引用 X"。Pasloe 是其实现。

**不是什么**：Event Store **不**是内容存储，**不**解引用 URI，**不**保证 URI 背后的字节仍然可达。它不持有 bundle 内容、不持有 save 文件、不持有大对象。

## 7. Content Authority

**是什么**：URI scheme 背后的系统，负责某一类引用的字节持久化与可达性。`git+*` 的 content authority 是 git 托管；`file://` 的 content authority 是文件系统；`http(s)://` 的 content authority 是上游服务。

**不是什么**：不存在一个统一的 content authority 模块。Content authority 按 scheme 分布式承担，这是 ADR-0015 相对 ADR-0013（统一 artifact store）最本质的转变。

## 8. Artifact

**是什么**：系统中任何被 event 引用过的持久对象——bundle 仓库快照、Factorio save 文件、日志归档、外部数据集等。Artifact 是**概念**，不是某个存储模块。

**不是什么**：不是 ADR-0013 定义的 `Blob` / `Tree` 实体，不是任何统一 content-addressed store 里的记录。Artifact 的物理形态由其 URI scheme 决定。

## 9. Artifact URI

**是什么**：指向一个 artifact 的字符串引用，scheme 决定解引用方式。ADR-0015 定义的 scheme 集合：`inline:` / `file://` / `git+file://` / `git+ssh://` / `git+https://` / `http(s)://`。`git+*` 支持 `@<sha-or-tag>#<subpath>` 语法定位仓库快照内的具体路径。`@<ref>` 必须是 commit sha 或 tag——**不允许**分支名。

**不是什么**：不是一个结构化对象——它是**单个字符串**。上下文信息（`relation`、`metadata`、`path` for 容器型 ref）由承载该 URI 的事件字段（如 `ArtifactBinding`）提供，不是 URI 本身的一部分。URI 里的 `@<ref>` 与 registry 里的 `selector` 不同——URI.ref 必须是固定值，selector 可以是分支名（由 trenni 解析）。

## 10. Publication

**是什么**：将 workspace 中 agent 产生的变更提交回 bundle repo 的阶段。执行序列：`git add -A` → 变更存在性 gate（§11） → 结构可接受性 gate（§12） → `git commit && git push`。失败则 job 失败。

**不是什么**：publication **不**判断 goal 是否达成。语义层面的判断属于 semantic evaluation（§13），不在 publication 链路上。

## 11. Hallucination Gate（变更存在性 gate）

**是什么**：publication 的第一道检查，等价于 `git diff --cached --quiet` 为假（即 staging 非空）。它只回答"agent 是否真的改了文件"。

**不是什么**：**不**做 whitespace 过滤，**不**做语义判断，**不**关心改得对不对。它唯一的作用是堵住"LLM 声称完成但没调用工具"的 hallucination 路径。

## 12. Structural Guardrail（结构可接受性 gate）

**是什么**：publication 的第二道检查，由 bundle/role 声明的 publication-time 校验，例如 Lua 语法、路径白名单、禁止修改受保护文件、Factorio DYNAMIC 脚本约束。默认为空——只有 bundle 主动声明时才生效。

**不是什么**：**不**是 evaluator 的工作。Structural guardrail 是"这批变更能不能进入仓库"的硬约束，评估发生在 commit 之前；evaluator 评估发生在 commit 之后，只读，不阻断 publication。

## 13. Semantic Evaluation

**是什么**：由 evaluator role 在独立 job 中回答"这批 commit 是否解决了 goal"。读取 bundle repo 的最新状态（或指定 ref），产出评估报告事件。

**不是什么**：**不**在 publication 链路上，**不**阻断 commit，**不**检查"文件是否存在"这类结构性问题。它只关心目标达成度。

## 14. Declared vs Ad-hoc Artifact

**Declared artifact**：在 `bundle.yaml` 的 `artifacts` 字段里静态列出的引用（Factorio save 模板、mod 来源、外部数据集）。Trenni 启动期可索引、可 lint、可做依赖校验。

**Ad-hoc reference**：role 运行时 emit 的未声明 URI 引用，直接出现在 `artifact.published` 事件的 ref 字段中。

**核心区别**：运行时路径上两者完全等价——都是 event 里的 URI 字符串。区别只在**启动期可见性**：declared 可静态扫描，ad-hoc 只能事后从事件流回溯。这让 bundle schema 呈现"接近封闭但允许溢出"的语义。

## 15. Evolve Branch

**是什么**：bundle repo 中专供 agent 演化使用的分支约定，通常命名为 `evolve` 或 `evolve/*`。Agent 的 publication 默认 push 到此类分支，与人类维护的 `main` 分支平行。

**不是什么**：**不**是 ADR 级别的强制约束。Evolve 分支是 convention（约定），具体命名、强制程度由 bundle authoring convention 文档决定，ADR-0015 只推荐其存在。
