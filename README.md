# agent-context-bridge

在 **DSH / Codex（ChatGPT）、Claude Code** 之间同步同一个项目的对话上下文与进度。

> 5 小时额度用完了想换工具继续，但新 agent 不知道之前聊过什么、项目做到哪一步了 ——
> 这个技能把三家的会话记录读出来，合成一份可以直接塞进上下文的项目速览。

---

## 1. 它解决什么问题

同一个项目里同时用三个 agent 时，三家的对话互相看不见：

```
Codex 里聊完方案  ──►  额度用完  ──►  换 DSH 继续
                                     ▲
                                     └──  DSH 只有自己的记录：方案在哪？改到哪了？下一步是什么？
```

`agentlink` 直接把三家的本地会话记录读出来（不联网、不上传），按项目归并成：

- **当前任务**：最近几条用户请求
- **各 agent 的最近对话**：每个会话里用户问了什么、助手最后说了什么
- **待办**：从对话和显式 note 里提取的未完成项
- **决定与约束**：已经拍板的结论
- **项目快照**：git 分支、最近提交、未提交改动

换到任一 agent 后，只要它读一次 `.agentlink/context.md`（或跑一次 `agentlink brief`），
就能接着干。

---

## 2. 快速开始

```powershell
# 1) 依赖（只需要读 DSH 的 zstd 压缩会话时用得到）
D:\PythonEnv\python.exe -m pip install zstandard

# 2) 把技能装进三家（复制 SKILL.md + 生成启动器）
D:\PythonEnv\python.exe -m agentlink install

# 3) 在项目里初始化并生成第一份速览
cd F:\path\to\your-project
agentlink init
agentlink brief
```

`brief` 的输出就是交给 agent 的上下文。之后无论在哪个工具里，都可以：

```
agentlink sync      # 抓取新增对话
agentlink brief     # 看项目速览
```

---

## 3. 在三个工具里怎么用

### DSH

