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
# gi_require_version('WebKit', '3.0')
gi_require_version('WebKit2', '4.0')


def test(url: str = 'http://biblesearch.pythonanywhere.com'):
    from gi.repository import Soup as libsoup
    from gi.repository import WebKit2 as libwebkit
    from gi.repository import Gtk as gtk
    from gi.repository import GLib as glib
    # gtk.init()


    # proxy_uri = libsoup.URI.new(os.getenv('http_proxy'))
    # session = libwebkit.get_default_session()
    # session.set_property('proxy-uri', proxy_uri)

    webview = libwebkit.WebView()
    # ctx = libwebkit.WebContext.get_default()
    # ctx.set_favicon_database_directory()
    # ctx.set_process_model(libwebkit.ProcessModel.MULTIPLE_SECONDARY_PROCESSES)
    # webview = libwebkit.WebView.new_with_context(ctx)
    # ctx = webview.get_context()
    # ctx.set_cache_model(libwebkit.CacheModel.DOCUMENT_VIEWER)
    # ctx.clear_cache()
    settings = webview.get_settings()
    # settings.set_property('enable-dns-prefetching', False)
    # settings.set_property('enable-html5-database', False)
    # settings.set_property('enable-html5-local-storage', False)
    # settings.set_property('enable-java', False)
    # settings.set_property('enable-offline-web-application-cache', False)
    # settings.set_property('enable-page-cache', False)
    # settings.set_property('enable-private-browsing', True)
    settings.set_property('user-agent', '''Mozilla/5.0 (X11; Linux x86_64)
                           AppleWebKit/537.36 (KHTML, like Gecko)
                           Chrome/47.0.2526.106 Safari/537.36''')
    webview.load_uri(url)

    scroll = gtk.ScrolledWindow()
    scroll.set_policy(gtk.PolicyType.AUTOMATIC,gtk.PolicyType.AUTOMATIC)
    scroll.set_shadow_type(gtk.ShadowType.IN)

    window = gtk.Window()
    window.connect_after('destroy', gtk.main_quit)
    scroll.add(webview)
    window.add(scroll)
    window.show_all()

    gtk.main()

test()
