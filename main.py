"""
Horizon Bot Modules — AstrBot Plugin
Loads and manages C# Horizon Bot modules via pythonnet.
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
    "Load and manage C# Horizon Bot modules via pythonnet",
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
        """Called when plugin is unloaded. Shut down all C# modules."""
        for module in self.loader.get_modules().values():
            try:
                module.Shutdown()
            except Exception as e:
                logger.error(f"Error shutting down module {module.ModuleId}: {e}")
        logger.info("HorizonBotModules shut down.")

    # === LLM Interception ===

    @filter.on_llm_request()
    async def _intercept_slash_commands(self, event: AstrMessageEvent):
        """Block messages starting with '/' from reaching the LLM."""
        message_str = event.message_str.strip()
        if message_str.startswith("/"):
            logger.info(f"Intercepted slash command from LLM: {message_str[:80]}")
            event.stop_event()

    # === AstrBot Command Handlers ===

    @filter.command("hb")
    async def _gateway(self, event: AstrMessageEvent):
        """Horizon Bot gateway. Usage: /hb <module_command> [args]"""
        message_str = event.message_str.strip()
        if not message_str:
            yield event.plain_result(
                "Horizon Bot Module System\n"
                "Usage: /hb <command> [args]\n"
                "Type /hb help for available commands"
            )
            return

        command_name, args = self.dispatcher.parse_message(message_str)
        if command_name is None:
            yield event.plain_result(
                "Unknown command. Type /hb help for available commands."
            )
            return

        is_group = self._is_group_message(event)

        # Permission check for group messages
        if is_group and not self.permissions.is_command_allowed(
            command_name, event
        ):
            yield event.plain_result(
                "This command is not available in this group."
            )
            return

        result = self.dispatcher.dispatch(command_name, args, event, is_group)

        if result is None:
            yield event.plain_result(f"Unknown command: {command_name}")
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
        """Admin command: reload all C# modules from disk."""
        if not self._is_admin(event):
            yield event.plain_result("Permission denied.")
            return

        self._load_modules()
        count = self.loader.module_count()
        yield event.plain_result(f"Reloaded {count} module(s).")

    @filter.command("hb_list")
    async def _list_modules(self, event: AstrMessageEvent):
        """List all loaded C# modules."""
        modules = self.loader.get_modules()
        if not modules:
            yield event.plain_result("No modules loaded.")
            return

        lines = ["=== Loaded Horizon Bot Modules ==="]
        for mid, module in modules.items():
            lines.append(
                f"  [{mid}] {module.ModuleName} v{module.ModuleVersion}"
                f" by {module.ModuleAuthor}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("hb_enable")
    async def _enable(self, event: AstrMessageEvent):
        """Admin command: enable a module in a group. Usage: /hb_enable <module_id>"""
        if not self._is_admin(event):
            yield event.plain_result("Permission denied.")
            return

        parts = event.message_str.strip().split()
        if len(parts) < 1:
            yield event.plain_result("Usage: /hb_enable <module_id>")
            return

        module_id = parts[0]
        if module_id not in self.loader.get_modules():
            yield event.plain_result(f"Unknown module: {module_id}")
            return

        group_id = self._extract_group_id_for_admin(event)
        if not group_id:
            yield event.plain_result("This command must be used in a group.")
            return

        self.permissions.enable_module_in_group(module_id, group_id)
        yield event.plain_result(
            f"Module '{module_id}' enabled in group {group_id}."
        )

    @filter.command("hb_disable")
    async def _disable(self, event: AstrMessageEvent):
        """Admin command: disable a module in a group. Usage: /hb_disable <module_id>"""
        if not self._is_admin(event):
            yield event.plain_result("Permission denied.")
            return

        parts = event.message_str.strip().split()
        if len(parts) < 1:
            yield event.plain_result("Usage: /hb_disable <module_id>")
            return

        module_id = parts[0]
        if module_id not in self.loader.get_modules():
            yield event.plain_result(f"Unknown module: {module_id}")
            return

        group_id = self._extract_group_id_for_admin(event)
        if not group_id:
            yield event.plain_result("This command must be used in a group.")
            return

        self.permissions.disable_module_in_group(module_id, group_id)
        yield event.plain_result(
            f"Module '{module_id}' disabled in group {group_id}."
        )

    # === Internal ===

    def _load_modules(self):
        logger.info(f"Loading C# modules from: {self.modules_dir}")
        self.loader.load_all()
        logger.info(f"Loaded {self.loader.module_count()} module(s)")

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
