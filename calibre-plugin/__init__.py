"""Colophon — AI-assisted EPUB repair (Calibre interface plugin)."""
from calibre.customize import InterfaceActionBase


class ColophonPlugin(InterfaceActionBase):
    name = "Colophon EPUB Repair"
    description = (
        "Repair EPUB structure, navigation, OCR artifacts, and proper nouns "
        "using the Colophon pipeline. Cloud AI (optional) improves name detection."
    )
    supported_platforms = ["windows", "osx", "linux"]
    author = "JSBinSLC"
    version = (0, 1, 0)
    minimum_calibre_version = (6, 0, 0)

    actual_plugin = "calibre_plugins.colophon.ui:ColophonAction"

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.colophon.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
        ac = self.actual_plugin_
        if ac is not None:
            ac.apply_settings()