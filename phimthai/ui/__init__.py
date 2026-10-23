"""Decoupled page widgets. They expose Qt signals/setters and never import phimthai.app."""
from .diagnostics_page import Check, DiagnosticsPage
from .models_page import ModelsPage
from .settings_page import SettingsPage
from .wizard import SetupWizard

__all__ = ["Check", "DiagnosticsPage", "ModelsPage", "SettingsPage", "SetupWizard"]
