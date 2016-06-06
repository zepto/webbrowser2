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
import sys
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
from classes import ChildDict, Profile, SettingsPopover, SearchSettings
from classes import SettingsManager, SessionManager, DownloadManager
from classes import AgentSettings, AdBlockSettings, MediaFilterSettings
from bookmarks import BookmarkMenu


class MainWindow(object):
    """ The main window.

    """

    def __init__(self, com_pipe: object, uri_list: list = ['about:blank'],
                 profile: str = 'default'):
        """ Initialize the process.


        """

        self._is_closing = False

        self._profile = Profile(profile)
        self._socket = self._profile.open_socket(uri_list)
        if not self._socket:
            com_pipe.send(('quit', True))
            return None

        self._name = 'Web Browser'

        self._pid_map = {}
        self._sig_ids = []
        self._windows = {}

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
                ('<Ctrl>w', '<Control><Alt>w'): self._close_tab_key,
                ('<Ctrl><Alt>r',): lambda *a: com_pipe.send(('refresh', True)),
                ('<Ctrl>l',): self._focus_address_entry_key,
                ('<Ctrl>m',): lambda *a: self._minimize_tab(self._get_child_dict()),
                ('<Ctrl>h',): lambda *a: self._hide_tab(self._get_child_dict()),
                ('<Ctrl>f',): self._findbar_toggle,
                ('<Ctrl>d',): lambda *a: self._bookmark_menu.bookmark_page(),
                ('<Ctrl>y',): self._yank_hover,
                ('<Ctrl>g', '<Ctrl><Shift>g'): self._find_next_key,
                ('Escape',): self._escape,
                ('<Ctrl>r', 'F5'): lambda *a: self._get_child_dict().send('refresh', True),
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
                                 self._switch_tab_key)

        self._window = Gtk.Window()
        self._window.set_title(self._name)
        self._window.add_accel_group(self._accels)
        self._window.set_size_request(500, 540)
        self._window.set_default_size(self._profile.get('width', width),
                                      self._profile.get('height', height))
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

        self._agent_settings = AgentSettings(self._profile.user_agents,
                                             self._window)
        self._agent_settings.set_default(self._profile.default_user_agent)
        self._agent_settings.connect('default-changed', self._default_agent_changed)
        self._agent_settings.connect('changed', lambda *a: self._save_config())
        self._agent_settings.connect('added', lambda *a: self._save_config())
        self._agent_settings.connect('removed', lambda *a: self._save_config())

        self._search_settings = SearchSettings(self._profile.search,
                                               self._window)
        self._search_settings.set_default(self._profile.default_search)
        self._search_settings.connect('default-changed', self._default_search_changed)
        self._search_settings.connect('changed', lambda *a: self._save_config())
        self._search_settings.connect('added', lambda *a: self._save_config())
        self._search_settings.connect('removed', lambda *a: self._save_config())

        self._adblock_settings = AdBlockSettings(self._profile.adblock,
                                                 self._window)
        self._adblock_settings.connect('set-active', self._adblock_set_active)

        self._media_filter_settings = MediaFilterSettings(self._profile.media_filters,
                                                      self._window)
        self._media_filter_settings.connect('set-active', self._media_filter_set_active)

        self._settings_manager = SettingsManager(self._profile)
        self._settings_manager.add_custom_setting(self._agent_settings)
        self._settings_manager.add_custom_setting(self._search_settings)
        self._settings_manager.add_custom_setting(self._adblock_settings)
        self._settings_manager.add_custom_setting(self._media_filter_settings)
        self._settings_manager.show_clear_buttons(True)
        self._settings_manager.connect('setting-changed',
                                       self._settings_changed)

        self._session_manager = SessionManager(self._profile)
        self._session_manager.connect('restore-session',
                                      self._restore_session_cb)

        self._download_manager = DownloadManager(self._window)

        self._main_popover = SettingsPopover()
        self._main_popover.set_size_request(500, 500)
        self._main_popover.add_tab(self._settings_manager, 'Settings')
        self._main_popover.add_tab(self._session_manager, 'Closed Sessions')
        self._main_popover.add_tab(self._download_manager, 'Downloads')

        icon = Gio.ThemedIcon.new_with_default_fallbacks('open-menu-symbolic')
        menu_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        menu_button = Gtk.MenuButton()
        menu_button.set_popover(self._main_popover)
        menu_button.set_image(menu_img)
        menu_button.set_relief(Gtk.ReliefStyle.NONE)

        end_action_box = Gtk.Grid()
        end_action_box.attach(menu_button, 0, 0, 1, 1)
        end_action_box.show_all()

        self._tabs = Gtk.Notebook()
        self._tabs.popup_enable()
        self._tabs.set_action_widget(start_action_box, Gtk.PackType.START)
        self._tabs.set_action_widget(end_action_box, Gtk.PackType.END)
        self._tabs.add_events(Gdk.EventMask.SCROLL_MASK)
        self._tabs.connect('page-reordered', self._tab_reordered)
        self._tabs.connect('page-removed', self._tab_removed)
        self._sig_ids.append((self._tabs,
                             self._tabs.connect('switch-page',
                                                self._tab_switched)))
        self._tabs.connect('scroll-event', self._tab_scrolled)
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)

        window_grid = Gtk.Grid()
        window_grid.attach(self._tabs, 0, 0, 1, 1)

        self._window.add(window_grid)
        self._window.show_all()

        self._bookmark_menu = BookmarkMenu(self._profile.bookmarks_file, self._window)
        self._bookmark_menu.connect('bookmark-release-event', self._bookmark_release)
        self._bookmark_menu.connect('open-folder', self._bookmark_open_folder)
        self._bookmark_menu.connect('new-bookmark', self._bookmark_new)
        self._bookmark_menu.connect('tab-list', self._bookmark_tab_list)

        self._pipe = com_pipe

        self._recv = self._pipe.recv

        GLib.io_add_watch(self._pipe.fileno(), GLib.IO_IN, self._recieve)

        # Recover the previous session.
        self._session_manager.restore_all()

        for uri in uri_list:
            if not self._windows and uri == 'about:blank':
                self._new_proc(*self._make_tab(uri=uri, focus=True))

        GLib.io_add_watch(self._socket.fileno(), GLib.IO_IN,
                          self._handle_extern_signal)

    def _make_tab(self, uri: str = 'about:blank', focus: bool = False,
                  private: bool = True, index: int = -1):
        """ Make a tab.

        """

        main_pipe, child_pipe = Pipe()
        socket_id, child = self._add_tab(main_pipe, child_pipe, focus, uri=uri,
                                         index=index, private=private)

        init_dict = {
                'uri': uri,
                'private': private,
                'web-view-settings': self._profile.web_view_settings,
                'search-url': self._search_settings.get_default(),
                'user-agent': self._agent_settings.get_default(),
                'adblock-filters': self._profile.adblock,
                'media-filters': self._profile.media_filters,
                'com-pipe': child_pipe,
                'socket-id': socket_id,
                }

        return init_dict, child

    def save_config(func):
        """ Wrap button release events.

        """

        def wrapper(self, *args, **kwargs):
            """ Call func only if the mouse is still over widget.

            """

            return_val = func(self, *args, **kwargs)
            self._save_config()
            return return_val

        return wrapper

    @save_config
    def _settings_changed(self, settings_manager: object, setting: str,
                          value: object):
        """ Send the changes to all children processes.

        """

        if setting == 'hide-address-bar':
            for child in self._windows.values():
                if value:
                    child.tab_grid.remove(child.address_bar)
                    child.overlay.add_overlay(child.address_bar)
                else:
                    child.overlay.remove(child.address_bar)
                    child.tab_grid.attach(child.address_bar, 0, 0, 1, 1)
        else:
            self._send_all('web-view-settings', (setting, value))

    @save_config
    def _default_agent_changed(self, agent_settings: object, agent: str):
        """ Set the default search engine.

        """

        self._send_all('web-view-settings', ('user-agent', agent))

    @save_config
    def _default_search_changed(self, search_settings: object, uri: str):
        """ Set the default search engine.

        """

        self._send_all('default-search', uri)

    @save_config
    def _adblock_set_active(self, adblock_settings: object, name: str,
                            data: str, active: bool):
        """ Set the default search engine.

        """

        self._send_all('adblock', (name, data, active))

    @save_config
    def _media_filter_set_active(self, adblock_settings: object, name: str,
                            data: str, active: bool):
        """ Set the default search engine.

        """

        self._send_all('media-filter', (name, data, active))

    @save_config
    def _size_allocate(self, window: object, allocation: object):
        """ Save the window size.

        """

        width, height = window.get_size()
        self._profile['width'] = width
        self._profile['height'] = height

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

        for widget, sig_id in child.sig_ids: widget.disconnect(sig_id)

        try:
            child.send('close', True)
        except BrokenPipeError as err:
            logging.error('Broken Pipe: {err}'.format(**locals()))

    def _delete_event(self, window: object, event: object):
        """ Try to close all tabs first.

        """

        logging.info("DELETE EVENT: {event}".format(**locals()))

        if not event:
            if self._is_closing:
                # Save all open sessions before closing them.
                self._session_manager.save_sessions()
            self._session_manager.close()
            # No event means that the tab-removed callback triggered
            # this event, so destroy the window.
            self._window.destroy()
            return False
        else:
            # Disconnect some event handlers.
            for widget, sig_id in self._sig_ids: widget.disconnect(sig_id)

            self._session_manager.clear()
            self._is_closing = True

            # Just store the tab layout, and wait for the tab to close
            # to store the session data.
            for child in self._windows.values(): child.update_session({})

            logging.info("CLOSING ALL TABS")

            # Send the close signal to all tabs.
            for child in self._windows.values(): child.close()

        # Don't let the window be destroyed until all the tabs are
        # closed.
        return True

    @save_config
    def _destroy(self, window: object):
        """ Quit

        """

        logging.info("DESTROY")

        if self._profile.clear_on_exit:
            # Clear all cache and cookies.
            self._settings_manager.clear('all')

        if self._profile.crash_file.exists():
            # Delete the file, because the program didn't crash.
            self._profile.crash_file.unlink()

        self._download_manager.cancel_all()

        Gtk.main_quit()
        self._send('quit', True)

        # Close and remove the socket file.
        self._profile.close_socket()

    def run(self):
        """ Run Gtk.main()

        """

        if self._socket: Gtk.main()

    def _save_config(self):
        """ Save the config.

        """

        self._profile['search'] = self._search_settings.get_all()
        self._profile['default-search'] = self._search_settings.get_default_name()
        self._profile['user-agents'] = self._agent_settings.get_all()
        self._profile['default-user-agent'] = self._agent_settings.get_default_name()
        self._profile.save_config()

    def _restore_session_cb(self, session_manager: object, session: dict):
        """ Restore session.

        """

        self._main_popover.hide()
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
            init_dict, child = self._make_tab(private=private,
                                              focus=session['focus'])
            self._pid_map[pid] = self._new_proc(init_dict, child)
            child.set_state(session['state'])
            child.order = session.get('order', 0)
            self._tabs.reorder_child(child.tab_grid, session['index'])
        child.send('restore-session', session)

    def _update_session(self, child: dict, session_data: bytes = {}) -> dict:
        """ Return a dictionary of session information for child.

        """

        child.session_dict = {
                'session-data': session_data,
                'index': self._tabs.page_num(child.tab_grid),
                'state': child.state,
                'pid': child.pid,
                'private': child.private,
                'focus': child.focus,
                'title': child.title,
                'uri': child.uri,
                'order': child.order,
                }

        return child.session_dict

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        signal, data = window.recv()

        debug_list = ['mouse-motion', 'back-forward-list', 'can-go-back',
                      'can-go-forward', 'is-secure', 'icon-bytes',
                      'estimated-load-progress', 'hover-link',
                      'session-data', 'closed']
        if signal in debug_list:
            logging.debug("_CALLBACK: {signal} => {data}".format(**locals()))
        else:
            logging.info("_CALLBACK: {signal} => {data}".format(**locals()))

        if signal == 'closed':
            session = data['session']
            if session['session-data']:
                # Store the closed session in the session manager, so it
                # can be re-opened.
                window.session_dict.update(session)
                self._session_manager.add_session(window.session_dict)

            if data['is-last']:
                logging.info('Sending terminate for: {pid}'.format(**window))
                self._send('terminate', window.pid)

            self._tabs.remove_page(self._tabs.page_num(window.tab_grid))

            window.com_pipe.close()
            self._windows.pop(window.socket_id).clear()
            logging.info('CLEAR')
            return False

        if signal == 'mouse-motion':
            window.address_bar.set_visible(not self._profile.hide_address_bar)

        if signal == 'tab-info':
            logging.info('TAB_INFO: {data}'.format(data=data))
            socket_id, child = self._add_tab(data['com-pipe'],
                                             data['child-pipe'], data['focus'],
                                             uri=data['uri'],
                                             index=data['index'],
                                             private=data['private'])
            child.update(data)
            self._windows[socket_id] = child
            child.send('socket-id', socket_id)
            self._update_title(child)

        if signal == 'create-tab':
            pid = self._new_proc(*self._make_tab(**data))

        if signal == 'title':
            window.title = data if data else window.uri
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
            entry = window.address_entry
            entry.set_progress_fraction(0)
            entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                      self._refresh_icon)
            entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY,
                                               'Reload current address.')
            window.icon_stack.set_visible_child_name('icon')
            window.icon_stack.get_child_by_name('spinner').stop()

        if signal == 'uri' and data:
            window['uri'] = data
            window.address_entry.set_text('' if data == 'about:blank' else data)

        if signal == 'estimated-load-progress':
            window.address_entry.set_progress_fraction(data if data < 1 else 0)

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

        if signal == 'back-forward-list':
            back_list, current_dict, forward_list = data
            window.back_list = back_list
            window.current = current_dict
            window.forward_list = forward_list

            # Save sessions to restore if the window crashes.
            session_list = [i.session_dict for i in self._windows.values()]
            self._session_manager.save_sessions(session_list, True)

        if signal == 'is-loading':
            window.is_loading = data

        if signal == 'crashed':
            if not self._is_closing: window.update_session(data)

        if signal == 'download':
            self._download_manager.new_download(data['uri'],
                                                start=data.get('start', True))

        if signal == 'session-data':
            if not self._is_closing: window.update_session(data)

        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """

        signal, data = self._pipe.recv()
        logging.info('RECIEVE: {signal} => {data}'.format(**locals()))

        if signal == 'add-tab':
            pid = self._new_proc(*self._make_tab(**data))

        return True

    def _update_title(self, child: dict):
        """ Update the window title.

        """

        child.title_str = '{title} (pid: {pid}) {private_str}'.format(**child)
        child.label.set_text(child.title_str)
        child.event_box.set_tooltip_text(child.title_str)
        if child == self._get_child_dict():
            self._window.set_title('{child.title-str} - {self._name}'.format(**locals()))

        label = Gtk.Label(child.title_str)
        label.set_max_width_chars(48)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        self._tabs.set_menu_label(child.tab_grid, label)

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

    def _add_tab(self, com_pipe: object, child_pipe: object,
                 focus: bool = False, uri: str = 'about:blank',
                 index: int = -1, private: bool = True):
        """ Add Tab.

        """

        child = ChildDict()

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

        address_bar = Gtk.Toolbar()
        address_bar.set_hexpand(True)
        address_bar.set_valign(Gtk.Align.START)
        address_bar.add(button_item)
        address_bar.add(address_item)

        label = Gtk.Label('about:blank')
        label.set_xalign(0)
        label.set_hexpand(True)
        label.set_margin_top(7)
        label.set_margin_bottom(5)
        label.set_ellipsize(Pango.EllipsizeMode.END)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('window-close-symbolic')
        btn_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        tab_close_btn = Gtk.Button()
        tab_close_btn.set_halign(Gtk.Align.END)
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
        eventbox.set_hexpand(False)
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
        if self._profile.hide_address_bar:
            overlay.add_overlay(address_bar)

        tab_grid = Gtk.Grid()
        if not self._profile.hide_address_bar:
            tab_grid.attach(address_bar, 0, 0, 1, 1)
        tab_grid.attach(overlay, 0, 1, 1, 1)
        tab_grid.show_all()
        tab_grid.attach_next_to(find_bar, overlay, Gtk.PositionType.BOTTOM, 1,
                                1)

        i = index if focus or index > -1 else self._tabs.get_current_page() + 1
        index = self._tabs.insert_page(tab_grid, eventbox, i)
        self._tabs.set_tab_reorderable(tab_grid, True)

        socket_id = socket.get_id()

        child.update({
            'close': lambda: self._close_child(child),
            'com-pipe': com_pipe,
            'child-pipe': child_pipe,
            'send': lambda signal, data: com_pipe.send((signal, data)),
            'recv': com_pipe.recv,
            'is-loading': False,
            'pid': 0,
            'uri': uri,
            'title': uri,
            'index': index,
            'focus': focus,
            'private': private,
            'private-str': 'Private' if private else '',
            'title-str': '{title} (pid: {pid}) {private-str}'.format(**child),
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
            'overlay': overlay,
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
            'update-session': lambda data: self._update_session(child, data),
            'session-dict': {},
            'sig-ids': [],
            'order': 0,
            })

        eventbox.set_size_request(child.normal_width, -1)

        self._windows[socket_id] = child

        signal_handlers = (
                (find_close, 'clicked', lambda btn: find_bar.hide()),
                (back_button, 'button-release-event', self._back_released,
                    child),
                (back_button, 'button-press-event',
                    lambda btn, evnt: evnt.button == 3),
                (forward_button, 'button-release-event',
                    self._forward_released, child),
                (forward_button, 'button-press-event',
                    lambda btn, evnt: evnt.button == 3),
                (socket, 'plug-removed', self._plug_removed, child),
                (socket, 'plug-added', self._plug_added, child),
                (eventbox, 'button-press-event', self._tab_button_press,
                    child),
                (eventbox, 'button-release-event', self._tab_button_release,
                    child),
                (address_entry, 'activate',
                    lambda e: child.send('open-uri', e.get_text())),
                (address_entry, 'icon-release',
                    self._address_entry_icon_release, child),
                (address_entry, 'changed', self._address_entry_changed, child),
                (address_entry, 'populate-popup', self._address_populate_popup,
                    child),
                (find_entry, 'activate', self._find, child),
                (find_entry, 'changed', self._find, child),
                (find_next, 'button-release-event', self._find_next_button,
                    child),
                (find_prev, 'button-release-event', self._find_prev_button,
                    child),
                (tab_close_btn, 'button-release-event',
                    self._tab_button_release, child),
                )

        for widget, event, func, *args in signal_handlers:
            child.sig_ids.append((widget, widget.connect(event, func, *args)))

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

        child = self._get_child_dict()
        if 'hover-uri' in child:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(child.hover_uri, -1)

    def _mouse_move(self, window: object, event: object):
        """ Hide/unhide address-bar.

        """

        if self._profile.hide_address_bar:
            child = self._get_child_dict()
            child.address_bar.show_all()
            child.address_entry.grab_focus()

    def _escape(self, accels: object, window: object, keyval: object, flags: object):
        """ Do stuff.

        """

        child = self._get_child_dict()
        if child.address_entry.has_focus():
            uri_str = '' if child.uri == 'about:blank' else child.uri
            child.address_entry.set_text(uri_str)
            icon = self._stop_icon if child.is_loading else self._refresh_icon
            child.address_entry.set_icon_from_gicon(Gtk.EntryIconPosition.SECONDARY,
                                                    icon)
            if self._profile.hide_address_bar:
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

    def _address_populate_popup(self, entry: object, popup: object,
                                child: dict):
        """ Add items to the popup.

        """

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if text:
            popup.prepend(Gtk.SeparatorMenuItem())
            item = Gtk.MenuItem('Paste and Go')
            item.connect('activate', lambda *a: child.send('open-uri', text))
            item.show_all()
            popup.prepend(item)


    def _findbar_toggle(self, *args):
        """ Toggle findbar visibility.

        """

        child = self._get_child_dict()
        find_bar = child['find-bar']
        find_entry = child['find-entry']

        if find_bar.is_visible():
            if find_entry.has_focus():
                child.send('find-finish', True)
                find_bar.hide()
            else:
                find_entry.grab_focus()
        else:
            if self._profile.find_str:
                find_entry.set_text(self._profile.find_str)
            find_bar.show_all()
            find_entry.grab_focus()

    def _find(self, entry: object, child: dict):
        """ Search the page.

        """

        self._profile.find_str = entry.get_text()
        child.send('find', entry.get_text())

    def _find_next_key(self, accels: object, window: object, keyval: object,
                       flags: object):
        """ Find next.

        """

        child = self._get_child_dict()
        find_bar = child['find-bar']
        find_entry = child['find-entry']

        if self._profile.find_str and not find_entry.get_text():
            find_entry.set_text(self._profile.find_str)

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

        if not child: child = self._get_child_dict()
        child.label.set_visible(not child.label.get_visible())
        child.state['minimized'] = not child.label.get_visible()
        if child.label.is_visible():
            child.event_box.set_size_request(child.normal_width, -1)
        elif child.label_grid.get_visible():
            child.event_box.set_size_request(child.minimized_width, -1)

    def _hide_tab(self, child: dict):
        """ Hide/unhide the label_grid of the current tab.

        """

        if not child: child = self._get_child_dict()
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
            self._bookmark_menu.popup(None, None,
                                      self._bookmark_menu._menu_position,
                                      event, event.button, event.time)
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

        if not child: child = self._get_child_dict()

        if not flags & Gdk.ModifierType.SHIFT_MASK:
            if flags & Gdk.ModifierType.MOD1_MASK:
                settings['private'] = False
            pid = self._new_proc(*self._make_tab(**settings))
        else:
            settings['index'] = self._tabs.get_current_page() + 1
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

    def _tab_reordered(self, notebook: object, tab_grid: object, index: int):
        """ Set the new ordering.

        """

        logging.info('{tab_grid} {index}'.format(**locals()))

    def _tab_switched(self, notebook: object, tab_grid: object, index: int):
        """ Do stuff when the tab is switched.

        """

        # Do nothing if there are no more tabs.
        if not self._windows: return True

        prev_child = self._get_child_dict()
        # Set the previous tabs focus to false.
        prev_child.focus = False

        child_dict = self._get_child_dict(tab_grid)
        child_dict.focus = True
        self._window.set_title('{title-str} - {name}'.format(**child_dict,
                                                             name=self._name))
        # Set the order to one greater than the last tab, so when this
        # tab is closed the last one will be selected.
        if child_dict != prev_child: child_dict.order = prev_child.order + 1

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

    def _to_last_tab(self, child: object):
        """ Switch to the correct tab before closing.

        """

        # Sort the tabs by the order they were last active.
        tmp_list = sorted(self._windows.values(), key=lambda i: i.order)

        # Get the last active tab.
        while tmp_list:
            last = tmp_list.pop(-1)
            if last != child: break

        # Switch to the last active tab.
        self._tabs.set_current_page(self._tabs.page_num(last.tab_grid))

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
            return self._close_tab(event.state, child)

    def _close_tab(self, flags: object, child: dict):
        """ Close child's tab.

        """

        if self._tabs.get_nth_page(self._tabs.get_current_page()) == child['tab_grid']:
            self._to_last_tab(child)
        if flags & Gdk.ModifierType.MOD1_MASK:
            for tab in self._windows.values():
                if tab['pid'] == child['pid']:
                    self._tabs.remove_page(self._tabs.page_num(tab['tab_grid']))
            logging.info("sending Terminate")
            self._send('terminate', child['pid'])
        else:
            logging.info("sending Close")
            child.close()

        return True

    def _get_child_dict(self, tab_grid: object = None):
        """ Returns the child dict of the current tab if tab_grid is None,
        otherwise the child_dict containing tab_grid.

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

    def _close_tab_key(self, accels: object, window: object, keyval: object,
                   flags: object):
        """ Close tab.

        """

        logging.info('Close tab')
        child = self._get_child_dict()
        self._close_tab(flags, child)

    def _switch_tab_key(self, accels: object, window: object, keyval: object,
                        flags: object):
        """ Switch tab.

        """

        logging.info('Switch tab {val} {keyval}'.format(val=(keyval - 49),keyval=keyval))
        if self._tabs.get_n_pages() > (keyval - 49):
            self._tabs.set_current_page(keyval - 49)

    def _focus_address_entry_key(self, accels: object, window: object,
                                 keyval: object, flags: object):
        """ Focus the address bar entry.

        """

        child = self._get_child_dict()
        child.address_bar.show_all()
        child.address_entry.grab_focus()

    def _new_proc(self, settings: dict, child: dict) -> int:
        """ Start a new process using settings and returns the pid.

        """

        self._send('new-proc', settings)
        signal, data = self._recv()
        if signal != 'proc-pid': return 0
        child.pid = data
        self._update_title(child)

        return data

    def _plug_removed(self, socket: object, child: dict):
        """ Re-open removed plug.

        """

        logging.info("PLUG REMOVED: {child.uri}".format(**locals()))
        self._send('terminate', child['pid'])
        self._restore_session(child.session_dict)

        child.com_pipe.close()
        child.child_pipe.close()
        self._tabs.remove_page(self._tabs.page_num(child.tab_grid))

        self._windows.pop(child.socket_id).clear()

        return True

    def _plug_added(self, socket: object, child: dict):
        """ Log that the plug was added.

        """

        logging.info('PLUG ADDED to {child.tab_grid}'.format(**locals()))
        # child.tab_grid.show_all()
        # child.find_bar.hide()
        # if child.focus:
        #     self._tabs.set_current_page(child.index)
        #     child.address_entry.grab_focus()

    def _bookmark_release(self, menu: object, event: object, uri: str):
        """ Open the bookmark.

        """

        child = self._get_child_dict()

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
            pid = self._new_proc(*self._make_tab(uri=uri, focus=True))

    def _bookmark_new(self, menu: object):
        """ Return the current tab.

        """

        child = self._get_child_dict()
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
                pid = self._new_proc(*self._make_tab(uri=uri))

        return True
