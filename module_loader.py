"""
Module loader: discovers and loads C# HorizonBot module DLLs via pythonnet.
"""

import os
import sys
from typing import Dict, Optional


class ModuleLoader:
    def __init__(self, modules_dir: str = None):
        self._modules_dir = modules_dir
        self._modules: Dict[str, "HorizonModuleEntry"] = {}
        self._commands: Dict[str, dict] = {}
        self._assemblies = []
        self._loaded = False

    def load_all(self) -> int:
        self._modules.clear()
        self._commands.clear()
        self._assemblies.clear()

        if not self._modules_dir or not os.path.isdir(self._modules_dir):
            self._loaded = True
            return 0

        # Ensure modules_dir is on sys.path for pythonnet resolution
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
                logger.error(f"Failed to load module DLL {filename}: {e}")

        self._loaded = True
        return loaded

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
        import clr
        import System

        clr.AddReference(dll_path)
        asm = System.Reflection.Assembly.LoadFrom(dll_path)
        self._assemblies.append(asm)

        from HorizonBot.Library import HorizonModuleEntry

        for t in asm.GetTypes():
            if not t.IsAbstract and t.IsSubclassOf(HorizonModuleEntry):
                module = System.Activator.CreateInstance(t)
                module.Init()
                self._register_module(module, dll_path)
                break  # One module class per DLL

    def _register_module(self, module: "HorizonModuleEntry", dll_path: str):
        mid = module.ModuleId
        if not mid:
            from astrbot.api import logger
            logger.warning(f"Skipping module with empty ID: {dll_path}")
            return
        if mid in self._modules:
            from astrbot.api import logger
            logger.warning(f"Skipping duplicate module ID '{mid}': {dll_path}")
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
            f"Loaded module: {module.ModuleName} v{module.ModuleVersion}"
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
