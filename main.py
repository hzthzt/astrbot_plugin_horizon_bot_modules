"""
Horizon Bot Modules — AstrBot Plugin
通过 pythonnet 加载和管理 C# Horizon Bot 模块。
"""

import os

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import AstrBotConfig, logger

from .module_loader import ModuleLoader
from .command_dispatcher import CommandDispatcher
from .permission_manager import PermissionManager


@register(
    "horizon_bot_modules",
    "horizon-bot",
    "通过 pythonnet 加载和管理 C# Horizon Bot 模块",
    "1.0.0",
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

        self._load_modules()

    async def terminate(self):
        self.loader.unload_all()
        logger.info("HorizonBotModules 已关闭。")

    # === LLM 拦截 ===

    @filter.on_llm_request()
    async def _intercept_slash_commands(self, event: AstrMessageEvent):
        """拦截以 '/' 开头的消息，阻止其发送给大模型。"""
        message_str = event.message_str.strip()
        if message_str.startswith("/"):
            logger.info(f"已拦截斜杠命令: {message_str[:80]}")
            event.stop_event()

    # === AstrBot 命令处理 ===

    @filter.command("hb")
    async def _gateway(self, event: AstrMessageEvent):
        """Horizon Bot 网关。用法: /hb <模块命令> [参数]"""
        message_str = event.message_str.strip()
        if not message_str:
            yield event.plain_result(
                "Horizon Bot 模块系统\n"
                "用法: /hb <命令> [参数]\n"
                "输入 /hb help 查看可用命令"
            )
            return

        command_name, args = self.dispatcher.parse_message(message_str)
        if command_name is None:
            yield event.plain_result("未知命令。输入 /hb help 查看可用命令。")
            return

        is_group = self._is_group_message(event)

        if is_group and not self.permissions.is_command_allowed(
            command_name, event
        ):
            yield event.plain_result("此命令在当前群不可用。")
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

        parts = event.message_str.strip().split()
        if len(parts) < 1:
            yield event.plain_result("用法: /hb_enable <模块ID>")
            return

        module_id = parts[0]
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

        parts = event.message_str.strip().split()
        if len(parts) < 1:
            yield event.plain_result("用法: /hb_disable <模块ID>")
            return

        module_id = parts[0]
        if module_id not in self.loader.get_modules():
            yield event.plain_result(f"未知模块: {module_id}")
            return

        group_id = self._extract_group_id_for_admin(event)
        if not group_id:
            yield event.plain_result("此命令需要在群聊中使用。")
            return

        self.permissions.disable_module_in_group(module_id, group_id)
        yield event.plain_result(f"模块 '{module_id}' 已在群 {group_id} 中禁用。")

    # === 内部方法 ===

    def _load_modules(self):
        logger.info(f"正在加载 C# 模块，路径: {self.modules_dir}")
        self.loader.load_all()
        logger.info(f"已加载 {self.loader.module_count()} 个模块")

    def _resolve_modules_dir(self) -> str:
        cfg_path = self.config.get("modules_directory", "./modules")
        if cfg_path and not os.path.isabs(cfg_path):
            cfg_path = os.path.join(os.path.dirname(__file__), cfg_path)
        return os.path.abspath(cfg_path)

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
