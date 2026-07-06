from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import webbrowser
from importlib import import_module
from dataclasses import asdict, dataclass
from typing import Any

import minecraft_launcher_lib
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


MINECRAFT_DIRECTORY = minecraft_launcher_lib.utils.get_minecraft_directory()
DEFAULT_VERSIONS = ["1.21", "1.20.1", "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9"]
LOADERS = ["Vanilla", "Fabric", "Forge", "NeoForge", "OptiFine"]
APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
CONFIG_DIRECTORY = os.path.join(APPDATA, "LarpLauncher")
PROFILES_PATH = os.path.join(CONFIG_DIRECTORY, "profiles.json")
PROFILE_DIRECTORIES = os.path.join(CONFIG_DIRECTORY, "profile_directories")
MICROSOFT_REDIRECT_URI = "http://localhost"
MICROSOFT_CLIENT_ID = "4e70895d-7499-46b2-9358-a664f3422909"


def safe_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "._-" else "-" for character in value)
    return cleaned.strip(".-_") or "profile"


def profile_directory(profile_id: str, profile_name: str) -> str:
    return os.path.join(PROFILE_DIRECTORIES, f"{safe_name(profile_name)}-{profile_id[:8]}")


@dataclass(frozen=True)
class LaunchSettings:
    version: str
    loader: str
    username: str
    ram_gb: int
    minecraft_directory: str
    auth_mode: str
    ms_client_id: str
    ms_redirect_uri: str
    ms_refresh_token: str


@dataclass
class LauncherProfile:
    id: str
    name: str
    version: str
    loader: str
    username: str
    ram_gb: int
    directory: str
    auth_mode: str = "Offline"
    ms_client_id: str = ""
    ms_redirect_uri: str = MICROSOFT_REDIRECT_URI
    ms_refresh_token: str = ""


