"""
Horizon Bot Modules — AstrBot Plugin
通过 pythonnet 加载和管理 C# Horizon Bot 模块。
"""

import os

from quart import request as quart_request

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .module_loader import ModuleLoader
from .command_dispatcher import CommandDispatcher
from .permission_manager import PermissionManager

VERSION = "1.0.3"


@register(
    "horizon_bot_modules",
    "horizon-bot",
    "通过 pythonnet 加载和管理 C# Horizon Bot 模块",
    VERSION,
)
class HorizonBotModules(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.modules_dir = self._resolve_modules_dir()
        self.command_prefix = self.config.get("command_prefix", "hb")

        self.permissions = PermissionManager(self)
        self.permissions.load()

        self.loader = ModuleLoader(self.modules_dir)
        self.dispatcher = CommandDispatcher(self.loader, self.permissions)

        self._register_pages()
        self._register_apis()

        self._load_modules()

    async def terminate(self):
        self.loader.unload_all()
        logger.info("HorizonBotModules 已关闭。")

    # === LLM 拦截 ===

    @filter.on_waiting_llm_request()
    async def _intercept_slash_commands(self, event: AstrMessageEvent):
        """拦截以 '/' 开头的消息，阻止其发送给大模型。"""
        # AstrBot strips leading '/' from message_str, check raw message chain
        raw_text = ""
        try:
            for comp in event.message_obj.message:
                text = getattr(comp, "text", None)
                if text:
                    raw_text += text
        except Exception:
            pass
        msg = raw_text.strip() or (event.message_str or "").strip()
        logger.info(f"[斜杠拦截] raw={raw_text!r} message_str={event.message_str!r}")
        if msg.startswith("/"):
            logger.info(f"已拦截斜杠命令: {msg[:80]}")
            event.stop_event()

    # === AstrBot 命令处理 ===

    @filter.command("hb")
    async def _gateway(self, event: AstrMessageEvent):
        """Horizon Bot 网关。用法: /hb <模块命令> [参数]"""
        message_str = self._strip_command(event, self.command_prefix)
        if not message_str:
            yield event.plain_result(
                f"Horizon Bot 模块系统 v{VERSION}\n"
                "用法: /hb <命令> [参数]\n"
                "/hb version  查看版本\n"
                "/hb help     查看可用命令"
            )
            return

        command_name, args = self.dispatcher.parse_message(message_str)
        if command_name is None:
            yield event.plain_result("未知命令。输入 /hb help 查看可用命令。")
            return

        is_group = self._is_group_message(event)

        if not self.permissions.is_command_allowed(command_name, event, is_group):
            yield event.plain_result(
                "此命令在当前群不可用。" if is_group else "此命令在私聊中不可用。"
            )
            return

        result = self.dispatcher.dispatch(command_name, args, event, is_group)

        if result is None:
            yield event.plain_result(f"未知命令: {command_name}")
            return

        msg = getattr(result, "Message", None)
        if msg is None and isinstance(result, dict):
            msg = result.get("Message")
        err = getattr(result, "ErrorMessage", None)
        if err is None and isinstance(result, dict):
            err = result.get("ErrorMessage")

        if err:
            yield event.plain_result(str(err))
        elif msg is not None:
            yield event.plain_result(str(msg))

    @filter.command("hb_version")
    async def _version(self, event: AstrMessageEvent):
        """显示插件和模块的版本信息。"""
        lines = ["=== Horizon Bot Modules ==="]
        lines.append(f"插件版本: v{VERSION}")

        # Library version
        try:
            import clr
            import System.Reflection
            for asm in System.AppDomain.CurrentDomain.GetAssemblies():
                name = asm.GetName()
                if name.Name == "HorizonBot.Library":
                    lines.append(f"SDK 版本: v{name.Version}")
                    break
        except Exception:
            pass

        # .NET runtime
        try:
            import System
            lines.append(f".NET 运行时: {System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription}")
        except Exception:
            pass

        # Loaded modules
        modules = self.loader.get_modules()
        lines.append(f"已加载模块: {len(modules)}")
        for mid, module in modules.items():
            lines.append(f"  [{mid}] {module.ModuleName} v{module.ModuleVersion}")

        yield event.plain_result("\n".join(lines))

    @filter.command("hb_reload")
    async def _reload(self, event: AstrMessageEvent):
        """管理命令: 从磁盘重载所有 C# 模块。"""
        if not self._is_admin(event):
            yield event.plain_result("权限不足。")
            return

        self._load_modules()
        count = self.loader.module_count()
        yield event.plain_result(f"已重载 {count} 个模块。")

    @filter.command("hb_list")
    async def _list_modules(self, event: AstrMessageEvent):
        """列出所有已加载的 C# 模块。"""
        modules = self.loader.get_modules()
        if not modules:
            yield event.plain_result("没有已加载的模块。")
            return

        lines = ["=== 已加载的 Horizon Bot 模块 ==="]
        for mid, module in modules.items():
            lines.append(
                f"  [{mid}] {module.ModuleName} v{module.ModuleVersion}"
                f" by {module.ModuleAuthor}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("hb_enable")
    async def _enable(self, event: AstrMessageEvent):
        """管理命令: 在当前群启用模块。用法: /hb_enable <模块ID>"""
        if not self._is_admin(event):
            yield event.plain_result("权限不足。")
            return

        module_id = self._strip_command(event, "hb_enable")
        if not module_id:
            yield event.plain_result("用法: /hb_enable <模块ID>")
            return
        if module_id not in self.loader.get_modules():
            yield event.plain_result(f"未知模块: {module_id}")
            return

        group_id = self._extract_group_id_for_admin(event)
        if not group_id:
            yield event.plain_result("此命令需要在群聊中使用。")
            return

        self.permissions.enable_module_in_group(module_id, group_id)
        yield event.plain_result(f"模块 '{module_id}' 已在群 {group_id} 中启用。")

    @filter.command("hb_disable")
    async def _disable(self, event: AstrMessageEvent):
        """管理命令: 在当前群禁用模块。用法: /hb_disable <模块ID>"""
        if not self._is_admin(event):
            yield event.plain_result("权限不足。")
            return

        module_id = self._strip_command(event, "hb_disable")
        if not module_id:
            yield event.plain_result("用法: /hb_disable <模块ID>")
            return
        if module_id not in self.loader.get_modules():
            yield event.plain_result(f"未知模块: {module_id}")
            return

        group_id = self._extract_group_id_for_admin(event)
        if not group_id:
            yield event.plain_result("此命令需要在群聊中使用。")
            return

        self.permissions.disable_module_in_group(module_id, group_id)
        yield event.plain_result(f"模块 '{module_id}' 已在群 {group_id} 中禁用。")

    # === 插件页面与 API ===

    def _register_pages(self):
        """AstrBot 自动扫描 pages/ 目录发现页面，无需手动注册。"""

    def _register_apis(self):
        """注册页面所需的 API 端点。"""
        pname = getattr(self, "name", "horizon_bot_modules")
        self.context.register_web_api(
            f"/{pname}/api/modules", self._api_list_modules, ["GET"],
            "列出已安装的模块"
        )
        self.context.register_web_api(
            f"/{pname}/api/toggle", self._api_toggle_module, ["POST"],
            "切换模块启用/禁用"
        )
        self.context.register_web_api(
            f"/{pname}/api/reload", self._api_reload_modules, ["POST"],
            "重载模块"
        )

    async def _api_list_modules(self):
        """返回已加载模块列表 + modules 目录中未加载的 DLL 文件名。"""
        try:
            modules = self.loader.get_modules()
        except Exception as e:
            logger.error(f"获取模块列表失败: {e}")
            return {"modules": [], "files": [], "error": str(e)}

        result = []
        for mid, module in modules.items():
            try:
                result.append({
                    "id": mid,
                    "name": module.ModuleName or mid,
                    "version": module.ModuleVersion or "",
                    "author": module.ModuleAuthor or "",
                    "enabled": self.permissions.is_module_enabled_private(mid),
                })
            except Exception as e:
                logger.error(f"读取模块 {mid} 信息失败: {e}")
                result.append({
                    "id": mid, "name": mid, "version": "",
                    "author": "", "enabled": True,
                })

        # Scan for DLL files that are not already loaded
        files = []
        loaded_names = {f"{mid}.dll" for mid in modules}
        # Also match by stripping common prefixes
        def _dll_module_id(filename):
            name = filename.replace(".dll", "")
            # HorizonBot.DemoModule -> demo
            parts = name.split(".")
            return parts[-1] if len(parts) > 1 else name

        loaded_simple = {_dll_module_id(f"{mid}.dll") for mid in modules}
        loaded_simple.add("horizonbot.library")

        if os.path.isdir(self.modules_dir):
            for f in sorted(os.listdir(self.modules_dir)):
                if not f.endswith(".dll"):
                    continue
                if f == "HorizonBot.Library.dll":
                    continue
                simple = f.replace(".dll", "").lower()
                if simple in loaded_simple:
                    continue  # Already loaded
                files.append(f)

        return {"modules": result, "files": files}

    async def _api_toggle_module(self):
        """切换模块的启用/禁用（全局，影响私聊）。"""
        try:
            body = await quart_request.get_json()
        except Exception:
            return {"success": False, "error": "无效的请求体"}
        module_id = body.get("module_id", "")
        enabled = body.get("enabled", True)

        if module_id not in self.loader.get_modules():
            return {"success": False, "error": f"模块 {module_id} 不存在"}

        # Toggle via config-based module_settings
        cfg_list = self.config.get("module_settings", [])
        if not isinstance(cfg_list, list):
            cfg_list = []
        found = False
        for item in cfg_list:
            if isinstance(item, dict) and item.get("module_id") == module_id:
                item["private_enabled"] = bool(enabled)
                found = True
                break
        if not found:
            cfg_list.append({
                "module_id": module_id,
                "blocked_groups": [],
                "enabled_groups": [],
                "private_enabled": bool(enabled),
            })

        # Save config
        self.config["module_settings"] = cfg_list
        try:
            self.config.save_config()
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return {"success": False, "error": str(e)}

        self.permissions.load()
        return {"success": True, "module_id": module_id, "enabled": enabled}

    async def _api_reload_modules(self):
        """重载所有模块。"""
        self._load_modules()
        return {"success": True, "count": self.loader.module_count()}

    # === 内部方法 ===

    def _strip_command(self, event: AstrMessageEvent, cmd: str) -> str:
        """从消息中去掉命令前缀，返回参数部分。"""
        raw = event.message_str.strip()
        # Strip leading /
        if raw.startswith("/"):
            raw = raw[1:]
        # Strip the command word
        if raw.startswith(cmd):
            raw = raw[len(cmd):]
        return raw.strip()

    def _load_modules(self):
        logger.info(f"正在加载 C# 模块，路径: {self.modules_dir}")
        self.loader.load_all()
        logger.info(f"已加载 {self.loader.module_count()} 个模块")

    def _resolve_modules_dir(self) -> str:
        cfg_path = self.config.get("modules_directory", "")
        if cfg_path and os.path.isabs(cfg_path):
            return cfg_path
        # Default: plugin_data/horizon_bot_modules/modules/ (persists across reinstalls)
        base = get_astrbot_plugin_data_path()
        if not cfg_path or cfg_path in ("./modules", ".", "modules", "./"):
            base = os.path.join(base, "horizon_bot_modules", "modules")
        else:
            base = os.path.join(base, cfg_path)
        os.makedirs(base, exist_ok=True)
        return os.path.abspath(base)

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        admins = self.config.get("admins", [])
        sender = event.get_sender_name()
        if sender in admins:
            return True
        sender_id = self._extract_sender_id_str(event)
        return sender_id in admins

    def _extract_sender_id_str(self, event: AstrMessageEvent) -> str:
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            return ""

    @staticmethod
    def _is_group_message(event: AstrMessageEvent) -> bool:
        try:
            return bool(event.group_id)
        except Exception:
            pass
        try:
            return bool(event.message_obj.group_id)
        except Exception:
            pass
        return False

    @staticmethod
    def _extract_group_id_for_admin(event: AstrMessageEvent) -> str:
        try:
            return str(event.group_id)
        except Exception:
            pass
        try:
            return str(event.message_obj.group_id)
        except Exception:
            pass
        return ""
