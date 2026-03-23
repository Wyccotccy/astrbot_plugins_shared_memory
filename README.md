# Shared Memory - AstrBot 跨会话记忆共享插件

> 实现 Bot 多会话间的"记忆共享"，支持私聊与群聊互通，让 Bot 记住跨对话的上下文。

## 📋 功能特性

- **跨会话记忆**：Bot 能记住与其他用户的对话，在新对话中自然引用
- **私聊群聊互通**：支持配置私聊和群聊的记忆是否互通
- **多 Bot 隔离**：支持多个 OneBot 实例（多个 QQ 号）数据完全隔离
- **存储模式**：
  - **常规模式**：所有用户共享记忆池（用户 A 私聊的内容，用户 B 能知道）
  - **简洁模式**：每个用户独立记忆（仅本人可见自己的历史）
- **实时注入**：自动将历史记忆注入 LLM 提示词，无需人工干预
- **管理命令**：支持查看、删除、清空记忆，方便管理

## 🚀 安装方法

### 方式一：WebUI 安装（推荐）
1. 下载插件压缩包
2. AstrBot WebUI → 插件管理 → 上传安装
3. 配置插件参数
4. 重载插件

### 方式二：手动安装
```bash
# 进入插件目录
cd /AstrBot/data/plugins/

# 创建插件目录
mkdir shared_memory

# 复制文件到目录
cp main.py _conf_schema.json metadata.yaml shared_memory/

# 重启 AstrBot
```

## ⚙️ 配置说明

在 AstrBot WebUI → 插件管理 → shared_memory → 配置 中修改：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `max_history` | 整数 | 15 | 每个记忆池最大存储的消息条数 |
| `storage_mode` | 字符串 | conventional | 存储模式：`simple`(用户隔离) / `conventional`(共享) |
| `互通_scope` | 字符串 | none | 互通范围：`none`/`private`/`group`/`all` |
| `platform_isolation` | 布尔 | true | 多 OneBot 实例隔离（每个 QQ 号独立数据） |
| `inject_position` | 字符串 | system | 注入位置：`system`(系统提示词) / `user`(用户消息) |
| `debug_mode` | 布尔 | false | 调试模式（日志输出注入前后文本） |
| `cleanup_on_terminate` | 布尔 | false | ⚠️ 停用时自动清理数据（测试用） |

### 互通范围说明

- `none`：私聊和群聊记忆各自独立，互不干扰
- `private`：仅私聊互通（群聊不共享记忆）
- `group`：仅群聊互通（私聊不共享记忆）
- `all`：全部互通（私聊能看到群聊历史，群聊也能看到私聊历史）

## 💬 使用示例

### 常规模式 + 全部互通

```
用户A（私聊）：你好
Bot：你好啊！
（存储：A在私聊说了"你好"）

用户B（私聊）：刚刚谁找你？
Bot看到注入提示：【历史记忆】[03-23 22:50] [私聊] 用户A: 你好 → 你回复: 你好啊
Bot回复：刚刚用户A在跟我打招呼呢！
```

### 简洁模式 + 全部互通

```
用户A（私聊）：待会去群里我给你打招呼，你要给大家打招呼
Bot：好的记住了！
（存储到A的独立记忆文件）

用户A（群聊@Bot）：你好
Bot加载A的私聊记忆，看到之前的约定
Bot回复：大家好！我是来打招呼的！（刚才A私聊让我来的）
```

## 🛠️ 管理命令

仅管理员可用（需配置管理员 QQ 号）：

| 命令 | 用法 | 说明 |
|------|------|------|
| `/memory list` | `/memory list [页码]` | 查看所有记忆列表（分页显示） |
| `/memory delete` | `/memory delete <序号>` | 删除指定序号的记忆 |
| `/memory del_last` | `/memory del_last` | 删除最新的一条记忆 |
| `/memory clear` | `/memory clear confirm` | ⚠️ 清空当前 Bot 所有记忆 |
| `/memory status` | `/memory status` | 查看记忆统计信息 |
| `/memory uninstall` | `/memory uninstall confirm` | 清理数据并准备卸载 |

### 删除记忆示例

