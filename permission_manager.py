"""
Permission manager: per-group module enable/disable with KV storage.
"""

import json

from astrbot.api import logger


class PermissionManager:
    KEY = "horizon_bot_module_permissions"

    def __init__(self, plugin_instance):
        self._plugin = plugin_instance
        self._data = {}

    def load(self):
        try:
            raw = self._plugin.get_kv_data(self.KEY)
            if raw:
                self._data = json.loads(raw)
        except Exception:
            self._data = {}

    def save(self):
        try:
            self._plugin.put_kv_data(
                self.KEY, json.dumps(self._data, ensure_ascii=False)
            )
        except Exception as e:
            logger.error(f"Failed to save permissions: {e}")

    def is_command_allowed(self, command_name: str, event) -> bool:
        """Check if a command is allowed in the current group context."""
        loader = self._plugin.loader
        group_id = None
        try:
            group_id = str(event.group_id)
        except Exception:
            pass
        if not group_id:
            try:
                group_id = str(event.message_obj.group_id)
            except Exception:
                pass
        if not group_id:
            return True  # Can't determine group, allow

        # Find which module owns this command
        handler_info = loader.find_handler(command_name, True)
        if handler_info is None:
            return True  # Unknown command, let gateway handle rejection

        module_id = handler_info["module"].ModuleId
        return self.is_module_enabled_in_group(module_id, group_id)

    def is_module_enabled_in_group(self, module_id: str, group_id: str) -> bool:
        """Check if a module is enabled in a specific group. Default: enabled."""
        module_perms = self._data.get(module_id, {})
        blocked = module_perms.get("blocked_groups", [])
        if group_id in blocked:
            return False

        enabled = module_perms.get("enabled_groups", None)
        if enabled is not None:
            return group_id in enabled

        return True  # Default: enabled everywhere

    def enable_module_in_group(self, module_id: str, group_id: str):
        perms = self._data.setdefault(module_id, {})
        perms.setdefault("enabled_groups", [])
        if group_id not in perms["enabled_groups"]:
            perms["enabled_groups"].append(group_id)
        perms.setdefault("blocked_groups", [])
        if group_id in perms["blocked_groups"]:
            perms["blocked_groups"].remove(group_id)
        self.save()

    def disable_module_in_group(self, module_id: str, group_id: str):
        perms = self._data.setdefault(module_id, {})
        perms.setdefault("blocked_groups", [])
        if group_id not in perms["blocked_groups"]:
            perms["blocked_groups"].append(group_id)
        perms.setdefault("enabled_groups", [])
        if group_id in perms["enabled_groups"]:
            perms["enabled_groups"].remove(group_id)
        self.save()

    def get_module_status(self, module_id: str) -> dict:
        return self._data.get(module_id, {})
