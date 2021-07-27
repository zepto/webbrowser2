from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
gi_require_version('WebKit2', '4.0')
from gi.repository import WebKit2 as libwebkit


def callback(data_manager, res, user_data):
    data_manager.clear_finish()
def fetch_callback(data_manager, result):

    items = data_manager.fetch_finish(result)
    print(items)
    data_manager.remove(libwebkit.WebsiteDataTypes.ALL, items, None)

def test(url: str = 'http://startpage.com'):
    from gi.repository import WebKit2 as libwebkit
    ctx = libwebkit.WebContext.get_default()
    data_manager = ctx.get_property('website-data-manager')
    data_manager.fetch(libwebkit.WebsiteDataTypes.ALL, None, fetch_callback)
    # data_manager = ctx.get_website_data_manager()
    # cancelable = Gio.Cancellable.new()
    # print(data_manager.get_property('disk-cache-directory'))
    # data_manager.clear(libwebkit.WebsiteDataTypes.ALL, 0, cancelable, callback, None)

test()
