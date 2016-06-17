#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Plug process
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


""" The plug process that has the webview.

"""

import os
import re
import sys
import tempfile
import subprocess
import logging
import codecs
import urllib.parse
from multiprocessing import Pipe, Process
from multiprocessing import current_process
from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
gi_require_version('WebKit2', '4.0')
from gi.repository import WebKit2, Gtk, Gdk, GLib, Pango, Gio

from .functions import looks_like_uri
from .classes import ChildDict


class BrowserProc(object):
    """ A Browser Process.

    """

    def __init__(self, com_dict: object):
        """ Initialize the process.


        """

        css_provider = Gtk.CssProvider.get_default()
        css_provider.load_from_data(b'''
                .status {
                    padding: 5px;
                    font-size: 10px;
                    background: rgba(0,0,0,100);
                    border-radius: 0px 2px 0px 0px;
                }
                ''')
        Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

        self._tmp_files = []

        self._fallback_search = 'https://startpage.com/do/search?query=%s'

        self._private = com_dict.pop('private', True)
        self._web_view_settings = com_dict.pop('web-view-settings', {})
        self._search_url = com_dict.pop('search-url', self._fallback_search)
        self._web_view_settings['user-agent'] = com_dict.get('user-agent', '')

        self._adblock_filters = {}
        adblock_filters = com_dict.get('adblock-filters', {})
        for name, (regex, active) in adblock_filters.items():
            if active:
                self._adblock_filters[name] = regex #re.compile(regex)

        self._media_filters = {}
        media_filters = com_dict.get('media-filters', {})
        for name, (regex, active) in media_filters.items():
            if active:
                self._media_filters[name] = re.compile(regex)

        self._pid = current_process().pid

        self._windows = []

        socket_id, com_pipe = com_dict['socket-id'], com_dict['com-pipe']
        logging.info("CREATING: {socket_id} {com_pipe}".format(**locals()))
        view_dict = self._create_window(socket_id, com_pipe)
        view_dict.load(com_dict.get('uri', 'about:blank'))
        self._windows.append(view_dict)

    def _new_webview(self, webview: object = None):
        """ Create a new webview.

        """

        logging.info("PRIVATE: {self._private}".format(**locals()))

        if webview: return webview.new_with_related_view()

        ctx = WebKit2.WebContext.get_default()
        ctx.set_process_model(WebKit2.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)

        webview = WebKit2.WebView.new_with_context(ctx)

        cookies = ctx.get_cookie_manager()
        cookies.set_accept_policy(WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)

        settings = webview.get_settings()
        for prop, value in self._web_view_settings.items():
            logging.info("setting: {prop} => {value}".format(**locals()))
            try:
                settings.set_property(prop, value)
            except TypeError as err:
                logging.error(err)

        if self._private:
            ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
            settings.set_property('enable-private-browsing', True)
        else:
            ctx.set_favicon_database_directory()

        return webview

    def _create_window(self, socket_id: int, com_pipe: object,
                       webview: object = None):
        """ Create a window with a webview in it.

        """

        webview = self._new_webview(webview)
        find_controller = webview.get_find_controller()

        status_label = Gtk.Label()
        status_label.set_ellipsize(Pango.EllipsizeMode(3))
        status_label.get_style_context().add_class('status')
        status_label.set_halign(Gtk.Align.START)
        status_label.set_valign(Gtk.Align.END)
        status_label.set_opacity(0.8)

        # Needed to keep pixman from segfaulting.
        # scroll = Gtk.ScrolledWindow()
        # scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        # scroll.set_shadow_type(Gtk.ShadowType.IN)
        # scroll.add(webview)

        overlay = Gtk.Overlay()
        overlay.add_overlay(webview)
        overlay.add_overlay(status_label)
        overlay.set_overlay_pass_through(status_label, True)
        overlay.show_all()
        status_label.hide()

        view_dict = ChildDict()
        view_dict.update({
            'send': lambda signal, data: self._send(signal, data, com_pipe),
            'recv': com_pipe.recv,
            'grab_focus': webview.grab_focus,
            'update-status': lambda info: self._update_status(view_dict, info),
            'load': lambda data: self._load(view_dict, data),
            'restore-session': lambda data: self._restore_session(data, view_dict),
            'send-session': lambda: self._send_session(view_dict),
            'get-session': lambda: self._get_session(view_dict),
            'search-url': self._search_url,
            'status-label': status_label,
            'webview': webview,
            'overlay': overlay,
            'socket-id': socket_id,
            'com-pipe': com_pipe,
            'find-controller': find_controller,
            'find-options': WebKit2.FindOptions.CASE_INSENSITIVE |
                            WebKit2.FindOptions.WRAP_AROUND,
            'is-blank-page': lambda: self._is_blank(view_dict),
            'webview-sig-ids': [],
            'session': b'',
            })

        if socket_id: view_dict['plug'] = self._create_plug(view_dict)

        signal_handlers = (
                ('motion-notify-event',
                    lambda *a: view_dict.send('mouse-motion', True)),
                ('decide-policy', self._policy, view_dict),
                ('permission-request', self._permission, view_dict),
                ('create', self._new_window, view_dict),
                ('load-failed-with-tls-errors', self._tls_errors, view_dict),
                ('load-changed', self._load_status, view_dict),
                ('mouse-target-changed', self._mouse_target_changed,
                    view_dict),
                ('notify::title', self._property_changed, view_dict),
                ('notify::uri', self._property_changed, view_dict),
                ('notify::estimated-load-progress', self._property_changed,
                    view_dict),
                ('notify::favicon', self._icon_loaded, view_dict),
                ('notify::load-failed', self._load_error, view_dict),
                ('notify::is-loading', self._property_changed, view_dict),
                ('notify::is-playing-audio', self._property_changed,
                    view_dict),
                ('insecure-content-detected', self._insecure_detect,
                    view_dict),
                ('resource-load-started', self._resource_started, view_dict),
                ('context-menu', self._context_menu, view_dict),
                ('web-process-crashed', self._crashed, view_dict),
                )

        for signal, func, *args in signal_handlers:
            view_dict.webview_sig_ids.append(webview.connect(signal, func,
                                             *args))

        find_controller.connect('found-text', self._found_text, view_dict)
        find_controller.connect('failed-to-find-text', self._found_failed,
                                view_dict)
        find_controller.connect('counted-matches', self._found_count,
                                view_dict)

        GLib.io_add_watch(com_pipe.fileno(), GLib.IO_IN, self._recieve,
                          view_dict)

        return view_dict

    def _create_plug(self, view_dict: dict):
        """ Create a plug.

        """

        plug = Gtk.Plug.new(view_dict.socket_id)
        plug.add(view_dict.overlay)
        plug.show()
        plug.connect('destroy', self._destroy, view_dict)
        plug.connect('delete-event', self._delete, view_dict)

        return plug

    def _send(self, signal: str, data: object, com_pipe: object):
        """ Send signal with data over com_pipe.

        """

        try:
            com_pipe.send((signal, data))
        except BrokenPipeError as err:
            logging.error("PIPE BROKE CLOSING: {err}".format(**locals()))

    def _restore_session(self, session_data: bytes, view_dict: dict) -> bool:
        """ Restores the session for view_dict.

        """

        if not session_data: return False

        logging.info('Restoring session...')

        session_bytes = GLib.Bytes.new(codecs.decode(session_data.encode(),
                                                     'base64'))
        session_state = WebKit2.WebViewSessionState.new(session_bytes)
        view_dict.webview.restore_session_state(session_state)

        item = view_dict.webview.get_back_forward_list().get_current_item()
        if item:
            view_dict.webview.go_to_back_forward_list_item(item)
            view_dict.webview.grab_focus()

        GLib.idle_add(self._send_back_forward, view_dict)

        logging.info('Session restored.')

        return True

    def _send_session(self, view_dict: dict):
        """ Send the session data for the webview in view_dict.

        """

        logging.info('Sending session data...')

        view_dict.send('session-data', view_dict.get_session())

        logging.info('Sent session data.')

    def _get_session(self, view_dict: dict):
        """ Return the session_data base64 encoded.

        """

        webview = view_dict.webview
        session_data = b''

        if not view_dict.is_blank_page():
            session_bytes = webview.get_session_state().serialize()
            session_data = codecs.encode(session_bytes.get_data(), 'base64')

        return session_data.decode()

    def _is_blank(self, view_dict: dict):
        """ Return True if the webview in view_dict is an empty session.

        """

        webview = view_dict.webview
        uri = webview.get_uri()
        logging.info('IS BLANK {uri} {back} {forward}'.format(uri=uri,
            back=webview.can_go_back(), forward=webview.can_go_forward()))

        return not (webview.can_go_back() or webview.can_go_forward() or
                    (uri and uri != 'about:blank'))

    def _delete(self, plug: object, event: object, view_dict: dict):
        """ Destroy the webview before the plug.

        """

        # Disconnect all signal handlers for the web_view.
        for sig_id in view_dict.webview_sig_ids:
            view_dict.webview.disconnect(sig_id)

        # Store the session data so it will be sent when the tab is
        # closed.
        view_dict.session = {
                'session-data': view_dict.get_session(),
                'title': view_dict.webview.get_title(),
                'uri': view_dict.webview.get_uri(),
                }

        # Try to make web_view clear up all memory before destroying.
        view_dict.webview.stop_loading()
        view_dict.webview.load_uri('about:blank')
        view_dict.overlay.remove(view_dict.webview)

        # Finally destory the plug.
        view_dict.plug.destroy()
        logging.info("DESTROYED IT")

        return False

    def _destroy(self, plug, view_dict):
        """ Quit

        """

        self._windows.remove(view_dict)

        if not self._windows:
            # Close all temporary files.
            for f in self._tmp_files: f.close()

            logging.info("DESTROYING: {self._pid}".format(**locals()))
            Gtk.main_quit()

        send_dict = {
                'session': view_dict.session,
                'is-last': not bool(self._windows),
                }
        try:
            view_dict.send('closed', send_dict)
        except BrokenPipeError as err:
            logging.error("PIPE BROKE CLOSING: {err}".format(**locals()))

        logging.info("CLOSED {view_dict.webview}".format(**locals()))
        view_dict.com_pipe.close()
        view_dict.clear()

    def _recieve(self, source: int, cb_condition: int, view_dict: dict):
        """ Recieve signals from outside.

        """

        logging.debug("IN RECIEVE: {view_dict.com_pipe}".format(**locals()))

        signal, data = view_dict.recv()

        if signal in ['restore-session']:
            logging.debug('SIGNAL: {signal}, DATA: {data}'.format(**locals()))
        else:
            logging.info('SIGNAL: {signal}, DATA: {data}'.format(**locals()))

        if signal == 'close' and data:
            view_dict.plug.emit('delete-event', None)
            return False

        if signal == 'grab-focus':
            view_dict.grab_focus()

        if signal == 'open-uri':
            view_dict.load(data)

        if signal == 'new-tab':
            new_win = self._new_tab(view_dict, data)
            new_win.load(data.get('uri', 'about:blank'))

        if signal == 'socket-id':
            view_dict['socket-id'] = data
            view_dict['plug'] = self._create_plug(view_dict)

        if signal == 'stop':
            view_dict['webview'].stop_loading()

        if signal == 'refresh':
            view_dict['webview'].reload()

        if signal == 'refresh-bypass':
            view_dict['webview'].reload_bypass_cache()

        if signal == 'history-go-to':
            webview = view_dict['webview']
            if data == 1:
                webview.go_forward()
            elif data == -1:
                webview.go_back()
            else:
                back_forward_list = webview.get_back_forward_list()
                item = back_forward_list.get_nth_item(data)
                webview.go_to_back_forward_list_item(item)

        if signal.startswith('find'):
            finder = view_dict['find-controller']
            if signal.endswith('prev'):
                finder.search_previous()
            elif signal.endswith('next'):
                finder.search_next()
            elif signal.endswith('finish'):
                finder.search_finish()
            else:
                finder.search(data, view_dict['find-options'], 0)

        if signal == 'restore-session':
            webview = view_dict.webview
            uri = webview.get_uri()
            if view_dict.is_blank_page():
                view_dict.restore_session(data['session-data'])
            else:
                new_win = self._new_tab(view_dict, data)

        if signal == 'get-session':
            view_dict.send_session()

        if signal == 'web-view-settings':
            settings = view_dict.webview.get_settings()
            try:
                settings.set_property(*data)
            except TypeError as err:
                logging.error(err)

        if signal == 'default-search':
            self._search_url = data
            view_dict.search_url = data

        if signal == 'adblock':
            name, regex, active = data
            if active:
                self._adblock_filters[name] = regex #re.compile(regex)
            else:
                self._adblock_filters.pop(name, None)

        if signal == 'media-filter':
            name, regex, active = data
            if active:
                self._media_filters[name] = re.compile(regex)
            else:
                self._media_filters.pop(name, None)

        return True

    def _new_tab(self, view_dict: dict, data: dict):
        """ Make a new window.

        """

        com_pipe, proc_pipe = Pipe()
        new_win = self._create_window(0, proc_pipe, view_dict.webview)
        info_dict = {
                'uri': data.get('uri', 'about:blank'),
                'pid': self._pid,
                'com-pipe': com_pipe,
                'child-pipe': proc_pipe,
                'focus': data.get('focus', False),
                'private': data.get('private', self._private),
                'index': data.get('index', -1),
                'order': data.get('order', 0),
                }
        view_dict.send('tab-info', info_dict)

        self._windows.append(new_win)

        if 'session-data' in data:
            new_win.restore_session(data['session-data'])

        return new_win

    def _new_window(self, webview: object, navigation_action: object,
                    view_dict: dict):
        """ New window in this process.

        """

        return self._new_tab(view_dict, {'focus': False}).webview

    def _context_menu(self, webview: object, menu: object, event: object,
                      hit_test_result: object, view_dict: dict):
        """ Modify the context menu before showing it.

        """

        if hit_test_result.context_is_selection():
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY)
            selected_text = clipboard.wait_for_text().strip()

            # Change the label for depending on what keys are pressed.
            if not event.state & Gdk.ModifierType.SHIFT_MASK:
                type_str = ' new tab'
                if event.state & Gdk.ModifierType.MOD1_MASK:
                    type_str = ' new non-private tab'
            else:
                type_str = ' new tab (same process)'

            # Allways allow searching for selected text.
            action = Gtk.Action('search-web', 'Search for selection in' + type_str,
                                'Search web for selection.', '')
            icon = Gio.ThemedIcon.new_with_default_fallbacks('edit-find-symbolic')
            action.set_gicon(icon)
            action.connect('activate', self._context_activate, selected_text,
                           view_dict, event.state)
            menu_item = WebKit2.ContextMenuItem.new(action)
            menu.prepend(WebKit2.ContextMenuItem.new_separator())
            menu.prepend(menu_item)

            # Add an open-uri option if the selected text looks like a uri.
            if looks_like_uri(selected_text):
                action = Gtk.Action('open-uri', 'Open in' + type_str,
                                    'Open selected uri in new tab',
                                    '')
                icon = Gio.ThemedIcon.new_with_default_fallbacks('go-jump-symbolic')
                action.set_gicon(icon)
                action.connect('activate', self._context_activate, selected_text,
                            view_dict, event.state)
                menu_item = WebKit2.ContextMenuItem.new(action)
                menu.append(WebKit2.ContextMenuItem.new_separator())
                menu.append(menu_item)

        if webview.get_uri() and webview.get_uri() != 'about:blank':
            action = Gtk.Action('print-page', 'Print Page', 'Print Page',
                                '')
            icon = Gio.ThemedIcon.new_with_default_fallbacks('printer-symbolic')
            action.set_gicon(icon)
            action.connect('activate', self._context_activate, '', view_dict)
            menu_item = WebKit2.ContextMenuItem.new(action)
            menu.append(WebKit2.ContextMenuItem.new_separator())
            menu.append(menu_item)
            menu.append(WebKit2.ContextMenuItem.new_separator())

            # Allow viewing the source of any webpage except a blank or
            # about:blank page.
            action = Gtk.Action('view-source', 'View Source', 'View Source',
                                '')
            icon = Gio.ThemedIcon.new_with_default_fallbacks('text-editor-symbolic')
            action.set_gicon(icon)
            action.connect('activate', self._context_activate, '', view_dict)
            menu_item = WebKit2.ContextMenuItem.new(action)
            menu.append(menu_item)

        translate = (
                ('OPEN_LINK', 'folder-symbolic'),
                ('OPEN_LINK_IN_NEW_WINDOW', 'folder-symbolic'),
                ('DOWNLOAD_LINK_TO_DISK', 'folder-download-symbolic'),
                ('COPY_LINK_TO_CLIPBOARD', 'edit-copy-symbolic'),
                ('OPEN_IMAGE_IN_NEW_WINDOW', 'folder-symbolic'),
                ('DOWNLOAD_IMAGE_TO_DISK', 'folder-download-symbolic'),
                ('COPY_IMAGE_TO_CLIPBOARD', 'edit-copy-symbolic'),
                ('COPY_IMAGE_URL_TO_CLIPBOARD', 'edit-copy-symbolic'),
                ('OPEN_FRAME_IN_NEW_WINDOW', 'folder-symbolic'),
                ('GO_BACK', 'go-previous-symbolic'),
                ('GO_FORWARD', 'go-next-symbolic'),
                ('STOP', 'process-stop-symbolic'),
                ('RELOAD', 'view-refresh-symbolic'),
                ('COPY', 'edit-copy-symbolic'),
                ('CUT', 'edit-cut-symbolic'),
                ('PASTE', 'edit-paste-symbolic'),
                ('DELETE', 'edit-delete-symbolic'),
                ('SELECT_ALL', 'edit-select-all-symbolic'),
                ('INPUT_METHODS', 'input-keyboard-symbolic'),
                ('BOLD', 'format-text-bold-symbolic'),
                ('ITALIC', 'format-text-italic-symbolic'),
                ('UNDERLINE', 'format-text-underline-symbolic'),
                ('OPEN_VIDEO_IN_NEW_WINDOW', 'folder-symbolic'),
                ('OPEN_AUDIO_IN_NEW_WINDOW', 'folder-symbolic'),
                ('COPY_VIDEO_LINK_TO_CLIPBOARD', 'edit-copy-symbolic'),
                ('COPY_AUDIO_LINK_TO_CLIPBOARD', 'edit-copy-symbolic'),
                ('ENTER_VIDEO_FULLSCREEN', 'view-fullscreen-symbolic'),
                ('MEDIA_PLAY', 'media-playback-start-symbolic'),
                ('MEDIA_PAUSE', 'media-playback-pause-symbolic'),
                ('MEDIA_MUTE', 'audio-volume-muted-symbolic'),
                ('DOWNLOAD_VIDEO_TO_DISK', 'folder-download-symbolic'),
                ('DOWNLOAD_AUDIO_TO_DISK', 'folder-download-symbolic'),
                )
        for index, item in enumerate(menu.get_items()):
            for action, icon_name in translate:
                if item.get_stock_action() == getattr(WebKit2.ContextMenuAction, action):
                    if 'DOWNLOAD' in action:
                        if action == 'DOWNLOAD_LINK_TO_DISK':
                            uri = hit_test_result.get_link_uri()
                            item_title = 'Save Link As'
                        elif action == 'DOWNLOAD_IMAGE_TO_DISK':
                            uri = hit_test_result.get_image_uri()
                            item_title = 'Save Image As'
                        elif action == 'DOWNLOAD_VIDEO_TO_DISK':
                            uri = hit_test_result.get_media_uri()
                            item_title = 'Save Video As'
                        elif action == 'DOWNLOAD_AUDIO_TO_DISK':
                            uri = hit_test_result.get_media_uri()
                            item_title = 'Save Audio As'

                        menu.remove(item)
                        action = Gtk.Action('download', item_title, item_title,
                                            '')
                        icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)
                        action.set_gicon(icon)
                        action.connect('activate', self._save_link, uri, view_dict)
                        menu_item = WebKit2.ContextMenuItem.new(action)
                        menu.insert(menu_item, index)
                    else:
                        icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)
                        item.get_action().set_stock_id('')
                        item.get_action().set_gicon(icon)

    def _save_link(self, action: object, uri: str, view_dict: dict):
        """ Download the selected uri.

        """

        user_agent = view_dict.webview.get_settings().get_property('user-agent')
        info_dict = {
                'uri': uri,
                'filename': uri.split('/')[-1],
                'mime-type': '',
                'length': 0,
                'user-agent': user_agent,
                }
        view_dict.send('download', info_dict)

    def _context_activate(self, action: object, selected_text: str,
                          view_dict: dict, flags: object = None):
        """ Handle custom context menu actions.

        """

        if action.get_name() == 'print-page':
            print_op = WebKit2.PrintOperation.new(view_dict.webview)
            print_op.run_dialog(view_dict.plug)
            return True

        if action.get_name() == 'view-source':
            res = view_dict.webview.get_main_resource()
            res.get_data(None, self._get_source, view_dict)
            return True

        if action.get_name() == 'search-web':
            selected_text = urllib.parse.quote(selected_text)
            try:
                selected_text = view_dict.search_url % selected_text
            except TypeError:
                selected_text = self._fallback_search % selected_text

        settings = {'uri': selected_text, 'focus': False}
        if not flags & Gdk.ModifierType.SHIFT_MASK:
            if flags & Gdk.ModifierType.MOD1_MASK:
                settings['private'] = False
            view_dict.send('create-tab', settings)
        else:
            new_tab = self._new_tab(view_dict, settings)
            new_tab.load(selected_text)

        return True

    def _load(self, view_dict: dict, data: str):
        """ Load the data in the webview in view_dict.

        """

        data = data.strip()

        if data == 'about:blank': return data

        webview = view_dict.webview

        if '\n' not in data:
            if not looks_like_uri(data):
                # Data doesn't look like a uri so treat it as a search
                # string.
                try:
                    data = view_dict.search_url % data
                except TypeError:
                    data = self._fallback_search % data
            # Data looks like a uri but it doesn't start with
            # somthing:// so prepend http:// to it.
            if not data.startswith(('http://', 'https://', 'ftp://')):
                data = 'http://%s' % data

            webview.load_uri(data)

            webview.grab_focus()
            view_dict.send('title', data)

        return data

    def _resource_started(self, webview: object, resource: object,
                          request: object, view_dict: dict):
        """ Moniter resources.

        """

        uri = request.get_uri()

        for _, regex in self._media_filters.items():
            if regex.search(uri):
                http_headers = request.get_http_headers()
                mimetype = http_headers.get_content_type()
                length = http_headers.get_content_length()
                user_agent = webview.get_settings().get_property('user-agent')
                filename = uri.split('/')[-1]
                info_dict = {
                        'uri': uri,
                        'filename': filename,
                        'mime-type': mimetype,
                        'length': length,
                        'user-agent': user_agent,
                        'start': False,
                        }
                view_dict.send('download', info_dict)

        logging.debug("RESOURCE {uri}".format(**locals()))
        if webview.get_uri().startswith('https') and uri.startswith('http:'):
            logging.info("INSECURE RESOURCE: {uri}".format(uri=uri))
            view_dict.send('insecure-content', True)

    def _permission(self, webview: object, request: object, view_dict: dict):
        """ Grant or deny permission for request.

        """

        logging.info("PERMISSION: {request}".format(request=request))
        request.deny()
        return True

    def _is_add_match(self, uri: str) -> bool:
        """ Returns true if uri looks like an add.

        """

        for _, regex in self._adblock_filters.items():
            # if regex.search(uri):
            logging.info('{regex} in {uri}'.format(**locals()))
            if re.search(regex, uri):
                logging.info('AdBlock Blocking: {uri}'.format(**locals()))
                return True

    def _policy(self, webview: object, decision: object, decision_type: object,
                view_dict: dict):
        """ Handle opening a new window.

        """

        page_uri = webview.get_uri()
        if decision_type in \
                [WebKit2.PolicyDecisionType.NAVIGATION_ACTION, \
                 WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION]:

            nav_action = decision.get_navigation_action()
            request = nav_action.get_request()
            uri = request.get_uri()

            # Block popups.
            if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                if not nav_action.is_user_gesture():
                    decision.ignore()
                    return True

            if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
                logging.debug('NAV ACTION {uri}'.format(**locals()))

            if nav_action.get_mouse_button() == 2 or \
                    (nav_action.get_mouse_button() == 1 and \
                    nav_action.get_modifiers() & \
                    Gdk.ModifierType.CONTROL_MASK):

                decision.ignore()

                data_dict = {'uri': uri, 'focus': False}
                if decision.get_modifiers() & Gdk.ModifierType.SHIFT_MASK:
                    new_tab = self._new_tab(view_dict, data_dict)
                    new_tab.load(uri)
                    return True

                if decision.get_modifiers() & Gdk.ModifierType.MOD1_MASK:
                    data_dict['private'] = False

                view_dict.send('create-tab', data_dict)

                return True
            # elif nav_action.get_navigation_type() == WebKit2.NavigationType.OTHER:
            #     if not self._load_scheme(page_uri, uri):
            #         logging.info("BLOCKING (REQUEST): {uri}".format(uri=uri))
            #         decision.ignore()
            #         return True

            if self._is_add_match(uri):
                logging.info('Blocking: {uri}'.format(**locals()))
                decision.ignore()
                return True

            if view_dict.webview.is_loading():
                # Show a loading status.
                view_dict.update_status('Request: {uri}...'.format(**locals()))
        elif decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            http_headers = response.get_http_headers()
            uri = response.get_uri()
            logging.debug('RESPONSE {uri}'.format(**locals()))

            if self._is_add_match(uri):
                logging.info('Blocking: {uri}'.format(**locals()))
                decision.ignore()
                return True

            if not decision.is_mime_type_supported():
                filename = response.get_suggested_filename()
                mimetype = response.get_mime_type()
                length = response.get_content_length()
                user_agent = webview.get_settings().get_property('user-agent')
                if not filename:
                    filename = uri.split('/')[-1]
                info_dict = {
                        'uri': uri,
                        'filename': filename,
                        'mime-type': mimetype,
                        'length': length,
                        'user-agent': user_agent,
                        }
                view_dict.send('download', info_dict)
                decision.ignore()
                return True

            if not self._load_scheme(page_uri, uri) and self._private:
                logging.info("BLOCKING (RESPONSE): {uri}".format(uri=uri))
                decision.ignore()
                return True

            if view_dict.webview.is_loading():
                # Show a loading status.
                view_dict.update_status('Response: {uri}...'.format(**locals()))
        else:
            logging.info("UNKNOWN: {decision} {decision_type}".format(**locals()))

        GLib.idle_add(self._send_back_forward, view_dict)
        decision.use()

        return True

    def _load_scheme(self, from_uri: str, to_uri: str):
        """ Check that the to uri scheme is either the same or more secure than
        the from uri scheme.

        """

        if not from_uri or to_uri.startswith('https'):
            return True

        if not from_uri.startswith('https'):
            return True

        return False

    def _insecure_detect(self, webview: object, event: object, view_dict: dict):
        """ Detect Insecure content

        """

        logging.info("INSECURE CONTENT: {event}".format(**locals()))
        view_dict.send('insecure-content', True)

    def _tls_errors(self, webview: object, uri: str, cert: object,
                    errors: object, view_dict: dict):
        """ Detect tls errors.

        """

        logging.error("TLS_ERROR {errors} ON {uri} with cert {cert}".format(**locals()))
        view_dict.send('tls-error', True)
        self._verify_view(view_dict)
        return False

    def _icon_loaded(self, webview: object, icon_uri: str, view_dict: dict):
        """ Set icon loaded signal.

        """

        uri = webview.get_uri()
        icon = webview.get_favicon()
        logging.info("ICON: {icon}".format(icon=icon))

        if icon:
            pixbuf = Gdk.pixbuf_get_from_surface(icon, 0, 0,
                                                       icon.get_width(),
                                                       icon.get_height())
            data = pixbuf.save_to_bufferv('png', '', '')[1]

        view_dict.send('icon-bytes', data if icon else b'')

    def _property_changed(self, webview: object, prop: object,
                          view_dict: dict):
        """ Send property value as a signal.

        """

        value = webview.get_property(prop.name)
        name = prop.name

        if name == 'uri':
            GLib.idle_add(self._send_back_forward, view_dict)

        logging.info("{name}: {value}".format(name=name.upper(), value=value))
        view_dict.send(name, value)

    def _get_source(self, source_object: object, res: object, view_dict: dict):
        """ print the source.

        """

        def block_run(cmd_line: list):
            """ Run cmd_line and block until it exits.

            """

            # Block until process exits.
            subprocess.Popen(cmd_line, stdout=subprocess.PIPE).communicate()

        tmpfile = tempfile.NamedTemporaryFile()
        tmpfile.write(source_object.get_data_finish(res))
        self._tmp_files.append(tmpfile)

        app_info = Gio.app_info_get_default_for_type('text/html', False)
        mp_proc = Process(target=block_run, args=([app_info.get_executable(),
                                                   tmpfile.name],))
        mp_proc.start()

        GLib.child_watch_add(GLib.PRIORITY_DEFAULT_IDLE, mp_proc.pid,
                             self._close_tmp, tmpfile)

    def _close_tmp(self, source: object, cb_condition: int, tmpfile: object):
        """ Close tmp files in view_dict.

        """

        logging.info("Closing: {tmpfile.name}".format(**locals()))
        tmpfile.close()
        self._tmp_files.remove(tmpfile)

        return False

    def _send_back_forward(self, view_dict: dict):
        """ Send the back/forward history lists.

        """

        # Send the session.
        view_dict.send_session()

        def build_list(hist_list: object) -> list:
            """ for each item is hist_list add the data to a dictionary and
            append that to a list.  Return the resulting list of dictionaries.

            """

            hist_dict_list = []

            if not hist_list: return hist_dict_list

            for item in hist_list:
                hist_dict_list.append({
                    'title': item.get_title(),
                    'uri': item.get_uri(),
                    'original-uri': item.get_original_uri()
                    })

            return hist_dict_list

        webview = view_dict.webview
        view_dict.send('can-go-back', webview.can_go_back())
        view_dict.send('can-go-forward', webview.can_go_forward())

        back_forward_list = webview.get_back_forward_list()

        current_item = back_forward_list.get_current_item()
        current_dict = build_list([current_item])[0] if current_item else {}

        back_dict_list = build_list(back_forward_list.get_back_list())
        forward_dict_list = build_list(back_forward_list.get_forward_list())

        view_dict.send('back-forward-list', (back_dict_list, current_dict,
                                             forward_dict_list))

        return False

    def _verify_view(self, view_dict: dict):
        """ Check for tls security.

        """

        webview = view_dict.webview
        tls_info = webview.get_tls_info()
        logging.info('CERTIFICATE: {tls_info}'.format(**locals()))
        verified, certificate, flags = tls_info
        if certificate:
            issuer_cert = certificate.get_issuer()
            if issuer_cert:
                issuer_known = True
                issuer_bytes = issuer_cert.get_property('certificate')
                issuer_pem = issuer_cert.get_property('certificate-pem')
            else:
                issuer_known = False
                issuer_bytes = bytearray()
                issuer_pem = ''
            cert_bytes = certificate.get_property('certificate')
            cert_pem = certificate.get_property('certificate-pem')
            cert_dict = {
                    'certificate': bytes(cert_bytes).hex(),
                    'cert-pem': cert_pem,
                    'issuer': issuer_bytes,
                    'issuer-pem': issuer_pem,
                    }
            view_dict.send('is-secure', (verified, issuer_known, cert_dict,
                                                    int(flags)))
        else:
            view_dict.send('is-secure', (verified, False, {}, int(flags)))

    def _load_status(self, webview: object, load_event: object,
                     view_dict: dict):
        """ Notify the parent process when the load status changes.

        """

        if load_event == WebKit2.LoadEvent.STARTED:
            pass
        elif load_event == WebKit2.LoadEvent.REDIRECTED:
            view_dict.send('uri-changed', webview.get_uri())
        elif load_event == WebKit2.LoadEvent.FINISHED:
            view_dict.update_status('')
            GLib.idle_add(self._send_back_forward, view_dict)
            self._verify_view(view_dict)

        view_dict.send('load-status', int(load_event))

    def _load_error(self, webview: object, webframe: object, uri: str,
                    weberror: object, view_dict: dict):
        """ Get the error.

        """

        logging.info("LOAD ERROR: {uri} {weberror.message}".format(**locals()))
        view_dict.send('load-error', {'uri': uri, 'message': weberror.message})

    def _mouse_target_changed(self, webview: object, hit_test_result: object,
                              modifiers: object, view_dict: dict):
        """ Send info about what the mouse is over.

        """

        uri = ''

        if hit_test_result.context_is_link():
            uri = hit_test_result.get_link_uri()
        elif hit_test_result.context_is_image():
            uri = hit_test_result.get_image_uri()
        elif hit_test_result.context_is_media():
            uri = hit_test_result.get_media_uri()

        title = hit_test_result.get_link_title()

        # Send the uri of the object under the mouse.
        view_dict.send('hover-link', {'uri': uri, 'title': title})

        view_dict.update_status(uri)

    def _update_status(self, view_dict: dict, info: str):
        """ If info is empty then hide the status label otherwise set the status
        labels text to info.

        """

        info = info.strip()

        if info == 'about:blank':
            view_dict.status_label.set_visible(False)

        # Show the status label if there is something to show.
        view_dict.status_label.set_text(info if info else '')
        view_dict.status_label.set_visible(bool(info))

    def _resource_response(self, webview: object, webframe: object,
                           resource: object, response: object,
                           view_dict: dict):
        """ Handle response.

        """

        message = response.get_message()
        if message:
            logging.info("RESOURCE RESPONSE: {flags}".format(flags=message.get_flags()))

    def _found_count(self, find_controller: object, match_count: int,
                     view_dict: dict):
        """ Gets the number of matches.

        """

        logging.info("FIND_COUNT: {match_count}".format(**locals()))

    def _found_failed(self, find_controller: object, view_dict: dict):
        """ Sends that find failed.

        """

        view_dict.send('find-failed', True)

    def _found_text(self, find_controller: object, match_count: int,
                    view_dict: dict):
        """ Found text.

        """

        logging.info("FOUND: {match_count}".format(**locals()))
        view_dict.send('find-failed', False)

    def run(self):
        """ Run the main Gtk loop.

        """

        Gtk.main()

    def _crashed(self, webview: object, view_dict: dict):
        """ Handle the crash

        """

        view_dict.send('crashed', view_dict.get_session())
        view_dict.restore_session(view_dict.get_session())