```
/memory list
📋 记忆列表 (Bot: 123456789)
第 1/2 页，共 15 条记忆
========================================
1. [03-23 22:50] [共享][私聊] 用户A: 你好...
2. [03-23 22:55] [共享][群聊] 用户B: 大家好...
...

/memory delete 1
✅ 已删除第 1 条记忆 [03-23 22:50] [私聊] 用户A: 你好
```

## 🔄 更新插件

由于 AstrBot 限制，重新安装时需要先删除旧目录：

### 方法1：使用卸载命令（推荐）
```
/memory uninstall confirm
```
然后 SSH 执行：
```bash
rm -rf /AstrBot/data/plugins/shared_memory/
```
再上传新版安装。

### 方法2：开启自动清理（仅测试）
在配置中开启 `cleanup_on_terminate: true`，然后：
- WebUI → 插件管理 → shared_memory → **停用** → **启用**（重载）
- 数据自动清空，然后直接覆盖安装

### 方法3：手动清理
```bash
rm -rf /AstrBot/data/plugins/shared_memory/
rm -rf /AstrBot/data/shared_memory/
```

## 📁 数据存储结构

```
/AstrBot/data/shared_memory/
├── 123456789/              # OneBot 1号（QQ:123456789）
│   ├── private_shared.json # 私聊共享记忆
│   └── group_shared.json   # 群聊共享记忆
├── 987654321/              # OneBot 2号（QQ:987654321）
│   ├── private_shared.json
│   └── group_shared.json
└── ...
```

简洁模式下：
```
123456789/
├── private_user_111.json   # 用户111的私聊记忆
├── private_user_222.json   # 用户222的私聊记忆
└── group_shared.json       # 群聊共享（如果互通）
```

## 📝 日志输出

开启 `debug_mode: true` 后，可在日志中看到：

```
[SharedMemory] ========== 记忆注入开始 ==========
[SharedMemory] [会话] Bot:123456789 | 用户:987654321 | 类型:私聊
[SharedMemory] [注入前] system_prompt长度: 1200
[SharedMemory] [注入内容] 共3条记忆
[SharedMemory] [注入内容详情]: 【历史记忆】...
[SharedMemory] [注入后] system_prompt长度: 1550 (增加350)
[SharedMemory] [状态] 成功注入system(3条) | 全部互通模式 | Bot:123456789 | 用户:987654321 | 类型:私聊
[SharedMemory] ========== 记忆注入结束 ==========
```

## ⚠️ 注意事项

1. **数据安全**：记忆数据以 JSON 形式存储在服务器本地，不包含敏感信息过滤，请确保服务器安全
2. **内存占用**：每个记忆条目包含用户消息和 Bot 回复，建议 `max_history` 不要设置过大（默认15条）
3. **LLM 上下文**：注入的记忆会占用 LLM 的 token 数量，注意控制总上下文长度
4. **多 Bot 隔离**：`platform_isolation` 开启时，不同 OneBot 实例（不同QQ号）的记忆完全隔离
5. **自动清理**：`cleanup_on_terminate` 默认关闭，仅在测试时开启，生产环境务必关闭以免误删数据

## 🐛 故障排查

### 插件加载失败
检查 `_conf_schema.json` 格式是否正确，确保是合法 JSON。

### 记忆未注入
- 检查 `debug_mode` 日志输出
- 确认 `互通_scope` 配置是否符合当前聊天类型
- 确认是否已有存储的记忆（先用 `/memory list` 查看）

### 存储失败
检查 `/AstrBot/data/shared_memory/` 目录权限：
```bash
chmod -R 755 /AstrBot/data/shared_memory/
chown -R $(whoami) /AstrBot/data/shared_memory/
```

## 📜 更新日志

### v1.0.0
- 初始版本发布
- 支持跨会话记忆共享
- 支持私聊/群聊互通配置
- 支持多 OneBot 实例隔离
- 支持记忆管理命令（查看、删除、清空）

## 👤 作者

- **作者**：Wyccotccy
- **项目**：烬熵Cinder QQ 机器人生态
- **协议**：MIT

## 🤝 贡献

欢迎提交 Issue 和 PR。

---

**⚡ 提示**：首次安装后建议先用 `/memory status` 查看状态，确认插件正常工作。
