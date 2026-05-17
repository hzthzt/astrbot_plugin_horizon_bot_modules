"""
Routes incoming messages to the appropriate C# module command handler.
"""

import os
from typing import Optional

from astrbot.api import logger


class CommandDispatcher:
    def __init__(self, module_loader, permission_manager=None, data_base_path=None):
        self.loader = module_loader
        self.permissions = permission_manager
        self.data_base_path = data_base_path or ""

    def parse_message(self, message_str: str):
        """
        Parse a raw message string into (command_name, args).
        Returns (None, []) if no command found.
        """
        if not message_str or not message_str.strip():
            return None, []
        parts = message_str.strip().split()
        cmd_name = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        return cmd_name, args

    def dispatch(self, command_name: str, args: list, event,
                 is_group: bool, image_path: str = "", image_source: str = ""):
        """
        Find matching C# module handler, build context, call handler, return
        the C# HorizonModuleResult or a fallback dict with Success/Message.
        Returns None if no handler matches.
        """
        handler_info = self.loader.find_handler(command_name, is_group)
        if handler_info is None:
            return None

        try:
            from HorizonBot.Library import HorizonCommandContext
        except ImportError:
            logger.error("HorizonBot.Library not loaded. Is pythonnet installed?")
            return None

        ctx = HorizonCommandContext()
        ctx.CommandName = command_name
        ctx.Args = list(args) if args else []
        ctx.SenderId = str(self._extract_sender_id(event))
        ctx.SenderName = event.get_sender_name() or ""
        ctx.GroupId = str(self._extract_group_id(event)) if is_group else ""
        ctx.IsGroupMessage = is_group
        ctx.ImagePath = image_path or ""
        ctx.ImageSource = image_source or ""

        # Set module data path
        module_id = handler_info["module"].ModuleId
        if self.data_base_path and module_id:
            ctx.DataPath = os.path.join(self.data_base_path, module_id)
        else:
            ctx.DataPath = ""

        descriptor = handler_info["descriptor"]
        try:
            result = descriptor.Handler(ctx)
            return result
        except Exception as e:
            logger.error(
                f"C# module handler error for '{command_name}': {e}"
            )
            # Fallback: return a dict so callers can still format output
            return {"Success": False, "Message": None,
                    "ErrorMessage": f"Internal module error: {e}"}

    @staticmethod
    def _extract_sender_id(event) -> str:
        try:
            return str(event.message_obj.sender.user_id)
        except Exception:
            try:
                return event.get_sender_name()
            except Exception:
                return "unknown"

    @staticmethod
    def _extract_group_id(event) -> str:
        try:
            return str(event.group_id)
        except Exception:
            try:
                return str(event.message_obj.group_id)
            except Exception:
                return "unknown"
