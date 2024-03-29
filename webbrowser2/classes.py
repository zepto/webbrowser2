#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Classes
# Copyright (C) 2016 Josiah Gordon <josiahg@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


""" Classes used by both processes.

"""

from .bookmarks import EntryDialog
from .functions import save_dialog
from json import dumps as json_dumps
from json import loads as json_loads
import socket
import logging
import shutil
import pathlib
from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib, Gio, WebKit2, Gdk, Pango


class ChildDict(dict):
    """A dictionary that has a send command."""

    def __init__(self, *args, **kwargs):
        """Initialize."""
        super(ChildDict, self).__init__(*args, **kwargs)

    def __getitem__(self, key: str):
        """Return the item associated with key."""
        try:
            item = super(ChildDict, self).__getitem__(key)
        except KeyError:
            key = key.replace('_', '-', key.count('_'))
            try:
                item = super(ChildDict, self).__getitem__(key)
            except KeyError:
                item = None

        return item

    def __getattr__(self, item: str):
        """Return the item from the dictionary."""
        return self.__getitem__(item)

    def __setattr__(self, item: str, data: object):
        """Put data in self[item]."""
        self.__setitem__(item.replace('_', '-', item.count('_')), data)


class Profile(dict):
    """A Profile configuration dictionary.

    A configuration dictionary that writes to a file in xdg-config
    directory.
    """

    def __init__(self, profile: str = 'default'):
        """Load the config from filename."""
        super(Profile, self).__init__()

        self._socket = None

        self._config_path = self.get_config_path(profile)
        self._config_file = self._config_path.joinpath('config.json')

        with pathlib.Path(self._config_file) as config_file:
            if config_file.is_file():
                config_dict = json_loads(config_file.read_text())
                for key, value in config_dict.items():
                    try:
                        self[key] = self[key]
                    except KeyError as err:
                        self[key] = value
                    if hasattr(self[key], 'update'):
                        self[key].update(value)
                    else:
                        self[key] = value

        self._socket_file = self._config_path.joinpath(__name__ + '.sock')
        self.sessions_file = self._config_path.joinpath('sessions.json')
        self.crash_file = self._config_path.joinpath('crash.json')
        self.bookmarks_file = str(self._config_path.joinpath('bookmarks.xbel'))

    def __getitem__(self, key: object) -> object:
        """Get the config item otherwise create a default."""
        try:
            return super(Profile, self).__getitem__(key)
        except KeyError:
            if key == 'web-view-settings':
                self[key] = {
                    'enable-page-cache': False,
                    'enable-dns-prefetching': False,
                    'enable-html5-database': False,
                    'enable-html5-local-storage': False,
                    'enable-offline-web-application-cache': False,
                    'enable-hyperlink-auditing': True,
                    'enable-media-stream': False,
                    'enable-java': False,
                    'enable-plugins': False,
                    'enable-mediasource': True,
                    'enable-javascript': True,
                    'enable-javascript-markup': True,
                    'enable-webaudio': True,
                    'enable-webgl': True,
                    'enable-accelerated-2d-canvas': True,
                    'enable-developer-extras': True,
                    'allow-file-access-from-file-urls': False,
                    'allow-modal-dialogs': False,
                    'auto-load-images': True,
                    'draw-compositing-indicators': False,
                    'enable-caret-browsing': False,
                    'enable-frame-flattening': False,
                    'enable-fullscreen': True,
                    'enable-resizable-text-areas': True,
                    'enable-site-specific-quirks': True,
                    'enable-smooth-scrolling': False,
                    'enable-spatial-navigation': False,
                    'enable-tabs-to-links': True,
                    'enable-write-console-messages-to-stdout': False,
                    'enable-xss-auditor': True,
                    'javascript-can-access-clipboard': False,
                    'javascript-can-open-windows-automatically': False,
                    'media-playback-requires-user-gesture': False,
                    'print-backgrounds': True,
                    'zoom-text-only': False,
                    'default-font-family': 'sans-serif',
                    'default-font-size': 16,
                    'serif-font-family': 'Serif 10',
                    'sans-serif-font-family': 'Sans 10',
                    'monospace-font-family': 'Monospace 10',
                    'enable-media': True,
                }
            elif key == 'adblock':
                self[key] = {
                    '/ads/': (r'\/ads\/', True),
                    'doubleclick': (r'doubleclick\.net', True),
                    'pubads': (r'pubads\.', True),
                }
            elif key == 'media-filters':
                self[key] = {
                    'soundcloud mp3s': (r'\.mp3\?', True),
                }
            elif key == 'search':
                self[key] = {
                    'StartPage': 'https://startpage.com/do/search?query=%s'
                }
            elif key == 'default-search':
                self[key] = 'StartPage'
            elif key == 'user-agents':
                self[key] = {
                    'Chromium': 'Mozilla/5.0 (X11; Linux x86_64) '
                                'AppleWebKit/537.36 (KHTML, like Gecko) '
                                'Chrome/49.0.2623.110 Safari/537.36',
                }
            elif key == 'content-filters':
                self[key] = {
                    'easylist_min': (
                        'https://easylist-downloads.adblockplus.org/easylist_m'
                        'in_content_blocker.json',
                        True
                    ),
                }
            elif key == 'content-filter-whitelist':
                self[key] = {}
            elif key == 'default-user-agent':
                self[key] = 'Chromium'
            elif key == 'find-str':
                self[key] = ''
            elif key == 'clear-on-exit':
                self[key] = True
            elif key == 'hide-address-bar':
                self[key] = False
            elif key == 'enable-user-stylesheet':
                self[key] = False
            elif key == 'home-uri':
                self[key] = 'https://www.startpage.com'
            return super(Profile, self).__getitem__(key)

    def __getattr__(self, item: str) -> object:
        """Return the item from the dictionary."""
        try:
            return super(Profile, self).__getattr__(item)
        except AttributeError:
            item = item.replace('_', '-', item.count('_'))
            return self.__getitem__(item)

    def __setattr__(self, item: str, data: object):
        """Put data in self[item]."""
        key = item.replace('_', '-', item.count('_'))
        if key in self:
            self.__setitem__(key, data)
        else:
            super(Profile, self).__setattr__(item, data)

    def get_config_path(self, profile: str = 'default') -> object:
        """Get and create config path.

        Returns the path to the config files.  If it doesn't exist it is
        created.
        """
        xdg_config = pathlib.Path(GLib.get_user_config_dir())
        if not xdg_config.exists():
            xdg_config.mkdir()

        config_path = xdg_config.joinpath('webbrowser2')
        if not config_path.exists():
            config_path.mkdir()

        profile_path = config_path.joinpath(profile)
        with pathlib.Path(profile_path) as prof_path:
            if not prof_path.exists():
                prof_path.mkdir()
            elif not prof_path.is_dir():
                logging.error("Can't Save Config")
                return ''
        return profile_path

    def save_config(self):
        """Save the config to a file."""
        with pathlib.Path(self._config_file) as config_file:
            config_file.write_text(json_dumps(self, indent=4))

    def open_socket(self, uri_list: list) -> object:
        """Open and return a socket."""
        if self._socket_file.is_socket():
            try:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._socket.connect(bytes(self._socket_file))
                self._socket.send(json_dumps(('new-tab', uri_list)).encode())
                self._socket.close()
                return None
            except ConnectionRefusedError:
                self._socket_file.unlink()

        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.bind(bytes(self._socket_file))

        return self._socket

    def close_socket(self):
        """Close the socket."""
        self._socket.close()
        self._socket_file.unlink()

    def get_file(self, target: str) -> str:
        """Return the target file text or path string or ''."""
        if target == 'content-filters':
            return str(self._config_path.joinpath('content filters'))

        target_file = self._config_path.joinpath(target)
        if target_file.is_file():
            return target_file.read_text()
        else:
            return ''
    get_path = get_file


