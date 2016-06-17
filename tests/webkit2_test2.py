from path import Path
from gi import require_version as gi_require_version
from multiprocessing import Process, Manager, Pipe
from multiprocessing import current_process
import multiprocessing
from json import loads as json_loads
from json import dumps as json_dumps
import pathlib
import json
import os
import re
import math
import tempfile
import subprocess

gi_require_version('Gtk', '3.0')
gi_require_version('WebKit2', '4.0')

CONFIG_PATH = pathlib.Path(os.getenv("HOME")).joinpath(".config/webbrowser2")
with pathlib.Path(CONFIG_PATH) as conf_path:
    if not conf_path.exists():
        conf_path.mkdir()
    elif not conf_path.is_dir():
        print("Can't Save Config")
CONFIG_FILE = pathlib.Path(CONFIG_PATH).joinpath('config')

def looks_like_uri(test_text: str):
    """ Test test_text and returns true if it looks like a uri.  Otherwise
    return False.

    """

    if not test_text.startswith(('http://', 'https://', 'ftp://',
                                    'file://', 'mailto:', 'javascript:',
                                    'about:blank')):
        if ' ' in test_text or '.' not in test_text or not test_text:
            return False

    return True

class ChildDict(dict):
    """ A dictionary that has a send command.

    """

    def __init__(self, *args, **kwargs):
        """ Initialize.

        """

        super(ChildDict, self).__init__(*args, **kwargs)

    def __getitem__(self, key: str):
        """ Return the item associated with key.

        """

        try:
            item = super(ChildDict, self).__getitem__(key)
        except KeyError:
            key = key.replace('_', '-', key.count('_'))
            item = super(ChildDict, self).__getitem__(key)

        return item

    def __getattr__(self, item: str):
        """ Return the item from the dictionary.

        """

        try:
            attr = self.__getitem__(item)
        except KeyError:
            attr = self.__getitem__(item.replace('_', '-', item.count('_')))

        return attr

    def __setattr__(self, item: str, data: object):
        """ Put data in self[item]

        """

        self.__setitem__(item.replace('_', '-', item.count('_')), data)


