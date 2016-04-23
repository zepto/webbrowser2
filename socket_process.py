#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Socket process
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


""" Socket process

"""

import os
import re
import math
import pathlib
import socket
import logging
from multiprocessing import Manager, Pipe
from json import loads as json_loads
from json import dumps as json_dumps

from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
gi_require_version('WebKit2', '4.0')
from gi.repository import WebKit2, Gtk, Gdk, GLib, Pango, Gio, GdkPixbuf

from functions import looks_like_uri, get_config_path, save_dialog
from classes import ChildDict, SettingsMenu, Config
from bookmarks import BookmarkMenu


class MainWindow(object):
    """ The main window.

    """

    def __init__(self, com_pipe: object, com_dict: object,
                 uri_list: list = ['about:blank'], profile: str = 'default'):
        """ Initialize the process.


        """

        self._config = Config('default')
        self._sessions_file = self._config.sessions_file
        self._bookmarks_file = self._config.bookmarks_file

        self._socket = self._config.open_socket(uri_list)
        if not self._socket:
            com_pipe.send(('quit', True))
            return None

        with pathlib.Path(self._sessions_file) as sessions_file:
            tmp_dict = {}
            if sessions_file.exists():
                tmp_dict = json_loads(sessions_file.read_text())
                sessions_file.unlink()
            self._sessions = tmp_dict.get('sessions', [])
            self._last_tab = tmp_dict.get('last-tab', [])

        self._name = 'Web Browser'
        self._find_str = self._config.get('find-str', '')

        self._search = self._config.get('search', {
            'startpage': 'https://startpage.com/do/search?query=%s',
            'default': 'startpage',
            })

        self._web_view_settings = self._config.get('web-view-settings', {
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
            'enable-webaudio': True,
            'enable-webgl': True,
            'enable-accelerated-2d-canvas': True,
            'enable-developer-extras': True,
            })

        self._revived = []
        self._pid_map = {}
        self._events = []
        self._settings_menu = SettingsMenu(self._web_view_settings)
        self._settings_menu.connect('setting-changed', self._web_view_settings_changed)
        self._fixed_address_bar = self._config.get('fixed-address-bar', True)

        button = Gtk.ModelButton.new()
        button.set_label('HELLO')
        button.set_property('margin', 6)
        button.connect('clicked', lambda *a: self._main_popover.hide())
        button.show_all()
        self._main_popover = Gtk.PopoverMenu()
        # self._main_popover.set_modal(False)
        # self._main_popover.set_transitions_enabled(True)
        self._main_popover.add(button)

        self._windows = {}
        self._closed = {}

        screen = Gdk.Screen.get_default()
        width = screen.get_width() // 2
        height = math.floor(screen.get_height() * 9 // 10)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('text-x-generic-symbolic')
        icon_info = Gtk.IconTheme().choose_icon(icon.get_names(), 16,
                                                Gtk.IconLookupFlags.USE_BUILTIN)
        self._html_pixbuf = icon_info.load_icon()

        self._stop_icon = Gio.ThemedIcon.new_with_default_fallbacks(
                'process-stop-symbolic')
        self._refresh_icon = Gio.ThemedIcon.new_with_default_fallbacks(
                'view-refresh-symbolic')
        self._go_icon = Gio.ThemedIcon.new_with_default_fallbacks(
                'go-jump-symbolic')
        self._find_icon = Gio.ThemedIcon.new_with_default_fallbacks(
                'edit-find-symbolic')

        css_provider = Gtk.CssProvider.get_default()
        css_provider.load_from_data(b'''
                #not-found {
                    background: #ff5555;
                }
                #verified {
                    border-color: #9dbf60;
                }
                #unverified {
                    border-color: #DE6951;
                }
                #insecure {
                    border-color: #E2A564;
                }
               ''')
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),
                css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._accels = Gtk.AccelGroup()

        accel_dict = {
                ('<Ctrl>t', '<Control><Alt>t', '<Ctrl><Shift>t'): self._new_tab,
                ('<Ctrl>w',): self._close_tab,
                ('<Ctrl><Alt>r',): lambda *a: com_pipe.send(('refresh', True)),
                ('<Ctrl>l',): self._focus_address_entry,
                ('<Ctrl>m',): lambda *a: self._minimize_tab(self._get_current_child()),
                ('<Ctrl>h',): lambda *a: self._hide_tab(self._get_current_child()),
                ('<Ctrl>f',): self._findbar_toggle,
                ('<Ctrl>d',): lambda *a: self._bookmark_menu.bookmark_page(),
                ('<Ctrl>y',): self._yank_hover,
                ('<Ctrl>g', '<Ctrl><Shift>g'): self._find_next_key,
                ('Escape',): self._escape,
                ('<Ctrl>r', 'F5'): lambda *a: self._get_current_child().send('refresh', True),
                }
        for accel_tup, func in accel_dict.items():
            for accel in accel_tup:
                keyval, modifier = Gtk.accelerator_parse(accel)
                self._accels.connect(keyval, modifier,
                                     Gtk.AccelFlags.VISIBLE,
                                     func)
        for i in range(9):
            self._accels.connect(Gdk.keyval_from_name(str(i)),
                                 Gdk.ModifierType.MOD1_MASK,
                                 Gtk.AccelFlags.VISIBLE,
                                 self._switch_tab)

        self._window = Gtk.Window()
        self._window.set_title(self._name)
        self._window.add_accel_group(self._accels)

        self._window.set_default_size(self._config.get('width', width),
                                      self._config.get('height', height))
        self._window.set_resizable(True)
        self._window.set_icon_name('web-browser')
        self._window.connect('motion-notify-event', self._mouse_move)
        self._window.connect('destroy', self._destroy)
        self._window.connect('delete-event', self._delete_event)
        self._window.connect('size-allocate', self._size_allocate)
        self._window.connect('window-state-event', self._state_event)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('tab-new-symbolic')
        new_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        new_button = Gtk.Button()
        new_button.set_image(new_img)
        new_button.set_focus_on_click(False)
        new_button.set_relief(Gtk.ReliefStyle.NONE)
        new_button.connect('button-release-event', self._new_tab_released)

        start_action_box = Gtk.Grid()
        start_action_box.attach(new_button, 0, 0, 1, 1)
        start_action_box.show_all()

        end_action_box = Gtk.Grid()
        end_action_box.show_all()

        self._tabs = Gtk.Notebook()
        self._tabs.set_action_widget(start_action_box, Gtk.PackType.START)
        self._tabs.set_action_widget(end_action_box, Gtk.PackType.END)
        self._tabs.add_events(Gdk.EventMask.SCROLL_MASK)
        self._tabs.connect('page-reordered', self._tab_reordered)
        self._tabs.connect('page-removed', self._tab_removed)
        self._events.append((self._tabs,
                             self._tabs.connect('switch-page',
                                                self._tab_switched)))
        self._tabs.connect('scroll-event', self._tab_scrolled)
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)

        window_grid = Gtk.Grid()
        window_grid.attach(self._tabs, 0, 0, 1, 1)

        self._window.add(window_grid)
        self._window.show_all()

        self._bookmark_menu = BookmarkMenu(self._bookmarks_file, self._window)
        self._bookmark_menu.connect('bookmark-release-event', self._bookmark_release)
        self._bookmark_menu.connect('open-folder', self._bookmark_open_folder)
        self._bookmark_menu.connect('new-bookmark', self._bookmark_new)
        self._bookmark_menu.connect('tab-list', self._bookmark_tab_list)

        self._pipe = com_pipe
        self._dict = com_dict

        self._recv = self._pipe.recv

        GLib.io_add_watch(self._pipe.fileno(), GLib.IO_IN,
                                self._recieve)

        self._restore_session_list(self._sessions)
        self._sessions = []

        for uri in uri_list:
            if not self._windows and uri == 'about:blank':
                pid = self._new_proc(self._make_tab(uri=uri, focus=True)[0])

        GLib.io_add_watch(self._socket.fileno(), GLib.IO_IN,
                          self._handle_extern_signal)

    def _make_tab(self, uri: str = 'about:blank', focus: bool = False,
                  private: bool = True, index: int = -1):
        """ Make a tab.

        """

        main_pipe, child_pipe = Pipe()
        com_dict = Manager().dict({
            'private': private,
            'web-view-settings': self._web_view_settings,
            'search-url': self._search[self._search['default']],
            })

        socket_id, child = self._add_tab(main_pipe, com_dict, focus, uri=uri,
                                         index=index)

        com_dict[socket_id] = child_pipe

        return com_dict, child

    def _web_view_settings_changed(self, settings_menu: object, setting: str,
                                   value: object):
        """ Send the changes to all children processes.

        """

        self._web_view_settings[setting] = value
        self._send_all('web-view-settings', (setting, value))

    def _size_allocate(self, window: object, allocation: object):
        """ Save the window size.

        """

        width, height = window.get_size()
        self._config['width'] = width
        self._config['height'] = height

        return False

    def _state_event(self, window: object, event: object):
        """ Save state.

        """

        if event.new_window_state & Gdk.WindowState.TILED:
            state = Gdk.WindowState.TILED
        return False

    def _close_child(self, child: dict):
        """ Close a tab.

        """

        child.socket.disconnect(child['plug-removed'])

        try:
            child.send('close', True)
        except BrokenPipeError as err:
            logging.error('Broken Pipe: {err}'.format(**locals()))

    def _delete_event(self, window: object, event: object):
        """ Try to close all tabs first.

        """

        logging.info("DELETE EVENT: {event}".format(**locals()))

        if not event:
            # No event means that the tab-removed callback triggered
            # this event, so destroy the window.
            self._window.destroy()
            return False
        else:
            # Disconnect some event handlers.
            for widget, event_id in self._events: widget.disconnect(event_id)

            # Save all open sessions.
            self._sessions = []
            for child in self._windows.values():
                child.send('get-session', True)
                signal, data = child.recv()
                logging.info("GETTING SESSION {signal}".format(**locals()))
                if signal == 'session-data' and data:
                    child.save_session(data)

            with pathlib.Path(self._sessions_file) as sessions_file:
                json_str = json_dumps({
                    'sessions': self._sessions,
                    'last-tab': self._last_tab,
                    }, indent=4)
                sessions_file.write_text(json_str)

            logging.info("CLOSING ALL TABS")
            # Send the close signal to all tabs.
            [child.close() for child in self._windows.values()]

        # Don't let the window be destroyed until all the tabs are
        # closed.
        return True

    def _destroy(self, window: object):
        """ Quit

        """

        logging.info("DESTROY")

        self._config['web-view-settings'] = self._settings_menu.get_config()

        # Save the config.
        self._config['web-view-settings'] = self._web_view_settings
        self._config['search'] = self._search
        self._config.save_config()

        Gtk.main_quit()
        self._send('quit', True)

        # Close and remove the socket file.
        self._config.close_socket()

    def run(self):
        """ Run Gtk.main()

        """

        if self._socket: Gtk.main()

    def _restore_session_list(self, session_list: list):
        """ Restore a list of sessions.

        """

        for session in sorted(session_list, key=lambda i: i['index']):
            self._restore_session(session)

    def _restore_session(self, session: dict):
        """ Restore the sessons in sessions.

        """

        pid = session.get('pid', 0)
        private = session.get('private', True)

        if pid in self._pid_map:
            # Find the child with the same pid as the session to be
            # restored.
            for child in self._windows.values():
                if child.pid == self._pid_map[pid]:
                    break
        else:
            # This is the first session from this pid to be restored, so
            # start a new process for it.
            com_dict, child = self._make_tab(private=private,
                                             focus=session['focus'])
            new_pid = self._new_proc(com_dict)
            self._pid_map[pid] = new_pid
            child.pid = new_pid
            child.set_state(session['state'])
            self._tabs.reorder_child(child.tab_grid, session['index'])
        child.send('restore-session', session)

    def _save_session(self, child: dict, session_data: object):
        """ Save the session data for child.

        """

        session_dict = {
                'session-data': session_data,
                'index': self._tabs.page_num(child.tab_grid),
                'state': child.state,
                'pid': child.pid,
                'private': child.private,
                'focus': child.focus,
                'title': child.title,
                }
        self._sessions.append(session_dict)

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        signal, data = window.recv()

        debug_list = ['mouse-motion', 'back-forward-list', 'can-go-back',
                      'can-go-forward', 'is-secure', 'icon-bytes',
                      'estimated-load-progress', 'hover-link',
                      'session-data']
        if signal in debug_list:
            logging.debug("_CALLBACK: {signal} => {data}".format(**locals()))
        else:
            logging.info("_CALLBACK: {signal} => {data}".format(**locals()))

        if signal == 'closed' or signal == 'terminate' and data:
            socket_id = data['socket-id']
            pid = data['pid']

            self._closed[pid] = self._windows.pop(socket_id).com_dict

            if signal == 'terminate':
                try:
                    while window.com_pipe.poll(): sig, _ = window.recv()
                except ConnectionResetError as err:
                    logging.error(err)
                self._closed.pop(pid, None)
                logging.info('Sending terminate for: {pid}'.format(**locals()))
                self._send('terminate', pid)

            logging.info('CLOSED DICT: {self._closed}'.format(**locals()))

            self._tabs.remove_page(self._tabs.page_num(window.tab_grid))

            window.com_pipe.close()

            return False

        if signal == 'mouse-motion':
            window.address_bar.set_visible(self._fixed_address_bar)

        if signal == 'pid':
            window.pid = data
            if window.uri != 'about:blank': window.send('open-uri', window.uri)
            self._update_title(window)

        if signal == 'tab-info':
            logging.info('TAB_INFO: {data}'.format(data=data))
            socket_id, child = self._add_tab(data['com-pipe'],
                                             data['com-dict'], data['focus'],
                                             uri=data['uri'])
            child.update(data)
            self._windows[socket_id] = child
            child.send('socket-id', socket_id)
            self._update_title(child)

        if signal == 'create-tab':
            pid = self._new_proc(self._make_tab(**data)[0])

        if signal == 'title':
            window['title'] = data if data else 'about:blank'
            self._update_title(window)

        if signal == 'icon-bytes':
            if data:
                loader = GdkPixbuf.PixbufLoader()
                loader.set_size(16, 16)
                loader.write(data)
                loader.close()
                pixbuf = loader.get_pixbuf()
            else:
                pixbuf = self._html_pixbuf
            window['icon-image'] = pixbuf
            window['icon'].set_from_pixbuf(pixbuf)

        if signal == 'load-status' and data == 0:
            window.address_entry.set_name('')
            window.address_entry.set_text(window.uri)
            window.address_entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                             self._stop_icon)
            window.address_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                                 'Stop loading page.')
            window.icon_stack.set_visible_child_name('spinner')
            window.icon_stack.get_child_by_name('spinner').start()
            window.insecure_content = False
        elif signal == 'load-status' and data == 3:
            window.address_entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                             self._refresh_icon)
            window.address_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                               'Reload current address.')
            window.icon_stack.set_visible_child_name('icon')
            window.icon_stack.get_child_by_name('spinner').stop()
            window.address_entry.set_progress_fraction(0)

        if signal == 'uri' and data:
            window['uri'] = data
            window.address_entry.set_text('' if data == 'about:blank' else data)

        if signal == 'estimated-load-progress':
            window.address_entry.set_progress_fraction(data)
            if data == 1.0: window.address_entry.set_progress_fraction(0)

        if signal == 'hover-link':
            window['hover-uri'] = data['uri']

        if signal == 'is-playing-audio':
            window['playing-icon'].set_visible(data)

        if signal == 'is-secure':
            insecure_str = ''
            verified, issuer_known, certificate, flags = data
            logging.info("ISSUER KNOWN: {issuer_known}".format(**locals()))

            window.cert_data = data if certificate else ()

            if verified:
                verified_str = 'Page has a verified certificate.'
                window.address_entry.set_name('verified')
            else:
                verified_str = 'Page has an invalid or un-verified certificate.'
                window.address_entry.set_name('unverified')

            if verified and window.get('insecure-content', True):
                insecure_str = '  Page contains insecure content.'
                window.address_entry.set_name('insecure')

            if not window.uri.startswith('https'):
                verified_str = 'Page is insecure.'
                window.address_entry.set_name('unverified')

            tooltip_text = '{verified_str} {insecure_str}'.format(**locals())
            window.address_entry.set_tooltip_text(tooltip_text)

        if signal == 'insecure-content':
            window.insecure_content = data

        if signal == 'can-go-back':
            window['back-button'].set_sensitive(data)
        if signal == 'can-go-forward':
            window['forward-button'].set_sensitive(data)

        if signal == 'find-failed':
            window['find-entry'].set_name('not-found' if data else '')

        if signal == 'private':
            window.private = data
            self._update_title(window)

        if signal == 'back-forward-list':
            back_list, current_dict, forward_list = data
            window.back_list = back_list
            window.current = current_dict
            window.forward_list = forward_list

        if signal == 'is-loading':
            window.is_loading = data

        if signal == 'session-data':
            logging.info("Recieved Session Data")
            window.session_data = data
            window.save_session(data)

        if signal == 'download':
            context = WebKit2.WebContext.get_default()
            download = context.download_uri(data['uri'])
            download.connect('created-destination', self._download_created_destination)
            download.connect('decide-destination', self._download_decide_destination)
            download.connect('failed', self._download_failed)
            download.connect('finished', self._download_finished)
            download.connect('notify::response', self._download_response)
            download.connect('notify::estimated-progress', self._download_progress)

        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """

        signal, data = self._pipe.recv()
        logging.info('RECIEVE: {signal} => {data}'.format(**locals()))

        if signal == 'add-tab':
            pid = self._new_proc(self._make_tab(**data)[0])

        return True

    def _download_created_destination(self, download: object, destination: str):
        """ The destination was decided on.

        """

        logging.info('DOWNLOAD DESTINATION {destination}'.format(**locals()))

    def _download_decide_destination(self, download: object,
                                     suggested_filename: str) -> bool:
        """ Get a filename to save to.

        """

        logging.info('DOWNLOAD TO {suggested_filename}'.format(**locals()))
        folder = GLib.get_user_special_dir(GLib.USER_DIRECTORY_DOWNLOAD)
        filename = save_dialog(suggested_filename, folder, self._window,
                               'Download To')
        if not filename:
            download.cancel()
            return True

        logging.info('Setting it to {filename}'.format(**locals()))
        download.set_destination(GLib.filename_to_uri(filename))

        return False

    def _download_failed(self, download: object, error: object):
        """ Download failed.

        """

        logging.error('DOWNLOAD FAILED: {error}'.format(**locals()))

    def _download_finished(self, download: object):
        """ Download finished.

        """

        logging.info('DOWNLOAD FINISHED')

    def _download_response(self, download: object, response: object):
        """ Download response changed.

        """

        uri = download.get_property(response.name).get_uri()
        logging.info('DOWNLOAD RESPONSE: {uri}'.format(**locals()))

    def _download_progress(self, download: object, progress: float):
        """ The download progress.

        """

        progress = download.get_property(progress.name)
        logging.info('DOWNLOAD PROGRESS: {progress}'.format(**locals()))

    def _update_title(self, child: dict):
        """ Update the window title.

        """

        child.private_str = 'Private' if child.private else ''
        child.title_str = '{title} (pid: {pid}) {private_str}'.format(**child)
        child.label.set_text(child.title_str)
        child.event_box.set_tooltip_text(child.title_str)
        if child == self._get_current_child():
            self._window.set_title('{child.title-str} - {self._name}'.format(**locals()))

    def _send(self, signal: str, data: object):
        """ Send signal and data using the main pipe.

        """

        self._pipe.send((signal, data))

    def _send_all(self, signal: str, data: object):
        """ Send a signal to all child processes.

        """

        for child in self._windows.values():
            try:
                child.send(signal, data)
            except Exception as err:
                logging.error(err)

    def _add_tab(self, com_pipe: object, com_dict: object,
                 focus: bool = False, uri: str = 'about:blank',
                 index: int = -1, **kwargs):
        """ Add Tab.

        """

        child = ChildDict(kwargs)

        find_entry = Gtk.Entry()

        icon = Gio.ThemedIcon.new_with_default_fallbacks('go-down-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        find_next = Gtk.Button()
        find_next.set_image(btn_img)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('go-up-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        find_prev = Gtk.Button()
        find_prev.set_image(btn_img)

        item_box = Gtk.Grid()
        item_box.get_style_context().add_class('linked')
        item_box.attach(find_entry, 0, 0, 1, 1)
        item_box.attach_next_to(find_prev, find_entry, Gtk.PositionType.RIGHT, 1, 1)
        item_box.attach_next_to(find_next, find_prev, Gtk.PositionType.RIGHT, 1, 1)
        box_item = Gtk.ToolItem()
        box_item.add(item_box)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('window-close-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        find_close = Gtk.Button()
        find_close.set_image(btn_img)
        find_close.set_relief(Gtk.ReliefStyle.NONE)

        close_item = Gtk.ToolItem()
        close_item.add(find_close)

        space_item = Gtk.ToolItem()
        space_item.set_expand(True)

        find_bar = Gtk.Toolbar()
        find_bar.set_icon_size(Gtk.IconSize.MENU)
        find_bar.add(box_item)
        find_bar.add(space_item)
        find_bar.add(close_item)

        address_entry = Gtk.Entry()
        address_entry.set_tooltip_text('Enter address or search string')
        address_entry.set_placeholder_text("Enter address or search string")
        entry_icons = (
                (
                    'user-bookmarks-symbolic',
                    Gtk.EntryIconPosition.PRIMARY,
                    'Open bookmark menu.',
                ),
                (
                    'go-jump-symbolic',
                    Gtk.EntryIconPosition.SECONDARY,
                    'Go to address or search for address bar text.',
                )
                )

        for icon_name, pos, tooltip in entry_icons:
            icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)
            address_entry.set_icon_from_gicon(pos, icon)
            address_entry.set_icon_tooltip_text(pos, tooltip)
            address_entry.set_icon_sensitive(pos, True)

        address_item = Gtk.ToolItem()
        address_item.set_expand(True)
        address_item.add(address_entry)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('go-previous-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        back_button = Gtk.Button()
        back_button.set_image(btn_img)
        back_button.set_relief(Gtk.ReliefStyle.NONE)
        back_button.set_sensitive(False)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('go-next-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        forward_button = Gtk.Button()
        forward_button.set_image(btn_img)
        forward_button.set_relief(Gtk.ReliefStyle.NONE)
        forward_button.set_sensitive(False)

        history_grid = Gtk.Grid()
        history_grid.attach(back_button, 0, 0, 1, 1)
        history_grid.attach_next_to(forward_button, back_button,
                                   Gtk.PositionType.RIGHT, 1, 1)

        button_item = Gtk.ToolItem()
        button_item.add(history_grid)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('open-menu-symbolic')
        menu_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        menu_button = Gtk.MenuButton()
        menu_button.set_popover(self._main_popover)
        menu_button.set_image(menu_img)
        menu_button.set_relief(Gtk.ReliefStyle.NONE)

        menu_item = Gtk.ToolItem()
        menu_item.add(menu_button)

        address_bar = Gtk.Toolbar()
        address_bar.set_hexpand(True)
        address_bar.set_valign(Gtk.Align.START)
        address_bar.add(button_item)
        address_bar.add(address_item)
        address_bar.add(Gtk.SeparatorToolItem())
        address_bar.add(menu_item)

        label = Gtk.Label('about:blank')
        label.set_margin_top(7)
        label.set_margin_bottom(5)
        label.set_ellipsize(Pango.EllipsizeMode.END)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('window-close-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        tab_close_btn = Gtk.Button()
        tab_close_btn.set_image(btn_img)
        tab_close_btn.set_relief(Gtk.ReliefStyle.NONE)
        tab_close_btn.set_margin_end(6)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('audio-volume-medium-symbolic')
        playing_icon = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.MENU)
        playing_icon.set_margin_top(6)
        playing_icon.set_margin_bottom(6)

        icon = Gtk.Image()
        icon.set_from_pixbuf(self._html_pixbuf)

        spinner = Gtk.Spinner()
        icon_stack = Gtk.Stack()
        icon_stack.set_margin_top(6)
        icon_stack.set_margin_bottom(6)
        icon_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        icon_stack.set_transition_duration(300)
        icon_stack.add_named(icon, 'icon')
        icon_stack.add_named(spinner, 'spinner')
        icon_stack.set_visible_child_name('icon')

        label_grid = Gtk.Grid()
        label_grid.set_column_spacing(6)
        label_grid.attach(icon_stack, 0, 0, 1, 1)
        label_grid.attach_next_to(label, icon_stack, Gtk.PositionType.RIGHT, 1,
                                  1)
        label_grid.attach_next_to(playing_icon, label, Gtk.PositionType.RIGHT,
                                  1, 1)
        label_grid.attach_next_to(tab_close_btn, playing_icon,
                                  Gtk.PositionType.RIGHT, 1, 1)

        eventbox= Gtk.EventBox()
        eventbox.add_events(Gdk.EventMask.SCROLL_MASK)
        eventbox.add(label_grid)
        eventbox.show_all()
        playing_icon.hide()

        socket = Gtk.Socket()

        overlay = Gtk.Overlay()
        overlay.set_name('overlay')
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        overlay.add_overlay(socket)
        if not self._fixed_address_bar:
            overlay.add_overlay(address_bar)

        tab_grid = Gtk.Grid()
        if self._fixed_address_bar:
            tab_grid.attach(address_bar, 0, 0, 1, 1)
        tab_grid.attach(overlay, 0, 1, 1, 1)
        tab_grid.show_all()
        tab_grid.attach_next_to(find_bar, overlay, Gtk.PositionType.BOTTOM, 1, 1)

        insert_at = index if focus else self._tabs.get_current_page() + 1
        index = self._tabs.insert_page(tab_grid, eventbox, insert_at)
        self._tabs.set_tab_reorderable(tab_grid, True)

        socket_id = socket.get_id()

        child.update({
            'close': lambda: self._close_child(child),
            'com-pipe': com_pipe,
            'com-dict': com_dict,
            'send': lambda signal, data: com_pipe.send((signal, data)),
            'recv': com_pipe.recv,
            'is-loading': False,
            'pid': 0,
            'uri': uri,
            'title': uri,
            'index': index,
            'focus': focus,
            'private': True,
            'private-str': 'Private',
            'title-str': '{title} (pid: 0) Private'.format(**child),
            'cert-data': (False, False, {}, 0),
            'back-list': [],
            'current-dict': {},
            'forward-list': [],
            'icon-stack': icon_stack,
            'address-bar': address_bar,
            'back-button': back_button,
            'forward-button': forward_button,
            'spinner': spinner,
            'icon': icon,
            'icon-image': self._html_pixbuf,
            'address-entry': address_entry,
            'label': label,
            'socket': socket,
            'event_box': eventbox,
            'tab_grid': tab_grid,
            'close-button': tab_close_btn,
            'label_grid': label_grid,
            'socket-id': socket_id,
            'playing-icon': playing_icon,
            'find-entry': find_entry,
            'find-bar': find_bar,
            'history-menu': Gtk.Menu(),
            'hidden-width': 0,
            'minimized-width': 6 + 16 + 16,
            'normal-width': 150 + 16 + 16,
            'state': {'minimized': False, 'hidden': False},
            'set-state': lambda state: self._set_state(child, state),
            'session-data': b'',
            'save-session': lambda data: self._save_session(child, data),
            })

        eventbox.set_size_request(child.normal_width, -1)

        self._windows[socket_id] = child

        find_close.connect('clicked', lambda btn: find_bar.hide())
        back_button.connect('button-release-event', self._back_released, child)
        forward_button.connect('button-release-event', self._forward_released,
                               child)
        child['plug-removed'] = socket.connect('plug-removed',
                                               self._plug_removed, child)
        socket.connect('plug-added', self._plug_added, child)
        eventbox.connect('button-press-event', self._tab_button_press, child)
        eventbox.connect('button-release-event', self._tab_button_release,
                         child)
        address_entry.connect('activate',
                              lambda e: child.send('open-uri', e.get_text()))
        address_entry.connect('icon-release', self._address_entry_icon_release,
                              child)
        address_entry.connect('changed', self._address_entry_changed, child)
        find_entry.connect('activate', self._find, child)
        find_entry.connect('changed', self._find, child)
        find_next.connect('button-release-event', self._find_next_button,
                          child)
        find_prev.connect('button-release-event', self._find_prev_button,
                          child)
        tab_close_btn.connect('button-release-event', self._tab_button_release,
                              child)

        child['event-source-id'] = GLib.io_add_watch(com_pipe.fileno(),
                                                     GLib.IO_IN,
                                                     self._callback, child)

        if focus:
            self._tabs.set_current_page(index)
            address_entry.grab_focus()

        return socket_id, child

    def _set_state(self, child: dict, state: dict):
        """ Set the state of child tab.

        """

        if state.get('hidden', False):
            self._hide_tab(child)
        if state.get('minimized', False):
            self._minimize_tab(child)

    def _yank_hover(self, accels: object, window: object, keyval: object,
                    flags: object):
        """ Put the last uri that was hovered over in the clipboard.

        """

        child = self._get_current_child()
        if 'hover-uri' in child:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(child.hover_uri, -1)

    def _mouse_move(self, window: object, event: object):
        """ Hide/unhide address-bar.

        """

        if not self._fixed_address_bar:
            child = self._get_current_child()
            child.address_bar.show_all()
            child.address_entry.grab_focus()

    def _escape(self, accels: object, window: object, keyval: object, flags: object):
        """ Do stuff.

        """

        child = self._get_current_child()
        if child.address_entry.has_focus():
            uri_str = '' if child.uri == 'about:blank' else child.uri
            child.address_entry.set_text(uri_str)
            icon = self._stop_icon if child.is_loading else self._refresh_icon
            child.address_entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                                    icon)
            if not self._fixed_address_bar:
                child.address_bar.hide()
        elif child.find_entry.has_focus():
            self._findbar_toggle()
        else:
            child.send('stop', True)

    def _address_entry_changed(self, entry: object, child: dict):
        """ Changes secondary icon depending on if entry has focus or not.

        """

        entry_uri = entry.get_text()
        is_uri = (entry_uri == child.uri)
        icon = self._stop_icon if child.is_loading else self._refresh_icon
        entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                  icon if is_uri else self._go_icon)
        if is_uri:
            if icon == self._stop_icon:
                tooltip_text = 'Stop loading page.'
            else:
                tooltip_text = 'Reload current address.'
        else:
            tooltip_text = 'Go to address in address entry.'
            if not looks_like_uri(entry_uri):
                entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                          self._find_icon)
                tooltip_text = 'Search for text in address entry.'

        child.address_entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                                  tooltip_text)

    def _findbar_toggle(self, *args):
        """ Toggle findbar visibility.

        """

        child = self._get_current_child()
        find_bar = child['find-bar']
        find_entry = child['find-entry']

        if find_bar.is_visible():
            if find_entry.has_focus():
                child.send('find-finish', True)
                find_bar.hide()
            else:
                find_entry.grab_focus()
        else:
            if self._find_str: find_entry.set_text(self._find_str)
            find_bar.show_all()
            find_entry.grab_focus()

    def _find(self, entry: object, child: dict):
        """ Search the page.

        """

        self._find_str = entry.get_text()
        self._config['find-str'] = self._find_str
        child.send('find', entry.get_text())

    def _find_next_key(self, accels: object, window: object, keyval: object,
                       flags: object):
        """ Find next.

        """

        child = self._get_current_child()
        find_bar = child['find-bar']
        find_entry = child['find-entry']

        if self._find_str and not find_entry.get_text():
            find_entry.set_text(self._find_str)

        if not find_bar.is_visible():
            find_bar.show_all()
            find_entry.grab_focus()

        if flags & Gdk.ModifierType.SHIFT_MASK:
            child.send('find-prev', find_entry.get_text())
        else:
            child.send('find-next', find_entry.get_text())

    def button_release(func):
        """ Wrap button release events.

        """

        def wrapper(self, *args, **kwargs):
            """ Call func only if the mouse is still over widget.

            """

            # Grab the event out of args.
            event = [i for i in args if type(i) == Gdk.EventButton][0]

            # Don't do anything if the pointer was moved off the button.
            if event.window != event.device.get_window_at_position()[0]:
                return False

            return func(self, *args, **kwargs)

        return wrapper

    @button_release
    def _find_next_button(self, button: object, event: object, child: dict):
        """ find next.

        """

        child.send('find-next', child.find_entry.get_text())

    @button_release
    def _find_prev_button(self, button: object, event: object, child: dict):
        """ find prev.

        """

        child.send('find-prev', child.find_entry.get_text())

    def _minimize_tab(self, child: dict):
        """ Hide/unhide the label of the current tab.

        """

        if not child: child = self._get_current_child()
        child.label.set_visible(not child.label.get_visible())
        child.state['minimized'] = not child.label.get_visible()
        if child.label.is_visible():
            child.event_box.set_size_request(child.normal_width, -1)
        elif child.label_grid.get_visible():
            child.event_box.set_size_request(child.minimized_width, -1)

    def _hide_tab(self, child: dict):
        """ Hide/unhide the label_grid of the current tab.

        """

        if not child: child = self._get_current_child()
        child.label_grid.set_visible(not child.label_grid.get_visible())
        child.state['hidden'] = not child.label_grid.get_visible()
        if child.label_grid.is_visible():
            if child.label.is_visible():
                child.event_box.set_size_request(child.normal_width, -1)
            else:
                child.event_box.set_size_request(child.minimized_width, -1)
        else:
            child.event_box.set_size_request(child.hidden_width, -1)

    def _hist_button_do(self, event: object, child: dict, index: int):
        """ Handles going forward or backward in the history if child.

        """

        hist_list = child.forward_list if index == 1 else child.back_list

        if event.button == 3:
            menu = self._make_history_menu(hist_list, True, child)
            menu.popup(None, None, None, None, event.button, event.time)
            logging.debug('{hist_list} {event.time}'.format(**locals()))
        else:
            self._history_go(event, child, index=index)

    @button_release
    def _back_released(self, button: object, event: object, child: dict):
        """ Go Back.

        """

        self._hist_button_do(event, child, -1)
        return False

    @button_release
    def _forward_released(self, button: object, event: object, child: dict):
        """ Go forward.

        """

        self._hist_button_do(event, child, 1)
        return False

    def _make_history_menu(self, hist_list: list, back: bool,
                           child: dict) -> object:
        """ Returns a menu or hist_list ready to popup.

        """

        menu = child.history_menu
        menu.foreach(menu.remove)

        for index, item in enumerate(hist_list):
            item_text = item['title'] if item['title'] else item['uri']
            menu_item = Gtk.MenuItem(item_text)
            menu_item.connect('button-release-event',
                              lambda itm, evnt, chld: \
                                      self._history_go(evnt, chld, itm.index),
                                      child)
            menu_item.index = -(index + 1) if back else len(hist_list) - index
            menu.append(menu_item) if back else menu.insert(menu_item, 0)

        menu.show_all()

        return menu

    def _history_go(self, event: object, child: dict, index: int):
        """ Go to index in child's history.

        """

        hist_list = child.forward_list if index > 0 else child.back_list

        if event.button == 2 or (event.button == 1 and \
                event.state & Gdk.ModifierType.CONTROL_MASK):
            uri = hist_list[abs(index) - 1]['uri']
            settings = {'uri': uri}
            self._open_new_tab(event.state, settings, child)
        else:
            child.send('history-go-to', index)


    @button_release
    def _address_entry_icon_release(self, entry: object, icon_pos: object,
                                    event: object, child: dict):
        """ Do stuff when an icon is clicked.

        """

        if icon_pos == Gtk.EntryIconPosition.PRIMARY:
            self._bookmark_menu.popup(event)
            return False

        if icon_pos == Gtk.EntryIconPosition.SECONDARY:
            if child.is_loading:
                child.send('stop', True)
            elif entry.get_text() not in (child.uri, ''):
                if event.button == 2 or (event.button == 1 and \
                        event.state & Gdk.ModifierType.CONTROL_MASK):
                    self._open_new_tab(event.state, {'uri': entry.get_text()},
                                       child)
                else:
                    child.send('open-uri', entry.get_text())
            else:
                if event.button == 2 or (event.button == 1 and \
                        event.state & Gdk.ModifierType.CONTROL_MASK):
                    self._open_new_tab(event.state, {'uri': child.uri}, child)
                elif event.state & Gdk.ModifierType.MOD1_MASK:
                    child.send('refresh-bypass', True)
                else:
                    child.send('refresh', True)

        return False

    def _open_new_tab(self, flags: object, settings: dict = {},
                      child: dict = {}):
        """ Open a new tab based on event.

        """

        if not child: child = self._get_current_child()

        if not flags & Gdk.ModifierType.SHIFT_MASK:
            if flags & Gdk.ModifierType.MOD1_MASK:
                settings['private'] = False
            pid = self._new_proc(self._make_tab(**settings)[0])
        else:
            child.send('new-tab', settings)

    @button_release
    def _new_tab_released(self, button: object, event: object):
        """ Open a new tab if the mouse is still on the button when it is
        released.

        """

        self._open_new_tab(event.state, settings={'focus': True})

        return True

    def _tab_scrolled(self, notebook: object, event: object):
        """ Switch to next or previous tab.

        """

        # Enable scrolling through the tabs.
        if event.direction == Gdk.ScrollDirection.DOWN:
            self._tabs.next_page()
        else:
            self._tabs.prev_page()

    def _tab_reordered(self, notebook: object, child: object, index: int):
        """ Set the new ordering.

        """

        logging.info('{child} {index}'.format(**locals()))

    def _tab_switched(self, notebook: object, child: object, index: int):
        """ Do stuff when the tab is switched.

        """

        # Do nothing if there are no more tabs.
        if not self._windows: return True


        # Set the previous tabs focus to false.
        self._get_current_child().focus = False

        child_dict = self._get_current_child(child)
        self._window.set_title('{title-str} - {name}'.format(**child_dict,
                                                             name=self._name))
        child_dict.focus = True

        self._last_tab.append(self._tabs.page_num(child))

        if not child_dict.address_entry.get_text():
            child_dict.address_bar.show_all()
            child_dict.address_entry.grab_focus()
        else:
            child_dict.send('grab-focus', True)

        return True

    def _tab_removed(self, notebook: object, child: object, index: int):
        """ Remove page info.

        """

        if notebook.get_n_pages() == 0:
            logging.info("NO MORE PAGES, EXITING")
            self._window.emit('delete-event', None)

    def _to_last_tab(self, old_index: int):
        """ Switch to the correct tab before closing.

        """

        try:
            # Remove all instances of old_index from the last tab list.
            self._last_tab = [i for i in self._last_tab if i != old_index]

            # Switch to the last tab.
            if self._last_tab:
                self._tabs.set_current_page(self._last_tab.pop(-1))
        except:
            pass

    def _tab_button_press(self, eventbox: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 2 or (event.button == 1 and \
                event.state & Gdk.ModifierType.CONTROL_MASK):
            return True

    @button_release
    def _tab_button_release(self, widget: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 2 or (event.button == 1 and \
                event.state & Gdk.ModifierType.CONTROL_MASK) or \
                widget == child.close_button:
            return self._button_close_tab(event, child)

    def _button_close_tab(self, event: object, child: dict):
        """ Close child's tab.

        """

        if self._tabs.get_nth_page(self._tabs.get_current_page()) == child['tab_grid']:
            self._to_last_tab(self._tabs.page_num(child.tab_grid))
        if event.state & Gdk.ModifierType.MOD1_MASK:
            for _, tab in self._windows.items():
                if tab['pid'] == child['pid']:
                    self._tabs.remove_page(self._tabs.page_num(tab['tab_grid']))
            logging.info("sending Terminate")
            self._send('terminate', child['pid'])
        else:
            logging.info("sending Close")
            child.close()

        return True

    def _get_current_child(self, tab_grid: object = None):
        """ Returns the child dict of the current tab.

        """

        if not self._windows:
            return {'title': 'about:blank', 'uri': 'about:blank'}

        if not tab_grid:
            tab_grid = self._tabs.get_nth_page(self._tabs.get_current_page())

        for widget in tab_grid.get_children():
            if widget.get_name() == 'overlay':
                break

        while not widget.get_children(): pass

        socket = widget.get_children()[0]
        return self._windows[socket.get_id()]

    def _new_tab(self, accels: object, window: object, keyval: object,
                 flags: object):
        """ Open a new tab.

        """

        settings = {'focus': True, 'uri': 'about:blank'}
        self._open_new_tab(flags, settings=settings)

    def _close_tab(self, accels: object, window: object, keyval: object,
                   flags: object):
        """ Close tab.

        """

        logging.info('Close tab')
        child = self._get_current_child()
        self._to_last_tab(self._tabs.page_num(child.tab_grid))
        child.close()

    def _switch_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Switch tab.

        """

        logging.info('Switch tab {val} {keyval}'.format(val=(keyval - 49),keyval=keyval))
        if self._tabs.get_n_pages() > (keyval - 49):
            self._tabs.set_current_page(keyval - 49)

    def _focus_address_entry(self, accels: object, window: object,
                             keyval: object, flags: object):
        """ Focus the address bar entry.

        """

        self._get_current_child().address_bar.show_all()
        self._get_current_child().address_entry.grab_focus()

    def _new_proc(self, settings: dict) -> int:
        """ Start a new process using settings and returns the pid.

        """

        self._send('new-proc', settings)
        signal, data = self._recv()
        if signal != 'proc-pid': return 0
        return data

    def _plug_removed(self, socket: object, child: dict):
        """ Re-open removed plug.

        """

        logging.info("PLUG REMOVED: {child.uri}".format(**locals()))
        logging.info("PLUG REMOVED CHILD: {child}".format(**locals()))
        self._send('terminate', child['pid'])

        if not child['pid'] in self._revived:
            self._revived.append(child['pid'])
            logging.info('COMDICT: {child.com_dict}'.format(**locals()))
            child['pid'] = self._new_proc(child.com_dict)

        return True

    def _plug_added(self, socket: object, child: dict):
        """ Log that the plug was added.

        """

        logging.info('PLUG ADDED to {child.tab_grid}'.format(**locals()))
        child.tab_grid.show_all()
        child.find_bar.hide()
        if child.focus:
            self._tabs.set_current_page(child.index)
            child.address_entry.grab_focus()

    def _bookmark_release(self, menu: object, event: object, uri: str):
        """ Open the bookmark.

        """

        child = self._get_current_child()

        if event.button == 2 or (event.button == 1 and \
                event.state & Gdk.ModifierType.CONTROL_MASK):
            settings = {
                    'uri': uri,
                    'focus': False,
                    'index': self._tabs.page_num(child.tab_grid) + 1,
                    }
            self._open_new_tab(event.state, settings, child)
        elif event.button == 1:
            child.send('open-uri', uri)

    def _bookmark_open_folder(self, menu: object, uri_list: list):
        """ Open the uri_list as tabs.

        """

        for uri in uri_list:
            pid = self._new_proc(self._make_tab(uri=uri, focus=True)[0])

    def _bookmark_new(self, menu: object):
        """ Return the current tab.

        """

        child = self._get_current_child()
        return child.uri, child.title

    def _bookmark_tab_list(self, menu: object):
        """ Return a list of the tabs info.

        """

        return [(i.uri, i.title) for _, i in self._windows.items()]

    def _handle_extern_signal(self, source: int, cb_condition: int):
        """ Open new tabs if send the correct signal.

        """

        data = self._socket.recv(4096)
        logging.info("EXTERN SIGNAL: {data}".format(**locals()))

        try:
            signal, data = json_loads(data.decode())
        except:
            signal, data = None, None

        if signal == 'new-tab':
            for uri in data:
                pid = self._new_proc(self._make_tab(uri=uri)[0])

        return True
