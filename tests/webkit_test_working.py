from path import Path
from gi import require_version as gi_require_version
from multiprocessing import Process, Manager, Pipe
from multiprocessing import current_process
import multiprocessing
import json
import os
import re

# gi_require_version('Soup', '2.4')
gi_require_version('Gtk', '3.0')
gi_require_version('WebKit', '3.0')
gi_require_version('WebKit2', '4.0')


def test(url: str = 'https://inbox.google.com'):
    # from gi.repository import Soup as libsoup
    from gi.repository import WebKit2 as libwebkit
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

    # scroll = gtk.ScrolledWindow()
    # scroll.set_policy(gtk.PolicyType.AUTOMATIC,gtk.PolicyType.AUTOMATIC)
    # scroll.set_shadow_type(gtk.ShadowType.IN)

    window = gtk.Window()
    window.connect_after('destroy', gtk.main_quit)
    # window.add(scroll)
    # scroll.add(webview)
    window.add(webview)
    window.show_all()

    gtk.main()


class BrowserProc(object):
    """ A Browser Process.

    """

    def __init__(self, com_pipe: object, com_dict: object):
        """ Initialize the process.


        """

        from gi.repository import Soup as libsoup
        from gi.repository import WebKit as libwebkit
        from gi.repository import Gtk as gtk
        from gi.repository import Gdk as gdk
        from gi.repository import GLib as glib

        self._icon_db = libwebkit.get_favicon_database()
        # proxy_uri = libsoup.URI.new(os.getenv('http_proxy'))
        # session = libwebkit.get_default_session()
        # session.set_property('proxy-uri', proxy_uri)

        self._gtk = gtk
        self._gdk = gdk
        self._glib = glib
        self._libwebkit = libwebkit

        self._pid = multiprocessing.current_process().pid

        # self._plugs = dict((self._create_window(com_dict, com_pipe),))
        # self._plugs = {}
        self._windows = [self._create_window(com_dict, com_pipe)]

    def _create_window(self, com_dict: object, com_pipe: object):
        """ Create a window with a webview in it.

        """

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
        webview.connect('mime-type-policy-decision-requested', self._mime_request, com_pipe)
        webview.connect('resource-content-length-received', self._resource_length, com_pipe)
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
        # settings.set_property('enable-scripts', False)
        # settings.set_property('media-playback-requires-user-gesture', True)
        settings.set_property('user-agent', 'Mozilla/5.0 (X11; Linux x86_64) \
                               AppleWebKit/537.36 (KHTML, like Gecko) \
                               Chrome/47.0.2526.106 Safari/537.36')

        scroll = self._gtk.ScrolledWindow()
        scroll.set_policy(self._gtk.PolicyType.AUTOMATIC,
                          self._gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(self._gtk.ShadowType.IN)
        scroll.add(webview)
        scroll.show_all()


        # plug = self._gtk.Plug()
        # view_dict = {'plug': plug, 'webview': webview, 'scroll': scroll}
        # plug.connect_after('delete-event', self._delete, view_dict, com_pipe)
        # plug.add(scroll)
        # plug.show_all()

        view_dict = {'webview': webview, 'scroll': scroll}

        self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                self._recieve, view_dict, com_dict,
                                com_pipe)

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
                 com_dict: object, com_pipe: object):
        """ Recieve signals from outside.

        """

        for signal, data in com_pipe.recv().items():
            print('signal: {signal}, data: {data}'.format(**locals()))
            if signal == 'Close' and data:
                send_dict = {'pid': self._pid,
                             'socket-id': view_dict['socket-id']}
                print('Closing', view_dict['webview'].get_uri())
                index = self._windows.index(view_dict)
                print('Removing: ', self._windows.pop(index))
                if not self._windows:
                    com_pipe.send({'Terminate': send_dict})
                    return False
                print("Sending Closed")
                com_pipe.send({'Closed': send_dict})
                return False

            if signal == 'open-uri':
                view_dict['webview'].load_uri(data)
                view_dict['webview'].grab_focus()

            if signal == 'socket-id':
                view_dict['socket-id'] = data

                plug = self._gtk.Plug.new(data)
                plug.connect_after('delete-event', self._delete,
                                   view_dict, com_pipe)
                plug.add(view_dict['scroll'])
                plug.show_all()
                view_dict['plug'] = plug

        return True

    def _new_window(self, webview: object, webframe: object, com_pipe: object):
        """ New window in this process.

        """

        conp, procp = Pipe()
        data_dict = Manager().dict()
        new_win = self._create_window(data_dict, procp)
        com_pipe.send({'new-window-info': {'pid': self._pid,
                                           'com-tup': (conp, data_dict),
                                           'title': 'about:blank',
                                           'switch-to': False}})

        self._windows.append(new_win)

        return new_win['webview']

    def _nav_policy(self, webview: object, webframe: object, request: object,
                    nav_action: object, policy_decision: object,
                    com_pipe: object):
        """ Handle opening a new window.

        """

        uri = request.get_uri()
        # print('nav policy: ', uri)
        # with open('easylist.txt', 'r') as adb:
        #     for line in adb:
        #         if line.startswith(('!', '[Adblock', '@@')) or '##' in line:
        #             continue
        #         if '$' in line:
        #             continue
        #         regx = line.replace('*', '.*')
        #         regx = regx.replace('^', '($|\?\/)')
        #         regx = re.sub('^\|\|(.*)', '^(http://|https://|ftp://)*[^/]*', regx)
        #         regx = re.sub(r'^\|', '^(http://|https://|ftp://)*', regx)
        #         regx = re.sub(r'\|', '\/', regx)
        #         regx = re.sub(r'([\+\?\]\[])', '\\\1', regx)
        #         try:
        #             regx_r = re.compile(regx)
        #         except:
        #             print('ERROR with: ', regx)
        #         s = regx_r.search(uri)
        #         if s:
        #             print('regx: ', regx)
        #             print('finding ', regx_r.search(uri))
        #             policy_decision.ignore()
        #             return True
                # regx = re.compile(line)
                # if regx.search(uri):
                # if line in uri:
                #     print('blocking: ', uri)
                #     policy_decision.ignore()
                #     return True

        if 'ads' in uri.lower():
            print('ADS: ', uri)
            policy_decision.ignore()
            return True
        if nav_action.get_button() == 2 or (nav_action.get_button() == 1 and
           nav_action.get_modifier_state() &
           self._gdk.ModifierType.CONTROL_MASK):

            policy_decision.ignore()

            uri = request.get_uri()
            com_pipe.send({'new-window': {'uri': uri, 'switch-to': False}})

            return True

        policy_decision.use()
        return False

    def _title_changed(self, webview: object, prop: object, com_pipe: object):
        """ The title changed.

        """

        title = webview.get_property(prop.name)
        com_pipe.send({'title': title if title else 'about:blank'})

    def _icon_loaded(self, webview: object, icon_uri: str, com_pipe: object):
        """ Set icon loaded signal.

        """

        uri = webview.get_uri()
        # icon = self._icon_db.try_get_favicon_pixbuf(uri, 0, 0)
        icon = webview.try_get_favicon_pixbuf(0, 0)
        if not icon:
            print('icon uri: ', webview.get_icon_uri())
            icontheme = self._gtk.IconTheme().get_default()
            icon = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                       self._gtk.IconLookupFlags.USE_BUILTIN)
        com_pipe.send({'icon-bytes': icon.save_to_bufferv('png', '', '')[1]})

    def _load_status(self, webview: object, prop: object, com_pipe: object):
        """ Notify the parent process when the load status changes.

        """

        status = webview.get_property(prop.name)
        if status == self._libwebkit.LoadStatus.PROVISIONAL:
            icontheme = self._gtk.IconTheme().get_default()
            icon = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                       self._gtk.IconLookupFlags.USE_BUILTIN)
            com_pipe.send({'icon-bytes': icon.save_to_bufferv('png', '', '')[1]})
        if status == self._libwebkit.LoadStatus.FAILED:
            print('LOAD_ERROR: ')

        print(webview.get_property(prop.name))
        com_pipe.send({'load-status': int(status)})

    def _load_error(self, webview: object, webframe: object, uri: str, weberror: object, com_pipe):
        """ Get the error.

        """

        print("LOAD ERROR: ", uri, weberror.message)

    def _uri_changed(self, webview: object, prop: object, com_pipe: object):
        """ Send new uri and history.

        """

        uri = webview.get_property(prop.name)
        print('uri changed: ', webview.get_property(prop.name))
        com_pipe.send({'uri-changed': uri})

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
        return True

    def _progress_changed(self, webview: object, prop: object, com_pipe):
        """ Send the progress

        """

        progress = webview.get_property(prop.name)
        # print('progress: ', progress)
        com_pipe.send({'progress': progress})

    def run(self):
        """ Run the main gtk loop.

        """

        self._gtk.main()


