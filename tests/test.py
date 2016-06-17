from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
from gi.repository import Gtk as gtk

def save_dialog(filename: str, folder: str, parent: object,
                title: str = 'Save File') -> str:
    """ Presents a file chooser dialog and returns a filename and folder tuple.

    """

    dialog = gtk.FileChooserDialog(title, parent, gtk.FileChooserAction.SAVE,
            (gtk.STOCK_CANCEL, gtk.ResponseType.CANCEL, gtk.STOCK_SAVE, gtk.ResponseType.ACCEPT))
    dialog.set_do_overwrite_confirmation(True)
    dialog.set_current_name(filename)
    dialog.set_current_folder(folder)
    response = dialog.run()
    # if response == gtk.ResponseType.ACCEPT:
    #     result = dialog.get_filename()
    # else:
    #     result = ''
    dialog.destroy()
    # return result

print(save_dialog('test', '/home/josiah/Desktop', None))
input()
