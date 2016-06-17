#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Build webbrowser2 package.
# Copyright (C) 2012 Josiah Gordon <josiahg@gmail.com>
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


""" Build webbrowser2 package.

"""

from distutils.core import setup

setup(
    name='webbrowser2',
    packages=['webbrowser2'],
    scripts=['scripts/webbrowser2'],
    version='1.0.0',
    description='Webkit2 webbrowser',
    long_description=open('README.mkd').read(),
    author='Josiah Gordon',
    author_email='josiahg@gmail.com',
    url='http://www.github.com/zepto/webbrowser2',
    download_url='http://www.github.com/zepto/webbrowser2/downloads',
    license='LICENSE.txt',
    keywords=['webkit2', 'webkit2gtk'],
    classifiers=[
        'Development Status :: 2 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License (GPL)',
        'Programming Language :: Python',
        'Natural Language :: English',
        'Operating System :: POSIX',
        'Environment :: X11 Applications ',
        'Topic :: Network ',
    ],
)
