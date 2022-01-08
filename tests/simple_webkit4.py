from gi import require_version as gi_require_version
gi_require_version('Gtk', '4.0')
gi_require_version('WebKit2', '5.0')
from gi.repository import WebKit2 as libwebkit
from gi.repository import Gtk as gtk


def test(app, url: str = 'https://www.startpage.com'):
    webview = libwebkit.WebView()
    settings = webview.get_settings()
    settings.set_property('user-agent', '''Mozilla/5.0 (X11; Linux x86_64)
                           AppleWebKit/537.36 (KHTML, like Gecko)
                           Chrome/47.0.2526.106 Safari/537.36''')
    webview.load_uri(url)

    scroll = gtk.ScrolledWindow()

    window = gtk.ApplicationWindow(application=app)
    scroll.set_child(webview)
    window.set_child(scroll)
    window.present()

app = gtk.Application(application_id="com.example.GtkApplication")
app.connect("activate", test)
app.run(None)
