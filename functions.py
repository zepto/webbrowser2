#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Functions
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


""" Functions used by both the socket process and the plug.

"""

from gi import require_version as gi_require_version
gi_require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
import pathlib
import logging


def looks_like_uri(test_text: str):
    """ Test test_text and returns true if it looks like a uri.  Otherwise
    return False.

    """

    if not test_text.startswith(('http://', 'https://', 'ftp://',
                                    'file://', 'mailto:', 'javascript:',
                                    'about:blank')):
        if ' ' in test_text or '.' not in test_text or not test_text:
            return False

    return True


def get_config_path(profile: str = 'default'):
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


def save_dialog(filename: str, folder: str, parent: object,
                title: str = 'Save File') -> str:
    """ Presents a file chooser dialog and returns a filename and folder tuple.

    """

    dialog = Gtk.FileChooserDialog(title, parent, Gtk.FileChooserAction.SAVE,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.ACCEPT))
    dialog.set_do_overwrite_confirmation(True)
    dialog.set_current_name(filename)
    dialog.set_current_folder(folder)
    response = dialog.run()
    if response == Gtk.ResponseType.ACCEPT:
        result = dialog.get_filename()
    else:
        result = ''
    dialog.destroy()
    return result
