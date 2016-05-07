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
from gi.repository import Gtk, GObject, GLib, Gio, WebKit2, Gdk, Pango
import pathlib
import logging
import socket
from json import loads as json_loads
from json import dumps as json_dumps

from functions import save_dialog
from bookmarks import EntryDialog


class SearchSettings(Gtk.Grid):
    """ Search engine list and settings.

    """

    __gsignals__ = {
            'changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str, str)),
            'default-changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str,)),
            'added': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str)),
            'removed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str)),
            }

    def __init__(self, search_dict: dict, parent: object = None):
        """ Create a list for configuring search engines.

        """

        super(SearchSettings, self).__init__()

        self._parent = parent

        self._last_radio = None
        self._search_dict = search_dict
        self._default_name = ''

        self._search_list = Gtk.ListBox()
        self._search_list.set_vexpand(True)
        self._search_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._search_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-add-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        add_button = Gtk.Button()
        add_button.set_tooltip_text('Add New Search Engine')
        add_button.set_image(button_img)
        add_button.set_relief(Gtk.ReliefStyle.NONE)
        add_button.connect('clicked', self._add_clicked)

        button_grid = Gtk.Grid()
        button_grid.attach(add_button, 0, 0, 1, 1)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.set_row_homogeneous(False)
        main_grid.attach(scroll, 0, 0, 1, 8)
        main_grid.attach(button_grid, 1, 0, 1, 1)
        main_grid.set_margin_bottom(6)
        main_grid.set_margin_top(6)
        main_grid.set_margin_start(6)
        main_grid.set_margin_end(6)

        frame_label = Gtk.Label('<b>Search Settings</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(main_grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self.set_size_request(-1, 150)
        self.attach(frame, 0, 0, 1, 1)

        self.show_all()

        for name, uri in sorted(search_dict.items()):
            self.add_search(name, uri)

    def _add_clicked(self, button: object):
        """ Add a new search engine.

        """

        name_dialog = EntryDialog('Add Search', 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title('Enter Name')
        name_dialog.set_uri_title('Enter Website URL (%s = search term)')
        result = name_dialog.run()
        if not result: return None

        self.add_search(result['name'], result['uri'])
        self.emit('added', result['name'], result['uri'])

    def add_search(self, name: str, uri: str):
        """ Add a search engine to the search_list.

        """

        self._search_dict[name] = uri

        radio_button = Gtk.RadioButton.new(None)
        radio_button.set_label(name)
        radio_button.connect('toggled', self._radio_toggled)
        radio_button.set_hexpand(True)
        radio_button.join_group(self._last_radio)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('text-editor-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        edit_button = Gtk.Button()
        edit_button.set_tooltip_text('Edit Search Engine')
        edit_button.set_image(button_img)
        edit_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text('Remove Search Engine')
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        button_grid = Gtk.Grid()
        button_grid.attach(radio_button, 0, 0, 1, 1)
        button_grid.attach(edit_button, 1, 0, 1, 1)
        button_grid.attach(remove_button, 2, 0, 1, 1)
        button_grid.show_all()

        self._last_radio = radio_button

        self._search_list.add(button_grid)
        remove_button.connect('clicked', self._remove_clicked, button_grid,
                              radio_button)
        edit_button.connect('clicked', self._edit_clicked, radio_button)

    def _remove_clicked(self, remove_button: object, grid: object,
                        radio_button: object):
        """ Remove this engine from the list.

        """

        name = radio_button.get_label()
        uri = self._search_dict.pop(name, None)

        self._search_list.remove(grid.get_parent())

        if self._last_radio == radio_button:
            for button in radio_button.get_group():
                if button != radio_button:
                    self._last_radio = button
                    break
            else:
                self._last_radio = None

        # Remove from group.
        radio_button.join_group(None)

        if self._default_name == name:
            if self._last_radio:
                self.set_default(self._last_radio.get_label())
        self.emit('removed', name, uri)

    def _edit_clicked(self, button: object, radio_button: object):
        """ Remove this engine from the list.

        """

        name = radio_button.get_label()
        uri = self._search_dict.pop(name)

        name_dialog = EntryDialog('Edit Search', 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title('Edit Name')
        name_dialog.set_default_name(name)
        name_dialog.set_uri_title('Edit Website URL')
        name_dialog.set_default_uri(uri)
        result = name_dialog.run()
        if not result: return None

        self._search_dict[result['name']] = result['uri']
        radio_button.set_label(result['name'])
        if self._default_name == name:
            self.set_default(result['name'])
        self.emit('changed', name, result['name'], result['uri'])

    def set_default(self, name: str):
        """ Set the default search engine.

        """

        if self._last_radio:
            if name in self._search_dict:
                self._default_name = name
                for radio in self._last_radio.get_group():
                    if radio.get_label() == name:
                        radio.set_active(True)
                        break
                self.emit('default-changed', self._search_dict[name])

    def get_all(self):
        """ Return the dict of search engines.

        """

        return self._search_dict

    def get_default(self):
        """ Return the default.

        """

        return self._search_dict.get(self._default_name,
                                     'https://startpage.com/do/search?query=%s')
    def get_default_name(self):
        """ Return the default name.

        """

        return self._default_name

    def _radio_toggled(self, radio_button: object):
        """ Emit if radio_button is active.

        """

        if radio_button.get_active():
            name = radio_button.get_label()
            if name in self._search_dict:
                self._default_name = name
                self.emit('default-changed', self._search_dict[name])


class AgentSettings(Gtk.Grid):
    """ User Agent list and settings.

    """

    __gsignals__ = {
            'changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str, str)),
            'default-changed': (GObject.SIGNAL_RUN_LAST, None,
                               (str,)),
            'added': (GObject.SIGNAL_RUN_LAST, None,
                         (str, str)),
            'removed': (GObject.SIGNAL_RUN_LAST, None,
                               (str, str)),
            }

    def __init__(self, agent_dict: dict, parent: object = None):
        """ Create a list for configuring agent engines.

        """

        super(AgentSettings, self).__init__()

        self._parent = parent

        self._last_radio = None
        self._agent_dict = agent_dict
        self._default_name = ''

        self._agent_list = Gtk.ListBox()
        self._agent_list.set_vexpand(True)
        self._agent_list.set_hexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._agent_list)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-add-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        add_button = Gtk.Button()
        add_button.set_tooltip_text('Add New User Agent')
        add_button.set_image(button_img)
        add_button.set_relief(Gtk.ReliefStyle.NONE)
        add_button.connect('clicked', self._add_clicked)

        button_grid = Gtk.Grid()
        button_grid.attach(add_button, 0, 0, 1, 1)

        main_grid = Gtk.Grid()
        main_grid.set_column_spacing(6)
        main_grid.set_row_homogeneous(False)
        main_grid.attach(scroll, 0, 0, 1, 8)
        main_grid.attach(button_grid, 1, 0, 1, 1)
        main_grid.set_margin_bottom(6)
        main_grid.set_margin_top(6)
        main_grid.set_margin_start(6)
        main_grid.set_margin_end(6)

        frame_label = Gtk.Label('<b>User Agent Settings</b>')
        frame_label.set_use_markup(True)

        frame = Gtk.Frame()
        frame.set_margin_start(3)
        frame.set_label_widget(frame_label)
        frame.add(main_grid)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.show_all()

        self.set_size_request(-1, 150)
        self.attach(frame, 0, 0, 1, 1)

        self.show_all()

        for name, uri in sorted(agent_dict.items()):
            self.add_agent(name, uri)

    def _add_clicked(self, button: object):
        """ Add a new agent engine.

        """

        name_dialog = EntryDialog('Add User Agent', 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title('Enter Name')
        name_dialog.set_uri_title('Enter User Agent String')
        result = name_dialog.run()
        if not result: return None

        self.add_agent(result['name'], result['uri'])
        self.emit('added', result['name'], result['uri'])

    def add_agent(self, name: str, uri: str):
        """ Add a agent engine to the agent_list.

        """

        self._agent_dict[name] = uri

        radio_button = Gtk.RadioButton.new(None)
        radio_button.set_label(name)
        radio_button.connect('toggled', self._radio_toggled)
        radio_button.set_hexpand(True)
        radio_button.join_group(self._last_radio)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('text-editor-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        edit_button = Gtk.Button()
        edit_button.set_tooltip_text('Edit User Agent')
        edit_button.set_image(button_img)
        edit_button.set_relief(Gtk.ReliefStyle.NONE)

        icon = Gio.ThemedIcon.new_with_default_fallbacks('list-remove-symbolic')
        button_img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)

        remove_button = Gtk.Button()
        remove_button.set_margin_end(6)
        remove_button.set_tooltip_text('Remove User Agent')
        remove_button.set_image(button_img)
        remove_button.set_relief(Gtk.ReliefStyle.NONE)

        button_grid = Gtk.Grid()
        button_grid.attach(radio_button, 0, 0, 1, 1)
        button_grid.attach(edit_button, 1, 0, 1, 1)
        button_grid.attach(remove_button, 2, 0, 1, 1)
        button_grid.show_all()

        self._last_radio = radio_button

        self._agent_list.add(button_grid)
        remove_button.connect('clicked', self._remove_clicked, button_grid,
                              radio_button)
        edit_button.connect('clicked', self._edit_clicked, radio_button)

    def _remove_clicked(self, remove_button: object, grid: object,
                        radio_button: object):
        """ Remove this engine from the list.

        """

        name = radio_button.get_label()
        uri = self._agent_dict.pop(name, None)

        self._agent_list.remove(grid.get_parent())

        if self._last_radio == radio_button:
            for button in radio_button.get_group():
                if button != radio_button:
                    self._last_radio = button
                    break
            else:
                self._last_radio = None

        # Remove from group.
        radio_button.join_group(None)

        if self._default_name == name:
            if self._last_radio:
                self.set_default(self._last_radio.get_label())
        self.emit('removed', name, uri)

    def _edit_clicked(self, button: object, radio_button: object):
        """ Remove this engine from the list.

        """

        name = radio_button.get_label()
        uri = self._agent_dict.pop(name)

        name_dialog = EntryDialog('Edit User Agent', 'list-add-symbolic',
                                  parent=self._parent, show_uri=True)
        name_dialog.set_name_title('Edit Name')
        name_dialog.set_default_name(name)
        name_dialog.set_uri_title('Edit User Agent String')
        name_dialog.set_default_uri(uri)
        result = name_dialog.run()
        if not result: return None

        self._agent_dict[result['name']] = result['uri']
        radio_button.set_label(result['name'])
        if self._default_name == name:
            self.set_default(result['name'])
        self.emit('changed', name, result['name'], result['uri'])

    def set_default(self, name: str):
        """ Set the default agent engine.

        """

        if self._last_radio:
            if name in self._agent_dict:
                self._default_name = name
                for radio in self._last_radio.get_group():
                    if radio.get_label() == name:
                        radio.set_active(True)
                        break
                self.emit('default-changed', self._agent_dict[name])

    def get_all(self):
        """ Return the dict of agent engines.

        """

        return self._agent_dict

    def get_default(self):
        """ Return the default.

        """

        return self._agent_dict.get(self._default_name,
                                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/49.0.2623.110 Safari/537.36')
    def get_default_name(self):
        """ Return the default name.

        """

        return self._default_name

    def _radio_toggled(self, radio_button: object):
        """ Emit if radio_button is active.

        """

        if radio_button.get_active():
            name = radio_button.get_label()
            if name in self._agent_dict:
                self._default_name = name
                self.emit('default-changed', self._agent_dict[name])



