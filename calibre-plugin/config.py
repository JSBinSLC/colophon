"""Plugin preferences — LLM model and API keys."""
from calibre.utils.config import JSONConfig
from qt.core import QCheckBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

prefs = JSONConfig("plugins/colophon")
prefs.defaults["llm_model"] = "anthropic/claude-haiku-4-5"
prefs.defaults["anthropic_api_key"] = ""
prefs.defaults["openai_api_key"] = ""
prefs.defaults["openrouter_api_key"] = ""
prefs.defaults["backup_original"] = True
prefs.defaults["persist_graph"] = True
prefs.defaults["rebuild_graph"] = False
prefs.defaults["host_colophon_repo"] = ""
prefs.defaults["host_python"] = ""


class ConfigWidget(QWidget):
    def __init__(self):
        QWidget.__init__(self)
        layout = QVBoxLayout()
        self.setLayout(layout)

        intro = QLabel(
            "Requires Calibre 9.5+. Structural repair (TOC, HTML, CSS, fonts) "
            "works without any API key.\n"
            "For AI features — proper noun detection, semantic graph, smarter "
            "text cleanup — configure a cloud model and its API key below. If "
            "you're using paid AI, keep Calibre up to date."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        layout.addLayout(form)

        self.model = QLineEdit(self)
        self.model.setText(prefs["llm_model"])
        self.model.setPlaceholderText("openrouter/google/gemini-2.5-flash")
        form.addRow("LLM model:", self.model)

        self.anthropic_key = QLineEdit(self)
        self.anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key.setText(prefs["anthropic_api_key"])
        form.addRow("Anthropic API key:", self.anthropic_key)

        self.openai_key = QLineEdit(self)
        self.openai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key.setText(prefs["openai_api_key"])
        form.addRow("OpenAI API key:", self.openai_key)

        self.openrouter_key = QLineEdit(self)
        self.openrouter_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.openrouter_key.setText(prefs["openrouter_api_key"])
        form.addRow("OpenRouter API key:", self.openrouter_key)

        layout.addWidget(QLabel("Repair options:"))

        self.backup_original = QCheckBox(
            "Keep a backup of the original EPUB in the book's colophon/ folder",
            self,
        )
        self.backup_original.setChecked(bool(prefs["backup_original"]))
        layout.addWidget(self.backup_original)

        self.persist_graph = QCheckBox(
            "Save the semantic knowledge graph (book_graph.json) for future repairs",
            self,
        )
        self.persist_graph.setChecked(bool(prefs["persist_graph"]))
        layout.addWidget(self.persist_graph)

        self.rebuild_graph = QCheckBox(
            "Rebuild the knowledge graph on each repair (ignore cached graph)",
            self,
        )
        self.rebuild_graph.setChecked(bool(prefs["rebuild_graph"]))
        layout.addWidget(self.rebuild_graph)

        future = QLabel(
            "The knowledge graph lists characters, places, and variant spellings — "
            "useful for proofreading today and a foundation for future features "
            "(chapter summaries, series consistency, etc.)."
        )
        future.setWordWrap(True)
        layout.addWidget(future)

    def save_settings(self):
        prefs["llm_model"] = self.model.text().strip() or prefs.defaults["llm_model"]
        prefs["anthropic_api_key"] = self.anthropic_key.text().strip()
        prefs["openai_api_key"] = self.openai_key.text().strip()
        prefs["openrouter_api_key"] = self.openrouter_key.text().strip()
        prefs["backup_original"] = self.backup_original.isChecked()
        prefs["persist_graph"] = self.persist_graph.isChecked()
        prefs["rebuild_graph"] = self.rebuild_graph.isChecked()


def build_pipeline_config():
    """Map plugin prefs to a Colophon PipelineConfig."""
    from colophon.config import LLMConfig, OutputConfig, PipelineConfig

    llm = LLMConfig(model=prefs["llm_model"], reconcile=True)
    if prefs["anthropic_api_key"]:
        llm.api_key = prefs["anthropic_api_key"]
    elif prefs["openai_api_key"]:
        llm.api_key = prefs["openai_api_key"]
    elif prefs["openrouter_api_key"]:
        llm.api_key = prefs["openrouter_api_key"]

    return PipelineConfig(
        llm=llm,
        output=OutputConfig(persist_graph=bool(prefs["persist_graph"])),
        rebuild_graph=bool(prefs["rebuild_graph"]),
        interactive=False,
    )