from __future__ import annotations

import sys
import tkinter
from pathlib import Path
from tkinter import ttk
from typing import Callable, Generic, TypeVar

from porcupine import get_main_window, tabs, textutils

from . import history

T = TypeVar("T")


class FormattingEntryAndLabels(Generic[T]):
    def __init__(
        self,
        entry_area: ttk.Frame,
        text: str,
        substitutions: dict[str, str],
        formatter: Callable[[str, dict[str, str]], T],
        value_validator: Callable[[T], bool],
        validated_callback: Callable[[], None],
    ):
        self._substitutions = substitutions
        self._value_validator = value_validator
        self._validated_callback = validated_callback
        self._formatter = formatter

        grid_y = entry_area.grid_size()[1]
        ttk.Label(entry_area, text=text).grid(row=grid_y, column=0, sticky="w")

        self.format_var = tkinter.StringVar()
        self.entry = ttk.Entry(entry_area, font="TkFixedFont", textvariable=self.format_var)
        self.entry.grid(row=grid_y, column=1, sticky="we")
        self.entry.selection_range(0, "end")

        grid_y += 1
        self._command_display = textutils.create_passive_text_widget(
            entry_area, width=1, height=2, wrap="char", cursor="arrow"
        )
        self._command_display.grid(row=grid_y, column=1, sticky="we")

        self.format_var.trace_add("write", self._validate)
        self.value: T | None = None
        self._validate()

    def _validate(self, *junk_from_var_trace: object) -> None:
        try:
            value = self._formatter(self.format_var.get(), self._substitutions)
        except (ValueError, KeyError, IndexError):
            self.value = None
            self._command_display.config(state="normal", font="TkDefaultFont")
            self._command_display.delete("1.0", "end")
            self._command_display.insert("1.0", "Substitution error")
            self._command_display.config(state="disabled")
        else:
            if self._value_validator(value):
                self.value = value
            else:
                self.value = None
            self._command_display.config(state="normal", font="TkFixedFont")
            self._command_display.delete("1.0", "end")
            self._command_display.insert("1.0", str(value))
            self._command_display.config(state="disabled")

        # _validated_callback might not work if called from __init__
        if junk_from_var_trace:
            self._validated_callback()


class CommandAsker:
    def __init__(self, file_path: Path, project_path: Path, suggestions: list[history.Command]):
        self.window = tkinter.Toplevel()
        self._suggestions = suggestions

        if sys.platform == "win32":
            terminal_name = "command prompt"
        else:
            terminal_name = "terminal"

        content_frame = ttk.Frame(self.window, borderwidth=10)
        content_frame.pack(fill="both", expand=True)

        entry_area = ttk.Frame(content_frame)
        entry_area.pack(fill="x")
        entry_area.grid_columnconfigure(1, weight=1)

        substitutions = history.get_substitutions(file_path, project_path)
        self.command: FormattingEntryAndLabels[str] = FormattingEntryAndLabels(
            entry_area,
            text="Run this command:",
            substitutions=substitutions,
            formatter=history.format_command,
            value_validator=(lambda command: bool(command.strip())),
            validated_callback=self.update_run_button,
        )
        self.cwd: FormattingEntryAndLabels[Path] = FormattingEntryAndLabels(
            entry_area,
            text="In this directory:",
            substitutions=substitutions,
            formatter=history.format_cwd,
            value_validator=(lambda path: path.is_dir()),
            validated_callback=self.update_run_button,
        )

        sub_text = "\n".join("{%s} = %s" % pair for pair in substitutions.items())
        ttk.Label(content_frame, text=f"Substitutions:\n{sub_text}\n").pack(fill="x")

        porcupine_text = (
            "Display the output inside the Porcupine window (does not support keyboard input)"
        )
        external_text = f"Use an external {terminal_name} window"

        self.terminal_var = tkinter.BooleanVar()
        ttk.Radiobutton(
            content_frame,
            variable=self.terminal_var,
            value=False,
            text=porcupine_text,
            underline=porcupine_text.index("Porcupine"),
        ).pack(fill="x")
        ttk.Radiobutton(
            content_frame,
            variable=self.terminal_var,
            value=True,
            text=external_text,
            underline=external_text.index("external"),
        ).pack(fill="x")
        self.window.bind("<Alt-p>", (lambda e: self.terminal_var.set(False)), add=True)
        self.window.bind("<Alt-e>", (lambda e: self.terminal_var.set(True)), add=True)

        ttk.Label(content_frame).pack()  # spacer

        button_frame = ttk.Frame(content_frame)
        button_frame.pack(fill="x")
        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.window.destroy)
        cancel_button.pack(side="left", fill="x", expand=True)
        self.run_button = ttk.Button(button_frame, text="Run", command=self.on_run_clicked)
        self.run_button.pack(side="left", fill="x", expand=True)
        self.run_clicked = False

        for entry in [self.command.entry, self.cwd.entry]:
            entry.bind("<Return>", (lambda e: self.run_button.invoke()), add=True)
            entry.bind("<Escape>", (lambda e: self.window.destroy()), add=True)

        if self._suggestions:
            # Run _autocomplete when pressing a key without alt
            self.command.entry.bind("<Key>", self._autocomplete, add=True)
            self.command.entry.bind("<Alt-Key>", (lambda e: None), add=True)
            self._select_command_autocompletion(self._suggestions[0], prefix="")

        self.command.entry.selection_range(0, "end")
        self.command.entry.focus_set()

    def _select_command_autocompletion(self, command: history.Command, prefix: str) -> None:
        assert command.command_format.startswith(prefix)
        self.command.format_var.set(command.command_format)
        self.command.entry.icursor(len(prefix))
        self.command.entry.selection_range("insert", "end")
        self.cwd.format_var.set(command.cwd_format)
        self.terminal_var.set(command.external_terminal)

    def _autocomplete(self, event: tkinter.Event[tkinter.Entry]) -> str | None:
        if len(event.char) != 1 or not event.char.isprintable():
            return None

        text_to_keep = self.command.entry.get()
        if self.command.entry.selection_present():
            if self.command.entry.index("sel.last") != self.command.entry.index("end"):
                return None
            text_to_keep = text_to_keep[: self.command.entry.index("sel.first")]

        for item in self._suggestions:
            if item.command_format.startswith(text_to_keep + event.char):
                self._select_command_autocompletion(item, text_to_keep + event.char)
                return "break"

        return None

    def update_run_button(self) -> None:
        if self.command.value is not None and self.cwd.value is not None:
            self.run_button.config(state="normal")
        else:
            self.run_button.config(state="disabled")

    def on_run_clicked(self) -> None:
        self.run_clicked = True
        self.window.destroy()


def ask_command(tab: tabs.FileTab, project_path: Path) -> history.Command | None:
    assert tab.path is not None
    asker = CommandAsker(tab.path, project_path, history.get(tab, project_path))
    asker.window.title("Run command")
    asker.window.transient(get_main_window())
    asker.window.wait_window()

    if asker.run_clicked:
        assert asker.command.value is not None
        assert asker.cwd.value is not None
        return history.Command(
            command_format=asker.command.format_var.get(),
            command=asker.command.value,
            cwd_format=asker.cwd.format_var.get(),
            cwd=str(asker.cwd.value),
            external_terminal=asker.terminal_var.get(),
        )
    return None