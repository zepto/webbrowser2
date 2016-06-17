from path import Path
from gi import require_version as gi_require_version
from multiprocessing import Process, Manager, Pipe
from multiprocessing import current_process
import multiprocessing
import json
import os
import re

gi_require_version('Gtk', '3.0')
gi_require_version('WebKit2', '4.0')


def test(url: str = 'https://inbox.google.com'):
    from gi.repository import WebKit2 as libwebkit
    from gi.repository import Gtk as gtk
    from gi.repository import GLib as glib


    webview = libwebkit.WebView()
    settings = webview.get_settings()
    settings.set_property('user-agent', '''Mozilla/5.0 (X11; Linux x86_64)
                           AppleWebKit/537.36 (KHTML, like Gecko)
                           Chrome/47.0.2526.106 Safari/537.36''')
    webview.load_uri(url)

    scroll = gtk.ScrolledWindow()
    scroll.set_policy(gtk.PolicyType.AUTOMATIC,gtk.PolicyType.AUTOMATIC)
    scroll.set_shadow_type(gtk.ShadowType.IN)

    window = gtk.Window()
    window.connect_after('destroy', gtk.main_quit)
    window.add(scroll)
    scroll.add(webview)
    window.show_all()

    gtk.main()


class BrowserProc(object):
    """ A Browser Process.

    """

    def __init__(self, com_dict: object):
        """ Initialize the process.


        """

        from gi.repository import WebKit2 as libwebkit
        from gi.repository import Gtk as gtk
        from gi.repository import Gdk as gdk
        from gi.repository import GLib as glib

        self._gtk = gtk
        self._gdk = gdk
        self._glib = glib
        self._libwebkit = libwebkit

        self._dict = com_dict
        self._private = com_dict.pop('private', True)

        self._pid = multiprocessing.current_process().pid

        self._windows = []
        for socket_id, com_pipe in self._dict.items():
            print("CREATING: ", socket_id, com_pipe)
            try:
                com_pipe.send(('pid', self._pid))
            except BrokenPipeError as err:
                print("BROKEN PIPE: ", err, ' on PIPE ', com_pipe)
                continue
            self._windows.append(self._create_window(socket_id, com_pipe))

    def _create_window(self, socket_id: int, com_pipe: object, oldwebview: object = None):
        """ Create a window with a webview in it.

        """

        if not oldwebview:
            ctx = self._libwebkit.WebContext.get_default()
            ctx.set_cache_model(self._libwebkit.CacheModel.DOCUMENT_VIEWER)
            ctx.set_process_model(self._libwebkit.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)
            webview = self._libwebkit.WebView.new_with_context(ctx)

            cookies = ctx.get_cookie_manager()
            cookies.set_accept_policy(self._libwebkit.CookieAcceptPolicy.NO_THIRD_PARTY)

            settings = webview.get_settings()
            settings.set_property('enable-dns-prefetching', False)
            settings.set_property('enable-html5-database', False)
            settings.set_property('enable-html5-local-storage', False)
            settings.set_property('enable-java', False)
            settings.set_property('enable-offline-web-application-cache', False)
            settings.set_property('enable-page-cache', False)
            settings.set_property('enable-private-browsing', True)
            settings.set_property('enable-media-stream', True)
            settings.set_property('enable-mediasource', True)
            settings.set_property('enable-webaudio', True)
            settings.set_property('enable-webgl', True)
            settings.set_property('user-agent', 'Mozilla/5.0 (X11; Linux x86_64) \
                                AppleWebKit/537.36 (KHTML, like Gecko) \
                                Chrome/47.0.2526.106 Safari/537.36')
        else:
            webview = oldwebview.new_with_related_view()

        webview.connect('decide-policy', self._policy, com_pipe)
        webview.connect('create', self._new_window, com_pipe)
        webview.connect('load-failed-with-tls-errors', self._tls_errors, com_pipe)
        webview.connect('load-changed', self._load_status, com_pipe)
        webview.connect('notify::title', self._title_changed, com_pipe)
        webview.connect('notify::uri', self._uri_changed, com_pipe)
        webview.connect('notify::estimated-load-progress', self._progress_changed, com_pipe)
        webview.connect('notify::favicon', self._icon_loaded, com_pipe)
        webview.connect('notify', self._prop_changed, com_pipe)
        webview.connect('notify::load-failed', self._load_error, com_pipe)
        webview.connect('notify::is-loading', self._is_loading, com_pipe)

        scroll = self._gtk.ScrolledWindow()
        scroll.set_policy(self._gtk.PolicyType.AUTOMATIC,
                          self._gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(self._gtk.ShadowType.IN)
        scroll.add(webview)
        scroll.show_all()

        view_dict = {
                'webview': webview,
                'scroll': scroll,
                'socket-id': socket_id,
                }

        if socket_id:
            plug = self._gtk.Plug.new(socket_id)
            view_dict['plug'] = plug
            plug.connect_after('delete-event', self._delete, view_dict, com_pipe)
            plug.add(scroll)
            plug.show_all()

        self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                self._recieve, view_dict, com_pipe)

        # com_pipe.send({'plug-id': plug.get_id()})

        # return plug, webview
        # return scroll, {'webview': webview}
        return view_dict

    def _delete(self, plug: object, event: object, view_dict: dict, com_pipe: object):
        """ Quit

        """

        print("delete", self._pid)
        if not self._windows:
            self._gtk.main_quit()
            # print("gtk main quit")
            # com_pipe.send({'Terminate': self._pid})
        print('deleted')

    def _recieve(self, source: int, cb_condition: int, view_dict: dict,
                 com_pipe: object):
        """ Recieve signals from outside.

        """

        signal, data = com_pipe.recv()
        print('signal: {signal}, data: {data}'.format(**locals()))
        if signal == 'close' and data:
            send_dict = {'pid': self._pid,
                            'socket-id': view_dict['socket-id']}
            print('Closing', view_dict['webview'].get_uri())
            index = self._windows.index(view_dict)
            print('Removing: ', self._windows.pop(index))
            if not self._windows:
                com_pipe.send(('terminate', send_dict))
                return False
            print("Sending Closed")
            com_pipe.send(('closed', send_dict))
            return False

        if signal == 'open-uri':
            view_dict['webview'].grab_focus()
            view_dict['webview'].load_uri(data)

        if signal == 'new-tab':
            conp, procp = Pipe()
            new_win = self._create_window(0, procp, view_dict['webview'])
            com_pipe.send(('new-window-info', {'pid': self._pid,
                                            'com-tup': (conp, self._dict),
                                            'switch-to': data['switch-to']}))

            self._windows.append(new_win)

        if signal == 'socket-id':
            self._dict[data] = com_pipe
            view_dict['socket-id'] = data

            plug = self._gtk.Plug.new(data)
            plug.connect_after('delete-event', self._delete,
                                view_dict, com_pipe)
            plug.add(view_dict['scroll'])
            plug.show_all()
            view_dict['plug'] = plug

        print("CHILD_DICT: ", self._dict)

        return True

    def _new_window(self, webview: object, navigation_action: object, com_pipe: object):
        """ New window in this process.

        """

        conp, procp = Pipe()
        new_win = self._create_window(0, procp, webview)
        com_pipe.send(('new-window-info', {'pid': self._pid,
                                           'com-tup': (conp, self._dict),
                                           'switch-to': False}))

        self._windows.append(new_win)

        return new_win['webview']

    def _policy(self, webview: object, decision: object, decision_type: object, com_pipe):
        """ Handle opening a new window.

        """

        print("REQUEST: ", decision_type)
        if decision_type == self._libwebkit.PolicyDecisionType.NAVIGATION_ACTION:
            nav_action = decision.get_navigation_action()
            request = nav_action.get_request()
            uri = request.get_uri()
            if nav_action.get_mouse_button() == 2 or (nav_action.get_mouse_button() == 1 and
            nav_action.get_modifiers() &
            self._gdk.ModifierType.CONTROL_MASK):

                decision.ignore()

                com_pipe.send(('new-window', {'uri': uri, 'switch_to': False}))

                return True

        decision.use()
        return False

    def _title_changed(self, webview: object, prop: object, com_pipe: object):
        """ The title changed.

        """

        title = webview.get_property(prop.name)
        com_pipe.send(('title', title if title else 'about:blank'))

    def _tls_errors(self, webview: object, uri: str, cert: object, errors: object, com_pipe: object):
        """ Detect tls errors.

        """

        print("TLS_ERROR {errors} ON {uri} with cert {cert}".format(**locals()))
        return False

    def _prop_changed(self, webview: object, data: str, com_pipe: object):
        """
        """
        print('PROP CHANGED: ', data.name, webview.get_property(data.name))
        settings = webview.get_settings()
        print('PRIVATE: ', settings.get_enable_private_browsing())

    def _icon_loaded(self, webview: object, icon_uri: str, com_pipe: object):
        """ Set icon loaded signal.

        """

        uri = webview.get_uri()
        icon = webview.get_favicon()
        print("ICON: ", icon)
        if icon:
            pixbuf = self._gdk.pixbuf_get_from_surface(icon, 0, 0, icon.get_width(), icon.get_height())
        if not icon:
            icontheme = self._gtk.IconTheme().get_default()
            pixbuf = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                         self._gtk.IconLookupFlags.USE_BUILTIN)
        com_pipe.send(('icon-bytes', pixbuf.save_to_bufferv('png', '', '')[1]))

    def _is_loading(self, webview: object, is_loading: bool, com_pipe: object):
        """ Tell if it is loading.

        """

        print("IS LOADING", webview.get_property(is_loading.name))

    def _load_status(self, webview: object, load_event: object, com_pipe: object):
        """ Notify the parent process when the load status changes.

        """

        print('LOAD_STATUS:' , webview.get_tls_info())
        # status = webview.get_property(prop.name)
        # if status == self._libwebkit.LoadStatus.PROVISIONAL:
        if load_event == self._libwebkit.LoadEvent.STARTED:
            icontheme = self._gtk.IconTheme().get_default()
            icon = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                       self._gtk.IconLookupFlags.USE_BUILTIN)
            com_pipe.send(('icon-bytes', icon.save_to_bufferv('png', '', '')[1]))
        if load_event == self._libwebkit.LoadEvent.REDIRECTED:
            com_pipe.send(('uri-changed', webview.get_uri()))
        # if status == self._libwebkit.LoadStatus.FAILED:
        #     print('LOAD_ERROR: ')
        # print("LOAD_STATUS", int(webview.get_tls_info()[2]))

        # print(webview.get_property(prop.name))
        com_pipe.send(('load-status', int(load_event)))

    # def _load_error(self, webview: object, webframe: object, uri: str, weberror: object, com_pipe):
    def _load_error(self, webview: object, load_event: object, uri: str, weberror: object, com_pipe):
        """ Get the error.

        """

        print("LOAD ERROR: ", uri, weberror.message)

    def _uri_changed(self, webview: object, prop: object, com_pipe: object):
        """ Send new uri and history.

        """

        uri = webview.get_property(prop.name)
        print('uri changed: ', webview.get_property(prop.name))
        com_pipe.send(('uri-changed', uri))

    def _status_text_changed(self, webview: object, data: str, com_pipe: object):
        """ Get new status text.

        """

        print("status text ", data)

    def _mime_request(self, webview: object, webframe: object, request: object,
                      mimetype: str, policy_decision: object, com_pipe: object):
        """ Handle Mime requests.

        """

        print('mime request: ', mimetype)
        return True

    def _resource_length(self, webview: object, webframe: object,
            webresource: object, length: int, com_pipe: object):
        """ Handle resource.

        """

        # print('resource length: ', length, ' resource: ', webresource.get_uri())
        if re.search(r'\.(mp4|mp3)([^a-zA-Z0-9]|$)', webresource.get_uri()):
        # if '.mp4' in webresource.get_uri():
            print('MEDIA URI: ', webresource.get_uri())
        return True

    def _progress_changed(self, webview: object, prop: object, com_pipe):
        """ Send the progress

        """

        progress = webview.get_property(prop.name)
        com_pipe.send(('progress', progress))

    def run(self):
        """ Run the main gtk loop.

        """

        self._gtk.main()


