#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Classes
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


""" Classes used by both processes.

"""

from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, Gdk, GLib, Pango, Gio
import pathlib
from xml.etree import ElementTree as etree
import logging
from functools import partial
from http.client import HTTPConnection
from urllib.parse import urlparse
import urllib.request as urlrequest
from urllib.error import URLError, HTTPError


class Bookmarks(object):
    """ Simple xbel bookmark object.

    """

    _empty_root = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xbel PUBLIC "+//IDN python.org//DTD XML Bookmark Exchange Language 1.0//EN//XML" "http://www.python.org/topics/xml/dtds/xbel-1.0.dtd">
<xbel version="1.0" xmlns:browser="lime.tree">
</xbel>"""

    def __init__(self, filename: str):
        """ Open a bookmarks file and parse it, and provide an easy interface.

        """

        self._filename = filename

        with pathlib.Path(filename) as xbel_file:
            if not xbel_file.exists():
                root = etree.fromstring(self._empty_root)
            else:
                root = etree.fromstring(xbel_file.read_text())

        self._tree = etree.ElementTree(root)
        self._root = root

    def get_root(self) -> object:
        """ Return the root.

        """

        return self._root

    def get_parent(self, element: object) -> object:
        """ Return the parent of element, or None if there is none.

        """

        for parent in self._tree.iter():
            if element in parent:
                return parent

        return None

    def sort_key_func(self, element: object) -> str:
        """ Return the title of the element prefixed with a 1 or a folder and a
        2 for a bookmark.

        """

        # Sort everything that isn't a folder or bookmark to the top.
        if element.tag not in ['folder', 'bookmark']: return '0'

        # Sort folders to the top.
        prefix = '1' if element.tag == 'folder' else '2'

        return prefix + element.find('title').text.lower()

    def make_title(self, text: str) -> object:
        """ Make and return a title element.

        """

        title = etree.fromstring('<title></title>\n')
        title.text = text
        return title

    def make_bookmark(self, url: str, title: str) -> object:
        """ Return a bookmark element.

        """

        bookmark = etree.fromstring('<bookmark>\n</bookmark>\n')
        bookmark.set('href', url if url else 'about:blank')
        bookmark.append(self.make_title(title))

        return bookmark

    def make_folder(self, title: str) -> object:
        """ Make and return a folder element.

        """

        folder = etree.fromstring('<folder>\n</folder>\n')
        folder.append(self.make_title(title))

        return folder

    def add_bookmark(self, parent: object, title: str, url: str):
        """ Add a bookmakr to parent.

        """

        parent.append(self.make_bookmark(url, title))

    def add_folder(self, parent: object, title: str):
        """ Add a folder with title in to parent.

        """

        folder = self.make_folder(title)
        parent.append(folder)
        return folder

    def remove(self, element: object):
        """ Removes element from the bookmarks.

        """

        parent = self.get_parent(element)
        if parent: parent.remove(element)

    def move(self, element: object, dest: object):
        """ Move element to dest.

        """

        if element.tag == 'folder' and dest in element.iter():
            logging.error("Can't move into self or child of self.")
            return False

        self.remove(element)
        dest.append(element)

        return True

    def edit(self, element: object, title: str, url: str = None):
        """ Edit the element.

        """

        if element.tag == 'bookmark' and url:
            if element.get('href') != url:
                element.set('href', url)

        if element.findtext('title') != title:
            element.find('title').text = title

    def to_dict(self, root: object) -> dict:
        """ Return a dictionary of this.

        """

        if root.tag == 'bookmark':
            title = root.findtext('title')
            url = root.get('href', 'about:blank')
            return {'title': title, 'url': url}

        tmp_dict = {}
        for element in sorted(root, key=self.sort_key_func):
            child_list = tmp_dict.get('children', [])
            if element.tag in ['folder', 'bookmark']:
                child_list.append(self.to_dict(element))
            elif element.tag == 'title':
                tmp_dict['title'] = element.text
            if child_list: tmp_dict['children'] = child_list

        return tmp_dict

    def from_dict(self, bm_dict: dict) -> object:
        """ Makes an xbel document from bm_dict.

        """

        if 'url' in bm_dict:
            return self.make_bookmark(bm_dict['url'], bm_dict['title'])

        if 'title' in bm_dict:
            element = self.make_folder(bm_dict['title'])
        else:
            element = etree.fromstring(self._empty_root)

        child_list = bm_dict.get('children', [])
        for el_dict in child_list:
            element.append(self.from_dict(el_dict))

        return element

    def iter(self, root: object) -> iter:
        """ Return an iter of all elements in root.

        """

        for element in sorted(root, key=self.sort_key_func):
            yield element

    def iter_type(self, root: object, type_desc: str) -> iter:
        """ Returns an iterator over the elements in self._root.

        """

        for element in sorted(root.findall(type_desc), key=self.sort_key_func):
            yield element

    def remove_dead(self, root: object) -> list:
        """ Returns a list of tuples (url, title) of dead urls in root.  Also
        it removes them from root.

        """

        result = []
        for element in root.iter('bookmark'):
            url = element.get('href', None)
            req = urlrequest.Request(
                    url,
                    method='HEAD',
                    headers={
                        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; \
                                rv:45.0) Gecko/20100101 Firefox/45.0',
                        }
                    )
            try:
                print('Checking: {url}'.format(**locals()))
                response = urlrequest.urlopen(req, timeout=120)
            except Exception as err:
                print('Error: {err} on url {url}'.format(**locals()))
                result.append((err, url, element.findtext('title')))
                self.remove(element)

        return result

    def save(self):
        """ Save the bookmarks to file.

        """

        with pathlib.Path(self._filename) as xbel_file:
            xbel_file.rename(self._filename + '.bak')
        self._tree.write(self._filename, encoding='UTF-8', xml_declaration=True)

class BookmarkMenu(GObject.GObject):
    """ A menu for all the bookmarks.

    """

    __gsignals__ = {
            'new-bookmark': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_PYOBJECT,
                             ()),
            'open-folder': (GObject.SIGNAL_RUN_LAST, None,
                            (GObject.TYPE_PYOBJECT,)),
            'tab-list': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_PYOBJECT, ()),
            'bookmark-release-event': (GObject.SIGNAL_RUN_LAST, None,
                                       (GObject.TYPE_PYOBJECT, str)),
            }

    def __init__(self, filename: str, parent: object):
        """ Make a bookmark menu using the file filename.

        """

        super(BookmarkMenu, self).__init__()

        self._parent = parent
        self._bookmarks = Bookmarks(filename)
        self._menu = Gtk.Menu()
        self._built = False
        self.show_action_icons = False

    def _do_build_menu(self):
        """ Build the menu in a thread.

        """

        try:
            GLib.idle_add(self._menu.foreach,self._menu.remove)
            GLib.idle_add(self._add_bookmark_item)
            self._build_menu(self._bookmarks.get_root())
            self._built = True
        except Exception as err:
            logging.error('Error building bookmarks menu: {err}'.format(**locals()))

    def _menu_position(self, menu: object, x: int, y: int,
                           data: object) -> tuple:
        """ Position the bookmark menu.

        """

        offset = 22
        return (int(data.x_root - data.x),
               int(data.y_root - data.y) + offset, False)

    def popup(self, event: object):
        """ Popup the menu.

        """

        if not self._built:
            GLib.idle_add(self._do_build_menu)
        self._menu.popup(None, None, self._menu_position, event, event.button,
                         event.time)

    def update_menu(func: object) -> object:
        """ Update the menu after every method that changes the bookmarks.

        """

        def wrapper(self, *args, **kwargs) -> object:
            """ Wrapper.

            """

            result = func(self, *args, **kwargs)
            if result:
                self._bookmarks.save()
                self._built = False

        return wrapper

    def _build_menu(self, root: object) -> object:
        """ Build the menu.

        """

        if root == self._bookmarks.get_root():
            menu = self._menu
        else:
            menu = Gtk.Menu()

        for i in self._bookmarks.iter(root):
            menu_item = None
            if i.tag == 'folder':
                menu_item = self._make_menu_item(i.findtext('title'),
                                                 'folder-symbolic',
                                                 show_icon=True)
                submenu = self._build_menu(i)
                GLib.idle_add(self._append_edit_items, submenu, i)
                menu_item.set_submenu(submenu)
            elif i.tag == 'bookmark':
                menu_item = self._make_menu_item(i.findtext('title'),
                                                 'text-x-generic-symbolic',
                                                 show_icon=True)
                menu_item.set_tooltip_text(i.get('href'))
                menu_item.connect('button-release-event',
                                 self._bookmark_release, i)
            if menu_item:
                GLib.idle_add(menu_item.show_all)
                GLib.idle_add(menu.add, menu_item)

        menu.append(Gtk.SeparatorMenuItem())
        GLib.idle_add(self._append_folder_items, menu, root)
        GLib.idle_add(menu.show_all)

        return menu

    def _add_bookmark_item(self):
        """ Put a bookmark page at top of main menu.

        """

        item = self._make_menu_item('Bookmark This Page',
                                    'bookmark-new-symbolic',
                                    show_icon=True)
        item.connect('activate', lambda itm: self.bookmark_page())
        GLib.idle_add(item.show_all)
        self._menu.append(item)
        self._menu.append(Gtk.SeparatorMenuItem())

    def _append_folder_items(self, menu: object, element: object):
        """ Append folder related items to the menu.

        """

        menu.append(Gtk.SeparatorMenuItem())

        folder_items_tup = (
                (('Open Folder As Tabs', 'document-open-symbolic'),
                    self._open_folder),
                (('Bookmark Tabs As Folder', 'bookmark-add-symbolic'),
                    self._bookmark_tabs),
                (('Add Folder Here', 'bookmark-add-symbolic'),
                    self._add_folder),
                (('Add Bookmark Here', 'bookmark-new-symbolic'),
                    self._add_bookmark),
                )

        for (title, icon_name), func in folder_items_tup:
            menu_item = Gtk.MenuItem()
            menu_item = self._make_menu_item(title, icon_name)
            menu_item.connect('activate', func, element)
            menu.append(menu_item)

    def _append_edit_items(self, menu: object, element: object):
        """ Append edit items to menu.

        """

        if element.tag == 'folder':
            menu.append(Gtk.SeparatorMenuItem())

        edit_items_tup = (
                (('Edit {element.tag}', 'text-editor-symbolic'),
                    self._edit_menu),
                (('Delete {element.tag}', 'edit-delete-symbolic'),
                    self._delete_menu),
                )

        for (title, icon_name), func in edit_items_tup:
            menu_item = self._make_menu_item(title.format(**locals()),
                                             icon_name)
            menu_item.connect('activate', func, element)
            menu.append(menu_item)

    def _make_menu_item(self, title: str, icon_name: str,
                        show_icon: bool = False) -> object:
        """ Make and return a menu_item.

        """

        label = Gtk.Label(title)
        label.set_max_width_chars(48)
        label.set_ellipsize(Pango.EllipsizeMode.END)

        grid = Gtk.Grid()
        grid.set_column_spacing(6)
        grid.attach(label, 0, 0, 1, 1)

        if icon_name and (show_icon or self.show_action_icons):
            icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.MENU)
            grid.attach_next_to(image, label, Gtk.PositionType.LEFT, 1, 1)

        menu_item = Gtk.MenuItem()
        menu_item.add(grid)

        return menu_item

    def _open_folder(self, menu_item: object, element: object):
        """ Open the items in element as tabs.

        """

        folder_list = [i.get('href') for i in element if i.tag == 'bookmark']
        self.emit('open-folder', folder_list)

    def _do_add_folder(self, element: object):
        """ Add a folder to element.

        """

        name_dialog = EntryDialog('Add Folder', 'folder-symbolic',
                                  parent=self._parent)
        name_dialog.set_name_title('Enter Folder Name')
        name_dialog.set_default_name('New Folder')
        result = name_dialog.run()
        if not result: return None

        logging.info('Name = {name}'.format(**result))

        return self._bookmarks.add_folder(element, result['name'])

    def _add_folders(self, folder_info: tuple) -> dict:
        """ Adds the folders in folder_info and returns a dictionary where the
        folder_id is linked to the new folder element.

        """

        parent_trans = {}
        for title, parent, folder_id in folder_info:
            parent = parent_trans.get(parent, parent)
            new_folder = self._bookmarks.add_folder(parent, title)
            parent_trans[folder_id] = new_folder

        return parent_trans

    @update_menu
    def bookmark_page(self):
        """ Add a bookmark of current page.

        """

        uri, title = self.emit('new-bookmark')
        self._menu.popdown()

        edit_dialog = EditDialog(self._parent, 'Bookmark Page',
                                 'bookmark-new-symbolic',
                                 self._bookmarks.iter_type, True)

        edit_dialog.populate_tree(self._bookmarks.get_root())
        edit_dialog.set_name_title('Edit Bookmark Title')
        edit_dialog.set_default_name(title)
        edit_dialog.set_uri_title('Edit Bookmark URL')
        edit_dialog.set_default_uri(uri)

        result = edit_dialog.run()

        if not result: return False

        logging.info(result)

        # Create the new folders and associate thier ids with the actual
        # folder elements.
        parent_trans = self._add_folders(result.get('new-folder', ()))
        # If result['move'] is a folder id then translate it into an
        # actual folder element.
        destination = parent_trans.get(result['move'], result['move'])

        self._bookmarks.add_bookmark(destination, *result['changed'])

        return True

    @update_menu
    def _bookmark_tabs(self, menu_item: object, element: object):
        """ Add all tabs as bookmark folder.

        """

        folder = self._do_add_folder(element)
        if not folder: return False

        tab_list = self.emit('tab-list')
        logging.info(tab_list)
        for uri, title in tab_list:
            self._bookmarks.add_bookmark(folder, title, uri)
        return True

    @update_menu
    def _add_folder(self, menu_item: object, element: object):
        """ Add a folder to element.

        """

        return True if self._do_add_folder(element) else False

    @update_menu
    def _add_bookmark(self, menu_item: object, element: object):
        """ Bookmark current tab in element.

        """

        uri, title = self.emit('new-bookmark')
        name_dialog = EntryDialog('Add Bookmark', 'bookmark-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title('Edit Bookmark Title')
        name_dialog.set_default_name(title)
        name_dialog.set_uri_title('Edit Bookmark URL')
        name_dialog.set_default_uri(uri)
        result = name_dialog.run()

        if not result: return False

        uri = result['uri']
        title = result['name']
        logging.info('Add bookmark {title} => {uri}'.format(**locals()))
        self._bookmarks.add_bookmark(element, title, uri)

        return True

    @update_menu
    def _edit_menu(self, menu_item: object, element: object):
        """ Edit element

        """

        self._menu.popdown()
        edit_dialog = EditDialog(self._parent,
                                 'Edit {element.tag}'.format(**locals()),
                                 'document-edit-symbolic',
                                 self._bookmarks.iter_type,
                                 element.tag == 'bookmark')
        if element.tag == 'bookmark':
            folder = self._bookmarks.get_parent(element)
            uri = element.get('href')
            edit_dialog.set_uri_title('Edit Bookmark URL')
            edit_dialog.set_default_uri(uri)
        else:
            folder = element

        edit_dialog.populate_tree(self._bookmarks.get_root(), folder)
        edit_dialog.set_name_title(
                'Edit {title} Title'.format(title=element.tag.capitalize())
                )
        edit_dialog.set_default_name(element.findtext('title'))

        result = edit_dialog.run()

        if not result: return False

        logging.info(result)

        parent_trans = self._add_folders(result.get('new-folder', ()))
        self._bookmarks.edit(element, *result['changed'])
        destination = parent_trans.get(result['move'], result['move'])
        logging.info('move from {folder} to {destination}'.format(**locals()))
        self._bookmarks.move(element, destination)

        return True

    @update_menu
    def _delete_menu(self, menu_item: object, element: object):
        """ Delete element

        """

        self._menu.popdown()
        self._bookmarks.remove(element)

        return True

    def _bookmark_release(self, menu_item: object, event: object,
                          element: object):
        """ Open the bookmark.

        """

        uri = element.get('href')

        if event.button == 3:
            menu = Gtk.Menu()
            self._append_edit_items(menu, element)
            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)
            return True
        else:
            self.emit('bookmark-release-event', event, uri)


class EntryDialog(GObject.GObject):
    """ A name entry dialog for adding bookmarks and folders.

    """

    def __init__(self, title: str, icon_name: str, parent: object = None,
                 show_uri: bool = False):
        """ Open an entry dialog.

        """

        super(EntryDialog, self).__init__()

        self._loop_level = 0
        self._result = {}

        self._name_entry = Gtk.Entry()
        self._name_entry.set_activates_default(True)
        self._name_entry.set_margin_start(12)
        self._name_entry.set_margin_top(6)
        self._name_entry.set_hexpand(True)

        self._name_frame = Gtk.Frame()
        self._name_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self._name_frame.set_margin_start(12)
        self._name_frame.set_margin_end(12)
        self._name_frame.set_margin_top(12)
        self._name_frame.add(self._name_entry)

        self._uri_entry = Gtk.Entry()
        self._uri_entry.set_activates_default(True)
        self._uri_entry.set_margin_start(12)
        self._uri_entry.set_margin_top(6)
        self._uri_entry.set_hexpand(True)

        self._uri_frame = Gtk.Frame()
        self._uri_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self._uri_frame.set_margin_start(12)
        self._uri_frame.set_margin_end(12)
        self._uri_frame.set_margin_top(6)
        self._uri_frame.add(self._uri_entry)

        cancel_button = Gtk.Button.new_with_label('Cancel')
        cancel_button.set_margin_start(12)
        cancel_button.set_margin_bottom(12)
        cancel_button.set_margin_top(12)
        cancel_button.connect('clicked', self._close_dialog,
                              Gtk.ResponseType.CANCEL)

        ok_button = Gtk.Button.new_with_label('OK')
        ok_button.set_can_default(True)
        ok_button.set_margin_end(12)
        ok_button.set_margin_bottom(12)
        ok_button.set_margin_top(12)
        ok_button.connect('clicked', self._close_dialog, Gtk.ResponseType.OK)

        button_grid = Gtk.Grid()
        button_grid.set_column_spacing(6)
        button_grid.set_column_homogeneous(True)
        button_grid.attach(cancel_button, 0, 0, 1, 1)
        button_grid.attach(ok_button, 1, 0, 1, 1)
        button_grid.set_halign(Gtk.Align.END)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.attach(self._name_frame, 0, 0, 5, 1)
        if show_uri: main_grid.attach(self._uri_frame, 0, 1, 5, 1)
        main_grid.attach(button_grid, 4, 2, 1, 1)

        self._window = Gtk.Window()
        self._window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self._window.set_focus(self._name_entry)
        self._window.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self._window.set_default(ok_button)
        self._window.set_size_request(300, -1)
        self._window.set_modal(True)
        self._window.set_transient_for(parent)
        self._window.set_destroy_with_parent(True)
        self._window.set_resizable(False)
        self._window.connect('destroy', self._close_dialog,
                             Gtk.ResponseType.CANCEL)
        self._window.set_title(title)
        self._window.set_icon_name(icon_name)
        self._window.add(main_grid)

        accels = Gtk.AccelGroup()
        keyval, modifier = Gtk.accelerator_parse('Escape')
        accels.connect(keyval, modifier, Gtk.AccelFlags.VISIBLE,
                       lambda *a: self._close_dialog(None,
                                                     Gtk.ResponseType.CANCEL))

        self._window.add_accel_group(accels)

        self.set_name_title = partial(self._set_frame_label, self._name_frame)
        self.set_uri_title = partial(self._set_frame_label, self._uri_frame)
        self.set_default_name = self._name_entry.set_text
        self.set_default_uri = self._uri_entry.set_text

    def run(self) -> dict:
        """ Run the dialog.

        """

        self._window.show_all()

        self._loop_level = Gtk.main_level() + 1
        Gtk.main()

        return self._result

    def _close_dialog(self, button: object, response: int):
        """ Close the dialog and set the result.

        """

        if response == Gtk.ResponseType.OK:
            self._result['name'] = self._name_entry.get_text()
            self._result['uri'] = self._uri_entry.get_text()

        if Gtk.main_level() == self._loop_level:
            Gtk.main_quit()

        self._window.destroy()

    def _set_frame_label(self, frame: object, label: str):
        """ Set the label text.

        """

        label = Gtk.Label('<b>{title}</b>'.format(title=label))
        label.set_use_markup(True)
        frame.set_label_widget(label)


class EditDialog(GObject.GObject):
    """ Edit dialog for editing folders and bookmarks.

    """

    def __init__(self, parent: object, title: str, icon_name: str,
                 func: object, show_uri: bool = False):
        """ A dialog with a tree view.

        """

        self._bookmarks_func = func
        self._loop_level = 0
        self._result = {}
        self._new_folder_list = []
        self._selected = None

        pix_render = Gtk.CellRendererPixbuf()
        text_render = Gtk.CellRendererText()

        column = Gtk.TreeViewColumn()
        column.pack_start(pix_render, False)
        column.pack_start(text_render, True)
        column.set_spacing(6)
        column.add_attribute(pix_render, 'gicon', 0)
        column.add_attribute(text_render, 'text', 1)

        self._tree_store = Gtk.TreeStore(Gio.Icon, str, object)
        self._tree_view = Gtk.TreeView(self._tree_store)
        self._tree_view.append_column(column)
        self._tree_view.set_headers_visible(False)
        self._tree_view.set_vexpand(True)
        self._tree_view.set_hexpand(True)
        self._tree_view.connect('cursor-changed', self._cursor_changed)

        scroll = Gtk.ScrolledWindow()
        scroll.set_margin_top(12)
        scroll.set_margin_bottom(12)
        scroll.set_margin_left(12)
        scroll.set_margin_right(12)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.add(self._tree_view)

        tree_frame_label = Gtk.Label('<b>Select Destination Folder</b>')
        tree_frame_label.set_use_markup(True)

        tree_frame = Gtk.Frame()
        tree_frame.set_label_widget(tree_frame_label)
        tree_frame.add(scroll)
        tree_frame.set_shadow_type(Gtk.ShadowType.NONE)
        tree_frame.set_margin_top(12)
        tree_frame.set_margin_left(12)

        new_folder_btn = Gtk.Button('New Folder')
        new_folder_btn.connect('clicked', self._new_folder_clicked)
        new_folder_btn.set_halign(Gtk.Align.END)
        new_folder_btn.set_margin_end(12)
        new_folder_btn.set_margin_bottom(6)

        self._name_entry = Gtk.Entry()
        self._name_entry.set_activates_default(True)
        self._name_entry.set_margin_start(12)
        self._name_entry.set_margin_top(6)
        self._name_entry.set_hexpand(True)

        self._name_frame = Gtk.Frame()
        self._name_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self._name_frame.set_margin_start(12)
        self._name_frame.set_margin_end(12)
        self._name_frame.add(self._name_entry)

        self._uri_entry = Gtk.Entry()
        self._uri_entry.set_activates_default(True)
        self._uri_entry.set_margin_start(12)
        self._uri_entry.set_margin_top(6)
        self._uri_entry.set_hexpand(True)

        self._uri_frame = Gtk.Frame()
        self._uri_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self._uri_frame.set_margin_start(12)
        self._uri_frame.set_margin_end(12)
        self._uri_frame.set_margin_top(6)
        self._uri_frame.add(self._uri_entry)

        cancel_button = Gtk.Button.new_with_label('Cancel')
        cancel_button.set_margin_start(12)
        cancel_button.set_margin_bottom(12)
        cancel_button.set_margin_top(12)
        cancel_button.connect('clicked', self._close_dialog,
                              Gtk.ResponseType.CANCEL)

        ok_button = Gtk.Button.new_with_label('OK')
        ok_button.set_can_default(True)
        ok_button.set_margin_end(12)
        ok_button.set_margin_bottom(12)
        ok_button.set_margin_top(12)
        ok_button.connect('clicked', self._close_dialog, Gtk.ResponseType.OK)

        button_grid = Gtk.Grid()
        button_grid.set_column_spacing(6)
        button_grid.set_column_homogeneous(True)
        button_grid.attach(cancel_button, 0, 0, 1, 1)
        button_grid.attach(ok_button, 1, 0, 1, 1)
        button_grid.set_halign(Gtk.Align.END)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.attach(tree_frame, 0, 0, 5, 1)
        main_grid.attach(new_folder_btn, 0, 1, 5, 1)
        main_grid.attach(self._name_frame, 0, 2, 5, 1)
        if show_uri: main_grid.attach(self._uri_frame, 0, 3, 5, 1)
        main_grid.attach(button_grid, 4, 4, 1, 1)

        headerbar = Gtk.HeaderBar()
        headerbar.set_show_close_button(True)
        headerbar.set_subtitle('Select the destination folder for this page.')

        self._window = Gtk.Window()
        self._window.set_titlebar(headerbar)
        self._window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self._window.set_focus(self._name_entry)
        self._window.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        self._window.set_default(ok_button)
        self._window.set_default_size(400, 400)
        self._window.set_modal(True)
        self._window.set_transient_for(parent)
        self._window.set_destroy_with_parent(True)
        self._window.connect('delete-event',
                             lambda *a: self._close_dialog(self._window,
                                 Gtk.ResponseType.CANCEL))
        self._window.set_title(title)
        self._window.set_icon_name(icon_name)
        self._window.add(main_grid)

        accels = Gtk.AccelGroup()
        keyval, modifier = Gtk.accelerator_parse('Escape')
        accels.connect(keyval, modifier, Gtk.AccelFlags.VISIBLE,
                       lambda *a: self._close_dialog(None,
                                                     Gtk.ResponseType.CANCEL))

        self._window.add_accel_group(accels)
        self._window.show_all()

        self.set_name_title = partial(self._set_frame_label, self._name_frame)
        self.set_uri_title = partial(self._set_frame_label, self._uri_frame)
        self.set_default_name = self._name_entry.set_text
        self.set_default_uri = self._uri_entry.set_text

    def run(self) -> dict:
        """ Start Gtk main.

        """

        self._loop_level = Gtk.main_level() + 1

        Gtk.main()

        return self._result

    def _close_dialog(self, widget: object, response: int):
        """ Close the dialog.

        """

        if response == Gtk.ResponseType.OK:
            self._result['new-folder'] = self._new_folder_list
            self._result['move'] = self._selected
            self._result['changed'] = (
                    self._name_entry.get_text(),
                    self._uri_entry.get_text()
                    )

        if Gtk.main_level() == self._loop_level:
            Gtk.main_quit()

        self._window.destroy()

    def _select_iter(self, active_iter: object):
        """ Select the row associated by active_iter.

        """

        self._tree_view.expand_to_path(self._tree_store.get_path(active_iter))
        self._tree_view.get_selection().select_iter(active_iter)
        self._tree_view.set_cursor(self._tree_store.get_path(active_iter))
        self._selected = self._tree_view.get_model().get_value(active_iter, 2)

    def populate_tree(self, root: object, selected: object = None):
        """ Populate the tree view from root.

        """

        self._tree_store.clear()
        self._selected = selected if selected else root

        icon = Gio.ThemedIcon.new_with_default_fallbacks('folder-symbolic')
        parent_iter = self._tree_store.append(None, (icon, 'Bookmarks', root))
        active_iter = self._build_tree(parent_iter, root, icon, selected)

        self._select_iter(active_iter if active_iter else parent_iter)

    def _build_tree(self, parent_iter: object, root: object, icon: object,
                    selected: object = None) -> object:
        """ Build the tree for root in tree_view.

        """

        active_iter = None

        for folder in self._bookmarks_func(root, 'folder'):
            folder_iter = self._tree_store.append(parent_iter, (icon,
                                                  folder.findtext('title'),
                                                  folder))
            return_iter = self._build_tree(folder_iter, folder, icon, selected)

            if folder == selected:
                active_iter = folder_iter
            elif return_iter != None:
                active_iter = return_iter

        return active_iter

    def _cursor_changed(self, tree_view: object):
        """ Set the entry boxes based on what row is selected.

        """

        tree_path, focus_column = tree_view.get_cursor()
        if tree_path and focus_column:
            model = tree_view.get_model()
            self._selected = model.get_value(model.get_iter(tree_path), 2)

    def _set_frame_label(self, frame: object, label: str):
        """ Set the label text.

        """

        label = Gtk.Label('<b>{title}</b>'.format(title=label))
        label.set_use_markup(True)
        label.show_all()
        frame.set_label_widget(label)

    def _new_folder_clicked(self, button: object):
        """ Get the name for the new folder.

        """

        name_dialog = EntryDialog('Add Folder', 'folder-symbolic',
                                  parent=self._window)
        name_dialog.set_name_title('Enter Folder Name')
        name_dialog.set_default_name('New Folder')
        result = name_dialog.run()

        if result:
            logging.info('Name = {name}'.format(**result))
            folder_name = result['name']

            # Get the tree_iter of the selection so the new folder can
            # be added to it.
            tree_path, _ = self._tree_view.get_cursor()
            model = self._tree_view.get_model()
            parent_iter = model.get_iter(tree_path)

            # Add the new folder.
            icon = Gio.ThemedIcon.new_with_default_fallbacks('folder-symbolic')
            folder_iter = self._tree_store.append(parent_iter, (icon,
                                                  folder_name, None))

            # Use the id of the folder_iter so folders/bookmarks can be
            # moved to the correct folder.
            iter_id = id(folder_iter)
            folder_id = '{folder_name}{iter_id}'.format(**locals())
            self._tree_store.set_value(folder_iter, 2, folder_id)

            self._new_folder_list.append((folder_name, self._selected,
                                          folder_id))

            # Select the new folder.
            self._select_iter(folder_iter)
