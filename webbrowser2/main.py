#!/usr/bin/env python
# vim: sw=4:ts=4:sts=4:fdm=indent:fdl=0:
# -*- coding: UTF8 -*-
#
# Main browser process
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


""" Main browser process

"""

from multiprocessing import Process, Manager, Pipe, active_children
import logging


def run_browser(data: object):
    """ Runs a browser.

    """

    from plug_process import BrowserProc
    browser = BrowserProc(data)
    browser.run()


def run_main(com_pipe: object, **kwargs):
    """ Runs a main.

    """

    from socket_process import MainWindow
    main_window = MainWindow(com_pipe, **kwargs)
    main_window.run()


def main(main_proc: object, main_cpipe: object):
    """ Listen on main_cpipe for signals.  Depending on what signal is recieved
    it will start new child processes.

    """

    window_dict = {}

    while main_proc.is_alive():
        try:
            signal, data = main_cpipe.recv()
        except KeyboardInterrupt:
            break

        if signal == 'quit':
            break
        if signal == 'refresh':
            # Make sure all children exit.
            logging.info('\n'.join([f'PID: {t.pid} of {t}' for t in active_children()]))
            for pid, proc in window_dict.items():
                logging.info(f'PROCESS: {pid}')
        if signal == 'new-proc':
            proc = Process(target=run_browser, args=(data,))
            proc.start()
            main_cpipe.send(('proc-pid', proc.pid))
            logging.info(f"MAIN_LOOP NEW_PROC: {data}")
            window_dict[proc.pid] = proc
            logging.info(f"child pid: {proc.pid}")
            logging.info(f'window_dict: {window_dict}')

        elif signal == 'terminate':
            proc = window_dict.pop(data, None)
            if proc:
                logging.info(f'Joining pid: {data}')
                proc.join(1)
                if proc.is_alive():
                    logging.info(f"Terminating: {proc}")
                    proc.terminate()

    logging.info("Quitting")

    logging.info(window_dict)
    for pid, proc in window_dict.items():
        logging.info(f"Joining: {proc}")
        proc.join(1)
        if proc.is_alive():
            logging.info(f"Terminating: {proc}")
            proc.terminate()

    # Make sure all children exit.
    active_children()

    return


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Webkit2 Web Browser")
    parser.add_argument('-p', '--profile', action='store', default='default',
                        help='The profile to use', dest='profile')
    parser.add_argument('-v', '--verbose', action='store', default=1, type=int,
                        help='How verbose to be', dest='verbosity')
    parser.add_argument('uri', nargs='*', default=['about:blank'])
    args, leftovers = parser.parse_known_args()

    if args.verbosity == 0:
        verbosity = 'CRITICAL'
    elif args.verbosity == 1:
        verbosity = 'ERROR'
    elif args.verbosity == 2:
        verbosity = 'INFO'
    elif args.verbosity == 3:
        verbosity = 'DEBUG'

    logging.basicConfig(format='\033[0;35m%(asctime)s\033[0m:\033[0;34m%(levelname)s\033[0m:%(message)s',
                        level=verbosity, datefmt='%a %h %d %T')

    main_cpipe, main_ppipe = Pipe()

    # main_p = Process(target=main, args=(main_cpipe, main_dict))
    main_p = Process(target=run_main, args=(main_ppipe,),
                     kwargs={'profile': args.profile, 'uri_list': args.uri})
    main_p.start()
    logging.info(f"main pid: {main_p.pid}")

    main(main_p, main_cpipe)

    # from socket_process import MainWindow
    # main = MainWindow(main_ppipe, main_dict, profile=args.profile,
    #                   uri=args.uri)
    # main.run()

    main_p.join(1)
    if main_p.is_alive():
        logging.info(f"Terminating main: {main_p.pid}")
        main_p.terminate()
    main_ppipe.close()
    main_cpipe.close()
