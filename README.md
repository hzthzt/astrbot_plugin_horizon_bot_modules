# Horizon Bot Modules

基于 pythonnet 加载和管理 C# Horizon Bot 模块的 AstrBot 插件。

**当前版本: v1.0.1** | 发送 `/hb version` 查看运行中版本

## 更新日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.1 | 2026-05-16 | 添加 `/hb version` 命令；隔离模块加载（AssemblyLoadContext），关闭插件时正确释放 DLL 文件锁；拦截斜杠命令防止发送给大模型 |
| v1.0.0 | 2026-05-16 | 初始版本：pythonnet 加载 C# 模块，网关命令分发，群权限管理 |

## 环境要求

- AstrBot v4.0+
- .NET Runtime 6.0+（64 位）
- Python 3.10+（64 位）
- `pythonnet>=3.0.0`

## 安装

### 通过 AstrBot 插件市场

在 AstrBot WebUI 的插件管理中搜索 `horizon_bot_modules` 安装。

### 手动安装

1. 将本目录复制到 AstrBot 的插件目录（`data/plugins/`）中。
2. 安装依赖：`pip install pythonnet>=3.0.0`
3. 重启 AstrBot 或重载插件。

## 使用

```
/hb version           查看插件及模块版本
/hb help              显示可用命令
/hb ping              测试连接
/hb echo <文本>        回显文本
/hb about             显示模块信息
```

### 管理命令

```
/hb_reload            重载所有 C# 模块
/hb_list              列出已加载的模块
/hb_enable <id>       在当前群启用模块
/hb_disable <id>      在当前群禁用模块
```

## 配置

参见 `_conf_schema.json`：
- `modules_directory` — C# DLL 目录（默认：`./modules`）
- `command_prefix` — 网关前缀（默认：`hb`）
- `admins` — 管理员用户名/ID

## 模块开发

C# 模块 SDK 及开发文档请见 [horizon-bot](https://github.com/example/horizon-bot) 仓库。
