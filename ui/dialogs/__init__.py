"""Диалоговые окна FBC GUI, разбитые по функциональным модулям."""

from ui.dialogs.common import (
    _format_bytes_human,
    ask_themed_text,
    show_conversion_summary_dialog,
    show_themed_confirm,
    show_themed_message,
    show_update_dialog,
)
from ui.dialogs.progress import (
    ConversionProgressDialog,
    ImportProgressDialog,
)
from ui.dialogs.setup_update import (
    FbcSetupDialog,
    UpdateDownloadDialog,
)
from ui.dialogs.inspector import BookInspectorDialog
from ui.dialogs.organizer import OrganizeBooksDialog
from ui.dialogs.metadata_lookup import MetadataLookupDialog
from ui.dialogs.book_edit import (
    BatchEditDialog,
    BookEditDialog,
)
from ui.dialogs.watch_folder import WatchFolderRuleDialog

__all__ = [
    "_format_bytes_human",
    "ask_themed_text",
    "show_conversion_summary_dialog",
    "show_themed_confirm",
    "show_themed_message",
    "show_update_dialog",
    "ConversionProgressDialog",
    "ImportProgressDialog",
    "FbcSetupDialog",
    "UpdateDownloadDialog",
    "BookInspectorDialog",
    "OrganizeBooksDialog",
    "MetadataLookupDialog",
    "BatchEditDialog",
    "BookEditDialog",
    "WatchFolderRuleDialog",
]