class LauncherWorker(QObject):
    progress = Signal(int)
    progress_text = Signal(str)
    status = Signal(str)
    log = Signal(str)
    microsoft_profile = Signal(dict)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, settings: LaunchSettings) -> None:
        super().__init__()
        self.settings = settings
        self._max_progress = 100
        self._last_status = "Installing"

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("Preparing Minecraft files...")
            version_id = self._install_selected_version()
            self.status.emit("Building launch command...")
            command = self._build_command(version_id)

            self.status.emit("Launching Minecraft...")
            self.log.emit("Starting Java process.")
            subprocess.Popen(command, cwd=self.settings.minecraft_directory)
            self.status.emit("Minecraft launched.")
            self.progress.emit(100)
            self.progress_text.emit("Complete")
            self.finished.emit()
        except Exception as exc:  # noqa: BLE001 - surface backend failures to the GUI.
            self.failed.emit(str(exc))

    def _install_selected_version(self) -> str:
        callbacks = self._callbacks()
        loader = self.settings.loader

        if loader == "Vanilla":
            self.log.emit(f"Installing Minecraft {self.settings.version}.")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.settings.version,
                self.settings.minecraft_directory,
                callback=callbacks,
            )
            return self.settings.version

        if loader in {"Fabric", "Forge", "NeoForge"}:
            return self._install_mod_loader(loader.lower())

        if loader == "OptiFine":
            return self._find_existing_optifine_profile()

        raise RuntimeError(f"Unsupported loader: {loader}")

    def _install_mod_loader(self, loader_id: str) -> str:
        loader_name = {"fabric": "Fabric", "forge": "Forge", "neoforge": "NeoForge"}[loader_id]
        try:
            mod_loader_module = import_module("minecraft_launcher_lib.mod_loader")
            mod_loader = mod_loader_module.get_mod_loader(loader_id)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{loader_name} is not available in this minecraft-launcher-lib install: {exc}") from exc

        if not mod_loader.is_minecraft_version_supported(self.settings.version):
            raise RuntimeError(f"{loader_name} does not support Minecraft {self.settings.version}.")
        self.log.emit(f"Installing {loader_name} for Minecraft {self.settings.version}.")
        installed_version = mod_loader.install(
            self.settings.version,
            self.settings.minecraft_directory,
            callback=self._callbacks(),
        )
        self.log.emit(f"Using installed profile: {installed_version}")
        return installed_version

    def _find_existing_optifine_profile(self) -> str:
        self.log.emit("Looking for an existing OptiFine profile.")
        version_id = self._find_installed_loader_version("optifine", required=False)
        if version_id:
            return version_id
        raise RuntimeError(
            "OptiFine cannot be installed by minecraft-launcher-lib. Install OptiFine into this "
            "profile folder first, then launch the matching OptiFine profile."
        )

    def _callbacks(self) -> dict[str, Any]:
        return {
            "setStatus": self._set_status,
            "setProgress": self._set_progress,
            "setMax": self._set_max,
        }

    def _set_status(self, value: str) -> None:
        if value:
            self._last_status = value
            self.status.emit(value)
            self.log.emit(value)

    def _set_progress(self, value: int) -> None:
        if self._max_progress <= 0:
            self.progress.emit(0)
            self.progress_text.emit("Preparing...")
            return
        self.progress.emit(max(0, min(100, int(value / self._max_progress * 100))))
        self.progress_text.emit(self._format_progress(value, self._max_progress))

    def _set_max(self, value: int) -> None:
        self._max_progress = max(1, value)
        self.progress_text.emit(self._format_progress(0, self._max_progress))

    def _format_progress(self, value: int, maximum: int) -> str:
        if maximum >= 1024 * 1024:
            current_mb = value / 1024 / 1024
            total_mb = maximum / 1024 / 1024
            return f"{current_mb:.1f} MB / {total_mb:.1f} MB"
        return f"{value} / {maximum} items"

    def _build_command(self, version_id: str) -> list[str]:
        offline_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{self.settings.username}").hex
        username = self.settings.username
        user_uuid = offline_uuid
        token = "0"

        if self.settings.auth_mode == "Microsoft":
            if not self.settings.ms_client_id:
                raise RuntimeError("Microsoft auth needs an Azure application Client ID.")
            if not self.settings.ms_refresh_token:
                raise RuntimeError("Microsoft auth is selected, but this profile is not logged in yet.")
            microsoft_account = import_module("minecraft_launcher_lib.microsoft_account")
            self.status.emit("Refreshing Microsoft session...")
            response = microsoft_account.complete_refresh(
                self.settings.ms_client_id,
                None,
                self.settings.ms_redirect_uri or None,
                self.settings.ms_refresh_token,
            )
            self.microsoft_profile.emit(dict(response))
            username = response["name"]
            user_uuid = response["id"]
            token = response["access_token"]

        options = {
            "username": username,
            "uuid": user_uuid,
            "token": token,
            "jvmArguments": [f"-Xmx{self.settings.ram_gb}G", f"-Xms{min(1, self.settings.ram_gb)}G"],
            "gameDirectory": self.settings.minecraft_directory,
        }
        return minecraft_launcher_lib.command.get_minecraft_command(
            version_id,
            self.settings.minecraft_directory,
            options,
        )

    def _find_installed_loader_version(
        self,
        loader: str,
        backend_version: str | None = None,
        required: bool = True,
    ) -> str:
        versions_directory = os.path.join(self.settings.minecraft_directory, "versions")
        if not os.path.isdir(versions_directory):
            if not required:
                return ""
            raise RuntimeError("The Minecraft versions directory was not created.")

        version_ids = [
            name
            for name in os.listdir(versions_directory)
            if os.path.isdir(os.path.join(versions_directory, name))
        ]
        loader_lower = loader.lower()
        candidates = [
            version_id
            for version_id in version_ids
            if loader_lower in version_id.lower()
            and (
                self.settings.version in version_id
                or (backend_version is not None and backend_version in version_id)
            )
        ]

        if not candidates:
            if not required:
                return ""
            raise RuntimeError(f"{loader.capitalize()} installed, but no matching launcher profile was found.")

        candidates.sort(
            key=lambda version_id: os.path.getmtime(os.path.join(versions_directory, version_id)),
            reverse=True,
        )
        selected = candidates[0]
        self.log.emit(f"Using installed profile: {selected}")
        return selected