def run_browser(com_pipe: object, com_dict: object):
    """ Runs a browser.

    """

    browser = BrowserProc(com_pipe, com_dict)
    browser.run()


def new_proc(data: dict):
    """ Create and run a new process.

    """

    conp, procp = Pipe()
    data_dict = Manager().dict({'open-uri': data['uri']})
    test_t = Process(target=run_browser, args=(procp, data_dict))
    test_t.start()
    conp.send({'open-uri': data['uri']})
    return test_t, {'pid': test_t.pid,
                    'com-tup': (conp, data_dict),
                    'title': 'about:blank',
                    'switch-to': data.get('switch-to', False),
                    'socket-id': data.get('socket-id', 0),
                    }


class MainWindow(object):
    """ The main window.

    """

    def __init__(self, com_pipe: object, com_dict: object):
        """ Initialize the process.


        """

        self._protocol_pat = re.compile(
                r'^(about:|http://|https://|ftp://|javascript:|mailto:|file://)', re.I)

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

        self._icon_db = libwebkit.get_favicon_database()

        self._accels = self._gtk.AccelGroup()

        accel_dict = {
                ('<Ctrl>t',): self._new_tab,
                ('<Ctrl>w',): self._close_tab,
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
        self._tabs.set_scrollable(True)
        self._tabs.set_show_tabs(True)
        self._window.add(self._tabs)
        self._window.show_all()

        self._pipe = com_pipe
        self._dict = com_dict

        self._windows = {}

        self._glib.io_add_watch(self._pipe.fileno(), self._glib.IO_IN,
                                self._recieve)

    def _quit(self, window: object, event: object):
        """ Quit

        """

        # for plug_id, data in self._plugs.items():
        # for data in self._windows:
        for socket_id, data in self._windows.items():
            com_pipe = data['com-tup'][0]
            com_pipe.send({'Close': True})
            print(data)
        self._dict['Quit'] = True
        self._pipe.send({'Quit': True})
        self._gtk.main_quit()

    def run(self):
        """ Run gtk.main()

        """

        self._gtk.main()

    def _callback(self, source: int, cb_condition: int, window: dict):
        """ Handle each window.

        """

        com_pipe, _ = window['com-tup']

        for signal, data in com_pipe.recv().items():
            if signal != 'icon-bytes':
                print(window['pid'], ' signal: {signal}: data: {data}'.format(**locals()))
            else:
                print(window['pid'], ' signal: {signal}: data: bytes_data'.format(**locals()))

            if signal == 'Closed' or signal == 'Terminate' and data:
                print(window, ' Closed')
                self._windows.pop(data['socket-id'])
                print(self._tabs.page_num(window['vbox']))
                self._tabs.remove_page(self._tabs.page_num(window['vbox']))

                if signal == 'Terminate':
                    print('Terminating ', data['pid'])
                    self._pipe.send({'terminate': data['pid']})

                if not self._windows:
                    self._window.emit('delete-event', None)
                    self._window.destroy()
                return False

            if signal == 'new-window-info':
                com_pipe, _ = data['com-tup']
                socket_id = self._add_tab(data, False)
                self._windows[socket_id] = data
                # com_pipe.send({'socket-id': socket_id})
                self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                        self._callback, data)

            if signal == 'new-window':
                self._pipe.send({'new-proc': data})

            if signal == 'plug-id' and data != window.get('plug-id', None):
                window['plug-id'] = data
                socket_id = window.get('socket-id', 0)
                if not window['socket'].get_plug_window():
                    if socket_id:
                        print('WINDOW: ', window)
                        window['socket'].add_id(data)
                    else:
                        socket_id = self._add_tab(window, False)
                        self._windows[socket_id] = window
                # self._tabs.foreach(print)

            if signal == 'title' and data != window.get('title', 'about:blank'):
                # index = self._tabs.page_num(window['vbox'])
                # tmp_child = self._tabs.get_nth_page(index)
                data += ' (pid: {pid})'.format(**window)
                window['label'].set_text(data)
                window['ebox'].set_tooltip_text(data)
                window['title'] = data
                # if tmp_child:
                #     eventbox = self._tabs.get_tab_label(tmp_child)
                #     window['title'] = data
                #     eventbox.set_tooltip_text(window['title'])
                #     if eventbox:
                #         eventbox.get_children()[0].get_children()[-1].set_text(data)

            if signal == 'icon-bytes' and data:
                loader = self._gdkpixbuf.PixbufLoader()
                loader.set_size(16, 16)
                loader.write(data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                window['icon-image'] = pixbuf
                window['icon'].set_from_pixbuf(pixbuf)
                window['entry'].set_icon_from_pixbuf(0, pixbuf)
                # index = self._tabs.page_num(window['vbox'])
                # tmp_child = self._tabs.get_nth_page(index)
                # if tmp_child:
                #     eventbox = self._tabs.get_tab_label(tmp_child)
                #     if eventbox:
                #         icon = eventbox.get_children()[0].get_children()[0]
                #         if icon:
                #             loader = self._gdkpixbuf.PixbufLoader()
                #             loader.set_size(16, 16)
                #             loader.write(data)
                #             loader.close()
                #             pixbuf = loader.get_pixbuf()
                #             window['icon-image'] = pixbuf
                #             icon.set_from_pixbuf(pixbuf)
                #             window['entry'].set_icon_from_pixbuf(0, pixbuf)

            if signal == 'load-status' and data <= 1:
                window['icon'].hide()
                window['spinner'].show_all()
                window['spinner'].start()
                # index = self._tabs.page_num(window['vbox'])
                # tmp_child = self._tabs.get_nth_page(index)
                # if tmp_child:
                #     eventbox = self._tabs.get_tab_label(tmp_child)
                #     if eventbox:
                #         hbox = eventbox.get_children()[0]
                #         icon = hbox.get_children()[0]
                #         icon.hide()
                #         spinner = hbox.get_children()[1]
                #         spinner.show_all()
                #         spinner.start()
            elif signal == 'load-status' and (data == 2 or data == 4):
                window['spinner'].stop()
                window['spinner'].hide()
                window['icon'].show_all()
                window['entry'].set_progress_fraction(0)
                # index = self._tabs.page_num(window['vbox'])
                # tmp_child = self._tabs.get_nth_page(index)
                # if tmp_child:
                #     eventbox = self._tabs.get_tab_label(tmp_child)
                #     if eventbox:
                #         hbox = eventbox.get_children()[0]
                #         spinner = hbox.get_children()[1]
                #         spinner.stop()
                #         spinner.hide()
                #         icon = hbox.get_children()[0]
                #         icon.show_all()
                #         window['entry'].set_progress_fraction(0)

            if signal == 'uri-changed' and data:
                window['uri'] = data
                window['entry'].set_text(data)
            if signal == 'progress':
                window['entry'].set_progress_fraction(data)


        return True

    def _recieve(self, source: int, cb_condition: int):
        """ Recieve signals from outside.

        """

        signal_dict = self._pipe.recv()
        print(signal_dict)

        for signal, data in signal_dict.items():
            if signal == 'open-tab':
                self._pipe.send({'new-proc': data})

            if signal == 'add-tab' and data not in self._windows.values():
                com_pipe, _ = data['com-tup']
                socket_id = self._add_tab(data, False)
                self._windows[socket_id] = data
                # com_pipe.send({'socket-id': socket_id})
                self._glib.io_add_watch(com_pipe.fileno(), self._glib.IO_IN,
                                        self._callback, data)

        return True

    def _load_uri(self, entry: object, com_pipe: object):
        """ Load uri.

        """

        uri = entry.get_text()
        # if not self._protocol_pat.match(uri):
        if not uri.startswith(('http://', 'https://', 'ftp://', 'file://',
                               'mailto:', 'javascript:')):
            if ' ' in uri or '.' not in uri or not uri:
                uri = 'https://startpage.com/do/search?query=%s' % uri
            else:
                uri = 'http://%s' % uri
        com_pipe.send({'open-uri': uri})

    def _add_tab(self, child: dict, switch_to: bool = False):
        """ Add Tab.

        """

        socket = self._gtk.Socket()
        vbox = self._gtk.VBox()
        address_bar = self._gtk.Toolbar()
        address_entry = self._gtk.Entry()
        address_entry.connect_after('activate', self._load_uri, child['com-tup'][0])
        child['entry'] = address_entry
        address_item = self._gtk.ToolItem()
        address_item.set_expand(True)
        address_item.add(address_entry)
        address_bar.add(address_item)
        vbox.pack_start(address_bar, False, False, 0)
        vbox.pack_start(socket, True, True, 0)

        label = self._gtk.Label(child['title'])
        label.set_justify(self._gtk.Justification.LEFT)
        label.set_alignment(xalign=0, yalign=0.5)
        label.set_width_chars(18)
        label.set_max_width_chars(18)
        label.set_ellipsize(self._pango.EllipsizeMode(3))
        label.show_all()
        child['label'] = label

        icon = self._gtk.Image()
        icontheme = self._gtk.IconTheme().get_default()
        pixbuf = icontheme.load_icon('text-html', self._gtk.IconSize.MENU,
                                     self._gtk.IconLookupFlags.USE_BUILTIN)
        child['icon-image'] = pixbuf
        address_entry.set_icon_from_pixbuf(0, pixbuf)
        address_entry.set_icon_from_icon_name(1, 'go-jump')
        icon.set_from_pixbuf(pixbuf)
        icon.show_all()
        child['icon'] = icon

        hbox = self._gtk.HBox(homogeneous=False, spacing=6)
        hbox.pack_start(icon, True, True, 0)
        spinner = self._gtk.Spinner()
        child['spinner'] = spinner
        hbox.pack_start(spinner, True, True, 0)
        hbox.pack_end(label, True, True, 0)
        hbox.show_all()
        spinner.hide()
        eventbox= self._gtk.EventBox()
        eventbox.add(hbox)
        eventbox.show_all()
        eventbox.set_has_window(False)
        eventbox.connect('button-press-event', self._tab_button_press, child)
        eventbox.connect('button-release-event', self._tab_button_release, child)
        index = self._tabs.insert_page(vbox, eventbox, self._tabs.get_current_page() + 1)
        self._tabs.set_tab_reorderable(vbox, True)
        if 'plug-id' in child:
            socket.add_id(child['plug-id'])
        socket.connect_after('plug-removed', self._plug_removed, child)
        child['socket'] = socket
        child['ebox'] = eventbox
        child['vbox'] = vbox
        child['com-tup'][0].send({'socket-id': socket.get_id()})
        vbox.show_all()
        if child['switch-to']:
            self._tabs.set_current_page(index)
        return socket.get_id()

    def _tab_reordered(self, notebook: object, child: object, index: int):
        """ Set the new ordering.

        """

        print(child, index)

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
            child['com-tup'][0].send({'Close': True})

    def _new_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Open a new tab.

        """

        print('open new tab')
        self._pipe.send({'new-proc': {'uri': 'about:blank', 'switch-to': True}})

    def _close_tab(self, accels: object, window: object, keyval: object, flags: object):
        """ Close tab.

        """

        print('Close tab')
        vbox = self._tabs.get_nth_page(self._tabs.get_current_page())
        socket = vbox.get_children()[1]
        print(vbox, socket)
        self._windows[socket.get_id()]['com-tup'][0].send({'Close': True})

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
        self._pipe.send({'new-proc': {'uri': child['uri'], 'switch-to': False,
                         'socket-id': socket.get_id()}})
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

    proc, proc_dict = new_proc({'uri': 'https://www.startpage.com'})
    print("child pid: ", proc.pid)
    main_cpipe.send({'add-tab': proc_dict})
    window_dict = {proc: proc_dict}

    while not main_dict['Quit']:
        try:
            tmp_dict = main_cpipe.recv()
        except KeyboardInterrupt:
            break
        for signal, data in tmp_dict.items():
            if signal == 'new-proc':
                proc, proc_dict = new_proc(data)
                window_dict[proc] = proc_dict
                main_cpipe.send({'add-tab': proc_dict})
                print("child pid: ", proc.pid)
                print('window_dict',window_dict)
            elif signal == 'terminate':
                for proc, proc_dict in window_dict.items():
                    if proc.pid == data:
                        print("Joining: ", proc)
                        proc.join(2)
                        if proc.is_alive():
                            print("Terminating: ", proc)
                            proc.terminate()
                        break
    print("Quitting")

    print(window_dict)
    for proc, proc_dict in window_dict.items():
        com_pipe, _ = proc_dict['com-tup']
        com_pipe.send({'Close': True})
        print("Joining: ", proc)
        proc.join(2)
        print(proc.is_alive())
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


    browser_windows = [new_proc('https://startpage.com', main_dict)]
    while browser_windows:
        for conp, data_dict, test_t in browser_windows:
            time_sleep(0.05)
            if conp.poll():
                if conp.recv():
                    main_cpipe.send('Remove')
                    main_dict['com-tup'] = (conp, data_dict)
                    browser_windows.remove((conp, data_dict, test_t))
                    continue
            new_window_data = data_dict.pop('new-window-info', ())
            if new_window_data:
                new_con, new_dict = new_window_data
                browser_windows.append((new_con, new_dict, test_t))
                main_dict['com-tup'] = (new_con, new_dict)

            new_window_uri = data_dict.pop('new-window', '')
            if new_window_uri:
                browser_windows.append(new_proc(new_window_uri, main_dict))

    main_dict['Exit'] = True
    main_p.join()

if __name__ == '__main__':
    # main()
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

    # l = []
    # for i in range(3):
    # l.append(new_proc('http://startpage.com'))
    # while l:
    #     for conp, data_dict, test_t in l:
    #         if conp.poll():
    #             if conp.recv():
    #                 l.remove((conp, data_dict, test_t))
    #                 continue
    #         new_window_data = data_dict.pop('new-window-info', ())
    #         if new_window_data:
    #             print(new_window_data)
    #             new_con, new_dict = new_window_data
    #             l.append((new_con, new_dict, test_t))

            # new_window_uri = data_dict.pop('new-window', '')
            # if new_window_uri:
            #     print('new-window uri', new_window_uri)
            #     new_win = new_proc(new_window_uri)
            #     l.append(new_win)
                # browser_windows.append(new_proc(new_window_uri))

    # l = [new_proc('http://google.com')]
    # l.append(new_proc('http://google.com'))
    # l.append(new_proc('http://google.com'))


    # data_dict2 = Manager().dict({'url': 'https://inbox.google.com'})
    # t2 = BrowserProc()
    # test2_t = Process(target=t2.run, args=(data_dict2,))
    # test2_t.start()

    # t1.load_uri(input("what url"))
    test_t = Process(target=test, args=('https://blender.org',))
    test_t.start()
    #
    # test2_t = Process(target=test)
    # test2_t.start()
    # test3_t = Process(target=test)
    # test3_t.start()