class BrowserProc(object):
    """ A Browser Process.

    """

    def __init__(self, com_dict: object):
        """ Initialize the process.


        """

        from gi.repository import WebKit2 as webkit2
        from gi.repository import Gtk as gtk
        from gi.repository import Gdk as gdk
        from gi.repository import GLib as glib
        from gi.repository import Pango as pango
        from gi.repository import Gio as gio

        self._gtk = gtk
        self._gio = gio
        self._gdk = gdk
        self._glib = glib
        self._webkit2 = webkit2
        self._pango = pango

        css_provider = self._gtk.CssProvider.get_default()
        css_provider.load_from_data(b'''
                .status {
                    padding: 5px;
                    font-size: 10px;
                    background: rgba(0,0,0,100);
                    border-radius: 0px 2px 0px 0px;
                }
                ''')
        self._gtk.StyleContext.add_provider_for_screen(
                self._gdk.Screen.get_default(),
                css_provider,
                self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

        icontheme = self._gtk.IconTheme().get_default()
        self._html_pixbuf = icontheme.load_icon('text-html',
                                                self._gtk.IconSize.MENU,
                                                self._gtk.IconLookupFlags.USE_BUILTIN)


        self._dict = com_dict
        self._private = com_dict.pop('private', True)
        self._search_url = 'https://startpage.com/do/search?query=%s'

        self._pid = multiprocessing.current_process().pid

        self._windows = []
        view_dict = {}

        for socket_id, com_pipe in self._dict.items():
            print("CREATING: ", socket_id, com_pipe)
            try:
                com_pipe.send(('pid', self._pid))
                com_pipe.send(('private', self._private))
            except BrokenPipeError as err:
                print("BROKEN PIPE: ", err, ' on PIPE ', com_pipe)
                continue
            view_dict = self._create_window(socket_id, com_pipe,
                                            view_dict.get('webview', None))
            self._windows.append(view_dict)

    def _new_webview(self, webview: object = None):
        """ Create a new webview.

        """

        if webview:
            return webview.new_with_related_view()

        ctx = self._webkit2.WebContext.get_default()
        if self._private:
            # sec_man = ctx.get_security_manager()
            # sec_man.register_uri_scheme_as_no_access('http')
            ctx.set_cache_model(self._webkit2.CacheModel.DOCUMENT_VIEWER)

        ctx.set_process_model(self._webkit2.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)
        webview = self._webkit2.WebView.new_with_context(ctx)

        cookies = ctx.get_cookie_manager()
        cookies.set_accept_policy(self._webkit2.CookieAcceptPolicy.NO_THIRD_PARTY)

        if not self._private:
            ctx.set_favicon_database_directory()

        settings = webview.get_settings()
        if self._private:
            print("PRIVATE: ", self._private)
            settings.set_property('enable-private-browsing', True)
            settings.set_property('enable-page-cache', False)
            settings.set_property('enable-dns-prefetching', False)
            settings.set_property('enable-html5-database', False)
            settings.set_property('enable-html5-local-storage', False)
            settings.set_property('enable-offline-web-application-cache',
                                  False)
            settings.set_property('enable-hyperlink-auditing', True)

        settings.set_property('enable-java', False)
        settings.set_property('enable-plugins', False)
        settings.set_property('enable-javascript', True)
        settings.set_property('enable-media-stream', True)
        settings.set_property('enable-mediasource', True)
        settings.set_property('enable-webaudio', True)
        settings.set_property('enable-webgl', True)
        settings.set_property('enable-accelerated-2d-canvas', True)
        settings.set_property('enable-developer-extras', True)
        # Chromium user agent string.
        settings.set_property('user-agent', 'Mozilla/5.0 (X11; Linux x86_64) \
                               AppleWebKit/537.36 (KHTML, like Gecko) \
                               Chrome/49.0.2623.110 Safari/537.36')
        # Firefox user agent string.
        # settings.set_property('user-agent', 'Mozilla/5.0 (X11; Linux x86_64; \
        #                        rv:45.0) Gecko/20100101 Firefox/45.0')

        return webview

    def _create_window(self, socket_id: int, com_pipe: object,
                       webview: object = None):
        """ Create a window with a webview in it.

        """

        webview = self._new_webview(webview)
        find_controller = webview.get_find_controller()

        status_label = self._gtk.Label()
        status_label.set_ellipsize(self._pango.EllipsizeMode(3))
        status_label.get_style_context().add_class('status')
        status_label.set_halign(self._gtk.Align.START)
        status_label.set_valign(self._gtk.Align.END)
        # status_label.set_margin_bottom(10)
        status_label.set_opacity(0.8)

        scroll = self._gtk.ScrolledWindow()
        scroll.set_policy(self._gtk.PolicyType.AUTOMATIC,
                          self._gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(self._gtk.ShadowType.IN)
        scroll.add(webview)

        overlay = self._gtk.Overlay()
        overlay.add_overlay(scroll)
        overlay.add_overlay(status_label)
        overlay.set_overlay_pass_through(status_label, True)
        overlay.show_all()
        status_label.hide()

        view_dict = ChildDict({
            'send': lambda signal, data: com_pipe.send((signal, data)),
            'recv': lambda: com_pipe.recv(),
            'status-label': status_label,
            'webview': webview,
            'overlay': overlay,
            'socket-id': socket_id,
            'com-tup': (com_pipe, self._dict),
            'find-controller': find_controller,
            'find-options': self._webkit2.FindOptions.CASE_INSENSITIVE |
                            self._webkit2.FindOptions.WRAP_AROUND,
            })

        view_dict.load = lambda data, data_type='uri': self._load(data, view_dict, data_type)

        if socket_id: view_dict['plug'] = self._create_plug(view_dict)

        webview.connect('motion-notify-event', lambda w, e, v: v.send('mouse-motion', True), view_dict)
        webview.connect('decide-policy', self._policy, view_dict)
        webview.connect('permission-request', self._permission, view_dict)
        webview.connect('create', self._new_window, view_dict)
        webview.connect('load-failed-with-tls-errors', self._tls_errors,
                        view_dict)
        webview.connect('load-changed', self._load_status, view_dict)
        webview.connect('mouse-target-changed', self._mouse_target_changed,
                        view_dict)
        webview.connect('notify::title', self._title_changed, view_dict)
        webview.connect('notify::uri', self._uri_changed, view_dict)
        webview.connect('notify::estimated-load-progress',
                        self._progress_changed, view_dict)
        webview.connect('notify::favicon', self._icon_loaded, view_dict)
        webview.connect('notify', self._prop_changed, view_dict)
        webview.connect('notify::load-failed', self._load_error, view_dict)
        webview.connect('notify::is-loading', self._is_loading, view_dict)
        webview.connect('notify::is-playing-audio', self._is_playing,
                        view_dict)
        webview.connect('insecure-content-detected', self._insecure_detect,
                        view_dict)
        webview.connect('resource-load-started', self._resource_started,
                        view_dict)
        webview.connect('context-menu', self._context_menu, view_dict)
        webview.connect('web-process-crashed', self._gtk.main_quit)

        find_controller.connect('found-text', self._found_text, view_dict)
        find_controller.connect('failed-to-find-text', self._found_failed,
                                view_dict)
        find_controller.connect('counted-matches', self._found_count,
                                view_dict)

        self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                self._recieve, view_dict)

        return view_dict

    def _create_plug(self, view_dict: dict):
        """ Create a plug.

        """

        plug = self._gtk.Plug.new(view_dict.socket_id)
        plug.connect('destroy', self._destroy, view_dict)
        plug.connect('delete-event', self._delete, view_dict)
        plug.add(view_dict.overlay)
        plug.show()

        return plug

    def _delete(self, plug: object, event: object, view_dict: dict):
        """ Destroy the webview before the plug.

        """

        view_dict.webview.stop_loading()
        view_dict.webview.load_uri('about:blank')
        view_dict.webview.destroy()
        while view_dict.webview.get_window(): pass
        view_dict.plug.destroy()
        print("DESTROYED IT")

        return False

    def _destroy(self, plug, view_dict):
        """ Quit

        """

        com_pipe = self._dict.pop(view_dict['socket-id'])

        print("delete", self._pid)
        send_dict = {'pid': self._pid, 'socket-id': view_dict['socket-id']}

        self._windows.remove(view_dict)

        if not self._windows:
            try:
                com_pipe.send(('terminate', send_dict))
            except BrokenPipeError as err:
                print("PIPE BROKE CLOSING", err)

            self._gtk.main_quit()

            print(self._pid, ' CLOSED')

        try:
            com_pipe.send(('closed', send_dict))
        except BrokenPipeError as err:
            print("PIPE BROKE CLOSING", err)

        print("CLOSED ", view_dict.webview)

    def _recieve(self, source: int, cb_condition: int, view_dict: dict):
        """ Recieve signals from outside.

        """

        print("IN RECIEVE: ", view_dict.com_tup[0])
        print("CHILD_DICT: ", self._dict)

        signal, data = view_dict.recv()
        print('signal: {signal}, data: {data}'.format(**locals()))

        if signal == 'close' and data:
            view_dict.plug.emit('delete-event', None)
            return False

        if signal == 'grab-focus': view_dict.webview.grab_focus()

        if signal == 'open-uri':
            view_dict.load(data)

        if signal == 'new-tab':
            new_win = self._new_tab(view_dict, data)
            uri = data.get('uri', 'about:blank')
            if uri != 'about:blank':
                new_win['webview'].load_uri(uri)

        if signal == 'socket-id':
            self._dict[data] = view_dict.com_tup[0]
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

        return True

    def _new_tab(self, view_dict: dict, data: dict):
        """ Make a new window.

        """

        conp, procp = Pipe()
        new_win = self._create_window(0, procp, view_dict.webview)
        info_dict = {
                'uri': data.get('uri', 'about:blank'),
                'pid': self._pid,
                'com-tup': (conp, self._dict),
                'switch-to': data.get('switch-to', False),
                'private': data.get('private', self._private),
                }
        view_dict.send('tab-info', info_dict)

        self._windows.append(new_win)

        return new_win

    def _new_window(self, webview: object, navigation_action: object,
                    view_dict: dict):
        """ New window in this process.

        """

        return self._new_tab(view_dict, {'switch-to': False}).webview

    def _context_menu(self, webview: object, menu: object, event: object,
                      hit_test_result: object, view_dict: dict):
        """ Modify the context menu before showing it.

        """

        if hit_test_result.context_is_selection():
            clipboard = self._gtk.Clipboard.get(self._gdk.SELECTION_PRIMARY)
            selected_text = clipboard.wait_for_text().strip()

            # Allways allow searching for selected text.
            action = self._gtk.Action('search-web', 'Search for selection',
                                      'Search for selection using current \
                                       search engine.', 'gtk-find')
            action.connect('activate', self._open_selection, selected_text,
                           view_dict)
            menu_item = self._webkit2.ContextMenuItem.new(action)
            menu.prepend(self._webkit2.ContextMenuItem.new_separator())
            menu.prepend(menu_item)

            # Add an open-uri option if the selected text looks like a uri.
            if looks_like_uri(selected_text):
                action = self._gtk.Action('open-uri', 'Open in new tab',
                                          'Open selected uri in new tab',
                                          'gtk-jump-to')
                action.connect('activate', self._open_selection, selected_text,
                            view_dict)

            menu_item = self._webkit2.ContextMenuItem.new(action)
            menu.append(self._webkit2.ContextMenuItem.new_separator())
            menu.append(menu_item)

        action = self._gtk.Action('view-source', 'View Source',
                                  'View Source', 'gtk-edit')
        action.connect('activate', self._open_selection, '', view_dict)
        menu_item = self._webkit2.ContextMenuItem.new(action)
        menu.append(menu_item)

    def _open_selection(self, action: object, selected_text: str,
                        view_dict: dict):
        """ Open a new tab searching for the selection.

        """

        if action.get_name() == 'view-source':
            res = view_dict.webview.get_main_resource()
            res.get_data(None, self._get_source, view_dict)
            return True

        if action.get_name() == 'search-web':
            selected_text = self._search_url % selected_text

        new_tab = self._new_tab(view_dict, {'switch-to': False,
                                            'uri': selected_text})
        new_tab.load(selected_text)

        return True

    def _load(self, data: str, view_dict: dict, data_type: str = 'uri'):
        """ Load the data in the webview in view_dict.

        """

        webview = view_dict.webview

        if data_type == 'uri':
            # Data doesn't look like a uri so treat it as a search
            # string.
            if not looks_like_uri(data): data = self._search_url % data
            # Data looks like a uri but it doesn't start with
            # somthing:// so prepend http:// to it.
            if ':' not in data: data = 'http://%s' % data

            webview.load_uri(data)

        webview.grab_focus()
        view_dict.send('title', data)

    def _resource_started(self, webview: object, resource: object,
                          request: object, view_dict: dict):
        """ Moniter resources.

        """

        # print("RESOURCE", request.get_uri())
        uri = request.get_uri()
        if webview.get_uri().startswith('https') and uri.startswith('http:'):
            print("INSECURE RESOURCE", uri)
            view_dict.send('insecure-content', True)

    def _permission(self, webview: object, request: object, view_dict: dict):
        """ Grant or deny permission for request.

        """

        print("PERMISSION", request)
        request.deny()
        return True

    def _policy(self, webview: object, decision: object, decision_type: object,
                view_dict: dict):
        """ Handle opening a new window.

        """

        if decision_type in \
                [self._webkit2.PolicyDecisionType.NAVIGATION_ACTION, \
                 self._webkit2.PolicyDecisionType.NEW_WINDOW_ACTION]:

            nav_action = decision.get_navigation_action()
            request = nav_action.get_request()
            uri = request.get_uri()

            if nav_action.get_mouse_button() == 2 or \
                    (nav_action.get_mouse_button() == 1 and \
                    nav_action.get_modifiers() & \
                    self._gdk.ModifierType.CONTROL_MASK):

                decision.ignore()

                if decision.get_modifiers() & self._gdk.ModifierType.SHIFT_MASK:
                    new_tab = self._new_tab(view_dict,
                                            {'switch-to': False, 'uri': uri})
                    new_tab['webview'].load_uri(uri)
                    return True

                data_dict = {'uri': uri, 'switch_to': False}
                if decision.get_modifiers() & self._gdk.ModifierType.MOD1_MASK:
                    data_dict['private'] = False


                view_dict.send('create-tab', data_dict)

                return True
            else:
                if nav_action.get_navigation_type() == self._webkit2.NavigationType.OTHER:
                    if not uri.startswith('https') and webview.get_uri().startswith('https'):
                        print("BLOCKING INSECURE (REQUEST)", uri)
                        decision.ignore()
                        return True
        elif decision_type == self._webkit2.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            uri = response.get_uri()
            if not uri.startswith('https') and webview.get_uri().startswith('https'):
                print("BLOCKING INSECURE (RESPONSE)", uri)
                decision.ignore()
                return True
        else:
            print("UNKNOWN", decision, decision_type)

        self._glib.idle_add(self._send_back_forward, webview, view_dict)
        decision.use()
        return True

    def _insecure_detect(self, webview: object, event: object, view_dict: dict):
        """ Detect Insecure content

        """

        print("INSECURE CONTENT: ", event)
        view_dict.send('insecure-content', True)

    def _title_changed(self, webview: object, prop: object, view_dict: dict):
        """ The title changed.

        """

        title = webview.get_property(prop.name)
        view_dict.send('title', title if title else 'about:blank')

    def _tls_errors(self, webview: object, uri: str, cert: object,
                    errors: object, view_dict: dict):
        """ Detect tls errors.

        """

        print("TLS_ERROR {errors} ON {uri} with cert {cert}".format(**locals()))
        view_dict.send('tls-error', True)
        self._verify_view(webview, view_dict)
        return False

    def _prop_changed(self, webview: object, data: str, view_dict: dict):
        """
        """
        # print('PROP CHANGED: ', data.name, webview.get_property(data.name))
        # settings = webview.get_settings()
        # print('PRIVATE: ', settings.get_enable_private_browsing())
        pass

    def _icon_loaded(self, webview: object, icon_uri: str, view_dict: dict):
        """ Set icon loaded signal.

        """

        uri = webview.get_uri()
        icon = webview.get_favicon()
        print("ICON: ", icon)

        if icon:
            pixbuf = self._gdk.pixbuf_get_from_surface(icon, 0, 0,
                                                       icon.get_width(),
                                                       icon.get_height())
        else:
            pixbuf = self._html_pixbuf

        view_dict.send('icon-bytes', pixbuf.save_to_bufferv('png', '', '')[1])

    def _is_playing(self, webview: object, is_playing: bool, view_dict: dict):
        """ Send if this tab is playing audio.

        """

        print("IS PLAYING", webview.get_property(is_playing.name))
        view_dict.send('is-playing', webview.get_property(is_playing.name))

    def _is_loading(self, webview: object, is_loading: object,
                    view_dict: dict):
        """ Tell if it is loading.

        """

        print("IS LOADING", webview.get_property(is_loading.name))
        view_dict.send('is-loading', webview.get_property(is_loading.name))
        # if not webview.get_property(is_loading.name):
        #     webview.get_main_resource().get_data(None, self._get_source, view_dict)

    def _get_source(self, source_object: object, res: object, view_dict: dict):
        """ print the source.

        """

        data = source_object.get_data_finish(res)
        tmpfile = tempfile.NamedTemporaryFile()
        tmpfile.write(data)
        view_dict['tmpfile'] = tmpfile
        proc = subprocess.Popen(['/usr/bin/gvim', tmpfile.name], stdout=subprocess.PIPE)
        self._glib.io_add_watch(proc.stdout.fileno(), self._glib.IO_IN, self._close_tmp, view_dict)

    def _close_tmp(self, source: int, cb_condition: int, view_dict: dict):
        """ Close tmp files in view_dict.

        """

        with os.fdopen(source, 'r') as tmpfile:
            if tmpfile.read():
                print("Closing")
                tmpfile = view_dict.pop('tmpfile')
                tmpfile.close()
                return False
        return True

    def _send_back_forward(self, webview: object, view_dict: dict):
        """ Send the back/forward history lists.

        """

        def build_list(hist_list: object) -> list:
            """ for each item is hist_list add the data to a dictionary and
            append that to a list.  Return the resulting list of dictionaries.

            """

            hist_dict_list = []

            if not hist_list: return hist_dict_list

            for item in hist_list:
                tmp_dict = {
                        'title': item.get_title(),
                        'uri': item.get_uri(),
                        'original-uri': item.get_original_uri()
                        }
                hist_dict_list.append(tmp_dict)

            return hist_dict_list

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

    def _verify_view(self, webview: object, view_dict: dict):
        """ Check for tls security.

        """

        print('CERTIFICATE: ' , webview.get_tls_info())
        verified, certificate, flags = webview.get_tls_info()
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

        if load_event == self._webkit2.LoadEvent.STARTED:
            pass
        elif load_event == self._webkit2.LoadEvent.REDIRECTED:
            view_dict.send('uri-changed', webview.get_uri())
        elif load_event == self._webkit2.LoadEvent.FINISHED:
            self._glib.idle_add(self._send_back_forward, webview, view_dict)
            self._verify_view(webview, view_dict)

        view_dict.send('load-status', int(load_event))

    def _load_error(self, webview: object, webframe: object, uri: str,
                    weberror: object, view_dict: dict):
        """ Get the error.

        """

        print("LOAD ERROR: ", uri, weberror.message)
        view_dict.send('load-error', {'uri': uri, 'message': weberror.message})

    def _uri_changed(self, webview: object, prop: object, view_dict: dict):
        """ Send new uri and history.

        """

        uri = webview.get_property(prop.name)
        print('uri changed: ', webview.get_property(prop.name))
        view_dict.send('uri-changed', uri)

    def _mouse_target_changed(self, webview: object, hit_test_result: object,
                              modifiers: object, view_dict: dict):
        """ Send info about what the mouse is over.

        """

        if hit_test_result.context_is_image():
            uri = hit_test_result.get_image_uri()
        elif hit_test_result.context_is_media():
            uri = hit_test_result.get_media_uri()
        else:
            uri = hit_test_result.get_link_uri()

        title = hit_test_result.get_link_title()

        # Send the uri of the object under the mouse.
        view_dict.send('hover-link', {'uri': uri, 'title': title})

        # Show the status label if there is something to show.
        view_dict['status-label'].set_text(uri if uri else '')
        view_dict['status-label'].set_visible(bool(uri))

    def _resource_response(self, webview: object, webframe: object,
                           resource: object, response: object,
                           view_dict: dict):
        """ Andle response.

        """

        message = response.get_message()
        if message:
            print("RESOURCE RESPONSE: ", message.get_flags())

    def _progress_changed(self, webview: object, prop: object, view_dict: dict):
        """ Send the progress

        """

        progress = webview.get_property(prop.name)
        view_dict.send('progress', progress)

    def _found_count(self, find_controller: object, match_count: int,
                     view_dict: dict):
        """ Gets the number of matches.

        """

        print("FIND_COUNT", match_count)

    def _found_failed(self, find_controller: object, view_dict: dict):
        """ Sends that find failed.

        """

        view_dict.send('find-failed', True)

    def _found_text(self, find_controller: object, match_count: int,
                    view_dict: dict):
        """ Found text.

        """

        print("FOUND", match_count)
        view_dict.send('find-failed', False)

    def run(self):
        """ Run the main gtk loop.

        """

        self._gtk.main()


def run_browser(data: object):
    """ Runs a browser.

    """

    browser = BrowserProc(data)
    browser.run()


def new_proc(data: dict):
    """ Create and run a new process.

    """

    test_t = Process(target=run_browser, args=(data,))
    test_t.start()
    return test_t


class MainWindow(object):
    """ The main window.

    """

    def __init__(self, com_pipe: object, com_dict: object):
        """ Initialize the process.


        """

        from gi.repository import Gtk as gtk
        from gi.repository import Gdk as gdk
        from gi.repository import GLib as glib
        from gi.repository import Pango as pango
        from gi.repository import Gio as gio
        from gi.repository import GdkPixbuf as gdkpixbuf

        with pathlib.Path(CONFIG_FILE) as config_file:
            if config_file.is_file():
                self._config = json_loads(config_file.read_text())
            else:
                self._config = {}

        self._gtk = gtk
        self._gdk = gdk
        self._glib = glib
        self._pango = pango
        self._gio = gio
        self._gdkpixbuf = gdkpixbuf
        self._name = 'Web Browser'
        self._find_str = ''

        css_provider = self._gtk.CssProvider.get_default()
        css_provider.load_from_data(b'''
                * {
                    -GtkEntry-icon-prelight: True;
                }
                GtkEntry#not-found {
                    background: #ff5555;
                }
                GtkEntry#verified {
                    border-color: #9dbf60;
                }
                GtkEntry#unverified {
                    border-color: #E2A564;
                }
                GtkEntry#insecure {
                    border-color: #E2A564;
                }
                GtkButton.close-button {
                    padding-top: 0px;
                    padding-bottom: 0px;
                }
                ''')
        self._gtk.StyleContext.add_provider_for_screen(
                self._gdk.Screen.get_default(),
                css_provider,
                self._gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )

        self._revived = []
        self._fixed_address_bar = True

        screen = self._gdk.Screen.get_default()
        width = screen.get_width() // 2
        height = math.floor(screen.get_height() * 9 // 10)

        icontheme = self._gtk.IconTheme().get_default()
        self._html_pixbuf = icontheme.load_icon('text-html',
                                                self._gtk.IconSize.MENU,
                                                self._gtk.IconLookupFlags.USE_BUILTIN)
        self._playing_pixbuf = icontheme.load_icon('audio-volume-medium',
                                                   self._gtk.IconSize.MENU,
                                                   self._gtk.IconLookupFlags.USE_BUILTIN)
        self._secure_pixbuf = icontheme.load_icon('security-high',
                                                   self._gtk.IconSize.MENU,
                                                   self._gtk.IconLookupFlags.USE_BUILTIN)
        self._insecure_pixbuf = icontheme.load_icon('security-low',
                                                   self._gtk.IconSize.MENU,
                                                   self._gtk.IconLookupFlags.USE_BUILTIN)

        self._accels = self._gtk.AccelGroup()

        accel_dict = {
                ('<Ctrl>t', '<Control><Alt>t', '<Ctrl><Shift>t'): self._new_tab,
                ('<Ctrl>w',): self._close_tab,
                ('<Ctrl><Alt>r',): lambda *a: com_pipe.send(('refresh', True)),
                ('<Ctrl>l',): self._focus_address_entry,
                ('<Ctrl>m',): self._minimize_tab,
                ('<Ctrl>h',): self._hide_tab,
                ('<Ctrl>f',): self._find_toggle,
                ('<Ctrl>y',): self._yank_hover,
                ('<Ctrl>g', '<Ctrl><Shift>g'): self._find_next_key,
                ('Escape',): self._escape,
                ('<Ctrl>r', 'F5'): lambda *a: self._get_current_child().send('refresh', True),
                }
        for accel_tup, func in accel_dict.items():
            for accel in accel_tup:
                keyval, modifier = self._gtk.accelerator_parse(accel)
                self._accels.connect(keyval, modifier,
                                     self._gtk.AccelFlags.VISIBLE,
                                     func)
        for i in range(9):
            self._accels.connect(self._gdk.keyval_from_name(str(i)),
                                 self._gdk.ModifierType.MOD1_MASK,
                                 self._gtk.AccelFlags.VISIBLE,
                                 self._switch_tab)



        self._window = self._gtk.Window()
        self._window.set_title(self._name)
        self._window.add_accel_group(self._accels)

        # self._header_bar = self._gtk.HeaderBar()
        # self._header_bar.set_show_close_button(True)
        # self._window.set_titlebar(self._header_bar)
        self._window.set_default_size(self._config.get('width', width),
                                      self._config.get('height', height))
        self._window.set_resizable(True)
        self._window.set_icon_name('web-browser')
        self._window.connect('motion-notify-event', self._mouse_move)
        self._window.connect('destroy', self._destroy)
        self._window.connect('delete-event', self._delete_event)
        self._window.connect('configure-event', self._configure_event)

        self._tabs = self._gtk.Notebook()
        self._tabs.add_events(self._gdk.EventMask.SCROLL_MASK)
        self._tabs.connect('page-reordered', self._tab_reordered)
        self._tabs.connect('page-removed', self._tab_removed)
        self._tabs.connect('switch-page', self._tab_switched)
        self._tabs.connect('scroll-event', self._tab_scrolled)
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)

        vbox = self._gtk.VBox()
        vbox.pack_start(self._tabs, True, True, 0)

        self._window.add(vbox)
        self._window.show_all()

        self._pipe = com_pipe
        self._dict = com_dict

        self._windows = {}
        self._closed = {}
        self._last_tab = []

        self._glib.io_add_watch(self._pipe.fileno(), self._glib.IO_IN,
                                self._recieve)

        self._send('new-proc', self._make_tab(switch_to=True))

    def _make_tab(self, uri: str = 'about:blank', switch_to: bool = False,
                  private: bool = True):
        """ Make a tab.

        """

        main_pipe, child_pipe = Pipe()
        com_dict = Manager().dict({'private': private})

        socket_id, _ = self._add_tab((main_pipe, com_dict), uri, switch_to)

        com_dict[socket_id] = child_pipe

        return com_dict

    def _configure_event(self, window: object, event: object):
        """ Get when the window is resized.

        """

        self._config['width'] = event.width
        self._config['height'] = event.height
        return False

    def _delete_event(self, window: object, event: object):
        """ Try to close all tabs first.

        """

        print("DELETE EVENT")
        for socket_id, data in self._windows.items():
            com_pipe = data['com-tup'][0]
            com_pipe.send(('close', True))

        self._window.destroy()

    def _destroy(self, window: object):
        """ Quit

        """

        with pathlib.Path(CONFIG_FILE) as config_file:
            config_file.write_text(json_dumps(self._config, indent=4))

        print("DESTROY")
        for socket_id, data in self._windows.items():
            self._pipe.send(('terminate', data['pid']))

        self._gtk.main_quit()
        self._pipe.send(('Quit', True))

    def run(self):
        """ Run gtk.main()

        """

        self._gtk.main()

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        signal, data = window.recv()

        quiet_list = [
                'mouse-motion',
                'back-forward-list',
                'can-go-back',
                'can-go-forward',
                'is-secure',
                'icon-bytes',
                'progress',
                'hover-link',
                ]
        if signal not in quiet_list:
            print("_CALLBACK: {signal} => {data}".format(**locals()))

        if signal == 'closed' or signal == 'terminate' and data:
            socket_id = data['socket-id']
            pid = data['pid']

            self._closed[pid] = self._windows.pop(socket_id)['com-tup'][1]

            if signal == 'terminate':
                self._closed.pop(pid, None)
                print('Terminating ', pid)
                self._pipe.send(('terminate', pid))

            print('CLOSED DICT', self._closed)

            self._tabs.remove_page(self._tabs.page_num(window['vbox']))

            return False

        if signal == 'mouse-motion':
            if not self._fixed_address_bar:
                window.address_bar.hide()

        if signal == 'pid':
            window.pid = data
            if window.uri != 'about:blank':
                window.send('open-uri', window.uri)
            self._update_title(window)

        if signal == 'tab-info':
            print('TAB_INFO', data)
            socket_id, child = self._add_tab(data['com-tup'], data['uri'],
                                             data['switch-to'])
            child.update(data)
            self._windows[socket_id] = child
            child.send('socket-id', socket_id)
            self._update_title(child)

        if signal == 'create-tab':
            self._pipe.send(('new-proc', self._make_tab(**data)))

        if signal == 'title' and data != window.get('title', 'about:blank'):
            window['title'] = data
            self._update_title(window)
            window['label'].set_text(window.title_str)
            window['ebox'].set_tooltip_text(window.title_str)

        if signal == 'icon-bytes' and data:
            loader = self._gdkpixbuf.PixbufLoader()
            loader.set_size(16, 16)
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            window['icon-image'] = pixbuf
            window['icon'].set_from_pixbuf(pixbuf)
            window['entry'].set_icon_from_pixbuf(self._gtk.EntryIconPosition.PRIMARY,
                                                 pixbuf)

        if signal == 'load-status' and data == 0:
            window.entry.set_name('')
            window['entry'].set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                                    'gtk-stop')
            window['entry'].set_icon_tooltip_text(self._gtk.EntryIconPosition.SECONDARY,
                                                'Stop loading page.')
            window['icon'].hide()
            window['spinner'].show_all()
            window['spinner'].start()
            window.insecure_content = False
        elif signal == 'load-status' and data == 3:
            window['entry'].set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                                    'gtk-refresh')
            window['entry'].set_icon_tooltip_text(self._gtk.EntryIconPosition.SECONDARY,
                                                'Reload current address.')
            window['spinner'].stop()
            window['spinner'].hide()
            window['icon'].show_all()
            window['entry'].set_progress_fraction(0)

        if signal == 'uri-changed' and data:
            window['uri'] = data
            window['entry'].set_text('' if data == 'about:blank' else data)

        if signal == 'progress':
            window['entry'].set_progress_fraction(data)
            if data == 1.0:
                window['entry'].set_progress_fraction(0)

        if signal == 'hover-link':
            uri = data['uri']
            window['hover-uri'] = uri

        if signal == 'is-playing':
            window['playing-icon'].set_visible(data)

        if signal == 'is-secure':
            insecure_str = ''
            verified, issuer_known, certificate, flags = data
            print("ISSUER KNOWN: ", issuer_known)

            window.cert_data = data if certificate else ()

            if verified:
                verified_str = 'Page has a verified certificate.'
                window.entry.set_name('verified')
            else:
                verified_str = 'Page has an invalid or un-verified certificate.'
                window.entry.set_name('unverified')

            if verified and window.get('insecure-content', True):
                insecure_str = '  Page contains insecure content.'
                window.entry.set_name('insecure')

            if not window.uri.startswith('https'):
                verified_str = 'Page is insecure.'
                window.entry.set_name('')

            tooltip_text = '{verified_str} {insecure_str}'.format(**locals())
            window.entry.set_tooltip_text(tooltip_text)

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

        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """


        signal, data = self._pipe.recv()
        print('RECIEVE: {signal} => {data}'.format(**locals()))
        if signal == 'open-tab':
            self._send('new-proc', data)

        if signal == 'add-tab':
            self._send('new-proc', self._make_tab(**data))

        return True

    def _update_title(self, child: dict):
        """ Update the window title.

        """

        child.private_str = 'Private' if child.private else ''
        child.title_str = '{title} (pid: {pid}) {private_str}'.format(**child)
        if child == self._get_current_child():
            self._window.set_title('{title-str} - {name}'.format(**child, name=self._name))

    def _send(self, signal: str, data: object):
        """ Send signal and data using the main pipe.

        """

        self._pipe.send((signal, data))

    def _load_uri(self, entry: object, child: dict):
        """ Load uri.

        """

        uri = entry.get_text()
        child.send('open-uri', uri)

    def _add_tab(self, com_tup: tuple, uri: str = 'about:blank',
                 switch_to: bool = False):
        """ Add Tab.

        """

        child = ChildDict({
            'com-tup': com_tup,
            'uri': uri,
            'title': 'about:blank',
            'title-str': 'about:blank (pid: 0) (Private)',
            'cert-data': (False, False, {}, 0),
            'private': True,
            'private-str': 'Private',
            'pid': 0,
            'back-list': [],
            'current-dict': {},
            'forward-list': [],
            'send': lambda signal, data: com_tup[0].send((signal, data)),
            'recv': lambda: com_tup[0].recv(),
            })

        find_entry = self._gtk.Entry()
        find_next = self._gtk.Button()
        find_next.add(self._gtk.Arrow(self._gtk.ArrowType.DOWN,
                                      self._gtk.ShadowType.NONE))
        find_prev = self._gtk.Button()
        find_prev.add(self._gtk.Arrow(self._gtk.ArrowType.UP,
                                      self._gtk.ShadowType.NONE))

        close_image = self._gtk.Image.new_from_stock('gtk-close',
                                                     self._gtk.IconSize.MENU)
        find_close = self._gtk.Button()
        find_close.connect('button-release-event',
                           lambda btn, evnt, chld: chld.find_bar.hide(), child)
        find_close.get_style_context().add_class('close-button')
        find_close.set_relief(self._gtk.ReliefStyle.NONE)
        find_close.set_image(close_image)
        close_item = self._gtk.ToolItem()
        close_item.add(find_close)

        item_box = self._gtk.HBox()
        item_box.get_style_context().add_class('linked')
        item_box.pack_start(find_entry, True, True, 0)
        item_box.pack_start(find_prev, False, False, 0)
        item_box.pack_start(find_next, False, False, 0)
        box_item = self._gtk.ToolItem()
        box_item.add(item_box)

        space_item = self._gtk.ToolItem()
        space_item.set_expand(True)

        find_bar = self._gtk.Toolbar()
        find_bar.set_icon_size(self._gtk.IconSize.MENU)
        find_bar.add(box_item)
        find_bar.add(space_item)
        find_bar.add(close_item)

        address_entry = self._gtk.Entry()
        address_entry.set_placeholder_text("Enter address or search string")
        address_entry.get_style_context().add_class('address_entry')
        address_entry.get_style_context().add_class('address')
        address_entry.set_icon_from_pixbuf(self._gtk.EntryIconPosition.PRIMARY,
                                           self._html_pixbuf)
        address_entry.set_icon_tooltip_text(self._gtk.EntryIconPosition.PRIMARY,
                                            'Open bookmark menu.')
        address_entry.set_icon_sensitive(self._gtk.EntryIconPosition.PRIMARY,
                                         True)
        address_entry.set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                              'go-jump')
        address_entry.set_icon_tooltip_text(self._gtk.EntryIconPosition.SECONDARY,
                                            'Go to address in address entry.')
        address_entry.set_icon_sensitive(self._gtk.EntryIconPosition.SECONDARY,
                                         True)

        back_button = self._gtk.Button()
        back_button.set_relief(self._gtk.ReliefStyle.NONE)
        back_button.set_sensitive(False)
        back_button.connect('button-release-event', self._back_released, child)
        back_button.add(self._gtk.Arrow(self._gtk.ArrowType.LEFT,
                                        self._gtk.ShadowType.NONE))
        forward_button = self._gtk.Button()
        forward_button.set_relief(self._gtk.ReliefStyle.NONE)
        forward_button.set_sensitive(False)
        forward_button.connect('button-release-event', self._forward_released, child)
        forward_button.add(self._gtk.Arrow(self._gtk.ArrowType.RIGHT,
                                           self._gtk.ShadowType.NONE))

        address_box = self._gtk.HBox()
        # address_box.get_style_context().add_class('linked')
        address_box.pack_start(back_button, False, False, 0)
        address_box.pack_start(forward_button, False, False, 0)
        address_box.pack_start(address_entry, True, True, 0)
        button_item = self._gtk.ToolItem()
        button_item.set_expand(True)
        button_item.add(address_box)

        address_bar = self._gtk.Toolbar()
        address_bar.set_valign(self._gtk.Align.START)
        address_bar.add(button_item)

        label = self._gtk.Label('about:blank')
        label.set_justify(self._gtk.Justification.LEFT)
        label.set_alignment(xalign=0, yalign=0.5)
        label.set_width_chars(18)
        label.set_max_width_chars(18)
        label.set_ellipsize(self._pango.EllipsizeMode(3))
        label.show_all()

        icon = self._gtk.Image()
        icon.set_from_pixbuf(self._html_pixbuf)

        playing_icon = self._gtk.Image()
        playing_icon.set_from_pixbuf(self._playing_pixbuf)

        spinner = self._gtk.Spinner()
        spinner.hide()

        hbox = self._gtk.HBox(homogeneous=False, spacing=0)
        hbox.pack_start(icon, False, False, 3)
        hbox.pack_start(spinner, False, False, 3)
        hbox.pack_end(playing_icon, False, False, 0)
        hbox.pack_end(label, False, False, 0)

        eventbox= self._gtk.EventBox()
        eventbox.add_events(self._gdk.EventMask.SCROLL_MASK)
        eventbox.add(hbox)
        eventbox.show_all()
        playing_icon.hide()

        socket = self._gtk.Socket()

        overlay = self._gtk.Overlay()
        overlay.add_overlay(socket)
        if not self._fixed_address_bar:
            overlay.add_overlay(address_bar)

        vbox = self._gtk.VBox()
        vbox.pack_end(find_bar, False, False, 0)
        vbox.pack_end(overlay, True, True, 0)
        if self._fixed_address_bar:
            vbox.pack_start(address_bar, False, False, 0)
        vbox.show_all()
        find_bar.hide()


        insert_at = -1 if switch_to else self._tabs.get_current_page() + 1
        index = self._tabs.insert_page(vbox, eventbox, insert_at)
        self._tabs.set_tab_reorderable(vbox, True)

        socket_id = socket.get_id()

        child.update({
            'address-bar': address_bar,
            'back-button': back_button,
            'forward-button': forward_button,
            'spinner': spinner,
            'icon': icon,
            'icon-image': self._html_pixbuf,
            'entry': address_entry,
            'label': label,
            'socket': socket,
            'ebox': eventbox,
            'vbox': vbox,
            'hbox': hbox,
            'socket-id': socket_id,
            'com-tup': com_tup,
            'playing-icon': playing_icon,
            'find-entry': find_entry,
            'find-bar': find_bar,
            'history-menu': self._gtk.Menu(),
            })


        self._windows[socket_id] = child

        child['plug-removed'] = socket.connect('plug-removed',
                                               self._plug_removed, child)
        eventbox.connect('button-press-event', self._tab_button_press, child)
        eventbox.connect('button-release-event', self._tab_button_release,
                         child)
        address_entry.connect('activate', self._load_uri, child)
        address_entry.connect('icon-release', self._entry_icon_release, child)
        address_entry.connect('changed', self._entry_changed, child)
        find_entry.connect('activate', self._find, child)
        find_entry.connect('changed', self._find, child)
        find_next.connect('button-release-event', self._find_next_button,
                          child)
        find_prev.connect('button-release-event', self._find_prev_button,
                          child)

        self._glib.io_add_watch(com_tup[0].fileno(), self._glib.IO_IN,
                                self._callback, child)

        if switch_to:
            self._tabs.set_current_page(index)
            address_entry.grab_focus()

        return socket_id, child

    def _yank_hover(self, accels: object, window: object, keyval: object,
                    flags: object):
        """ Put the last uri that was hovered over in the clipboard.

        """

        child = self._get_current_child()
        if 'hover-uri' in child:
            clipboard = self._gtk.Clipboard.get(self._gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(child.hover_uri, -1)

    def _mouse_move(self, window: object, event: object):
        """ Hide/unhide address-bar.

        """

        if not self._fixed_address_bar:
            child = self._get_current_child()
            child.address_bar.show_all()
            child.entry.grab_focus()

    def _escape(self, accels: object, window: object, keyval: object, flags: object):
        """ Do stuff.

        """

        child = self._get_current_child()
        if child.entry.has_focus():
            uri_str = '' if child.uri == 'about:blank' else child.uri
            child.entry.set_text(uri_str)
            icon = 'gtk-stop' if child.spinner.is_visible() else 'gtk-refresh'
            child.entry.set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                                icon)
            if not self._fixed_address_bar:
                child.address_bar.hide()
        elif child.find_entry.has_focus():
            self._findbar_toggle()
        else:
            child.send('stop', True)

    def _entry_changed(self, entry: object, child: dict):
        """ Changes secondary icon depending on if entry has focus or not.

        """

        is_uri = entry.get_text() == child.uri
        icon = 'gtk-stop' if child.spinner.is_visible() else 'gtk-refresh'
        entry.set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                      icon if is_uri else 'go-jump')
        if is_uri:
            if icon == 'gtk-stop':
                tooltip_text = 'Stop loading page.'
            else:
                tooltip_text = 'Reload current address.'
        else:
            uri = entry.get_text()
            tooltip_text = 'Go to address in address entry.'
            if not looks_like_uri(uri):
                tooltip_text = 'Search for text in address entry.'

        child.entry.set_icon_tooltip_text(self._gtk.EntryIconPosition.SECONDARY,
                                          tooltip_text)

    def _find_toggle(self, accels: object, window: object, keyval: object, flags: object):
        """ Toggle findbar visibility.

        """

        self._findbar_toggle()

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
        child.send('find', entry.get_text())

    def _find_next_key(self, accels: object, window: object, keyval: object, flags: object):
        """ Find next.

        """

        child = self._get_current_child()
        find_bar = child['find-bar']
        find_entry = child['find-entry']

        if self._find_str and self._find_str != find_entry.get_text():
            find_entry.set_text(self._find_str)

        if not find_bar.is_visible():
            find_bar.show_all()
            find_entry.grab_focus()

        if flags & self._gdk.ModifierType.SHIFT_MASK:
            child.send('find-prev', find_entry.get_text())
        else:
            child.send('find-next', find_entry.get_text())

    def _find_next_button(self, button: object, event: object, child: dict):
        """ find next.

        """

        child.send('find-next', child.find_entry.get_text())

    def _find_prev_button(self, button: object, event: object, child: dict):
        """ find prev.

        """

        child.send('find-prev', child.find_entry.get_text())

    def _minimize_tab(self, accels: object, window: object, keyval: object,
                      flags: object):
        """ Hide/unhide the label of the current tab.

        """

        child = self._get_current_child()
        child.label.set_visible(not child.label.get_visible())

    def _hide_tab(self, accels: object, window: object, keyval: object,
                  flags: object):
        """ Hide/unhide the hbox of the current tab.

        """

        child = self._get_current_child()
        child.hbox.set_visible(not child.hbox.get_visible())

    def _back_released(self, button: object, event: object, child: dict):
        """ Go Back.

        """

        if event.button == 1:
            child.send('history-go-to', -1)
        elif event.button == 3:
            menu = self._make_history_menu(child.back_list, True, child)
            menu.popup(None, None, None, None, event.button, event.time)
            print(child.back_list, event.time)
        elif event.button == 2:
            uri = child.back_list[0]['uri']
            self._send('new-proc', self._make_tab(uri=uri))

        return False

    def _forward_released(self, button: object, event: object, child: dict):
        """ Go forward.

        """

        if event.button == 1:
            child.send('history-go-to', 1)
        elif event.button == 3:
            menu = self._make_history_menu(child.forward_list, False, child)
            menu.popup(None, None, None, None, event.button, event.time)
            print(child.forward_list, event.time)
        elif event.button == 2:
            uri = child.forward_list[0]['uri']
            self._send('new-proc', self._make_tab(uri=uri))

        return False

    def _make_history_menu(self, hist_list: list, back: bool, child: dict) -> object:
        """ Returns a menu or hist_list ready to popup.

        """

        menu = child.history_menu
        menu.foreach(menu.remove)

        for index, item in enumerate(hist_list):
            item_text = item['title'] if item['title'] else item['uri']
            menu_item = self._gtk.MenuItem(item_text)
            menu_item.connect('button-release-event',
                                lambda mi, e, c: \
                                        c.send('history-go-to', mi.index),
                                        child)
            menu_item.index = -(index + 1) if back else len(hist_list) - index
            menu.append(menu_item) if back else menu.insert(menu_item, 0)

        menu.show_all()

        return menu

    def _entry_icon_release(self, entry: object, icon_pos: object,
                            event: object, child: dict):
        """ Do stuff when an icon is clicked.

        """

        if icon_pos == self._gtk.EntryIconPosition.SECONDARY:
            if entry.get_text() not in (child.uri, ''):
                self._load_uri(entry, child)
            elif child.spinner.get_property('active'):
                child.send('stop', True)
            else:
                if event.button == 2 or (event.button == 1 and \
                        event.state & self._gdk.ModifierType.CONTROL_MASK):
                    if event.state & self._gdk.ModifierType.SHIFT_MASK:
                        data_dict = {'uri': child.uri}
                        child.send('new-tab', data_dict)
                    else:
                        self._send('new-proc', self._make_tab(uri=child.uri))
                elif event.state & self._gdk.ModifierType.MOD1_MASK:
                    child.send('refresh-bypass', True)
                else:
                    child.send('refresh', True)

        return False

    def _tab_scrolled(self, notebook: object, event: object):
        """ Switch to next or previous tab.

        """

        # Enable scrolling through the tabs.
        if event.direction == self._gdk.ScrollDirection.DOWN:
            self._tabs.next_page()
        else:
            self._tabs.prev_page()

    def _tab_reordered(self, notebook: object, child: object, index: int):
        """ Set the new ordering.

        """

        print(child, index)

    def _tab_switched(self, notebook: object, child: object, index: int):
        """ Do stuff when the tab is switched.

        """

        # Do nothing if there are no more tabs.
        if not self._windows: return True

        child_dict = self._get_current_child(child)
        self._window.set_title('{title-str} - {name}'.format(**child_dict,
                                                             name=self._name))

        self._last_tab.append(child)

        if not child_dict.entry.get_text():
            child_dict.address_bar.show_all()
            child_dict.entry.grab_focus()
        else:
            child_dict.back_button.grab_focus()
            child_dict.send('grab-focus', True)

        return True

    def _tab_removed(self, notebook: object, child: object, index: int):
        """ Remove page info.

        """

        if notebook.get_n_pages() == 0:
            print("NO MORE PAGES, EXITING")
            self._window.emit('delete-event', None)

    def _to_last_tab(self, child: object):
        """ Switch to the correct tab before closing.

        """

        try:
            # Remove all instances of child from the last tab list.
            self._last_tab = [i for i in self._last_tab if i != child]

            # Switch to the last tab.
            if self._last_tab:
                self._tabs.set_current_page(
                        self._tabs.page_num(self._last_tab.pop(-1))
                        )
        except:
            pass

    def _tab_button_press(self, eventbox: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 2 or (event.button == 1 and \
                event.state & self._gdk.ModifierType.CONTROL_MASK):
            return True

    def _tab_button_release(self, eventbox: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 2 or (event.button == 1 and \
                event.state & self._gdk.ModifierType.CONTROL_MASK):
            child['socket'].disconnect(child['plug-removed'])

            if self._tabs.get_nth_page(self._tabs.get_current_page()) == child['vbox']:
                self._to_last_tab(child['vbox'])

            if event.state & self._gdk.ModifierType.MOD1_MASK:
                for _, tab in self._windows.items():
                    if tab['pid'] == child['pid']:
                        self._tabs.remove_page(self._tabs.page_num(tab['vbox']))
                print("sending Terminate")
                self._send('terminate', child['pid'])
            else:
                print("sending Close")
                child.send('close', True)

    def _get_current_child(self, vbox: object = None):
        """ Returns the child dict of the current tab.

        """

        overlay_index = 1 if self._fixed_address_bar else 0

        if not self._windows:
            return {'title': 'about:blank', 'uri': 'about:blank'}

        if not vbox:
            vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
            while not vbox.get_children()[overlay_index].get_children(): pass

        socket = vbox.get_children()[overlay_index].get_children()[0]
        return self._windows[socket.get_id()]

    def _new_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Open a new tab.

        """

        print("MODIFIER NEW TAB: ", flags)
        if flags & self._gdk.ModifierType.SHIFT_MASK:
            data_dict = {'switch-to': True, 'uri': 'about:blank'}
            self._get_current_child().send('new-tab', data_dict)
        elif flags & self._gdk.ModifierType.MOD1_MASK:
            self._send('new-proc', self._make_tab(private=False,
                                                  switch_to=True))
        else:
            self._send('new-proc', self._make_tab(switch_to=True))

    def _close_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Close tab.

        """

        print('Close tab')
        child = self._get_current_child()
        self._to_last_tab(child['vbox'])
        child['socket'].disconnect(child['plug-removed'])
        child.send('close', True)

    def _switch_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Switch tab.

        """

        print('Switch tab ', keyval - 49, keyval)
        if self._tabs.get_n_pages() > (keyval - 49):
            self._tabs.set_current_page(keyval - 49)

    def _focus_address_entry(self, accels: object, window: object,
                             keyval: object, flags: object):
        """ Focus the address bar entry.

        """

        self._get_current_child().address_bar.show_all()
        self._get_current_child()['entry'].grab_focus()

    def _plug_removed(self, socket: object, child: dict):
        """ Re-open removed plug.

        """

        print("PLUG REMOVED: ", child['uri'])
        print("PLUG REMOVED CHILD: ", child)
        self._send('terminate', child['pid'])

        if not child['pid'] in self._revived:
            self._revived.append(child['pid'])
            child['pid'] = 0
            print('COMDICT: ', child['com-tup'][1])
            self._send('new-proc', child['com-tup'][1])

        return True