def run_browser(data: object):
    """ Runs a browser.

    """

    # from webkit2_test2 import BrowserProc
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

        self._gtk = gtk
        self._gdk = gdk
        self._glib = glib
        self._pango = pango
        self._gio = gio
        self._gdkpixbuf = gdkpixbuf

        self._revived = []

        self._closed = {}

        self._accels = self._gtk.AccelGroup()

        accel_dict = {
                ('<Ctrl>t', '<Ctrl><Shift>t'): self._new_tab,
                ('<Ctrl>w',): self._close_tab,
                ('<Ctrl><Alt>r',): lambda *a: com_pipe.send(('refresh', True)),
                ('<Ctrl>l',): self._focus_address_entry,
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
        self._window.add_accel_group(self._accels)
        self._window.set_default_size(1024, 768)
        self._window.set_resizable(True)
        self._window.set_icon_name('web-browser')
        self._window.connect_after('delete-event', self._quit)
        self._tabs = self._gtk.Notebook()
        self._tabs.connect('page-reordered', self._tab_reordered)
        self._tabs.connect('page-removed', self._tab_removed)
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)
        self._window.add(self._tabs)
        self._window.show_all()

        self._pipe = com_pipe
        self._dict = com_dict

        self._windows = {}

        self._glib.io_add_watch(self._pipe.fileno(), self._glib.IO_IN,
                                self._recieve)

        self._pipe.send(('new-proc', self._make_tab()))

    def _make_tab(self, uri: str = 'about:blank', switch_to: bool = False):
        """ Make a tab.

        """

        socket_id, child = self._add_tab(switch_to)

        main_pipe, child_pipe = Pipe()

        com_dict = Manager().dict({socket_id: child_pipe})

        child['com-tup'] = (main_pipe, com_dict)
        child['pid'] = 0
        child['uri'] = uri
        self._windows[socket_id] = child

        self._glib.io_add_watch(main_pipe.fileno(), self._glib.IO_IN,
                                self._callback, child)

        return com_dict

    def _quit(self, window: object, event: object):
        """ Quit

        """

        for socket_id, data in self._windows.items():
            com_pipe = data['com-tup'][0]
            com_pipe.send(('close', True))
            print(data)
        self._dict['Quit'] = True
        self._pipe.send(('quit', True))
        self._gtk.main_quit()

    def run(self):
        """ Run gtk.main()

        """

        self._gtk.main()

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        com_pipe, _ = window['com-tup']
        # print('_CALLBACK', window)

        signal, data = com_pipe.recv()
        if signal != 'icon-bytes':
            print(window['pid'], ' signal: {signal}: data: {data}'.format(**locals()))
        else:
            print(window['pid'], ' signal: {signal}: data: bytes_data'.format(**locals()))

        if signal == 'closed' or signal == 'terminate' and data:
            print(window, ' Closed')
            socket_id = data['socket-id']
            print('REMOVING: ', window['com-tup'][1].pop(socket_id))
            self._closed[data['pid']] = self._windows.pop(socket_id)['com-tup'][1]
            print(self._tabs.page_num(window['vbox']))
            self._tabs.remove_page(self._tabs.page_num(window['vbox']))

            if signal == 'terminate':
                print('Terminating ', data['pid'])
                self._pipe.send(('terminate', data['pid']))

            if not self._windows:
                self._window.emit('delete-event', None)
                self._window.destroy()
            return False

        if signal == 'pid':
            window['pid'] = data
            window['com-tup'][0].send(('open-uri', window['uri']))

        if signal == 'new-window-info':
            com_pipe, _ = data['com-tup']
            socket_id, child = self._add_tab(data['switch-to'])
            child.update(data)
            self._windows[socket_id] = child
            com_pipe.send(('socket-id', socket_id))
            self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                    self._callback, child)

        if signal == 'new-window':
            self._pipe.send(('new-proc', self._make_tab(**data)))

        if signal == 'title' and data != window.get('title', 'about:blank'):
            data += ' (pid: {pid})'.format(**window)
            window['label'].set_text(data)
            window['ebox'].set_tooltip_text(data)
            window['title'] = data

        if signal == 'icon-bytes' and data:
            loader = self._gdkpixbuf.PixbufLoader()
            loader.set_size(16, 16)
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            window['icon-image'] = pixbuf
            window['icon'].set_from_pixbuf(pixbuf)
            window['entry'].set_icon_from_pixbuf(0, pixbuf)

        if signal == 'load-status' and data == 0:
            window['icon'].hide()
            window['spinner'].show_all()
            window['spinner'].start()
        elif signal == 'load-status' and data == 3:
            window['spinner'].stop()
            window['spinner'].hide()
            window['icon'].show_all()
            window['entry'].set_progress_fraction(0)

        if signal == 'uri-changed' and data:
            window['uri'] = data
            if data == 'about:blank':
                window['entry'].set_text('')
                window['entry'].grab_focus()
            else:
                window['entry'].set_text(data)
        if signal == 'progress':
            window['entry'].set_progress_fraction(data)
            if data == 1.0:
                window['entry'].set_progress_fraction(0)


        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """

        signal, data = self._pipe.recv()
        print('RECIEVE: ', signal, data)

        if signal == 'open-tab':
            self._pipe.send(('new-proc', data))

        if signal == 'add-tab':
            self._windows[data['socket-id']].update(data)
            # com_pipe, _ = data['com-tup']
            # socket_id = self._add_tab(data)
            # self._windows[socket_id] = data
            # com_pipe.send({'socket-id': socket_id})
            # self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
            #                         self._callback, data)

        return True

    def _load_uri(self, entry: object, child: dict):
        """ Load uri.

        """

        uri = entry.get_text()
        com_pipe = child['com-tup'][0]
        if not uri.startswith(('http://', 'https://', 'ftp://', 'file://',
                               'mailto:', 'javascript:')):
            if ' ' in uri or '.' not in uri or not uri:
                uri = 'https://startpage.com/do/search?query=%s' % uri
            else:
                uri = 'http://%s' % uri
        com_pipe.send(('open-uri', uri))

    def _add_tab(self, switch_to: bool = False):
        """ Add Tab.

        """

        socket = self._gtk.Socket()
        vbox = self._gtk.VBox()
        address_bar = self._gtk.Toolbar()
        address_entry = self._gtk.Entry()
        address_item = self._gtk.ToolItem()
        address_item.set_expand(True)
        address_item.add(address_entry)
        address_bar.add(address_item)
        vbox.pack_start(address_bar, False, False, 0)
        vbox.pack_start(socket, True, True, 0)

        label = self._gtk.Label('about:blank')
        label.set_justify(self._gtk.Justification.LEFT)
        label.set_alignment(xalign=0, yalign=0.5)
        label.set_width_chars(18)
        label.set_max_width_chars(18)
        label.set_ellipsize(self._pango.EllipsizeMode(3))
        label.show_all()

        icon = self._gtk.Image()
        icontheme = self._gtk.IconTheme().get_default()
        pixbuf = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                     self._gtk.IconLookupFlags.USE_BUILTIN)
        address_entry.set_icon_from_pixbuf(0, pixbuf)
        address_entry.set_icon_from_icon_name(1, 'go-jump')
        icon.set_from_pixbuf(pixbuf)
        icon.show_all()

        hbox = self._gtk.HBox(homogeneous=False, spacing=6)
        hbox.pack_start(icon, True, True, 0)
        spinner = self._gtk.Spinner()
        hbox.pack_start(spinner, True, True, 0)
        hbox.pack_end(label, True, True, 0)
        hbox.show_all()
        spinner.hide()
        eventbox= self._gtk.EventBox()
        eventbox.add(hbox)
        eventbox.show_all()
        eventbox.set_has_window(False)
        if not switch_to:
            insert_at = self._tabs.get_current_page() + 1
        else:
            insert_at = -1

        index = self._tabs.insert_page(vbox, eventbox, insert_at)
        self._tabs.set_tab_reorderable(vbox, True)

        child = {
                'spinner': spinner,
                'icon': icon,
                'icon-image': pixbuf,
                'entry': address_entry,
                'label': label,
                'socket': socket,
                'ebox': eventbox,
                'vbox': vbox,
                'uri': 'about:blank',
                'title': 'about:blank',
                'socket-id': 0,
                'pid': 0,
                'history': {},
                }

        socket.connect_after('plug-removed', self._plug_removed, child)
        eventbox.connect('button-press-event', self._tab_button_press, child)
        eventbox.connect('button-release-event', self._tab_button_release, child)
        address_entry.connect_after('activate', self._load_uri, child)

        vbox.show_all()

        if switch_to:
            self._tabs.set_current_page(index)

        return socket.get_id(), child

    def _tab_reordered(self, notebook: object, child: object, index: int):
        """ Set the new ordering.

        """

        print(child, index)

    def _tab_removed(self, notebook: object, child: object, index: int):
        """ Remove page info.

        """

        # print(child.get_children())
        # socket = child.get_children()[1]
        # # print('TAB REMOVED SOCKET_ID: ', socket.get_id())
        # print('TAB REMOVED SOCKET: ', socket)
        # d = self._windows[socket.get_id()]['com-tup'][1].pop(socket.get_id(), None)
        # print('TAB REMOVED: ', d)
        pass

    def _tab_button_press(self, eventbox: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 1 and \
                event.state & self._gdk.ModifierType.CONTROL_MASK:
            return True

    def _tab_button_release(self, eventbox: object, event: object, child: dict):
        """ Close the tab.

        """

        if event.button == 2 or (event.button == 1 and \
                event.state & self._gdk.ModifierType.CONTROL_MASK):
            print("sending Close")
            child['com-tup'][0].send(('close', True))

    def _new_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Open a new tab.

        """

        print('open new tab', flags)
        if flags & self._gdk.ModifierType.SHIFT_MASK:
            print("SHIFT WAS PRESSED")
            vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
            socket = vbox.get_children()[1]
            pipe = self._windows[socket.get_id()]['com-tup'][0]
            pipe.send(('new-tab', {'switch-to': True, 'uri': 'about:blank'}))
        else:
            print("SHIFT WAS NOT PRESSED")
            self._pipe.send(('new-proc', self._make_tab(switch_to=True)))

    def _close_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Close tab.

        """

        print('Close tab')
        vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
        socket = vbox.get_children()[1]
        print(vbox, socket)
        self._windows[socket.get_id()]['com-tup'][0].send(('close', True))

    def _switch_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Switch tab.

        """

        print('Switch tab ', 49 - keyval)
        if self._tabs.get_n_pages() > (49 - keyval):
            self._tabs.set_current_page(49 - keyval)

    def _focus_address_entry(self, accels: object, window: object,
                             keyval: object, flags: object):
        """ Focus the address bar entry.

        """

        vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
        socket = vbox.get_children()[1]
        self._windows[socket.get_id()]['entry'].grab_focus()

    def _plug_removed(self, socket: object, child: dict):
        """ Re-open removed plug.

        """

        print("PLUG REMOVED: ", child['uri'])
        print("PLUG REMOVED CHILD: ", child)
        self._pipe.send(( 'terminate', child['pid'] ))
        # self._pipe.send({'new-proc': {'uri': child['uri'], 'switch-to': False,
        #                  'socket-id': socket.get_id()}})

        if not child['pid'] in self._revived:
            self._revived.append(child['pid'])
            child['pid'] = 0
            print('COMDICT: ', child['com-tup'][1])
            self._pipe.send(( 'new-proc', child['com-tup'][1] ))

        return True