class SettingsPopover(Gtk.Popover):
    """The Settings and session popover."""

    def __init__(self):
        """Init."""
        super(SettingsPopover, self).__init__()

        self._tabs = Gtk.Notebook()
        self._tabs.set_border_width(5)
        self._tabs.set_tab_pos(Gtk.PositionType.LEFT)
        self._tabs.show_all()

        self.add(self._tabs)

    def add_tab(self, widget: object, title: str):
        """Add a tab for widget."""
        title_widget = Gtk.Label(title)
        title_widget.set_angle(90)
        self._tabs.append_page(widget, title_widget)


class DownloadManager(Gtk.Grid):
    """The download manager grid holds indevidule downloads in a listbox."""

    def __init__(self, parent: object = None):
        """Create the listbox to hold downloads."""
        super(DownloadManager, self).__init__()

        self._parent = parent
        self._downloads = []

        empty_label = Gtk.Label('No Downloads')
        empty_label.set_margin_top(12)
        empty_label.set_margin_start(12)
        empty_label.set_margin_end(12)
        empty_label.set_vexpand(True)
        empty_label.set_hexpand(True)

        self._download_list = Gtk.ListBox()
        self._download_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._download_list.set_vexpand(True)
        self._download_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._download_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        self._scroll = scroll

        main_stack = Gtk.Stack()
        main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        main_stack.set_transition_duration(300)
        main_stack.add_named(scroll, 'download')
        main_stack.add_named(empty_label, 'empty')

        self._download_list.connect(
            'remove', self._download_removed, main_stack)
        self._download_list.connect('add', self._download_added, main_stack)

        clear_button = Gtk.Button('Clear List')
        clear_button.set_tooltip_text('Cancel and Remove All Downloads')
        clear_button.set_halign(Gtk.Align.END)
        clear_button.connect('clicked', self._clear_clicked)

        self.set_row_spacing(6)
        self.attach(main_stack, 0, 0, 5, 1)
        self.attach(clear_button, 4, 2, 1, 1)
        self.set_margin_bottom(6)
        self.set_margin_top(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self.show_all()
        main_stack.set_visible_child_name('empty')

    def _download_size_allocate(self, download_list, rect):
        """Scroll to the bottom of the download list."""
        # Scroll to the bottom.
        v_adj = self._scroll.get_vadjustment()
        v_adj.set_value(v_adj.get_upper() - v_adj.get_page_size())

        # Disconnect so it won't always scroll to the bottom when the
        # mouse is moved.
        self._download_list.disconnect_by_func(self._download_size_allocate)

    def new_download(self, uri: str, start: bool = True):
        """Add a download to the list."""
        if not start:
            # If download is just added for the uri do not add
            # duplicates.
            for list_box_row in self._download_list.get_children():
                if uri == list_box_row.get_children()[0].uri: return

        progress_bar = Gtk.ProgressBar()
        progress_bar.set_margin_start(3)
        progress_bar.set_margin_end(12)
        progress_bar.set_margin_bottom(5)
        progress_bar.set_halign(Gtk.Align.START)
        progress_bar.set_hexpand(True)
        progress_bar.set_show_text(True)
        progress_bar.set_text(uri)
        progress_bar.set_ellipsize(Pango.EllipsizeMode.END)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('edit-copy-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        copy_button = Gtk.Button()
        copy_button.set_tooltip_text('Copy Download URL')
        copy_button.set_image(button_img)
        copy_button.set_relief(Gtk.ReliefStyle.NONE)
        copy_button.connect('clicked', self._copy_clicked, uri)

        icon = Gio.ThemedIcon.new_with_default_fallbacks(
            'window-close-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        cancel_button = Gtk.Button()
        cancel_button.set_margin_end(6)
        cancel_button.set_tooltip_text('Cancel and Remove Download')
        cancel_button.set_image(button_img)
        cancel_button.set_relief(Gtk.ReliefStyle.NONE)

        download_grid = Gtk.Grid()
        download_grid.set_border_width(5)
        download_grid.set_hexpand(True)
        download_grid.set_column_homogeneous(False)
        download_grid.attach(progress_bar, 0, 0, 1, 1)
        download_grid.attach(copy_button, 1, 0, 1, 1)
        download_grid.attach(cancel_button, 2, 0, 1, 1)
        download_grid.show_all()

        finish_label = Gtk.Label()
        finish_label.set_halign(Gtk.Align.START)
        finish_label.set_ellipsize(Pango.EllipsizeMode.END)
        finish_label.set_margin_end(12)
        finish_label.set_margin_start(10)
        finish_label.set_vexpand(True)
        finish_label.set_hexpand(True)

        finish_label_event = Gtk.EventBox()
        finish_label_event.add(finish_label)
        finish_label_event.connect(
            'button-release-event', self._finish_button_release, uri)

        icon = Gio.ThemedIcon.new_with_default_fallbacks(
            'document-open-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        open_button = Gtk.Button()
        open_button.set_tooltip_text('Open')
        open_button.set_image(button_img)
        open_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks(
            'list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text('Remove Download')
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        finish_grid = Gtk.Grid()
        finish_grid.set_hexpand(True)
        finish_grid.set_border_width(5)
        finish_grid.set_column_homogeneous(False)
        finish_grid.attach(finish_label_event, 0, 0, 1, 1)
        finish_grid.attach(open_button, 1, 0, 1, 1)
        finish_grid.attach(remove_button, 2, 0, 1, 1)
        finish_grid.show_all()

        download_stack = Gtk.Stack()
        download_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        download_stack.set_transition_duration(300)
        download_stack.add_named(download_grid, 'download')
        download_stack.add_named(finish_grid, 'finish')
        download_stack.set_visible_child_name('download')
        download_stack.show_all()
        download_stack.uri = uri

        self._download_list.add(download_stack)

        # Scroll to the bottom when the download list is displayed.
        self._download_list.connect(
            'size-allocate', self._download_size_allocate)

        if start:
            context = WebKit2.WebContext.get_default()
            download = context.download_uri(uri)
            download.connect('created-destination',
                             self._download_created_destination, progress_bar)
            download.connect('decide-destination',
                             self._download_decide_destination)
            download.connect('failed', self._download_failed, finish_label,
                             download_stack)
            download.connect('finished', self._download_finished, finish_label,
                             download_stack)
            download.connect('notify::response', self._download_response,
                             progress_bar)
            download.connect('notify::estimated-progress',
                             self._download_progress, progress_bar)
            open_button.connect('clicked', self._open_clicked, download)
            self._downloads.append(download)
        else:
            download = None

        cancel_button.connect(
            'clicked', self._close_button_clicked, download_stack, download)
        remove_button.connect(
            'clicked', self._close_button_clicked, download_stack, download)

    def _finish_button_release(self, button: object, event: object, uri: str):
        """Popup menu."""
        # Don't do anything if the pointer was moved off the button.
        if event.window != event.device.get_window_at_position()[0]:
            return False

        if event.button == 3:
            copy_item = Gtk.MenuItem('Copy URL')
            copy_item.connect('activate', self._copy_clicked, uri)
            menu = Gtk.Menu()
            menu.append(copy_item)
            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)

    def cancel_all(self):
        """Cancel all downloads."""
        for download in self._downloads:
            download.disconnect_by_func(self._download_failed)
            download.disconnect_by_func(self._download_finished)
            download.cancel()
        self._downloads = []

    def _clear_clicked(self, button: object):
        """Clear all downloads from the list."""
        self.cancel_all()

        self._download_list.foreach(self._download_list.remove)

    def _copy_clicked(self, button: object, uri: str):
        """Copy uri into clipboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(uri, -1)

    def _close_button_clicked(self, button: object, download_stack: object,
                              download: object):
        """Remove the download."""
        if download:
            download.disconnect_by_func(self._download_failed)
            download.disconnect_by_func(self._download_finished)
            download.cancel()
            self._downloads.remove(download)

        self._download_list.remove(download_stack.get_parent())

    def _open_clicked(self, button: object, download: object):
        """Open the downloaded file."""
        destination = download.get_destination()
        if destination:
            ret = Gtk.show_uri(None, download.get_destination(),
                               Gtk.get_current_event_time())

    def _download_removed(self, listbox: object, widget: object,
                          stack: object):
        """Add a label if the listbox is empty."""
        if not listbox.get_children():
            stack.set_visible_child_name('empty')

    def _download_added(self, listbox: object, widget: object, stack: object):
        """Remove the label if a download is added."""
        stack.set_visible_child_name('download')

    def _download_created_destination(self, download: object, destination: str,
                                      progress_bar: object):
        """The destination was decided on."""
        progress_bar.set_text(destination.split('/')[-1])
        logging.info(f'DOWNLOAD DESTINATION {destination}')

    def _download_decide_destination(self, download: object,
                                     suggested_filename: str) -> bool:
        """Get a filename to save to."""
        logging.info(f'DOWNLOAD TO {suggested_filename}')
        folder = GLib.get_user_special_dir(GLib.USER_DIRECTORY_DOWNLOAD)
        filename = save_dialog(suggested_filename, folder,
                               self._parent, 'Download To')
        if not filename:
            download.cancel()
            return False

        logging.info(f'Setting it to {filename}')
        download.set_allow_overwrite(True)
        download.set_destination(GLib.filename_to_uri(filename))

        return False

    def _download_failed(self, download: object, error: object, label: object,
                         stack: object):
        """Download failed."""
        dest_str = download.get_destination()
        uri = download.get_request().get_uri()
        dest_str = dest_str.split('/')[-1] if dest_str else uri

        label.set_text(dest_str)
        label.set_tooltip_text(f'Failed: {error}')
        stack.set_visible_child_name('finish')
        stack.get_children()[1].get_children()[1].hide()

        logging.error(f'DOWNLOAD FAILED: {error}')

    def _download_finished(self, download: object, label: object,
                           stack: object):
        """Download finished."""
        dest_str = download.get_destination()
        uri = download.get_request().get_uri()
        dest_str = dest_str.split('/')[-1] if dest_str else uri

        label.set_text(dest_str)
        label.set_tooltip_text('Finished Downloading')
        stack.set_visible_child_name('finish')

        logging.info('DOWNLOAD FINISHED')

    def _download_response(self, download: object, response: object,
                           progress_bar: object):
        """Download response changed."""
        uri = download.get_property(response.name).get_uri()
        progress_bar.set_tooltip_text(uri)

        logging.info(f'DOWNLOAD RESPONSE: {uri}')

    def _download_progress(self, download: object, progress: float,
                           progress_bar: object):
        """The download progress."""

        progress = download.get_property(progress.name)
        progress_bar.set_fraction(progress)

        logging.debug(f'DOWNLOAD PROGRESS: {progress}')


class SessionManager(Gtk.Grid):
    """ A list of closed tabs that can be restored.

    """

    __gsignals__ = {
            'restore-session': (GObject.SIGNAL_RUN_LAST, None,
                                (GObject.TYPE_PYOBJECT,)),
            }

    def __init__(self, profile: object):
        """ Create a listbox to list all the closed tabs.

        """

        super(SessionManager, self).__init__()

        self._profile = profile

        empty_label = Gtk.Label('No Sessions to Restore')
        empty_label.set_margin_top(12)
        empty_label.set_margin_start(12)
        empty_label.set_margin_end(12)
        empty_label.set_vexpand(True)
        empty_label.set_hexpand(True)

        self._session_list = Gtk.ListBox()
        self._session_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._session_list.set_vexpand(True)
        self._session_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._session_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        self._scroll = scroll

        main_stack = Gtk.Stack()
        main_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        main_stack.set_transition_duration(300)
        main_stack.add_named(scroll, 'sessions')
        main_stack.add_named(empty_label, 'empty')

        self._restore_selected_button = Gtk.Button('Restore Selected')
        self._restore_selected_button.set_tooltip_text('Restore the selected Sessions.')
        self._restore_selected_button.connect('clicked',
                                        lambda button: self.restore_selected())
        self._restore_selected_button.set_sensitive(False)

        self._select_toggle_button = Gtk.Button('Select All')
        self._select_toggle_button.set_tooltip_text('Select all Sessions.')
        self._select_toggle_button.connect('clicked', self._select_toggle)
        self._select_toggle_button.set_sensitive(False)

        self._clear_selected_button = Gtk.Button('Clear Selected')
        self._clear_selected_button.set_tooltip_text('Remove all selected Sessions.')
        self._clear_selected_button.connect('clicked', lambda button: self.clear_selected())
        self._clear_selected_button.set_sensitive(False)

        button_grid = Gtk.Grid()
        button_grid.set_column_spacing(6)
        button_grid.set_column_homogeneous(True)
        button_grid.attach(self._select_toggle_button, 0, 0, 1, 1)
        button_grid.attach(self._restore_selected_button, 1, 0, 1, 1)
        button_grid.attach(self._clear_selected_button, 2, 0, 1, 1)
        button_grid.set_halign(Gtk.Align.END)

        self.set_row_spacing(6)
        self.attach(main_stack, 0, 0, 5, 1)
        self.attach(button_grid, 4, 2, 1, 1)
        self.set_margin_bottom(6)
        self.set_margin_top(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self.show_all()
        main_stack.set_visible_child_name('empty')

        self._session_list.connect('remove', self._session_removed, main_stack)
        self._session_list.connect('add', self._session_added, main_stack)

        self._selected = []
        self._sessions = []
        for session in sorted(self.load_sessions(), key=lambda i: i['index']):
            self.add_session(session)

    def _session_size_allocate(self, session_list: object, rect: object):
        """ Scroll to the bottom of the session list.

        """

        # Scroll to the bottom.
        v_adj = self._scroll.get_vadjustment()
        v_adj.set_value(v_adj.get_upper() - v_adj.get_page_size())

        # Disconnect so it won't always scroll to the bottom when the
        # mouse is moved.
        self._session_list.disconnect_by_func(self._session_size_allocate)

    def load_sessions(self) -> list:
        """ First check for the sessions file, and if it exists return the
        dictionary from it.  If it doesn't exist try the crash file, and if
        that doesn't exist return an empty dictionary.

        """

        if self._profile.sessions_file.exists():
            session_file = self._profile.sessions_file
        elif self._profile.crash_file.exists():
            session_file = self._profile.crash_file
        else:
            return []

        with pathlib.Path(session_file) as sessions_file:
            sessions = json_loads(sessions_file.read_text())
            sessions_file.unlink()

        # Only return non-empty sessions.
        return [i for i in sessions if i]

    def save_sessions(self, sessions: list = [], to_crash: bool = False):
        """ Save sessions_dict to the sessions file unless to_crash is True,
        then save it to the crash file.

        """

        # Save all open sessions.
        sessions = sessions if sessions else self._sessions
        filename = self._profile.crash_file if to_crash else self._profile.sessions_file

        if sessions:
            logging.info('Saving Sessions...')
            with pathlib.Path(filename) as sessions_file:
                sessions_file.write_text(json_dumps(sessions, indent=4))
            logging.info('Saved Sessions.')

    @property
    def sessions(self) -> list:
        """ Return the list of sessions.

        """

        return self._sessions

    def close(self):
        """ Disconnect some signal handlers to prevent errors.

        """

        self._session_list.disconnect_by_func(self._session_added)
        self._session_list.disconnect_by_func(self._session_removed)

    def clear(self):
        """ Clear all sessions from list.

        """

        self._session_list.foreach(self._session_list.remove)
        self._sessions.clear()
        self._selected.clear()

        self._select_toggle_button.set_sensitive(False)
        self._clear_selected_button.set_sensitive(False)

    def clear_selected(self):
        """ Clear all sessions from list.

        """

        self._selected.sort(key=lambda i: i[0]['index'])
        for session, button, grid in self._selected[:]:
            button.set_active(False)
            self._session_list.remove(grid.get_parent())
            self._sessions.remove(session)

        self._clear_selected_button.set_sensitive(False)

    def restore_all(self):
        """ Restore all sessions.

        """

        for session in sorted(self._sessions, key=lambda i: i['index']):
            self.emit('restore-session', session)

        self.clear()

    def _select_toggle(self, button):
        """ Select all sessions.

        """

        self._session_list.foreach(self._session_foreach_callback, 
                                   button.get_label() == 'Select All')

    def _session_foreach_callback(self, session_row, data):
        """ Do something with each child.

        """

        grid = session_row.get_children()[0]
        for child in grid.get_children():
            if type(child) != Gtk.CheckButton: continue
            child.set_active(data)

    def restore_selected(self):
        """ Restore all the selected sessions.

        """

        self._selected.sort(key=lambda i: i[0]['index'])
        for session, button, grid in self._selected[:]:
            self.emit('restore-session', session)
            button.set_active(False)
            self._session_list.remove(grid.get_parent())
            self._sessions.remove(session)

        self._selected.clear()

    def add_session(self, session: dict) -> bool:
        """ Add as session to the list.

        """

        if not session: return False

        # Store the session.
        self._sessions.append(session)

        title = session['title'] if session['title'] else session['uri']
        label = Gtk.Label(title)
        label.set_halign(Gtk.Align.START)
        label.set_tooltip_text(session['uri'])
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
        label.set_margin_end(12)
        label.set_margin_start(3)

        check_button = Gtk.CheckButton()
        check_button.add(label)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('document-open-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        restore_button = Gtk.Button()
        restore_button.set_tooltip_text('Restore Session')
        restore_button.set_image(button_img)
        restore_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text('Remove From List')
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        grid = Gtk.Grid()
        grid.set_border_width(5)
        grid.attach(check_button, 0, 0, 1, 1)
        grid.attach(restore_button, 1, 0, 1, 1)
        grid.attach(remove_button, 2, 0, 1, 1)
        grid.show_all()

        restore_button.connect('clicked', self._restore_clicked, session, grid)
        remove_button.connect('clicked', self._remove_clicked, session, grid)
        check_button.connect('toggled', self._check_toggled, session, grid)
        check_button.connect('button-release-event',
                             self._check_button_release, session)

        self._session_list.add(grid)
        # Scroll to the bottom when displayed.
        self._session_list.connect('size-allocate',
                                   self._session_size_allocate)

        return True

    def _check_button_release(self, button: object, event: object,
                              session: dict):
        """ Popup menu.

        """

        # Don't do anything if the pointer was moved off the button.
        if event.window != event.device.get_window_at_position()[0]:
            return False

        if event.button == 3:
            copy_item = Gtk.MenuItem('Copy URL')
            copy_item.connect('activate', self._copy_clicked, session['uri'])
            menu = Gtk.Menu()
            menu.append(copy_item)
            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)

    def _copy_clicked(self, item: object, uri: str):
        """ Put uri in clipboard.

        """

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(uri, -1)

    def _restore_clicked(self, button: object, session: dict, grid: object):
        """ Emit the restore session signal.

        """

        self._session_list.remove(grid.get_parent())
        self._sessions.remove(session)

        self.emit('restore-session', session)

    def _remove_clicked(self, button: object, session: dict, grid: object):
        """ Remove grid from session_list.

        """

        self._session_list.remove(grid.get_parent())
        self._sessions.remove(session)

    def _check_toggled(self, button: object, session: dict, grid: object):
        """ Add session and button to self._selected.

        """

        if button.get_active():
            self._selected.append((session, button, grid))
        else:
            self._selected.remove((session, button, grid))

        self._restore_selected_button.set_sensitive(bool(self._selected))
        self._clear_selected_button.set_sensitive(bool(self._selected))

        if self._selected:
            self._select_toggle_button.set_label('Unselect All')
            self._select_toggle_button.set_tooltip_text('Unselect all Sessions.')
        else:
            self._select_toggle_button.set_label('Select All')
            self._select_toggle_button.set_tooltip_text('Select all Sessions.')

    def _session_removed(self, listbox: object, widget: object, stack: object):
        """ Add a label if the listbox is empty.

        """

        if not listbox.get_children():
            stack.set_visible_child_name('empty')
            self._select_toggle_button.set_sensitive(False)
            self._restore_selected_button.set_sensitive(False)

    def _session_added(self, listbox: object, widget: object, stack: object):
        """ Remove the label if a download is added.

        """

        stack.set_visible_child_name('sessions')
        self._select_toggle_button.set_sensitive(True)


class SettingsManager(Gtk.Grid):
    """ A list of settings.

    """

    __gsignals__ = {
            'setting-changed': (GObject.SIGNAL_RUN_LAST, None,
                                (str, object)),
            }

    def __init__(self, profile: object):
        """ Create a listbox to list all the settings.

        """

        super(SettingsManager, self).__init__()

        self._profile = profile

        self._settings_grid = Gtk.Grid()
        self._settings_grid.set_border_width(15)
        self._settings_grid.set_row_spacing(3)
        self._settings_grid.set_vexpand(True)
        self._settings_grid.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._settings_grid)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        clear_cache_button = Gtk.Button('Clear Website Data')
        clear_cache_button.set_tooltip_text('Clear All Cached Data Except HTML5 Databases.')
        clear_cache_button.connect('clicked', lambda btn: self.clear('all'))

        # clear_cookies_button = Gtk.Button('Clear All Cookies')
        # clear_cookies_button.set_tooltip_text('Clear All Cookies')
        # clear_cookies_button.connect('clicked',
        #                              lambda btn: self.clear('cookies'))

        self._clear_grid = Gtk.Grid()
        self._clear_grid.set_column_spacing(6)
        self._clear_grid.set_column_homogeneous(True)
        self._clear_grid.attach(clear_cache_button, 1, 0, 1, 1)
        # self._clear_grid.attach(clear_cookies_button, 1, 0, 1, 1)
        self._clear_grid.show_all()

        self.set_row_spacing(6)
        self.attach(scroll, 0, 0, 5, 1)
        self.attach(self._clear_grid, 4, 1, 1, 1)
        self.set_margin_bottom(6)
        self.set_margin_top(6)
        self.set_margin_start(6)
        self.set_margin_end(6)

        self.show_all()

        self.add_str_setting('home-uri', self._profile.home_uri,
                              'Homepage URI',
                              'The default homepage.')
        self.add_bool_setting('hide-address-bar',
                              self._profile.hide_address_bar,
                              'Auto Hide Address Bar',
                              'Hide the address bar when it is not active.')
        self.add_bool_setting('clear-on-exit', self._profile.clear_on_exit,
                              'Clear All Data On Exit',
                              'Clear cache, site database, and cookies on exit.')
        self.add_bool_setting('enable-user-stylesheet',
                               self._profile.enable_user_stylesheet,
                              'Use User Stylesheet',
                              'Apply the user-stylesheet.css to every webpage.')
        self.add_settings(self._profile.web_view_settings)

    def add_settings(self, settings: dict):
        """ Add settings to the list.

        """

        # Sort in this order bool, int, str, other.
        key_func = lambda tup: \
            '%s%s' % ({bool: 0, int: 1, str: 3}.get(type(tup[1]), 4), tup[0])

        for setting, value in sorted(settings.items(), key=key_func):
            if type(value) == str:
                self.add_str_setting(setting, value)
            elif type(value) == bool:
                self.add_bool_setting(setting, value)
            elif type(value) == int:
                self.add_int_setting(setting, value)

    def add_bool_setting(self, setting: str, value: bool, title: str = '',
                         tooltip: str = ''):
        """ Add a setting to the listbox.

        """

        if not title:
            title = setting.replace('-', ' ', setting.count('-')).title()
        if not tooltip:
            tooltip = title

        label = Gtk.Label(title)
        label.set_tooltip_text(tooltip)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.set_margin_start(3)
        switch = Gtk.Switch()
        switch.set_active(value)
        switch.set_margin_end(6)
        switch.connect('notify::active', self._switch_active, setting)
        grid = Gtk.Grid()
        grid.attach(label, 0, 0, 1, 1)
        grid.attach(switch, 1, 0, 1, 1)
        grid.show_all()

        self._settings_grid.attach_next_to(grid, None, Gtk.PositionType.BOTTOM,
                                           1, 1)

    def add_str_setting(self, setting: str, value: str, title: str = '',
                        tooltip: str = ''):
        """ Show the user agent setting.

        """

        if not title:
            title = setting.replace('-', ' ', setting.count('-')).title()
        if not tooltip:
            tooltip = title

        entry = Gtk.Entry()
        entry.set_tooltip_text(tooltip)
        entry.set_margin_start(3)
        entry.set_margin_top(3)
        entry.set_margin_bottom(3)
        entry.set_hexpand(True)
        entry.set_text(value)
        entry.connect('activate', self._setting_changed, entry.get_text, setting)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('emblem-ok-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        apply_button = Gtk.Button()
        apply_button.set_margin_end(6)
        apply_button.set_margin_top(3)
        apply_button.set_margin_bottom(3)
        apply_button.set_tooltip_text('Apply')
        apply_button.set_image(button_img)
        apply_button.connect('clicked', self._setting_changed,
                            entry.get_text, setting)

        grid = Gtk.Grid()
        grid.get_style_context().add_class('linked')
        grid.attach(entry, 0, 0, 1, 1)
        grid.attach(apply_button, 1, 0, 1, 1)

        frame_label = Gtk.Label(f'<b>{title}</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self._settings_grid.attach_next_to(frame, None,
                                           Gtk.PositionType.BOTTOM, 1, 1)

    def add_int_setting(self, setting: str, value: int, title: str = '',
                        tooltip: str = ''):
        """ Show the user agent setting.

        """

        if not title:
            title = setting.replace('-', ' ', setting.count('-')).title()
        if not tooltip:
            tooltip = title

        adjustment = Gtk.Adjustment(value, 0, 100, 1, 0, 0)
        spin_button = Gtk.SpinButton.new(adjustment, 1, 0)
        spin_button.set_tooltip_text(tooltip)
        spin_button.set_margin_start(3)
        spin_button.set_margin_top(3)
        spin_button.set_margin_bottom(3)
        spin_button.set_margin_end(5)
        spin_button.set_hexpand(True)
        spin_button.set_value(value)
        spin_button.connect('value-changed', self._setting_changed,
                            spin_button.get_value_as_int, setting)

        grid = Gtk.Grid()
        grid.get_style_context().add_class('linked')
        grid.attach(spin_button, 0, 0, 1, 1)

        frame_label = Gtk.Label(f'<b>{title}</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self._settings_grid.attach_next_to(frame, None,
                                           Gtk.PositionType.BOTTOM, 1, 1)

    def add_custom_setting(self, widget: object):
        """ Add a custom setting widget.

        """

        self._settings_grid.attach_next_to(widget, None,
                                           Gtk.PositionType.BOTTOM, 1, 1)

    def _setting_changed(self, widget: object, get_value: object, setting: str):
        """ Send the setting value and save it.

        """

        value = get_value()
        if setting == 'home-uri':
            self._profile.home_uri = value
        else:
            self._profile.web_view_settings[setting] = value
        self.emit('setting-changed', setting, value)

    def _switch_active(self, switch: object, prop: object, setting: str):
        """ Send the switch value.

        """

        active = switch.get_property(prop.name)

        if setting == 'clear-on-exit':
            self._profile.clear_on_exit = active
        elif setting == 'hide-address-bar':
            self._profile.hide_address_bar = active
            self.emit('setting-changed', setting, active)
        elif setting == 'enable-user-stylesheet':
            self._profile.enable_user_stylesheet = active
            self.emit('setting-changed', setting, active)
        else:
            self._profile.web_view_settings[setting] = active
            self.emit('setting-changed', setting, active)

    def show_clear_buttons(self, show: bool):
        """ Show the clear buttons.

        """

        self._clear_grid.set_visible(show)

    def clear(self, target: str = 'all'):
        """ Clear cookies, cache, or favicons, or all of them.

        """

        ctx = WebKit2.WebContext.get_default()
        ctx.set_favicon_database_directory()
        data_manager = ctx.get_website_data_manager()
        # print(data_manager.get_property('local-storage-directory'))

        cache_dir = data_manager.get_property('disk-cache-directory')
        cache_path = pathlib.Path(cache_dir)

        favicon_dir = ctx.get_favicon_database_directory()
        favicon_path = pathlib.Path(favicon_dir)

        if target in ['all', 'cookies']:
            logging.info('Clearing Cookies')
            # ctx.get_cookie_manager().delete_all_cookies()
            # data_manager.clear(WebKit2.WebsiteDataTypes.COOKIES, 0, None,
            #                    self._clear_callback, None)
        if target in ['all', 'cache']:
            logging.info(f'Clearing favicon database in {favicon_path}')

            if favicon_path.is_dir():
                ctx.get_favicon_database().clear()
                for f in favicon_path.rglob('*'): f.unlink(missing_ok=True)

            logging.info('Cleared favicon database')

            logging.info(f'Clearing Cache from {cache_path}')
            ctx.clear_cache()
            # data_manager.clear(WebKit2.WebsiteDataTypes.ALL, 0, None, 
            #                    self._clear_callback, None)

            # Just delete the entire path to make sure it is gone.
            if cache_path.is_dir():
                shutil.rmtree(cache_path, ignore_errors=True)

            logging.info('Cleared Cache')

    def _clear_callback(self, data_manager, res, user_data):
        """ Data Manager clear callback.

        """

        logging.info(f'Cleared: {data_manager.clear_finish(res)}')


class ToggleListSettings(Gtk.Grid):
    """ Creates a list of radio button options.  Each option has the ability to
    be removed or edited.

    """

    __gsignals__ = {
            'changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str, str)),
            'default-changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str,)),
            'added': (GObject.SIGNAL_RUN_LAST, None,
                         (str, str)),
            'removed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str)),
            }

    def __init__(self, options_dict: dict, parent: object = None):
        """ Create a list for configuring options.

        """

        super(ToggleListSettings, self).__init__()

        self._parent = parent

        self._last_radio = None
        self._options_dict = options_dict
        self._default_name = ''
        # self._default = ''

        # Change these.
        # self._add_tooltip = 'Add Option'
        # self._edit_tooltip = 'Edit Option'
        # self._remove_tooltip = 'Remove Option'
        # self._frame_text = 'Options Settings'
        #
        # self._add_title = 'Add Option'
        # self._add_name_title = 'Add Name'
        # self._add_uri_title = 'Add URI'
        #
        # self._edit_title = 'Edit Option'
        # self._edit_name_title = 'Edit Name'
        # self._edit_uri_title = 'Edit URI'

        self._options_list = Gtk.ListBox()
        self._options_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._options_list.set_vexpand(True)
        self._options_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._options_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-add-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        add_button = Gtk.Button()
        add_button.set_tooltip_text(self._add_tooltip)
        add_button.set_image(button_img)
        add_button.set_relief(Gtk.ReliefStyle.NONE)
        add_button.connect('clicked', self._add_clicked)

        button_grid = Gtk.Grid()
        button_grid.attach(add_button, 0, 0, 1, 1)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.set_row_homogeneous(False)
        main_grid.attach(scroll, 0, 0, 1, 8)
        main_grid.attach(button_grid, 1, 0, 1, 1)
        main_grid.set_margin_bottom(6)
        main_grid.set_margin_top(6)
        main_grid.set_margin_start(6)
        main_grid.set_margin_end(6)

        frame_label = Gtk.Label(f'<b>{self._frame_text}</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(main_grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self.set_size_request(-1, 150)
        self.attach(frame, 0, 0, 1, 1)

        self.show_all()

        for name, uri in sorted(options_dict.items()):
            self.add_options(name, uri)

    def _add_clicked(self, button: object):
        """ Add a new option.

        """

        name_dialog = EntryDialog(self._add_title, 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title(self._add_name_title)
        name_dialog.set_uri_title(self._add_uri_title)
        result = name_dialog.run()
        if not result: return None

        self.add_options(result['name'], result['uri'])
        self.emit('added', result['name'], result['uri'])

    def add_options(self, name: str, uri: str):
        """ Add an option to the options_list.

        """

        self._options_dict[name] = uri

        radio_button = Gtk.RadioButton.new(None)
        radio_button.set_label(name)
        radio_button.connect('toggled', self._radio_toggled)
        radio_button.set_hexpand(True)
        radio_button.join_group(self._last_radio)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('text-editor-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        edit_button = Gtk.Button()
        edit_button.set_tooltip_text(self._edit_tooltip)
        edit_button.set_image(button_img)
        edit_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text(self._remove_tooltip)
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        button_grid = Gtk.Grid()
        button_grid.attach(radio_button, 0, 0, 1, 1)
        button_grid.attach(edit_button, 1, 0, 1, 1)
        button_grid.attach(remove_button, 2, 0, 1, 1)
        button_grid.show_all()

        self._last_radio = radio_button

        self._options_list.add(button_grid)
        remove_button.connect('clicked', self._remove_clicked, button_grid,
                              radio_button)
        edit_button.connect('clicked', self._edit_clicked, radio_button)

    def _remove_clicked(self, remove_button: object, grid: object,
                        radio_button: object):
        """ Remove this option from the list.

        """

        name = radio_button.get_label()
        uri = self._options_dict.pop(name, None)

        self._options_list.remove(grid.get_parent())

        if self._last_radio == radio_button:
            for button in radio_button.get_group():
                if button != radio_button:
                    self._last_radio = button
                    break
            else:
                self._last_radio = None

        # Remove from group.
        radio_button.join_group(None)

        if self._default_name == name:
            if self._last_radio:
                self.set_default(self._last_radio.get_label())
        self.emit('removed', name, uri)

    def _edit_clicked(self, button: object, radio_button: object):
        """ Remove this option from the list.

        """

        name = radio_button.get_label()
        uri = self._options_dict.pop(name)

        name_dialog = EntryDialog(self._edit_title, 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title(self._edit_name_title)
        name_dialog.set_default_name(name)
        name_dialog.set_uri_title(self._edit_uri_title)
        name_dialog.set_default_uri(uri)
        result = name_dialog.run()
        if not result:
            self._options_dict[name] = uri
        else:
            self._options_dict[result['name']] = result['uri']
            radio_button.set_label(result['name'])
            if self._default_name == name:
                self.set_default(result['name'])
            self.emit('changed', name, result['name'], result['uri'])

    def set_default(self, name: str):
        """ Set the default option.

        """

        if self._last_radio:
            if name in self._options_dict:
                self._default_name = name
                for radio in self._last_radio.get_group():
                    if radio.get_label() == name:
                        radio.set_active(True)
                        break
                self.emit('default-changed', self._options_dict[name])

    def get_all(self):
        """ Return the dict of options engines.

        """

        return self._options_dict

    def get_default(self):
        """ Return the default.

        """

        return self._options_dict.get(self._default_name, self._default)

    def get_default_name(self):
        """ Return the default name.

        """

        return self._default_name

    def _radio_toggled(self, radio_button: object):
        """ Emit if radio_button is active.

        """

        if radio_button.get_active():
            name = radio_button.get_label()
            if name in self._options_dict:
                self._default_name = name
                self.emit('default-changed', self._options_dict[name])


class AgentSettings(ToggleListSettings):
    """ User Agent list and settings.

    """

    def __init__(self, agent_dict: dict, parent: object = None):
        """ Create a list for configuring agent engines.

        """

        self._default = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.110 Safari/537.36'

        # Change these.
        self._add_tooltip = 'Add User Agent'
        self._edit_tooltip = 'Edit User Agent'
        self._remove_tooltip = 'Remove User Agent'
        self._frame_text = 'User Agent Settings'

        self._add_title = 'Add User Agent'
        self._add_name_title = 'Enter Name'
        self._add_uri_title = 'Enter User Agent String'

        self._edit_title = 'Edit User Agent'
        self._edit_name_title = 'Edit Name'
        self._edit_uri_title = 'Edit User Agent String'

        super(AgentSettings, self).__init__(agent_dict, parent)


class SearchSettings(ToggleListSettings):
    """ Search engine list and settings.

    """

    def __init__(self, search_dict: dict, parent: object = None):
        """ Create a list for configuring search engines.

        """

        self._default = 'https://startpage.com/do/search?query=%s'

        # Change these.
        self._add_tooltip = 'Add New Search Engine'
        self._edit_tooltip = 'Edit Search Engine'
        self._remove_tooltip = 'Remove Search Engine'
        self._frame_text = 'Search Settings'

        self._add_title = 'Add Search'
        self._add_name_title = 'Enter Name'
        self._add_uri_title = 'Enter Website URL (%s = search term)'

        self._edit_title = 'Edit Search'
        self._edit_name_title = 'Edit Name'
        self._edit_uri_title = 'Edit Website URL'

        super(SearchSettings, self).__init__(search_dict, parent)


class CheckListSettings(Gtk.Grid):
    """ Creates a list of check button options.  Each option has the ability to
    be removed or edited.

    """

    __gsignals__ = {
            'changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str, str)),
            'set-active': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str, bool)),
            'added': (GObject.SIGNAL_RUN_LAST, None,
                         (str, str)),
            'removed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str)),
            }

    def __init__(self, options_dict: dict, parent: object = None):
        """ Create a list for configuring options.

        """

        super(CheckListSettings, self).__init__()

        self._parent = parent

        self._options_dict = options_dict
        # self._default = ''

        # Change these.
        # self._add_tooltip = 'Add Option'
        # self._edit_tooltip = 'Edit Option'
        # self._remove_tooltip = 'Remove Option'
        # self._frame_text = 'Options Settings'
        #
        # self._add_title = 'Add Option'
        # self._add_name_title = 'Add Name'
        # self._add_data_title = 'Add URI'
        #
        # self._edit_title = 'Edit Option'
        # self._edit_name_title = 'Edit Name'
        # self._edit_data_title = 'Edit URI'

        self._options_list = Gtk.ListBox()
        self._options_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._options_list.set_vexpand(True)
        self._options_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._options_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-add-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        add_button = Gtk.Button()
        add_button.set_tooltip_text(self._add_tooltip)
        add_button.set_image(button_img)
        add_button.set_relief(Gtk.ReliefStyle.NONE)
        add_button.connect('clicked', self._add_clicked)

        button_grid = Gtk.Grid()
        button_grid.attach(add_button, 0, 0, 1, 1)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.set_row_homogeneous(False)
        main_grid.attach(scroll, 0, 0, 1, 8)
        main_grid.attach(button_grid, 1, 0, 1, 1)
        main_grid.set_margin_bottom(6)
        main_grid.set_margin_top(6)
        main_grid.set_margin_start(6)
        main_grid.set_margin_end(6)

        frame_label = Gtk.Label(f'<b>{self._frame_text}</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(main_grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self.set_size_request(-1, 150)
        self.attach(frame, 0, 0, 1, 1)

        self.show_all()

        for name, (data, active) in sorted(options_dict.items()):
            self.add_options(name, data, active)

    def _add_clicked(self, button: object):
        """ Add a new option.

        """

        name_dialog = EntryDialog(self._add_title, 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title(self._add_name_title)
        name_dialog.set_uri_title(self._add_data_title)
        result = name_dialog.run()
        if not result: return None

        self.add_options(result['name'], result['uri'], False)
        name = result['name']
        self.emit('set-active', name, *self._options_dict[name])

    def add_options(self, name: str, data: str, active: bool):
        """ Add an option to the options_list.

        """

        self._options_dict[name] = (data, active)

        check_button = Gtk.CheckButton.new_with_label(name)
        check_button.set_hexpand(True)
        check_button.set_halign(Gtk.Align.START)
        check_button.connect('toggled', self._check_toggled)
        check_button.set_active(active)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('text-editor-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        edit_button = Gtk.Button()
        edit_button.set_tooltip_text(self._edit_tooltip)
        edit_button.set_image(button_img)
        edit_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text(self._remove_tooltip)
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        button_grid = Gtk.Grid()
        button_grid.attach(check_button, 0, 0, 1, 1)
        button_grid.attach(edit_button, 1, 0, 1, 1)
        button_grid.attach(remove_button, 2, 0, 1, 1)
        button_grid.show_all()

        self._options_list.add(button_grid)
        remove_button.connect('clicked', self._remove_clicked, button_grid,
                              check_button)
        edit_button.connect('clicked', self._edit_clicked, check_button)

    def _remove_clicked(self, remove_button: object, grid: object,
                        check_button: object):
        """ Remove this option from the list.

        """

        name = check_button.get_label()
        data, _ = self._options_dict.pop(name, None)

        self._options_list.remove(grid.get_parent())

        self.emit('set-active', name, data, False)
        self.emit('removed', name, data)

    def _edit_clicked(self, button: object, check_button: object):
        """ Remove this option from the list.

        """

        name = check_button.get_label()
        data, active = self._options_dict.pop(name)

        name_dialog = EntryDialog(self._edit_title, 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title(self._edit_name_title)
        name_dialog.set_default_name(name)
        name_dialog.set_uri_title(self._edit_data_title)
        name_dialog.set_default_uri(data)
        result = name_dialog.run()
        if not result:
            # Operation canceld so do nothing.
            self._options_dict[name] = (data, active)
        else:
            # Remove old item.
            self.emit('removed', name, data)

            new_name = result['name']
            self._options_dict[result['name']] = (result['uri'], active)
            check_button.set_label(result['name'])
            # De-activate old.
            self.emit('set-active', name, result['uri'], False)
            # Activate new.
            self.emit('set-active', new_name, *self._options_dict[new_name])

    def get_all(self):
        """ Return the dict of options engines.

        """

        return self._options_dict

    def _check_toggled(self, check_button: object):
        """ Emit if check_button is active.

        """

        name = check_button.get_label()
        if name in self._options_dict:
            data, _ = self._options_dict[name]
            self._options_dict[name] = (data, check_button.get_active())
            self.emit('set-active', name, *self._options_dict[name])


class AdBlockSettings(CheckListSettings):
    """ AdBlock settings.

    """

    def __init__(self, filter_dict: dict, parent: object = None):
        """ Create a list for configuring adblock.

        """

        # Change these.
        self._add_tooltip = 'Add New Filter'
        self._edit_tooltip = 'Edit Filter'
        self._remove_tooltip = 'Remove Filter'
        self._frame_text = 'AdBlock Settings'

        self._add_title = 'Add Filter'
        self._add_name_title = 'Enter Name'
        self._add_data_title = 'Enter Regex'

        self._edit_title = 'Edit Filter'
        self._edit_name_title = 'Edit Name'
        self._edit_data_title = 'Edit Regex'

        super().__init__(filter_dict, parent)


class MediaFilterSettings(CheckListSettings):
    """ Media filter settings.

    """

    def __init__(self, filter_dict: dict, parent: object = None):
        """ Create a list for configuring media filters.

        """

        # Change these.
        self._add_tooltip = 'Add New Filter'
        self._edit_tooltip = 'Edit Filter'
        self._remove_tooltip = 'Remove Filter'
        self._frame_text = 'Media Filter Settings'

        self._add_title = 'Add Filter'
        self._add_name_title = 'Enter Name'
        self._add_data_title = 'Enter Regex'

        self._edit_title = 'Edit Filter'
        self._edit_name_title = 'Edit Name'
        self._edit_data_title = 'Edit Regex'

        super().__init__(filter_dict, parent)


class ContentFilterSettings(CheckListSettings):
    """ Content Filter settings.

    """

    def __init__(self, filter_dict: dict, parent: object = None):
        """ Create a list for configuring content filter files.

        """

        # Change these.
        self._add_tooltip = 'Add New Filter'
        self._edit_tooltip = 'Edit Filter'
        self._remove_tooltip = 'Remove Filter'
        self._frame_text = 'Content Filter Settings'

        self._add_title = 'Add Filter'
        self._add_name_title = 'Enter Name'
        self._add_data_title = 'Enter URI'

        self._edit_title = 'Edit Filter'
        self._edit_name_title = 'Edit Name'
        self._edit_data_title = 'Edit URI'

        super().__init__(filter_dict, parent)


class ContentFilterWhitelistSettings(CheckListSettings):
    """ Content Filter whitelist settings.

    """

    def __init__(self, whitelist_dict: dict, parent: object = None):
        """ Create a list for configuring content filter files.

        """

        # Change these.
        self._add_tooltip = 'Add New URL'
        self._edit_tooltip = 'Edit URL'
        self._remove_tooltip = 'Remove URL'
        self._frame_text = 'Content Filter Whitelist'

        self._add_title = 'Add URL'
        self._add_name_title = 'Enter Name'
        self._add_data_title = 'Enter URI'

        self._edit_title = 'Edit URL'
        self._edit_name_title = 'Edit Name'
        self._edit_data_title = 'Edit URI'

        super().__init__(whitelist_dict, parent)
