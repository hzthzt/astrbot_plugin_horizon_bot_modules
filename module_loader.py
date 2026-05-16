"""
Module loader: discovers and loads C# HorizonBot module DLLs via pythonnet.
Uses isolated AssemblyLoadContext for clean unload and file lock release.
"""

import os
import sys
from typing import Dict, Optional


class ModuleLoader:
    def __init__(self, modules_dir: str = None):
        self._modules_dir = modules_dir
        self._modules: Dict[str, "HorizonModuleEntry"] = {}
        self._commands: Dict[str, dict] = {}
        self._loaded = False

    def load_all(self) -> int:
        # Unload old modules first to release file locks
        self.unload_all()

        if not self._modules_dir or not os.path.isdir(self._modules_dir):
            self._loaded = True
            return 0

        if self._modules_dir not in sys.path:
            sys.path.insert(0, self._modules_dir)

        self._ensure_library_loaded()

        loaded = 0
        for filename in sorted(os.listdir(self._modules_dir)):
            if not filename.endswith(".dll"):
                continue
            if filename == "HorizonBot.Library.dll":
                continue
            dll_path = os.path.join(self._modules_dir, filename)
            try:
                self._load_dll(dll_path)
                loaded += 1
            except Exception as e:
                from astrbot.api import logger
                logger.error(f"加载模块 DLL 失败 {filename}: {e}")

        self._loaded = True
        return loaded

    def unload_all(self):
        """Shutdown all modules and unload their AssemblyLoadContexts."""
        if not self._modules:
            return

        from astrbot.api import logger
        from HorizonBot.Library import ModuleLoaderHelper

        # Call Shutdown on each module first
        for mid, module in list(self._modules.items()):
            try:
                module.Shutdown()
            except Exception as e:
                logger.error(f"关闭模块失败 {mid}: {e}")

        # Unload all isolated contexts via C# helper (releases file locks)
        try:
            ModuleLoaderHelper.UnloadAll()
        except Exception as e:
            logger.error(f"卸载 AssemblyLoadContext 失败: {e}")

        self._modules.clear()
        self._commands.clear()

    def _ensure_library_loaded(self):
        lib_path = os.path.join(self._modules_dir, "HorizonBot.Library.dll")
        if not os.path.exists(lib_path):
            return
        import clr
        try:
            clr.AddReference(lib_path)
        except Exception:
            pass

    def _load_dll(self, dll_path: str):
        from HorizonBot.Library import ModuleLoaderHelper

        module = ModuleLoaderHelper.LoadIsolated(dll_path)
        if module is None:
            from astrbot.api import logger
            logger.warning(f"DLL 中未找到 HorizonModuleEntry 子类: {dll_path}")
            return

        self._register_module(module, dll_path)

    def _register_module(self, module: "HorizonModuleEntry", dll_path: str):
        mid = module.ModuleId
        if not mid:
            from astrbot.api import logger
            logger.warning(f"跳过 ID 为空的模块: {dll_path}")
            return
        if mid in self._modules:
            from astrbot.api import logger
            logger.warning(f"跳过重复模块 ID '{mid}': {dll_path}")
            return

        self._modules[mid] = module

        for cmd in module.GetPrivateCommands():
            key = f"private:{cmd.CommandName}"
            self._commands[key] = {"module": module, "descriptor": cmd}

        for cmd in module.GetGroupCommands():
            key = f"group:{cmd.CommandName}"
            self._commands[key] = {"module": module, "descriptor": cmd}

        from astrbot.api import logger
        logger.info(
            f"已加载模块: {module.ModuleName} v{module.ModuleVersion}"
            f" ({mid}) by {module.ModuleAuthor}"
        )

    def find_handler(self, command_name: str, is_group: bool) -> Optional[dict]:
        prefix = "group" if is_group else "private"
        return self._commands.get(f"{prefix}:{command_name}")

    def get_modules(self) -> Dict[str, "HorizonModuleEntry"]:
        return dict(self._modules)

    def module_count(self) -> int:
        return len(self._modules)

    def get_module_ids(self):
        return sorted(self._modules.keys())