class VersionLoader(QObject):
    loaded = Signal(list)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            versions = minecraft_launcher_lib.utils.get_version_list()
            release_ids = [item["id"] for item in versions if item.get("type") == "release"]
            self.loaded.emit(release_ids or DEFAULT_VERSIONS)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class CreateProfileDialog(QDialog):
    def __init__(self, versions: list[str], username: str, ram_gb: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Profile")
        self.setModal(True)
        self.setMinimumWidth(420)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Profile name")

        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.addItems(versions or DEFAULT_VERSIONS)

        self.loader_combo = QComboBox()
        self.loader_combo.addItems(LOADERS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        form.addWidget(QLabel("Name"), 0, 0)
        form.addWidget(self.name_input, 0, 1)
        form.addWidget(QLabel("Version"), 1, 0)
        form.addWidget(self.version_combo, 1, 1)
        form.addWidget(QLabel("Software"), 2, 0)
        form.addWidget(self.loader_combo, 2, 1)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._username = username
        self._ram_gb = ram_gb

    def profile(self) -> LauncherProfile:
        name = self.name_input.text().strip()
        version = self.version_combo.currentText().strip()
        loader = self.loader_combo.currentText()
        if not name:
            name = f"{loader} {version}"
        profile_id = uuid.uuid4().hex
        return LauncherProfile(
            id=profile_id,
            name=name,
            version=version,
            loader=loader,
            username=self._username,
            ram_gb=self._ram_gb,
            directory=profile_directory(profile_id, name),
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LarpLauncher")
        self.setMinimumSize(980, 620)

        self.launch_thread: QThread | None = None
        self.version_thread: QThread | None = None
        self.available_versions = list(DEFAULT_VERSIONS)
        self.profiles = self._load_profiles()

        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._profile_selected)

        self.create_profile_button = QPushButton("+ Create")
        self.create_profile_button.clicked.connect(self.create_profile)

        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.clicked.connect(self.open_current_profile_folder)

        self.save_profile_button = QPushButton("Save Profile")
        self.save_profile_button.clicked.connect(self.save_current_profile)

        self.delete_profile_button = QPushButton("Delete")
        self.delete_profile_button.clicked.connect(self.delete_current_profile)

        self.version_combo = QComboBox()
        self.version_combo.setEditable(True)
        self.version_combo.addItems(DEFAULT_VERSIONS)

        self.loader_combo = QComboBox()
        self.loader_combo.addItems(LOADERS)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Offline username")
        self.username_input.setText(self._default_username())

        self.auth_combo = QComboBox()
        self.auth_combo.addItems(["Offline", "Microsoft"])
        self.auth_combo.currentTextChanged.connect(self._auth_mode_changed)

        self.microsoft_login_button = QPushButton("Login Microsoft")
        self.microsoft_login_button.clicked.connect(self.login_microsoft)

        self.ram_slider = QSlider(Qt.Orientation.Horizontal)
        self.ram_slider.setMinimum(2)
        self.ram_slider.setMaximum(16)
        self.ram_slider.setSingleStep(1)
        self.ram_slider.setPageStep(2)
        self.ram_slider.setValue(4)
        self.ram_label = QLabel("4 GB")

        self.launch_button = QPushButton("Launch")
        self.launch_button.setObjectName("launchButton")
        self.launch_button.setMinimumHeight(48)
        self.launch_button.clicked.connect(self.launch)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_label = QLabel("Idle")
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)

        self.user_panel = QFrame()
        self.user_panel.setObjectName("panel")
        self.user_panel.setVisible(False)

        self.welcome_label = QLabel("")
        self.welcome_label.setObjectName("welcomeLabel")
        self.login_button = QPushButton("Login Microsoft")
        self.login_button.clicked.connect(self.login_microsoft)
        self.logout_button = QPushButton("Logout")
        self.logout_button.clicked.connect(self.logout_microsoft)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Install and launch details will appear here.")

        self.ram_slider.valueChanged.connect(self._update_ram_label)

        self._build_layout()
        self._apply_styles()
        self.open_folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self._ensure_default_profile()
        self._refresh_profile_list()
        self._update_user_panel()
        self._auth_mode_changed(self.auth_combo.currentText())
        self._load_versions()

    def _build_layout(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(12)

        profiles_title = QLabel("Profiles")
        profiles_title.setObjectName("sectionTitle")
        sidebar_layout.addWidget(profiles_title)
        sidebar_layout.addWidget(self.profile_list, 1)
        sidebar_layout.addWidget(self.create_profile_button)
        sidebar_layout.addWidget(self.open_folder_button)
        sidebar_layout.addWidget(self.delete_profile_button)

        content = QFrame()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(26, 24, 26, 24)
        content_layout.setSpacing(18)

        title = QLabel("LarpLauncher")
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel("Build a profile, install the files, and jump in.")
        subtitle.setObjectName("subtitle")

        user_layout = QHBoxLayout(self.user_panel)
        user_layout.setContentsMargins(12, 10, 12, 10)
        user_layout.setSpacing(10)
        avatar = QLabel("👤")
        avatar.setObjectName("avatarLabel")
        user_layout.addWidget(avatar)
        user_text = QVBoxLayout()
        user_text.setContentsMargins(0, 0, 0, 0)
        user_text.setSpacing(2)
        user_text.addWidget(self.welcome_label)
        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)
        buttons_row.addWidget(self.login_button)
        buttons_row.addWidget(self.logout_button)
        user_text.addLayout(buttons_row)
        user_layout.addLayout(user_text, 1)

        form = QFrame()
        form.setObjectName("panel")
        form_layout = QGridLayout(form)
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setHorizontalSpacing(18)
        form_layout.setVerticalSpacing(16)

        form_layout.addWidget(QLabel("Minecraft Version"), 0, 0)
        form_layout.addWidget(self.version_combo, 0, 1)
        form_layout.addWidget(QLabel("Software"), 1, 0)
        form_layout.addWidget(self.loader_combo, 1, 1)
        form_layout.addWidget(QLabel("Username"), 2, 0)
        form_layout.addWidget(self.username_input, 2, 1)
        form_layout.addWidget(QLabel("Account"), 3, 0)
        form_layout.addWidget(self.auth_combo, 3, 1)
        form_layout.addWidget(QLabel("Microsoft Login"), 4, 0)
        form_layout.addWidget(self.microsoft_login_button, 4, 1)
        form_layout.addWidget(QLabel("RAM Allocation"), 5, 0)

        ram_row = QHBoxLayout()
        ram_row.addWidget(self.ram_slider)
        ram_row.addWidget(self.ram_label)
        form_layout.addLayout(ram_row, 5, 1)

        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.progress_label)

        action_row = QHBoxLayout()
        action_row.addWidget(self.save_profile_button)
        action_row.addWidget(self.launch_button, 1)

        content_layout.addWidget(title)
        content_layout.addWidget(subtitle)
        content_layout.addWidget(self.user_panel)
        content_layout.addWidget(form)
        content_layout.addLayout(action_row)
        content_layout.addLayout(progress_row)
        content_layout.addWidget(self.status_label)
        content_layout.addWidget(self.log_output, 1)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

    def _default_username(self) -> str:
        try:
            return os.getlogin()
        except OSError:
            return os.environ.get("USERNAME") or "Player"

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QDialog {
                background: #090d12;
            }
            QLabel {
                color: #dbe7f3;
                font-size: 14px;
            }
            QLabel#subtitle {
                color: #7f91a6;
                font-size: 15px;
            }
            QLabel#sectionTitle {
                color: #f6fbff;
                font-size: 18px;
                font-weight: 800;
            }
            QLabel#welcomeLabel {
                color: #f6fbff;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#avatarLabel {
                font-size: 24px;
            }
            QFrame#sidebar, QFrame#content, QFrame#panel {
                background: #111821;
                border: 1px solid #203040;
                border-radius: 8px;
            }
            QFrame#content {
                background: #0f151d;
            }
            QComboBox, QLineEdit {
                min-height: 38px;
                border: 1px solid #2a3b4d;
                border-radius: 7px;
                padding: 4px 11px;
                background: #0b1118;
                color: #eef6ff;
                selection-background-color: #2f80ed;
                font-size: 14px;
            }
            QComboBox:focus, QLineEdit:focus {
                border-color: #44d7b6;
            }
            QComboBox QAbstractItemView {
                background: #101822;
                color: #eef6ff;
                border: 1px solid #2a3b4d;
                selection-background-color: #244b67;
            }
            QListWidget {
                background: #0b1118;
                border: 1px solid #223246;
                border-radius: 8px;
                color: #dbe7f3;
                outline: none;
                padding: 6px;
            }
            QListWidget::item {
                min-height: 42px;
                border-radius: 6px;
                padding: 8px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background: #18364a;
                color: #ffffff;
            }
            QPushButton {
                background: #172232;
                border: 1px solid #2b4056;
                border-radius: 7px;
                color: #eef6ff;
                min-height: 36px;
                padding: 0 14px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #203247;
                border-color: #44d7b6;
            }
            QPushButton:disabled {
                color: #718096;
                background: #111821;
                border-color: #1d2937;
            }
            QPushButton#launchButton {
                background: #18a999;
                border: none;
                color: #04100f;
                font-size: 17px;
                font-weight: 900;
            }
            QPushButton#launchButton:hover {
                background: #22c7b5;
            }
            QProgressBar {
                min-height: 20px;
                border: 1px solid #2a3b4d;
                border-radius: 7px;
                text-align: center;
                background: #0b1118;
                color: #dbe7f3;
            }
            QProgressBar::chunk {
                border-radius: 6px;
                background: #44d7b6;
            }
            QSlider::groove:horizontal {
                height: 6px;
                border-radius: 3px;
                background: #243244;
            }
            QSlider::sub-page:horizontal {
                border-radius: 3px;
                background: #44d7b6;
            }
            QSlider::handle:horizontal {
                width: 18px;
                height: 18px;
                margin: -6px 0;
                border-radius: 9px;
                background: #eef6ff;
                border: 2px solid #44d7b6;
            }
            QTextEdit {
                border: 1px solid #203040;
                border-radius: 8px;
                background: #080c11;
                padding: 10px;
                color: #a9f5df;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QDialogButtonBox QPushButton {
                min-width: 92px;
            }
            """
        )

    def _load_profiles(self) -> list[LauncherProfile]:
        try:
            with open(PROFILES_PATH, "r", encoding="utf-8") as file:
                payload = json.load(file)
            profiles = []
            for raw_profile in payload.get("profiles", []):
                profile_id = raw_profile.get("id") or uuid.uuid4().hex
                profile_name = raw_profile.get("name") or "Profile"
                raw_profile["id"] = profile_id
                raw_profile["name"] = profile_name
                raw_profile.setdefault("version", "1.20.1")
                raw_profile.setdefault("loader", "Vanilla")
                raw_profile.setdefault("username", self._default_username())
                raw_profile.setdefault("ram_gb", 4)
                raw_profile.setdefault("directory", profile_directory(profile_id, profile_name))
                raw_profile.setdefault("auth_mode", "Offline")
                raw_profile.setdefault("ms_client_id", "")
                raw_profile.setdefault("ms_redirect_uri", MICROSOFT_REDIRECT_URI)
                raw_profile.setdefault("ms_refresh_token", "")
                allowed_keys = LauncherProfile.__dataclass_fields__.keys()
                profiles.append(LauncherProfile(**{key: raw_profile[key] for key in allowed_keys}))
            return profiles
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _save_profiles(self) -> None:
        os.makedirs(CONFIG_DIRECTORY, exist_ok=True)
        with open(PROFILES_PATH, "w", encoding="utf-8") as file:
            json.dump({"profiles": [asdict(profile) for profile in self.profiles]}, file, indent=2)

    def _ensure_default_profile(self) -> None:
        if self.profiles:
            return
        profile_id = uuid.uuid4().hex
        self.profiles.append(
            LauncherProfile(
                id=profile_id,
                name="Default",
                version="1.20.1",
                loader="Vanilla",
                username=self._default_username(),
                ram_gb=4,
                directory=profile_directory(profile_id, "Default"),
            )
        )
        self._save_profiles()

    def _refresh_profile_list(self, selected_id: str | None = None) -> None:
        current_id = selected_id or self._current_profile_id()
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for profile in self.profiles:
            item = QListWidgetItem(f"{profile.name}\n{profile.loader} {profile.version}")
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.profile_list.addItem(item)
            if profile.id == current_id:
                self.profile_list.setCurrentItem(item)
        if self.profile_list.currentRow() < 0 and self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)
        self.profile_list.blockSignals(False)
        self._apply_current_profile()

    def _current_profile_id(self) -> str | None:
        item = self.profile_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _current_profile(self) -> LauncherProfile | None:
        profile_id = self._current_profile_id()
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    @Slot()
    def create_profile(self) -> None:
        dialog = CreateProfileDialog(
            self.available_versions,
            self.username_input.text().strip() or self._default_username(),
            self.ram_slider.value(),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dialog.profile()
        if not profile.version:
            QMessageBox.warning(self, "Missing Version", "Choose a Minecraft version for the profile.")
            return
        self.profiles.append(profile)
        self._save_profiles()
        self._refresh_profile_list(profile.id)

    @Slot()
    def open_current_profile_folder(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        os.makedirs(profile.directory, exist_ok=True)
        for child in ("mods", "config", "saves", "resourcepacks", "shaderpacks"):
            os.makedirs(os.path.join(profile.directory, child), exist_ok=True)
        try:
            os.startfile(profile.directory)  # type: ignore[attr-defined]
        except OSError as exc:
            QMessageBox.critical(self, "Open Folder Failed", str(exc))

    @Slot()
    def save_current_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        profile.version = self.version_combo.currentText().strip()
        profile.loader = self.loader_combo.currentText()
        profile.username = self.username_input.text().strip() or self._default_username()
        profile.ram_gb = self.ram_slider.value()
        profile.auth_mode = self.auth_combo.currentText()
        profile.ms_client_id = MICROSOFT_CLIENT_ID
        profile.ms_redirect_uri = MICROSOFT_REDIRECT_URI
        self._save_profiles()
        self._refresh_profile_list(profile.id)
        self._append_log(f"Saved profile: {profile.name}")

    @Slot(str)
    def _auth_mode_changed(self, mode: str) -> None:
        profile = self._current_profile()
        is_logged_in = bool(profile and profile.ms_refresh_token)
        enabled = mode == "Microsoft"
        self.microsoft_login_button.setEnabled(enabled and not is_logged_in)
        self._update_user_panel()

    def _update_user_panel(self) -> None:
        profile = self._current_profile()
        if profile and profile.ms_refresh_token:
            self.welcome_label.setText(f"Welcome {profile.username}")
            self.user_panel.setVisible(True)
            self.login_button.setVisible(False)
            self.logout_button.setVisible(True)
        else:
            self.welcome_label.setText("")
            self.user_panel.setVisible(False)
            self.login_button.setVisible(True)
            self.logout_button.setVisible(False)

    @Slot()
    def logout_microsoft(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        profile.ms_refresh_token = ""
        profile.auth_mode = "Offline"
        self.auth_combo.setCurrentText("Offline")
        self._update_user_panel()
        self._auth_mode_changed("Offline")
        self._save_profiles()
        self._refresh_profile_list(profile.id)

    @Slot()
    def login_microsoft(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return

        client_id = MICROSOFT_CLIENT_ID
        redirect_uri = MICROSOFT_REDIRECT_URI
        if not client_id:
            QMessageBox.warning(
                self,
                "Missing Client ID",
                "Microsoft login requires an Azure application Client ID.",
            )
            return

        try:
            microsoft_account = import_module("minecraft_launcher_lib.microsoft_account")
            login_url, state, code_verifier = microsoft_account.get_secure_login_data(client_id, redirect_uri)
            webbrowser.open(login_url)
            redirect_url, accepted = QInputDialog.getText(
                self,
                "Microsoft Login",
                "After signing in, paste the final redirected URL here:",
            )
            if not accepted or not redirect_url.strip():
                return
            auth_code = microsoft_account.parse_auth_code_url(redirect_url.strip(), state)
            response = microsoft_account.complete_login(
                client_id,
                None,
                redirect_uri,
                auth_code,
                code_verifier,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Microsoft Login Failed", str(exc))
            return

        profile.auth_mode = "Microsoft"
        profile.ms_client_id = client_id
        profile.ms_redirect_uri = redirect_uri
        profile.ms_refresh_token = response["refresh_token"]
        profile.username = response["name"]
        self.auth_combo.setCurrentText("Microsoft")
        self.username_input.setText(response["name"])
        self._update_user_panel()
        self._save_profiles()
        self._refresh_profile_list(profile.id)
        QMessageBox.information(self, "Microsoft Login", f"Logged in as {response['name']}.")

    @Slot(dict)
    def _microsoft_profile_refreshed(self, response: dict) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        refresh_token = response.get("refresh_token")
        username = response.get("name")
        if refresh_token:
            profile.ms_refresh_token = refresh_token
        if username:
            profile.username = username
            self.username_input.setText(username)
        self._save_profiles()

    @Slot()
    def delete_current_profile(self) -> None:
        profile = self._current_profile()
        if profile is None or len(self.profiles) <= 1:
            QMessageBox.information(self, "Profile Required", "Keep at least one profile.")
            return
        if QMessageBox.question(self, "Delete Profile", f"Delete profile '{profile.name}'?") != QMessageBox.StandardButton.Yes:
            return
        self.profiles = [item for item in self.profiles if item.id != profile.id]
        self._save_profiles()
        self._refresh_profile_list()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _profile_selected(
        self,
        current: QListWidgetItem | None = None,
        previous: QListWidgetItem | None = None,
    ) -> None:
        del current, previous
        self._apply_current_profile()

    def _apply_current_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        self.version_combo.setCurrentText(profile.version)
        loader_index = self.loader_combo.findText(profile.loader)
        if loader_index >= 0:
            self.loader_combo.setCurrentIndex(loader_index)
        self.username_input.setText(profile.username)
        self.ram_slider.setValue(profile.ram_gb)
        auth_index = self.auth_combo.findText(profile.auth_mode)
        if auth_index >= 0:
            self.auth_combo.setCurrentIndex(auth_index)
        self._update_user_panel()
        self._auth_mode_changed(self.auth_combo.currentText())

    def _load_versions(self) -> None:
        self.status_label.setText("Loading version list...")
        self.version_thread = QThread(self)
        self.version_loader = VersionLoader()
        self.version_loader.moveToThread(self.version_thread)
        self.version_thread.started.connect(self.version_loader.run)
        self.version_loader.loaded.connect(self._versions_loaded)
        self.version_loader.failed.connect(self._versions_failed)
        self.version_loader.loaded.connect(self.version_thread.quit)
        self.version_loader.failed.connect(self.version_thread.quit)
        self.version_loader.loaded.connect(self.version_loader.deleteLater)
        self.version_loader.failed.connect(self.version_loader.deleteLater)
        self.version_thread.finished.connect(self.version_thread.deleteLater)
        self.version_thread.start()

    @Slot(list)
    def _versions_loaded(self, versions: list[str]) -> None:
        current = self.version_combo.currentText()
        self.available_versions = versions
        self.version_combo.clear()
        self.version_combo.addItems(versions)
        if current:
            self.version_combo.setCurrentText(current)
        self.status_label.setText("Ready.")

    @Slot(str)
    def _versions_failed(self, message: str) -> None:
        self.status_label.setText("Could not load the online version list. Common releases are available.")
        self._append_log(f"Version list error: {message}")

    @Slot(int)
    def _update_ram_label(self, value: int) -> None:
        self.ram_label.setText(f"{value} GB")

    @Slot()
    def launch(self) -> None:
        username = self.username_input.text().strip()
        version = self.version_combo.currentText().strip()
        if not username and self.auth_combo.currentText() == "Offline":
            QMessageBox.warning(self, "Missing Username", "Enter an offline username before launching.")
            return
        if not version:
            QMessageBox.warning(self, "Missing Version", "Choose a Minecraft version before launching.")
            return

        self.save_current_profile()
        profile = self._current_profile()
        settings = LaunchSettings(
            version=version,
            loader=self.loader_combo.currentText(),
            username=username or "Player",
            ram_gb=self.ram_slider.value(),
            minecraft_directory=profile.directory if profile else MINECRAFT_DIRECTORY,
            auth_mode=self.auth_combo.currentText(),
            ms_client_id=MICROSOFT_CLIENT_ID,
            ms_redirect_uri=MICROSOFT_REDIRECT_URI,
            ms_refresh_token=profile.ms_refresh_token if profile else "",
        )

        os.makedirs(settings.minecraft_directory, exist_ok=True)
        self.launch_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Preparing...")
        self.status_label.setText("Starting...")
        self._append_log(f"Launch requested: {settings.loader} {settings.version} as {settings.username}.")

        self.launch_thread = QThread(self)
        self.launch_worker = LauncherWorker(settings)
        self.launch_worker.moveToThread(self.launch_thread)
        self.launch_thread.started.connect(self.launch_worker.run)
        self.launch_worker.progress.connect(self.progress_bar.setValue)
        self.launch_worker.progress_text.connect(self.progress_label.setText)
        self.launch_worker.status.connect(self.status_label.setText)
        self.launch_worker.log.connect(self._append_log)
        self.launch_worker.microsoft_profile.connect(self._microsoft_profile_refreshed)
        self.launch_worker.finished.connect(self._launch_finished)
        self.launch_worker.failed.connect(self._launch_failed)
        self.launch_worker.finished.connect(self.launch_thread.quit)
        self.launch_worker.failed.connect(self.launch_thread.quit)
        self.launch_worker.finished.connect(self.launch_worker.deleteLater)
        self.launch_worker.failed.connect(self.launch_worker.deleteLater)
        self.launch_thread.finished.connect(self.launch_thread.deleteLater)
        self.launch_thread.start()

    @Slot()
    def _launch_finished(self) -> None:
        self.launch_button.setEnabled(True)

    @Slot(str)
    def _launch_failed(self, message: str) -> None:
        self.launch_button.setEnabled(True)
        self.status_label.setText("Launch failed.")
        self.progress_label.setText("Failed")
        self._append_log(f"Error: {message}")
        QMessageBox.critical(self, "Launch Failed", message)

    @Slot(str)
    def _append_log(self, message: str) -> None:
        self.log_output.append(message)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LarpLauncher")
    window = MainWindow()
    window.show()
    return app.exec()
