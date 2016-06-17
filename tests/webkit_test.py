from path import Path
from gi import require_version as gi_require_version
from multiprocessing import Process, Manager, Pipe
from multiprocessing import current_process
import multiprocessing
import json
import os
import re

gi_require_version('Soup', '2.4')
gi_require_version('Gtk', '3.0')
gi_require_version('WebKit', '3.0')


def test(url: str = 'https://inbox.google.com'):
    from gi.repository import Soup as libsoup
    from gi.repository import WebKit as libwebkit
    from gi.repository import Gtk as gtk
    from gi.repository import GLib as glib


    # proxy_uri = libsoup.URI.new(os.getenv('http_proxy'))
    # session = libwebkit.get_default_session()
    # session.set_property('proxy-uri', proxy_uri)

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

        from gi.repository import Soup as libsoup
        from gi.repository import WebKit as libwebkit
        from gi.repository import Gtk as gtk
        from gi.repository import Gdk as gdk
        from gi.repository import GLib as glib

        self._icon_db = libwebkit.get_favicon_database()
        cookiejar = libsoup.CookieJar()
        cookiejar.set_accept_policy(libsoup.CookieJarAcceptPolicy.NO_THIRD_PARTY)
        session = libwebkit.get_default_session()
        print("SESSION: ", session)
        session.add_feature(cookiejar)
        session.set_property('ssl-use-system-ca-file', True)
        session.set_property('ssl-strict', True)
        print("SESSION PROP", session.get_property('tls-database'))
        # session.connect('connection-created', self._soup_connection)
        # proxy_uri = libsoup.URI.new(os.getenv('http_proxy'))
        # session.set_property('proxy-uri', proxy_uri)

        self._libsoup = libsoup
        self._gtk = gtk
        self._gdk = gdk
        self._glib = glib
        self._libwebkit = libwebkit

        self._dict = com_dict
        self._coms = []

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

    def _soup_connection(self, session: object, connection: object):
        print("SOUP: ", session, connection.props.socket_properties)
        print("SOUP CONNECTION: ", dir(connection.props.socket_properties))

    def _create_window(self, socket_id: int, com_pipe: object):
        """ Create a window with a webview in it.

        """

        self._coms.append((com_pipe, self._dict))
        webview = self._libwebkit.WebView()
        webview.connect('navigation-policy-decision-requested',
                        self._nav_policy, com_pipe)
        webview.connect('create-web-view', self._new_window, com_pipe)
        webview.connect('notify::title', self._title_changed, com_pipe)
        webview.connect('notify::uri', self._uri_changed, com_pipe)
        webview.connect('notify::progress', self._progress_changed, com_pipe)
        webview.connect('icon-loaded', self._icon_loaded, com_pipe)
        webview.connect('notify::load-status', self._load_status, com_pipe)
        webview.connect('notify::load-error', self._load_error, com_pipe)
        webview.connect('status-bar-text-changed', self._status_text_changed, com_pipe)
        webview.connect('hovering-over-link', self._hover_link, com_pipe)
        webview.connect('mime-type-policy-decision-requested', self._mime_request, com_pipe)
        webview.connect('resource-content-length-received', self._resource_length, com_pipe)
        # webview.connect('resource-response-received', self._resource_response, com_pipe)
        webview.connect('notify::has-focus', lambda *a: print("COMS: ", self._coms))
        settings = webview.get_settings()
        settings.set_property('enable-private-browsing', True)
        settings.set_property('enable-running-of-insecure-content', False)
        settings.set_property('enable-display-of-insecure-content', False)
        settings.set_property('enable-accelerated-compositing', True)
        settings.set_property('enable-media-stream', True)
        settings.set_property('enable-mediasource', True)
        settings.set_property('enable-plugins', False)
        settings.set_property('enable-webaudio', True)
        settings.set_property('enable-webgl', True)
        settings.set_property('user-agent', 'Mozilla/5.0 (X11; Linux x86_64) \
                               AppleWebKit/537.36 (KHTML, like Gecko) \
                               Chrome/47.0.2526.106 Safari/537.36')

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
                'com-tup': (com_pipe, self._dict),
                }
        if socket_id:
            plug = self._gtk.Plug.new(socket_id)
            view_dict['plug'] = plug
            plug.connect('destroy', self._destroy, view_dict)
            plug.add(scroll)
            plug.show_all()

        self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                self._recieve, view_dict, com_pipe)

        return view_dict

    def _destroy(self, plug, view_dict):
        """ Quit

        """

        com_pipe, _ = view_dict['com-tup']
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

    def _recieve(self, source: int, cb_condition: int, view_dict: dict,
                 com_pipe: object):
        """ Recieve signals from outside.

        """

        print("IN RECIEVE: ", com_pipe)
        print("CHILD_DICT: ", self._dict)

        signal, data = com_pipe.recv()
        print('signal: {signal}, data: {data}'.format(**locals()))

        if signal == 'close' and data:
            view_dict['plug'].destroy()
            print("DESTROYED IT")
            return False

        if signal == 'open-uri':
            view_dict['webview'].grab_focus()
            view_dict['webview'].load_uri(data)

        if signal == 'new-tab':
            self._new_tab(com_pipe, data)

        if signal == 'socket-id':
            self._dict[data] = com_pipe
            view_dict['socket-id'] = data

            plug = self._gtk.Plug.new(data)
            plug.connect('destroy', self._destroy, view_dict)
            plug.add(view_dict['scroll'])
            plug.show_all()
            view_dict['plug'] = plug

        return True

    def _new_tab(self, com_pipe: object, data: dict):
        """ Make a new window.

        """

        conp, procp = Pipe()
        new_win = self._create_window(0, procp)
        info_dict = {
                'uri': 'about:blank',
                'pid': self._pid,
                'com-tup': (conp, self._dict),
                'switch-to': data.get('switch-to', False),
                }
        com_pipe.send(('tab-info', info_dict))

        self._windows.append(new_win)

        return new_win

    def _new_window(self, webview: object, webframe: object, com_pipe: object):
        """ New window in this process.

        """

        return self._new_tab(com_pipe, {'switch-to': False})['webview']

    def _nav_policy(self, webview: object, webframe: object, request: object,
                    nav_action: object, policy_decision: object,
                    com_pipe: object):
        """ Handle opening a new window.

        """

        # message = request.get_message()
        # if message:
        #     print("TLS CERT: ", message.get_property('tls-certificate'))
        #     print("TLS ERROR: ", message.get_property('tls-errors'))
        #     print("NAV POLICY: ", message.get_flags())
        # uri = request.get_uri()
        # if 'ads' in uri.lower():
        #     print('ADS: ', uri)
        #     policy_decision.ignore()
        #     return True
        if nav_action.get_button() == 2 or (nav_action.get_button() == 1 and
           nav_action.get_modifier_state() &
           self._gdk.ModifierType.CONTROL_MASK):

            policy_decision.ignore()

            uri = request.get_uri()
            com_pipe.send(('create-tab', {'uri': uri, 'switch_to': False}))

            return True
        policy_decision.use()
        return False

    def _title_changed(self, webview: object, prop: object, com_pipe: object):
        """ The title changed.

        """

        title = webview.get_property(prop.name)
        com_pipe.send(('title', title if title else 'about:blank'))

    def _icon_loaded(self, webview: object, icon_uri: str, com_pipe: object):
        """ Set icon loaded signal.

        """

        uri = webview.get_uri()
        # icon = self._icon_db.try_get_favicon_pixbuf(uri, 0, 0)
        icon = webview.try_get_favicon_pixbuf(0, 0)
        print('ICON URI', webview.get_icon_uri())
        if not icon:
            icontheme = self._gtk.IconTheme().get_default()
            icon = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                       self._gtk.IconLookupFlags.USE_BUILTIN)
        com_pipe.send(('icon-bytes', icon.save_to_bufferv('png', '', '')[1]))
        settings = webview.get_settings()
        print("PRIVATE: ", settings.get_property('enable-private-browsing'))

    def _load_status(self, webview: object, prop: object, com_pipe: object):
        """ Notify the parent process when the load status changes.

        """

        frame = webview.get_main_frame()
        source = frame.get_data_source()
        request = source.get_request()
        message = request.get_message()
        if message:
            print("REASON: ", message.get_property('reason-phrase'))
            print("URI HOST: ", message.get_uri().get_host())
            print("HTTPS STATUS: ", message.get_https_status())
            cert = message.get_property('tls-certificate')
            if cert:
                print("LOAD STATUS TLS CERT: ", cert)
            errors = message.get_property('tls-errors')
            if errors != 0:
                print("LOAD STATUS TLS ERROR: ", errors)
            print("LOAD STATUS: ", message.get_flags())
            if message.get_flags() & self._libsoup.MessageFlags.CERTIFICATE_TRUSTED:
                print("TRUSTED")

        status = webview.get_property(prop.name)
        if status == self._libwebkit.LoadStatus.PROVISIONAL:
            icontheme = self._gtk.IconTheme().get_default()
            icon = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                       self._gtk.IconLookupFlags.USE_BUILTIN)
            com_pipe.send(('icon-bytes', icon.save_to_bufferv('png', '', '')[1]))
        if status == self._libwebkit.LoadStatus.FAILED:
            print('LOAD_ERROR: ')

        print(webview.get_property(prop.name))
        com_pipe.send(('load-status', int(status)))

    def _load_error(self, webview: object, webframe: object, uri: str, weberror: object, com_pipe):
        """ Get the error.

        """

        print("LOAD ERROR: ", uri, weberror.message)

    def _uri_changed(self, webview: object, prop: object, com_pipe: object):
        """ Send new uri and history.

        """

        uri = webview.get_property(prop.name)
        print('uri changed: ', webview.get_property(prop.name))
        com_pipe.send(('uri-changed', uri))

    def _hover_link(self, webview: object, title: str, uri: str, com_pipe: object):
        """ Send hover link.

        """

        print("HOVER_LINK: {uri} : TITLE : {title}".format(**locals()))
        com_pipe.send(('hover-link', {'uri': uri, 'title': title}))

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

    def _resource_response(self, webview: object, webframe: object,
                           resource: object, response: object,
                           com_pipe: object):
        """ Andle response.

        """

        message = response.get_message()
        if message:
            print("RESOURCE RESPONSE: ", message.get_flags())

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

        from gi.repository import Soup as libsoup
        from gi.repository import WebKit as libwebkit
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
        self._webkit = libwebkit
        self._gio = gio
        self._gdkpixbuf = gdkpixbuf

        self._revived = []

        self._icon_db = libwebkit.get_favicon_database()

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
        # self._window.connect('delete-event', self._quit)
        self._window.connect('destroy', self._quit)
        self._tabs = self._gtk.Notebook()
        self._tabs.connect('page-reordered', self._tab_reordered)
        self._tabs.connect('page-removed', self._tab_removed)
        self._tabs.connect('switch-page', self._tab_switched)
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)

        self._statusbar = self._gtk.Statusbar()
        self._status_context = self._statusbar.get_context_id('hover-link')

        vbox = self._gtk.VBox()
        vbox.pack_start(self._tabs, True, True, 0)
        vbox.pack_end(self._statusbar, False, False, 0)

        self._window.add(vbox)
        self._window.show_all()

        self._pipe = com_pipe
        self._dict = com_dict

        self._windows = {}
        self._closed = {}

        self._glib.io_add_watch(self._pipe.fileno(), self._glib.IO_IN,
                                self._recieve)

        self._pipe.send(('new-proc', self._make_tab()))

    def _make_tab(self, uri: str = 'about:blank', switch_to: bool = False):
        """ Make a tab.

        """

        main_pipe, child_pipe = Pipe()
        com_dict = Manager().dict()

        socket_id, child = self._add_tab(uri, switch_to, (main_pipe, com_dict))

        com_dict[socket_id] = child_pipe
        # child['com-tup'] = (main_pipe, com_dict)
        # child['uri'] = uri
        # self._windows[socket_id] = child

        return com_dict

    def _quit(self, window: object):
        """ Quit

        """

        for socket_id, data in self._windows.items():
            com_pipe = data['com-tup'][0]
            com_pipe.send(('close', True))
            print(data)

        self._pipe.send(('Quit', True))
        self._gtk.main_quit()

    def run(self):
        """ Run gtk.main()

        """

        self._gtk.main()

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        com_pipe, _ = window['com-tup']

        signal, data = com_pipe.recv()

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

        if signal == 'pid':
            window['pid'] = data
            window['com-tup'][0].send(('open-uri', window['uri']))

        if signal == 'tab-info':
            print('TAB_INFO', data)
            com_pipe, com_dict = data['com-tup']
            socket_id, child = self._add_tab(data['uri'], data['switch-to'],
                                             data['com-tup'])
            child.update(data)
            self._windows[socket_id] = child
            com_pipe.send(('socket-id', socket_id))

        if signal == 'create-tab':
            self._pipe.send(('new-proc', self._make_tab(**data)))

        if signal == 'title' and data != window.get('title', 'about:blank'):
            data += ' (pid: {pid})'.format(**window)
            window['label'].set_text(data)
            window['ebox'].set_tooltip_text(data)
            window['title'] = data
            if window == self._get_current_child():
                self._window.set_title(data)

        if signal == 'icon-bytes' and data:
            loader = self._gdkpixbuf.PixbufLoader()
            loader.set_size(16, 16)
            loader.write(data)
            loader.close()
            pixbuf = loader.get_pixbuf()
            window['icon-image'] = pixbuf
            window['icon'].set_from_pixbuf(pixbuf)
            window['entry'].set_icon_from_pixbuf(0, pixbuf)

        if signal == 'load-status' and data <= 1:
            window['icon'].hide()
            window['spinner'].show_all()
            window['spinner'].start()
        elif signal == 'load-status' and (data == 2 or data == 4):
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

        if signal == 'hover-link':
            uri = data['uri']
            if uri:
                self._statusbar.push(self._status_context, uri)
            else:
                self._statusbar.remove_all(self._status_context)


        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """


        signal, data = self._pipe.recv()
        print('RECIEVE: {signal} => {data}'.format(**locals()))
        if signal == 'open-tab':
            self._pipe.send(('new-proc', data))

        if signal == 'add-tab':
            self._pipe.send(('new-proc', self._make_tab(**data)))

        return True

    def _send_signal(self, child: dict, signal: str, data: object):
        """ Send signal signal with data on pipe.

        """

        com_pipe, _ = child['com-tup']
        com_pipe.send((signal, data))

    def _load_uri(self, entry: object, child: dict):
        """ Load uri.

        """

        uri = entry.get_text()
        if not uri.startswith(('http://', 'https://', 'ftp://', 'file://',
                               'mailto:', 'javascript:')):
            if ' ' in uri or '.' not in uri or not uri:
                uri = 'https://startpage.com/do/search?query=%s' % uri
            else:
                uri = 'http://%s' % uri

        self._send_signal(child, 'open-uri', uri)

    def _entry_icon_release(self, entry: object, icon_pos: object,
                            event: object, child: dict):
        """ Do stuff when an icon is clicked.

        """

        if icon_pos == self._gtk.EntryIconPosition.SECONDARY:
            self._load_uri(entry, child)

    def _add_tab(self, uri: str = 'about:blank', switch_to: bool = False,
                 com_tup: tuple = ()):
        """ Add Tab.

        """

        icontheme = self._gtk.IconTheme().get_default()
        icon_pixbuf = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                          self._gtk.IconLookupFlags.USE_BUILTIN)

        address_entry = self._gtk.Entry()
        address_entry.set_icon_from_pixbuf(self._gtk.EntryIconPosition.PRIMARY,
                                           icon_pixbuf)
        address_entry.set_icon_from_icon_name(self._gtk.EntryIconPosition.SECONDARY,
                                              'go-jump')
        address_entry.set_icon_sensitive(self._gtk.EntryIconPosition.SECONDARY,
                                         True)
        address_entry.set_property('secondary-icon-tooltip-text',
                                   'Load uri in addres entry.')
        address_style_context = address_entry.get_style_context()
        print(address_style_context.get_section('icon-prelight'))
        css_provider = self._gtk.CssProvider.get_default()
        css_provider.load_from_data(b"""GtkEntry:hover{
                                                background-color: #ffffff;
                                               }""")
        address_style_context.add_provider_for_screen(address_style_context.get_screen(), css_provider, 800)

        address_item = self._gtk.ToolItem()
        address_item.set_expand(True)
        address_item.add(address_entry)

        address_bar = self._gtk.Toolbar()
        address_bar.add(address_item)


        label = self._gtk.Label('about:blank')
        label.set_justify(self._gtk.Justification.LEFT)
        label.set_alignment(xalign=0, yalign=0.5)
        label.set_width_chars(18)
        label.set_max_width_chars(18)
        label.set_ellipsize(self._pango.EllipsizeMode(3))
        label.show_all()

        icon = self._gtk.Image()
        icon.set_from_pixbuf(icon_pixbuf)

        spinner = self._gtk.Spinner()
        spinner.hide()

        hbox = self._gtk.HBox(homogeneous=False, spacing=6)
        hbox.pack_start(icon, True, True, 0)
        hbox.pack_start(spinner, True, True, 0)
        hbox.pack_end(label, True, True, 0)

        eventbox= self._gtk.EventBox()
        eventbox.add(hbox)
        eventbox.show_all()
        eventbox.set_has_window(False)

        if not switch_to:
            insert_at = self._tabs.get_current_page() + 1
        else:
            insert_at = -1

        socket = self._gtk.Socket()

        vbox = self._gtk.VBox()
        vbox.pack_start(address_bar, False, False, 0)
        vbox.pack_start(socket, True, True, 0)

        index = self._tabs.insert_page(vbox, eventbox, insert_at)
        self._tabs.set_tab_reorderable(vbox, True)

        socket_id = socket.get_id()

        child = {
                'spinner': spinner,
                'icon': icon,
                'icon-image': icon_pixbuf,
                'entry': address_entry,
                'label': label,
                'socket': socket,
                'ebox': eventbox,
                'vbox': vbox,
                'uri': 'about:blank',
                'title': 'about:blank',
                'socket-id': socket_id,
                'pid': 0,
                'history': {},
                'com-tup': com_tup,
                'uri': uri,
                }

        self._windows[socket_id] = child

        child['plug-removed'] = socket.connect('plug-removed', self._plug_removed, child)
        eventbox.connect('button-press-event', self._tab_button_press, child)
        eventbox.connect('button-release-event', self._tab_button_release, child)
        address_entry.connect('activate', self._load_uri, child)
        address_entry.connect('icon-release', self._entry_icon_release, child)

        vbox.show_all()

        if switch_to:
            self._window.set_title(child['title'])
            self._tabs.set_current_page(index)

        self._glib.io_add_watch(com_tup[0].fileno(), self._glib.IO_IN,
                                self._callback, child)

        return socket_id, child

    def _tab_reordered(self, notebook: object, child: object, index: int):
        """ Set the new ordering.

        """

        print(child, index)

    def _tab_switched(self, notebook: object, child: object, index: int):
        """ Do stuff when the tab is switched.

        """

        self._statusbar.remove_all(self._status_context)
        if not self._windows:
            return True

        socket = child.get_children()[1]
        print("TAB SWITCHED: ",  self._windows[socket.get_id()]['title'])
        self._window.set_title(self._windows[socket.get_id()]['title'])

        return True

    def _tab_removed(self, notebook: object, child: object, index: int):
        """ Remove page info.

        """

        if notebook.get_n_pages() == 0:
            print("NO MORE PAGES, EXITING")
            self._window.destroy()

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
            print("sending Close")
            child['socket'].disconnect(child['plug-removed'])
            self._send_signal(child, 'close', True)

    def _get_current_child(self):
        """ Returns the child dict of the curren tab.

        """

        if not self._windows:
            return {'title': 'about:blank', 'uri': 'about:blank'}

        vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
        socket = vbox.get_children()[1]
        return self._windows[socket.get_id()]

    def _new_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Open a new tab.

        """

        print('open new tab', flags)
        if flags & self._gdk.ModifierType.SHIFT_MASK:
            print("SHIFT WAS PRESSED")
            data_dict = {'switch-to': True, 'uri': 'about:blank'}
            self._send_signal(self._get_current_child(), 'new-tab', data_dict)
        else:
            print("SHIFT WAS NOT PRESSED")
            self._pipe.send(('new-proc', self._make_tab(switch_to=True)))

    def _close_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Close tab.

        """

        print('Close tab')
        child = self._get_current_child()
        child['socket'].disconnect(child['plug-removed'])
        self._send_signal(child, 'close', True)

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

        self._get_current_child()['entry'].grab_focus()

    def _plug_removed(self, socket: object, child: dict):
        """ Re-open removed plug.

        """

        print("PLUG REMOVED: ", child['uri'])
        print("PLUG REMOVED CHILD: ", child)
        self._pipe.send(('terminate', child['pid']))
        # self._pipe.send({'new-proc': {'uri': child['uri'], 'switch-to': False,
        #                  'socket-id': socket.get_id()}})

        if not child['pid'] in self._revived:
            self._revived.append(child['pid'])
            child['pid'] = 0
            print('COMDICT: ', child['com-tup'][1])
            self._pipe.send(('new-proc', child['com-tup'][1]))

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
