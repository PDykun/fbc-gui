"""Контроллеры главного окна FBC GUI."""

from ui.controllers.conversion_controller import ConversionController
from ui.controllers.presets_controller import PresetsController
from ui.controllers.preview_controller import PreviewController
from ui.controllers.queue_controller import QueueController
from ui.controllers.settings_controller import SettingsController
from ui.controllers.updates_controller import UpdatesController

__all__ = [
    "ConversionController",
    "PresetsController",
    "PreviewController",
    "QueueController",
    "SettingsController",
    "UpdatesController",
]
