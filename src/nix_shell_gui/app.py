from __future__ import annotations

import getpass
import os
import shutil
import threading

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk, Pango

from . import classify, store, terminal
from .search import Package, SearchError, filter_catalog, load_catalog

NIX_BIN_CANDIDATES = [
    "nix",
    "/run/current-system/sw/bin/nix",
    f"/etc/profiles/per-user/{getpass.getuser()}/bin/nix",
    "/nix/var/nix/profiles/default/bin/nix",
]

MODE_LABELS = {
    "gui": "launches directly",
    "tui": "launches in an external terminal",
    "cli": "opens a shell in an external terminal",
}

PAGE_SIZE = 200


def find_nix() -> str | None:
    for candidate in NIX_BIN_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        elif shutil.which(candidate):
            return candidate
    return None


def install_css(window: Gtk.Window) -> None:
    css = b"""
    .card {
      background-color: alpha(@theme_bg_color, 0.6);
      border: 1px solid alpha(@theme_fg_color, 0.15);
      border-radius: 10px;
      margin: 4px;
      padding: 8px;
    }
    .card-title { font-size: 15px; font-weight: bold; }
    .tag {
      font-size: 10px;
      padding: 2px 8px;
      border-radius: 8px;
      background-color: alpha(@theme_fg_color, 0.12);
    }
    .status-icon { font-size: 12px; }
    .fav-icon { color: #f2c94c; }
    .offline-icon { color: alpha(@theme_fg_color, 0.4); }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        window.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def _section_of(attr_path: str) -> str | None:
    parts = attr_path.split(".")
    return parts[0] if len(parts) > 1 else None


class PackageCard(Gtk.Box):
    def __init__(self, package: Package):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.get_style_context().add_class("card")
        self.package = package
        self.offline = False

        self.fav_icon = Gtk.Label(label="★")
        self.fav_icon.set_no_show_all(True)
        self.fav_icon.set_tooltip_text("favourite")
        for css_class in ("status-icon", "fav-icon"):
            self.fav_icon.get_style_context().add_class(css_class)

        self.off_icon = Gtk.Label(label="●")
        self.off_icon.set_no_show_all(True)
        self.off_icon.set_tooltip_text("offline")
        for css_class in ("status-icon", "offline-icon"):
            self.off_icon.get_style_context().add_class(css_class)

        name_label = Gtk.Label(label=package.name)
        name_label.set_xalign(0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.get_style_context().add_class("card-title")

        header = Gtk.Box(spacing=6)
        header.pack_start(name_label, True, True, 0)
        header.pack_end(self.fav_icon, False, False, 0)
        header.pack_end(self.off_icon, False, False, 0)
        self.pack_start(header, False, False, 0)

        self.meta = Gtk.Box(spacing=6)
        self.pack_start(self.meta, False, False, 0)
        self._rebuild_meta()

    def _chip(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.get_style_context().add_class("tag")
        return label

    def _rebuild_meta(self) -> None:
        for child in self.meta.get_children():
            self.meta.remove(child)
        if self.package.version:
            self.meta.pack_start(self._chip(self.package.version), False, False, 0)
        section = _section_of(self.package.attr_path)
        if section:
            self.meta.pack_start(self._chip(section), False, False, 0)
        if self.offline:
            self.meta.pack_start(self._chip("offline"), False, False, 0)
        self.meta.show_all()

    def update_state(self, favourites: set[str]) -> None:
        self.fav_icon.set_visible(self.package.attr_path in favourites)
        self.off_icon.set_visible(self.offline)
        self._rebuild_meta()


class NixAppStore:
    def __init__(self):
        self.nix_bin = find_nix()
        self.favourites = store.load_favourites()
        self.catalog: list[Package] | None = None
        self.packages: list[Package] = []
        self.rows: dict[str, PackageCard] = {}
        self.selected: Package | None = None
        self._debounce_id = None
        self._rendered = 0
        self._store_count = store.store_entry_count()

        self.window = Gtk.Window(title="Nix App Store")
        self.window.set_default_size(960, 640)
        self.window.connect("destroy", Gtk.main_quit)
        install_css(self.window)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search nixpkgs...")
        self.search_entry.connect("search-changed", self._on_search_changed)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)

        self.offline_filter = Gtk.CheckButton(label="Offline only")
        self.offline_filter.connect("toggled", lambda *_: self._refresh())
        self.fav_filter = Gtk.CheckButton(label="Favourites")
        self.fav_filter.connect("toggled", lambda *_: self._refresh())

        filters = Gtk.Box(spacing=8)
        filters.pack_start(self.offline_filter, False, False, 0)
        filters.pack_start(self.fav_filter, False, False, 0)

        self.search_list = Gtk.ListBox()
        self.search_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.search_list.set_filter_func(self._filter_row)
        self.search_list.connect("row-selected", self._on_row_selected)

        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.add(self.search_list)
        results_scroll.set_size_request(380, -1)
        self.scroll_adjustment = results_scroll.get_vadjustment()
        self.scroll_adjustment.connect("value-changed", self._on_scroll_changed)

        left = Gtk.VBox(spacing=4)
        left.pack_start(self.search_entry, False, False, 0)
        left.pack_start(filters, False, False, 0)
        left.pack_start(results_scroll, True, True, 0)

        self.detail_name = Gtk.Label(label="No package selected")
        self.detail_name.set_xalign(0)
        self.detail_name.get_style_context().add_class("title-1")

        self.detail_attr = Gtk.Label(label="")
        self.detail_attr.set_xalign(0)

        self.detail_version = Gtk.Label(label="")
        self.detail_version.set_xalign(0)

        self.detail_desc = Gtk.Label(label="")
        self.detail_desc.set_xalign(0)
        self.detail_desc.set_line_wrap(True)
        self.detail_desc.set_selectable(True)

        self.detail_mode = Gtk.Label(label="")
        self.detail_mode.set_xalign(0)

        self.fav_button = Gtk.ToggleButton(label="Favourite")
        self.fav_button.connect("toggled", self._on_fav_toggled)

        self.launch_button = Gtk.Button(label="Launch")
        self.launch_button.set_sensitive(False)
        self.launch_button.connect("clicked", self._on_launch)

        buttons = Gtk.Box(spacing=8)
        buttons.pack_start(self.fav_button, False, False, 0)
        buttons.pack_start(self.launch_button, False, False, 0)

        details = Gtk.VBox(spacing=8)
        details.pack_start(self.detail_name, False, False, 0)
        details.pack_start(self.detail_attr, False, False, 0)
        details.pack_start(self.detail_version, False, False, 0)
        details.pack_start(self.detail_desc, True, True, 0)
        details.pack_start(self.detail_mode, False, False, 0)
        details.pack_start(buttons, False, False, 0)

        split = Gtk.HBox(spacing=8)
        split.pack_start(left, True, True, 0)
        split.pack_start(details, True, True, 0)

        root = Gtk.VBox(spacing=4)
        root.pack_start(split, True, True, 0)
        root.pack_start(self.status_label, False, False, 0)
        self.window.add(root)

        cached_catalog = store.load_catalog_cache()
        if cached_catalog:
            GLib.idle_add(self._catalog_ready, cached_catalog, True)
            self.status_label.set_text("Loading package index (cached)...")
        else:
            self.status_label.set_text("Loading package index...")
        GLib.timeout_add(60_000, self._recheck_store)
        threading.Thread(target=self._load_catalog, daemon=True).start()

    def _load_catalog(self) -> None:
        if not self.nix_bin:
            GLib.idle_add(self._catalog_failed, "nix not found on PATH")
            return
        try:
            catalog = load_catalog(self.nix_bin)
        except (SearchError, TimeoutError) as error:
            GLib.idle_add(self._catalog_failed, str(error))
            return
        GLib.idle_add(self._catalog_ready, catalog, False)

    def _catalog_failed(self, message: str) -> bool:
        if self.catalog is not None:
            self.status_label.set_text(f"{len(self.packages)} results (cached index, refresh failed: {message})")
        else:
            self.status_label.set_text(f"Failed to load package index: {message}")
        return False

    def _catalog_ready(self, catalog: list[Package], from_cache: bool) -> bool:
        self.catalog = catalog
        if not from_cache:
            store.save_catalog_cache(catalog)
            store._availability = store.compute_availability(catalog)
            store.save_availability(store._availability)
        self._refresh()
        return False

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(350, self._do_search)

    def _do_search(self) -> bool:
        self._debounce_id = None
        self._refresh()
        return False

    def _refresh(self) -> None:
        if self.catalog is None:
            self.status_label.set_text("Loading package index...")
            return
        query = self.search_entry.get_text()
        matches = filter_catalog(self.catalog, query)
        matches.sort(
            key=lambda package: (package.attr_path not in self.favourites, package.name.lower())
        )
        if self.fav_filter.get_active():
            matches = [package for package in matches if package.attr_path in self.favourites]
        if self.offline_filter.get_active():
            matches = [package for package in matches if store.is_available(package.attr_path)]
        self._set_results(matches)

    def _set_results(self, packages: list[Package]) -> None:
        self.packages = packages
        self._rendered = 0
        for listbox_row in list(self.search_list.get_children()):
            self.search_list.remove(listbox_row)
        self.rows = {}
        self._append_page()
        self.status_label.set_text(f"{len(packages)} results" if packages else "No results")
        self.search_list.invalidate_filter()

    def _append_page(self) -> None:
        end = min(len(self.packages), self._rendered + PAGE_SIZE)
        while self._rendered < end:
            package = self.packages[self._rendered]
            card = PackageCard(package)
            card.offline = store.is_available(package.attr_path)
            card.update_state(self.favourites)
            self.rows[package.attr_path] = card
            self.search_list.add(card)
            card.show_all()
            self._rendered += 1

    def _on_scroll_changed(self, adjustment: Gtk.Adjustment) -> None:
        if adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 50:
            self._append_page()

    def _recheck_store(self) -> bool:
        count = store.store_entry_count()
        if count != self._store_count:
            self._store_count = count
            self._recompute_availability()
        return True

    def _settle_store_change(self) -> bool:
        self._recheck_store()
        return False

    def _recompute_availability(self) -> None:
        if self.catalog is None:
            return
        store._availability = store.compute_availability(self.catalog)
        store.save_availability(store._availability)
        for attr_path, row in self.rows.items():
            row.offline = store.is_available(attr_path)
            row.update_state(self.favourites)
        self.search_list.invalidate_filter()

    def _filter_row(self, listbox_row: Gtk.ListBoxRow) -> bool:
        card: PackageCard = listbox_row.get_child()
        if self.offline_filter.get_active() and not card.offline:
            return False
        if self.fav_filter.get_active() and card.package.attr_path not in self.favourites:
            return False
        return True

    def _on_row_selected(self, listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        package = row.get_child().package
        self.selected = package
        self.detail_name.set_text(package.name)
        self.detail_attr.set_text(package.attr_path)
        self.detail_version.set_text(f"version {package.version}" if package.version else "")
        self.detail_desc.set_text(package.description)
        handler_id = self.fav_button.handler_block_by_func(self._on_fav_toggled)
        self.fav_button.set_active(package.attr_path in self.favourites)
        self.fav_button.handler_unblock_by_func(self._on_fav_toggled)
        self.detail_mode.set_text("detecting launch mode...")
        self.launch_button.set_sensitive(False)
        threading.Thread(
            target=self._classify_worker, args=(package.attr_path,), daemon=True
        ).start()

    def _classify_worker(self, attr_path: str) -> None:
        if not self.nix_bin:
            GLib.idle_add(self._apply_mode, attr_path, "cli")
            return
        mode = classify.classify(self.nix_bin, attr_path)
        GLib.idle_add(self._apply_mode, attr_path, mode)

    def _apply_mode(self, attr_path: str, mode: str) -> bool:
        if self.selected is None or self.selected.attr_path != attr_path:
            return False
        self.detail_mode.set_text(MODE_LABELS[mode])
        self.launch_button.set_sensitive(True)
        return False

    def _on_fav_toggled(self, button: Gtk.ToggleButton) -> None:
        if self.selected is None:
            return
        attr_path = self.selected.attr_path
        if button.get_active():
            self.favourites.add(attr_path)
        else:
            self.favourites.discard(attr_path)
        store.save_favourites(self.favourites)
        self._refresh()

    def _on_launch(self, button: Gtk.Button) -> None:
        if self.selected is None:
            return
        if not self.nix_bin:
            self.status_label.set_text("nix not found on PATH")
            return
        package = self.selected
        mode = classify.classify(self.nix_bin, package.attr_path)
        if mode == "gui":
            terminal.launch_direct(self.nix_bin, package.attr_path)
        else:
            terminal.launch_in_terminal(self.nix_bin, package.attr_path, mode)
        GLib.timeout_add(30_000, self._settle_store_change)


def main() -> None:
    app = NixAppStore()
    app.window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()