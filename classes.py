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
from gi.repository import Gtk, GObject, GLib
import pathlib
import logging
import socket
from json import loads as json_loads
from json import dumps as json_dumps


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
            try:
                item = super(ChildDict, self).__getitem__(key)
            except KeyError:
                item = None

        return item

    def __getattr__(self, item: str):
        """ Return the item from the dictionary.

        """

        return self.__getitem__(item)

    def __setattr__(self, item: str, data: object):
        """ Put data in self[item]

        """

        self.__setitem__(item.replace('_', '-', item.count('_')), data)


class Config(dict):
    """ A configuration dictionary that writes to a file in xdg-config
    directory.

    """

    def __init__(self, profile: str = 'default'):
        """ Load the config from filename.

        """

        super(Config, self).__init__()

        self._socket = None

        self._config_path = self.get_config_path(profile)
        self._config_file = self._config_path.joinpath('config.json')

        with pathlib.Path(self._config_file) as config_file:
            if config_file.is_file():
                self.update(json_loads(config_file.read_text()))

        self._socket_file = self._config_path.joinpath(__name__ + '.sock')
        self.sessions_file = self._config_path.joinpath('sessions.json')
        self.bookmarks_file = str(self._config_path.joinpath('bookmarks.xbel'))

    def get_config_path(self, profile: str = 'default'):
        """ Returns the path to the config files.  If it doesn't exist it is
        created.

        """

        xdg_config = pathlib.Path(GLib.get_user_config_dir())
        config_path = xdg_config.joinpath('webbrowser2').joinpath(profile)
        with pathlib.Path(config_path) as conf_path:
            if not conf_path.exists():
                conf_path.mkdir()
            elif not conf_path.is_dir():
                logging.error("Can't Save Config")
                return ''
        return config_path

    def save_config(self):
        """ Save the config to a file.

        """

        with pathlib.Path(self._config_file) as config_file:
            config_file.write_text(json_dumps(self, indent=4))

    def open_socket(self, uri_list: list) -> object:
        """ Open and return a socket.

        """

        if self._socket_file.is_socket():
            try:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._socket.connect(bytes(self._socket_file))
                self._socket.send(json_dumps(('new-tab', uri_list)).encode())
                self._socket.close()
                return None
            except ConnectionRefusedError:
                self._socket_file.unlink()

        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.bind(bytes(self._socket_file))

        return self._socket

    def close_socket(self):
        """ Close the socket.

        """

        self._socket.close()
        self._socket_file.unlink()


class SettingsMenu(Gtk.Menu):
    """ A settings menu.

    """

    __gsignals__ = {
            'setting-changed': (GObject.SIGNAL_RUN_LAST, None,
                                (str, bool)),
            }

    def __init__(self, config: dict):
        """ Build and initialize the menu.

        """

        super(SettingsMenu, self).__init__()

        self._config = config

        self._build_menu(self, config)

        self.show_all()

    def _build_menu(self, base: object, config: dict) -> object:
        """ Build and return a menu config.

        """

        for setting, value in sorted(config.items()):
            if value not in [True, False]:
                submenu = Gtk.Menu()
                self._build_menu(submenu, value)
                item = Gtk.MenuItem(setting)
                item.set_submenu(submenu)
                base.append(item)
                continue
            item_title = setting.replace('-', ' ', setting.count('-'))
            menu_item = Gtk.CheckMenuItem.new_with_label(item_title.title())
            menu_item.connect('toggled', self._settings_toggled, setting)
            menu_item.set_active(value)
            base.append(menu_item)

    def _settings_toggled(self, item: object, setting: str):
        """ Emit the setting and the value.

        """

        self._config[setting] = item.get_active()
        self.emit('setting-changed', setting, item.get_active())

    def get_config(self):
        """ Return the config state.

        """

        return self._config

class SettingsPopover(Gtk.Popover):
    """ The Settings and session popover.

    """

    def __init__(self):
        """ Init.

        """

        super(SettingsPopover, self).__init__()