def run_main(com_pipe: object, com_dict: object):
    """ Runs a main.

    """

    main = MainWindow(com_pipe, com_dict)
    main.run()


def main():
    from time import sleep as time_sleep

    main_cpipe, main_ppipe = Pipe()
    main_dict = Manager().dict({'Quit': False})
    main_p = Process(target=run_main, args=(main_ppipe, main_dict))
    main_p.start()
    print("main pid: ", main_p.pid)

    # from multiprocessing.reduction import reduce_connection
    import multiprocessing.reduction as multireduce
    # with open('main.pipe', 'wb') as pipe_file:
    #     multireduce.dump(main_cpipe, pipe_file)
    # with open('auth.key', 'wb') as auth_file:
    #     auth_file.write(current_process().authkey)
        # pipe_file.write(reduce_connection(main_cpipc))
        # pipe_file.write(current_process().authkey)

    # proc, proc_dict = new_proc({'uri': 'https://www.startpage.com'})
    # print("child pid: ", proc.pid)
    # main_cpipe.send({'add-tab': {'uri': 'about:blank', 'switch_to': True}})
    # window_dict = {proc.pid: {'proc': proc, 'data': proc_dict}}
    window_dict = {}

    while True:
        try:
            tmp_tup = main_cpipe.recv()
        except KeyboardInterrupt:
            break
        signal, data = tmp_tup
        if signal == 'Quit':
            break
        if signal == 'refresh':
            # Make sure all children exit.
            print(['PID: %s of %s' % (t.pid, t) for t in multiprocessing.active_children()])
            for pid, proc in window_dict.items():
                print('PROCESS: ', pid)
        if signal == 'new-proc':
            proc = new_proc(data)
            print("MAIN_LOOP NEW_PROC: ", data)
            window_dict[proc.pid] = proc
            print("child pid: ", proc.pid)
            print('window_dict', window_dict)

        elif signal == 'terminate':
            print('Terminate pid: ', data)
            proc = window_dict.pop(data, None)
            if proc:
                if proc.is_alive():
                    print("Terminating: ", proc)
                    proc.terminate()

    print("Quitting")

    print(window_dict)
    for pid, proc in window_dict.items():
        print("Joining: ", proc)
        proc.join(1)
        if proc.is_alive():
            print("Terminating: ", proc)
            proc.terminate()

    main_p.join(1)
    if main_p.is_alive():
        main_p.terminate()

    # Make sure all children exit.
    multiprocessing.active_children()

    # Path('auth.key').unlink()
    # Path('main.pipe').unlink()

    return


if __name__ == '__main__':
    main()
    # if Path('auth.key').exists() and Path('main.pipe').exists():
    #     import pickle
    #     with open('auth.key', 'rb') as auth_file:
    #         current_process().authkey = auth_file.read()
    #     with open('main.pipe', 'rb') as pipe_file:
    #         cpipe = pickle.load(pipe_file)
    #     url = 'https://inbox.google.com'
    #     cpipe.send({'open-tab': url})
    #     cpipe.close()
    # else:
    #     main()
