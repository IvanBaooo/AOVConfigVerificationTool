import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV10 import AOVAutoPackerMVPCommitV10App


APP_ID = "AOVAutoPacker.LocalCompact"


class AOVAutoPackerLocalCompactApp(AOVAutoPackerMVPCommitV10App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker Local Compact")
		self._rebuild_compact_layout()
		self._apply_daily_defaults()

	def _rebuild_compact_layout(self) -> None:
		for child in self.main_frame.winfo_children():
			child.destroy()

		for row in range(20):
			self.main_frame.rowconfigure(row, weight=0)
		self.main_frame.rowconfigure(0, weight=1)
		self.main_frame.columnconfigure(0, weight=1)

		self.notebook = ttk.Notebook(self.main_frame)
		self.notebook.grid(row=0, column=0, sticky="nsew")

		daily_tab = ttk.Frame(self.notebook, padding=12)
		config_tab = ttk.Frame(self.notebook, padding=12)
		self.notebook.add(daily_tab, text="Daily")
		self.notebook.add(config_tab, text="Config")

		self._build_daily_tab(daily_tab)
		self._build_config_tab(config_tab)
		self.refresh_input_labels()
		self.append_log("Compact UI loaded. Daily tab only needs region and current revision.", "info")

	def _build_daily_tab(self, parent: ttk.Frame) -> None:
		parent.columnconfigure(0, weight=1)
		parent.rowconfigure(2, weight=1)

		quick_frame = ttk.LabelFrame(parent, text="Daily pack", padding=10)
		quick_frame.grid(row=0, column=0, sticky="ew")
		quick_frame.columnconfigure(1, weight=1)
		quick_frame.columnconfigure(3, weight=1)

		ttk.Label(quick_frame, text="Region").grid(row=0, column=0, sticky="w", padx=(0, 8))
		region_combo = ttk.Combobox(
			quick_frame,
			textvariable=self.var_package_region,
			values=("TW", "TH", "VN", "ID"),
			width=10,
			state="readonly",
		)
		region_combo.grid(row=0, column=1, sticky="w")
		region_combo.bind("<<ComboboxSelected>>", lambda _event: self.sync_region_scope())

		ttk.Label(quick_frame, text="Current revision").grid(row=0, column=2, sticky="w", padx=(18, 8))
		ttk.Entry(quick_frame, textvariable=self.var_current_revision_spec).grid(row=0, column=3, sticky="ew")

		button_row = ttk.Frame(parent)
		button_row.grid(row=1, column=0, sticky="ew", pady=(12, 0))
		button_row.columnconfigure(0, weight=1)
		ttk.Button(button_row, text="Pack", command=self.on_start_packaging).grid(row=0, column=1, sticky="e")

		log_frame = ttk.LabelFrame(parent, text="Result", padding=8)
		log_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
		log_frame.rowconfigure(0, weight=1)
		log_frame.columnconfigure(0, weight=1)
		self.txt_log = tk.Text(log_frame, height=18, wrap="none", state="disabled")
		self.txt_log.grid(row=0, column=0, sticky="nsew")
		log_scroll_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview)
		log_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_log.configure(yscrollcommand=log_scroll_y.set)

	def _build_config_tab(self, parent: ttk.Frame) -> None:
		parent.columnconfigure(0, weight=1)
		parent.rowconfigure(4, weight=1)

		path_frame = ttk.LabelFrame(parent, text="Paths", padding=8)
		path_frame.grid(row=0, column=0, sticky="ew")
		path_frame.columnconfigure(1, weight=1)
		ttk.Label(path_frame, text="ServerBytes local root").grid(row=0, column=0, sticky="w", padx=(0, 8))
		ttk.Entry(path_frame, textvariable=self.var_local_root).grid(row=0, column=1, sticky="ew")
		ttk.Label(path_frame, text="TdrTable local root").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(path_frame, textvariable=self.var_tdr_root).grid(row=1, column=1, sticky="ew", pady=(6, 0))

		svn_frame = ttk.LabelFrame(parent, text="SVN", padding=8)
		svn_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
		svn_frame.columnconfigure(1, weight=1)
		svn_frame.columnconfigure(3, weight=1)
		self.var_input_method.set("revision_spec")
		ttk.Radiobutton(
			svn_frame,
			text="Auto svn log by revision",
			variable=self.var_svn_log_source,
			value="auto",
			command=self.refresh_input_labels,
		).grid(row=0, column=0, sticky="w", columnspan=2)
		ttk.Radiobutton(
			svn_frame,
			text="Manual pasted svn log",
			variable=self.var_svn_log_source,
			value="manual",
			command=self.refresh_input_labels,
		).grid(row=0, column=2, sticky="w", columnspan=2)
		ttk.Label(svn_frame, text="SVN target").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(svn_frame, textvariable=self.var_svn_target).grid(row=1, column=1, sticky="ew", pady=(6, 0))
		ttk.Label(svn_frame, text="SVN exe").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		ttk.Entry(svn_frame, textvariable=self.var_svn_exe).grid(row=1, column=3, sticky="ew", pady=(6, 0))
		ttk.Checkbutton(svn_frame, text="Use SVN auth cache", variable=self.var_use_auth_cache).grid(
			row=2, column=0, sticky="w", columnspan=2, pady=(6, 0)
		)
		ttk.Label(svn_frame, text="Username").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(svn_frame, textvariable=self.var_svn_username).grid(row=3, column=1, sticky="ew", pady=(6, 0))
		ttk.Label(svn_frame, text="Password").grid(row=3, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		ttk.Entry(svn_frame, textvariable=self.var_svn_password, show="*").grid(row=3, column=3, sticky="ew", pady=(6, 0))

		baseline_frame = ttk.LabelFrame(parent, text="Baseline and naming", padding=8)
		baseline_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
		baseline_frame.columnconfigure(1, weight=1)
		baseline_frame.columnconfigure(3, weight=1)
		ttk.Checkbutton(baseline_frame, text="Enable commit check", variable=self.var_enable_commit_check).grid(
			row=0, column=0, sticky="w", columnspan=4
		)
		ttk.Label(baseline_frame, text="Last external revision").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(baseline_frame, textvariable=self.var_last_external_revision_spec).grid(row=1, column=1, sticky="ew", pady=(6, 0))
		ttk.Label(baseline_frame, text="Last external time").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		ttk.Entry(baseline_frame, textvariable=self.var_last_external_time).grid(row=1, column=3, sticky="ew", pady=(6, 0))
		ttk.Label(baseline_frame, text="Scope roots").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(baseline_frame, textvariable=self.var_scope_roots).grid(row=2, column=1, sticky="ew", pady=(6, 0))
		ttk.Label(baseline_frame, text="Package version").grid(row=2, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		ttk.Entry(baseline_frame, textvariable=self.var_package_version).grid(row=2, column=3, sticky="ew", pady=(6, 0))
		ttk.Checkbutton(
			baseline_frame,
			text="Filter by selected ServerBytes region",
			variable=self.var_enable_region_filter,
		).grid(row=3, column=0, sticky="w", columnspan=4, pady=(6, 0))

		validation_frame = ttk.LabelFrame(parent, text="Validation", padding=8)
		validation_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))
		validation_frame.columnconfigure(1, weight=1)
		validation_frame.columnconfigure(3, weight=1)
		ttk.Checkbutton(validation_frame, text="Enable skin precheck", variable=self.var_enable_skin_validation).grid(
			row=0, column=0, sticky="w", columnspan=4
		)
		ttk.Label(validation_frame, text="Window start").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		ttk.Entry(validation_frame, textvariable=self.var_window_start).grid(row=1, column=1, sticky="ew", pady=(6, 0))
		ttk.Label(validation_frame, text="Window end").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		ttk.Entry(validation_frame, textvariable=self.var_window_end).grid(row=1, column=3, sticky="ew", pady=(6, 0))

		texts = ttk.PanedWindow(parent, orient="horizontal")
		texts.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
		manual_frame = ttk.LabelFrame(texts, text="Manual svn log / file list", padding=8)
		whitelist_frame = ttk.LabelFrame(texts, text="Commit whitelist", padding=8)
		texts.add(manual_frame, weight=3)
		texts.add(whitelist_frame, weight=2)

		manual_frame.rowconfigure(1, weight=1)
		manual_frame.columnconfigure(0, weight=1)
		self.lbl_package_input = ttk.Label(manual_frame, text="")
		self.lbl_package_input.grid(row=0, column=0, sticky="w")
		self.txt_package_input = tk.Text(manual_frame, height=8, wrap="none")
		self.txt_package_input.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

		whitelist_frame.rowconfigure(1, weight=1)
		whitelist_frame.columnconfigure(0, weight=1)
		ttk.Label(
			whitelist_frame,
			text="每行一个：文件名、完整路径或通配符（# 开头为注释）",
		).grid(row=0, column=0, sticky="w")
		self.txt_commit_whitelist = tk.Text(whitelist_frame, height=8, wrap="none")
		self.txt_commit_whitelist.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

	def _apply_daily_defaults(self) -> None:
		self.var_input_method.set("revision_spec")
		self.var_svn_log_source.set("auto")
		self.var_enable_commit_check.set(True)
		self.var_enable_region_filter.set(True)
		self.sync_region_scope()
		self.refresh_input_labels()


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
		except Exception:
			pass

	root = tk.Tk()
	try:
		icon_path = resource_path("icon.ico")
		if os.path.exists(icon_path):
			root.iconbitmap(default=icon_path)
	except Exception:
		pass

	try:
		style = ttk.Style()
		if "vista" in style.theme_names():
			style.theme_use("vista")
		elif "clam" in style.theme_names():
			style.theme_use("clam")
	except Exception:
		pass

	AOVAutoPackerLocalCompactApp(root)
	root.minsize(900, 680)
	root.mainloop()


if __name__ == "__main__":
	main()
