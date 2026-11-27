"""Контроллеры главного окна FBC GUI."""

from ui.controllers.conversion_controller import ConversionController
from ui.controllers.library_controller import LibraryController
from ui.controllers.presets_controller import PresetsController
from ui.controllers.preview_controller import PreviewController
from ui.controllers.queue_controller import QueueController
from ui.controllers.settings_controller import SettingsController
from ui.controllers.tray_controller import TrayWatchController
from ui.controllers.updates_controller import UpdatesController

__all__ = [
    "ConversionController",
    "LibraryController",
    "PresetsController",
    "PreviewController",
    "QueueController",
    "SettingsController",
    "TrayWatchController",
    "UpdatesController",
]
