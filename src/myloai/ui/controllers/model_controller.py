from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from myloai.backends.manager import create_backend
from myloai.core.operations import OperationStreamParser


class ModelWindowPort(Protocol):
    def model_name(self) -> str: ...
    def begin_operation(self, operation: str) -> None: ...
    def update_operation(self, update) -> None: ...
    def complete_operation(self, operation: str) -> None: ...
    def fail_operation(self, operation: str, error: str) -> None: ...
    def refresh_backend(self) -> None: ...
    def run_async(
        self,
        coro_factory,
        done_msg: str,
        *,
        start_msg: str,
        error_title: str,
        parent,
    ) -> None: ...
    def run_stream(
        self,
        iterator_factory,
        on_token: Callable[[str], None],
        on_done: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None: ...
    def ask_text(self, title: str, label: str, text: str = "") -> tuple[str, bool]: ...
    def ask_confirm(self, title: str, text: str) -> bool: ...
    def show_info(self, title: str, text: str) -> None: ...
    def show_error(self, title: str, text: str) -> None: ...
    def open_modelfile_editor(self) -> None: ...


class ModelController:
    def __init__(self, config, window: ModelWindowPort) -> None:
        self.config = config
        self.window = window

    def pull_model(self, parent) -> None:
        self._model_stream_op(parent, "Pull Model", "pull_model")

    def push_model(self, parent) -> None:
        self._model_stream_op(parent, "Push Model", "push_model")

    def create_model(self) -> None:
        self.window.open_modelfile_editor()

    def clone_model(self, parent) -> None:
        source = self.window.model_name().strip()
        if not source:
            self.window.show_info("Clone Model", "Select a model before attempting to clone it.")
            return

        destination, ok = self.window.ask_text("Clone Model", "Destination model name:")
        if not ok:
            return
        destination = destination.strip()
        if not destination:
            self.window.show_info("Clone Model", "Destination model name is required.")
            return

        operation = f"Clone model {source} -> {destination}"
        self.window.run_async(
            lambda: create_backend(self.config.active_profile()).copy_model(
                source, destination
            ),
            operation,
            start_msg=operation,
            error_title="Clone Model",
            parent=parent,
        )

    def delete_model(self, parent) -> None:
        name = self.window.model_name().strip()
        if not name:
            self.window.show_info("Delete Model", "Select a model before attempting deletion.")
            return

        if not self.window.ask_confirm(
            "Delete Model", f"Delete model '{name}'? This action cannot be undone."
        ):
            return

        operation = f"Delete model {name}"
        self.window.run_async(
            lambda: create_backend(self.config.active_profile()).delete_model(name),
            operation,
            start_msg=operation,
            error_title="Delete Model",
            parent=parent,
        )

    def _model_stream_op(self, parent, title: str, method: str) -> None:
        name, ok = self.window.ask_text(title, "Model name:", self.window.model_name().strip())
        if not ok:
            return
        name = name.strip()
        if not name:
            self.window.show_info(title, "Model name is required.")
            return

        operation = f"{title}: {name}"
        parser = OperationStreamParser()
        self.window.begin_operation(operation)

        def on_token(chunk: str) -> None:
            for update in parser.feed(chunk):
                self.window.update_operation(update)

        def on_done(_output: str) -> None:
            self.window.complete_operation(operation)
            self.window.refresh_backend()

        def on_error(error: str) -> None:
            self.window.fail_operation(operation, error)
            self.window.show_error(title, error)

        self.window.run_stream(
            lambda: getattr(create_backend(self.config.active_profile()), method)(name),
            on_token,
            on_done,
            on_error,
        )