def run_main(com_pipe: object, com_dict: object):
    """ Runs a main.

    """

    from webkit2_test2 import MainWindow
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
    # main_cpipe.send({'add-tab': proc_dict})
    # window_dict = {proc.pid: {'proc': proc, 'data': proc_dict}}
    window_dict = {}

    while not main_dict['Quit']:
        try:
            signal, data = main_cpipe.recv()
        except KeyboardInterrupt:
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
            # main_cpipe.send({'add-tab': proc_dict})
            print("child pid: ", proc.pid)
            print('window_dict', window_dict)
        # elif signal == 'died':
        #     pid = data['pid']
        #     com_pipe, com_dict = data['com-tup']
        #     proc = window_dict.get(pid, {}).get('proc', None)
        #     if not proc:
        #         print("{pid} is gone".format(**data))
        #         continue
        #     if not proc.is_alive():
        #         proc = revive_proc(data['com-tup'])
        #     if proc.is_alive():
        #         proc_pipe = window_dict[pid]['data']['com-tup'][0]
        #         proc_pipe.send({'revive': data})
        #     else:

        elif signal == 'terminate':
            print('Terminate pid: ', data)
            # proc = window_dict.get(data, {}).get('proc', None)
            proc = window_dict.get(data, None)
            if proc:
                print("Joining: ", proc)
                proc.join(2)
                if proc.is_alive():
                    print("Terminating: ", proc)
                    proc.terminate()

    print("Quitting")

    print(window_dict)
    for pid, proc in window_dict.items():
        print("Joining: ", proc)
        proc.join(2)
        if proc.is_alive():
            print("Terminating: ", proc)
            proc.terminate()

    main_p.join(2)
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
