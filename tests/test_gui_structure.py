"""GUI package structure (#123 split): every submodule imports and App composes correctly.

These run WITHOUT a display (no Tk() instantiation) — they guard the refactor's wiring:
imports resolve, the mixins compose, and the full method surface is present on App.
"""
import importlib

import pytest

GUI_SUBMODULES = [
    "syncthing_manager.gui",
    "syncthing_manager.gui.common",
    "syncthing_manager.gui.app",
    "syncthing_manager.gui.settings",
    "syncthing_manager.gui.page_connect",
    "syncthing_manager.gui.page_folder",
    "syncthing_manager.gui.page_devices",
    "syncthing_manager.gui.page_names",
    "syncthing_manager.gui.page_topology",
    "syncthing_manager.gui.page_execute",
]

# Every method the monolithic App exposed must still be on the composed App.
EXPECTED_METHODS = [
    "__init__", "_center_dialog", "_build_header", "_open_settings", "_build_footer",
    "_cw", "_update_steps", "_show", "_on_next", "_on_back", "_post", "_drain", "_status",
    "_unlock_modal", "_idle_reset", "_setup_idle_lock", "_lock_now",
    "_page_connect", "_page_folder", "_page_discover", "_page_rename",
    "_open_change_preview", "_build_change_preview", "_page_topology", "_page_execute",
]


@pytest.mark.parametrize("mod", GUI_SUBMODULES)
def test_submodule_imports(mod):
    importlib.import_module(mod)


def test_app_has_full_method_surface():
    from syncthing_manager.gui import App
    missing = [m for m in EXPECTED_METHODS if not callable(getattr(App, m, None))]
    assert not missing, f"App is missing methods after the split: {missing}"


def test_app_composes_all_mixins():
    from syncthing_manager.gui import App
    from syncthing_manager.gui.settings import SettingsMixin
    from syncthing_manager.gui.page_connect import ConnectPageMixin
    from syncthing_manager.gui.page_folder import FolderPageMixin
    from syncthing_manager.gui.page_devices import DiscoverPageMixin
    from syncthing_manager.gui.page_names import NamesPageMixin
    from syncthing_manager.gui.page_topology import TopologyPageMixin
    from syncthing_manager.gui.page_execute import ExecutePageMixin
    for mixin in (SettingsMixin, ConnectPageMixin, FolderPageMixin, DiscoverPageMixin,
                  NamesPageMixin, TopologyPageMixin, ExecutePageMixin):
        assert issubclass(App, mixin)


def test_main_is_callable():
    from syncthing_manager.gui import main
    assert callable(main)