技能装到 `%USERPROFILE%\.dsh\skills\agent-context-bridge\`，新开会话后技能目录里就能看到。
直接说「用 agent-context-bridge 同步一下上下文」，或手动跑 `agentlink brief`。

### Codex / ChatGPT（桌面端）

技能装到 `%USERPROFILE%\.codex\skills\agent-context-bridge\`。
Codex 的会话记录在 `%USERPROFILE%\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`，
本工具按 `session_meta.cwd` 判断是否属于当前项目。

### Claude Code

技能装到 `%USERPROFILE%\.claude\skills\agent-context-bridge\`。
会话记录在 `%USERPROFILE%\.claude\projects\<项目路径转义>\*.jsonl`。
（本机如果还没装 Claude Code，这个目录会在你首次使用后自动出现，技能已提前装好。）

### 让它自动想起来（可选）

```powershell
agentlink hook
```

在项目根的 `AGENTS.md`（DSH、Codex 读）和 `CLAUDE.md`（Claude 读）里写入一段带标记的提示，
新会话一开始就会看到「先读 `.agentlink/context.md`」。移除用 `agentlink hook --remove`。

---

## 4. 命令参考

| 命令 | 说明 |
| --- | --- |
| `agentlink init` | 在项目里创建 `.agentlink/`，探测三家历史会话 |
| `agentlink sync` | 增量抽取新记录，刷新 `context.md`（`--json` 供程序用） |
| `agentlink brief` | 打印项目速览；默认先 sync，`--no-sync` 只看已有记录 |
| `agentlink brief --budget 8000` | 限制速览长度（按显示宽度，中文算 2） |
| `agentlink status` | 三家数据源是否可用、各有几个会话、上次同步时间 |
| `agentlink show --session <id>` | 查原始记录；支持 `--agent` `--role` `--limit` `--full` |
| `agentlink note "..." --kind todo` | 写人工进度，三方共享（`note`/`todo`/`decision`/`done`） |
| `agentlink handoff --to claude` | 生成 `.agentlink/HANDOFF.md` 交接文件 |
| `agentlink hook` | 写入/刷新 `AGENTS.md`、`CLAUDE.md` 的提示段 |
| `agentlink install` | 安装技能到三家；`--path` 顺带把 `bin/` 加进用户 PATH |
| `agentlink doctor` | 自检：Python、zstandard、git、会话目录、技能安装状态 |

通用参数：`--root <项目根>`、`--agent dsh,codex,claude`、`--budget`、`--max-events`。

---

## 5. 工作原理

```
~/.dsh/sessions/<--munge-->/session-*/session.v4.jsonl.zstd   ← zstd + JSONL
~/.codex/sessions/**/rollout-*.jsonl                          ← JSONL，追加写
~/.claude/projects/<munge>/*.jsonl                            ← JSONL，追加写
        │
        ├─ 按会话头里的 cwd 认领项目（同一台机器上多个项目互不干扰）
        ├─ 增量读取：字节偏移 / 记录序号（DSH 用 seq，因为 zstd 会整文件重写）
        ├─ 归一化成 Event(agent, session, role, text, ts, kind)
        └─ .agentlink/journal.jsonl  →  digest  →  context.md
```

几个刻意的设计：

- **不调用任何大模型**：摘要靠规则（最近请求、结论/待办关键词、git 快照），
  零成本、可复现、离线可用。
- **完全本地**：只读三家的会话文件，不发请求，不写云端。
- **增量**：第二次 `sync` 只读新增的字节/序号，几万条记录的项目也是秒级。
- **有预算**：速览按显示宽度裁剪，默认 24000（约合 8k tokens），可 `--budget` 调整。

### 项目状态目录

```
<项目根>/.agentlink/
├── config.json      # 参与同步的 agent、速览预算、git 开关
├── state.json       # 每个会话文件的读取游标、会话标题、已见记录
├── journal.jsonl    # 归一化后的全部记录（可删，删了会重建）
├── notes.jsonl      # `agentlink note` 写入的人工进度
├── context.md       # 生成的速览（agent 直接读这个）
└── HANDOFF.md       # `handoff` 生成的交接文件
```

`.agentlink/.gitignore` 默认忽略该目录，不会把本地对话记录提交到仓库。

---

## 6. 隐私

- 只在**本机**读取会话文件；除 `pip install` 外没有任何网络请求。
- `.agentlink/` 默认被 git 忽略，里面的对话摘要不会被推送。
- 分享项目时如果担心历史泄露，直接删掉 `.agentlink/` 即可，它随时可以重建。
- 想换一个状态目录（比如放到别的盘）：设置环境变量 `AGENTLINK_STATE_DIR`。

---

## 7. 本机安装清单（这台 Windows 机器）

| 内容 | 位置 |
| --- | --- |
| Python | `D:\PythonEnv\python.exe`（3.12.15） |
| `zstandard` 依赖 | 装进 `D:\PythonEnv\Lib\site-packages` |
| 源码仓库（本仓库） | `F:\development\skills` |
| 启动器 | `F:\development\skills\bin\agentlink.cmd` |
| DSH 技能 | `%USERPROFILE%\.dsh\skills\agent-context-bridge\` |
| Codex 技能 | `%USERPROFILE%\.codex\skills\agent-context-bridge\` |
| Claude 技能 | `%USERPROFILE%\.claude\skills\agent-context-bridge\` |
| 项目状态 | `<项目根>\.agentlink\`（每个项目一份） |

不需要 C 盘空间：依赖在 D 盘，代码与启动器在 F 盘。

---

## 8. 常见问题

**Q：`agentlink` 提示找不到命令？**
读安装到技能目录里的 `LOCAL.md`，里面写着本机启动器的绝对路径；或者把
`F:\development\skills\bin` 加到 PATH（`agentlink install --path` 会自动做）。

**Q：某一家显示"0 个会话"？**
说明那个项目在该工具里的工作目录和当前目录不一致。常见原因：Codex 里打开的是子目录、
项目挪过位置。用 `agentlink sync --root <当时的目录>` 试一次，或在该目录下运行。

**Q：报 `zstandard` 缺失？**
DSH 的会话是 zstd 压缩的：`D:\PythonEnv\python.exe -m pip install zstandard`。
没装也不影响读取 Codex / Claude。

**Q：速览太长 / 太短？**
`agentlink brief --budget 12000`。冲突时以仓库和 `git log` 为准，速览只是对话线索。

**Q：会不会把别的项目的数据混进来？**
不会：只认会话记录里 `cwd` 属于当前项目（含子目录）的会话。

---

## 9. 开发

```powershell
# 直接跑源码
$env:PYTHONPATH = "F:\development\skills\src"
D:\PythonEnv\python.exe -m agentlink doctor

# 测试（离线，使用临时目录造的假会话，不碰真实数据）
D:\PythonEnv\python.exe -m unittest discover -s tests -v
```

代码结构：

```
src/agentlink/
├── cli.py          # 命令行入口
├── store.py        # .agentlink/ 状态、游标、journal、notes
├── sources/        # 三家解析器：dsh.py / codex.py / claude.py
├── digest.py       # 速览生成（分节、关键词提取、预算裁剪）
├── gitinfo.py      # git 快照
└── install.py      # 安装到三家技能目录、写提示段
```

---

## 10. 已知边界

- 会话格式是各家的内部实现，升级客户端后可能变化；解析器对未知记录一律跳过，
  不会因为多出一种记录类型就崩掉。
- 只做"文本级"摘要，不做语义理解；重要结论建议顺手 `agentlink note` 写一条。
- 同一项目如果被复制到两个路径，会被当成两个项目（按 cwd 匹配）。

## License

MIT