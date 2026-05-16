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

    def is_command_allowed(self, command_name: str, event, is_group: bool) -> bool:
        """Check if a command is allowed in the current context."""
        loader = self._plugin.loader
        handler_info = loader.find_handler(command_name, is_group)
        if handler_info is None:
            return True  # Unknown command, let gateway handle rejection

        module_id = handler_info["module"].ModuleId

        if is_group:
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
                return True
            return self.is_module_enabled_in_group(module_id, group_id)
        else:
            return self.is_module_enabled_private(module_id)

    def _get_config_for_module(self, module_id: str) -> dict:
        """Get config entry for a module from the list-based module_settings."""
        config_list = self._plugin.config.get("module_settings", [])
        if not isinstance(config_list, list):
            return {}
        for item in config_list:
            if isinstance(item, dict) and item.get("module_id") == module_id:
                return item
        return {}

    def is_module_enabled_in_group(self, module_id: str, group_id: str) -> bool:
        """Check if a module is enabled in a specific group. Default: enabled.
        Consults both config (_conf_schema.json module_settings) and KV storage."""
        # 1. Check config-based module_settings (higher priority)
        cfg = self._get_config_for_module(module_id)
        if cfg:
            cfg_blocked = list(cfg.get("blocked_groups", []))
            cfg_enabled = list(cfg.get("enabled_groups", []))
            if str(group_id) in [str(g) for g in cfg_blocked]:
                return False
            if cfg_enabled:
                return str(group_id) in [str(g) for g in cfg_enabled]

        # 2. Check KV-stored runtime permissions
        module_perms = self._data.get(module_id, {})
        blocked = module_perms.get("blocked_groups", [])
        if group_id in blocked:
            return False

        enabled = module_perms.get("enabled_groups", None)
        if enabled is not None:
            return group_id in enabled

        return True  # Default: enabled everywhere

    def is_module_enabled_private(self, module_id: str) -> bool:
        """Check if a module is enabled in private chat. Default: enabled."""
        cfg = self._get_config_for_module(module_id)
        if cfg:
            enabled = cfg.get("private_enabled", True)
            if not enabled:
                return False
        return True

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
