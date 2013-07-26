#
# Class that exposes the command line functionality
#
# Author: Gregory Fleischer (gfleischer@gmail.com)
#
# Copyright (c) 2013 RAFT Team
#
# This file is part of RAFT.
#
# RAFT is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# RAFT is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with RAFT.  If not, see <http://www.gnu.org/licenses/>.
#
import sys
import argparse
import os

from lib.parsers.burpparse import burp_parse_log, burp_parse_state, burp_parse_xml, burp_parse_vuln_xml
from lib.parsers.webscarabparse import webscarab_parse_conversation
from lib.parsers.parosparse import paros_parse_message
from lib.parsers.raftparse import raft_parse_xml, ParseAdapter
from lib.parsers.appscanparse import appscan_parse_xml

from raft import __version__

class RaftCmdLine():
    # TODO: refactor this definition to be shared with importers
    FILE_PROCESSOR_DEFINTIONS = {
        'raft_capture_xml' : raft_parse_xml,
        'burp_log' : burp_parse_log,
        'burp_xml' : burp_parse_xml,
        'burp_vuln_xml' : burp_parse_vuln_xml,
        'burp_state' : burp_parse_state,
        'appscan_xml' : appscan_parse_xml,
        'webscarab' : webscarab_parse_conversation,
        'paros_message' : paros_parse_message,
        }
    def __init__(self):
        self.scripts = {}

    def process_args(self, args):

        do_create = getattr(args, 'create')
        do_import = getattr(args, 'import')
        do_parse = getattr(args, 'parse')

        # was DB file specified?
        db_filename = getattr(args, 'db')
        if db_filename is not None:
            if not db_filename.endswith('.raftdb'):
                db_filename += '.raftdb'

            if not os.path.exists(db_filename) and not do_create:
                sys.stderr.write('\nDB file [%s] does not exist\n' % (db_filename))
                return 1

        # setup any capture filters
        self.capture_filter_scripts = []
        arg = getattr(args, 'capture_filter')
        if arg is not None:
            for filearg in arg:
                self.capture_filter_scripts.append(self.load_script_file(filearg))

        # setup any capture filters
        self.process_capture_scripts = []
        arg = getattr(args, 'process_capture')
        if arg is not None:
            for filearg in arg:
                self.process_capture_scripts.append(self.load_script_file(filearg))

        if do_import:
            pass
        elif do_parse:
            self.run_parse_process_loop(args)
        else:
            sys.stderr.write('\nNo recognized options\n')

        return 0

    def run_parse_process_loop(self, args):
        for name, func in self.FILE_PROCESSOR_DEFINTIONS.items():
            arg = getattr(args, name)
            if arg is None:
                continue
            for filearg in arg:
                if '*' in filearg:
                    file_list = glob.glob(filearg)
                elif os.path.exists(filearg):
                    file_list = [filearg]
                for filename in file_list:
                    self.parse_one_file(filename, func)

    def parse_one_file(self, filename, func):
        adapter = ParseAdapter()
        sys.stderr.write('processing [%s]\n' % (filename))
        filters = []
        processors = []
        for key, script_env in self.scripts.items():
            script_env['initialized'] = False
        for script_env in self.capture_filter_scripts:
            initializer = script_env['functions'].get('initialize')
            if initializer and not script_env['initialized']:
                initializer(filename)
                script_env['initialized'] = True
            capture_filter = script_env['functions'].get('capture_filter')
            if capture_filter:
                filters.append(capture_filter)
        for script_env in self.process_capture_scripts:
            initializer = script_env['functions'].get('initialize')
            if initializer and not script_env['initialized']:
                initializer(filename)
                script_env['initialized'] = True
            process_capture = script_env['functions'].get('process_capture')
            if process_capture:
                processors.append(process_capture)
        try:
            for result in func(filename):
                capture = adapter.adapt(result)
                skip = False
                for capture_filter in filters:
                    result = capture_filter(capture)
                    if not result:
                        skip = True
                        break
                if not skip:
                    for processor in processors:
                        result = processor(capture)

        except Exception as error:
            print(error)
            # TODO: should continue(?)
            raise error

    def load_script_file(self, filename):
        if filename in self.scripts:
            return self.scripts[filename]
        python_code = open(filename, 'rb').read()
        script_env = {
            'filename' : filename,
            'valid' : True,
            'initialized' : False,
            'instance': False,
            'functions' : {},
            'global_ns' : {},
            'local_ns' : {}
            }
        try:
            compiled = compile(python_code, '<string>', 'exec')
            exec(compiled, script_env['global_ns'], script_env['local_ns'])
            for key in script_env['local_ns']:
                value = script_env['local_ns'][key]
                if str(type(value)) == "<class 'type'>":
                    instance = value()
                    script_env['instance'] = instance
                    for item in dir(instance):
                        if not item.startswith('_'):
                            itemvalue = getattr(instance, item)
                            if str(type(itemvalue)) == "<class 'method'>":
                                script_env['functions'][item] = itemvalue
                elif str(type(value)) == "<class 'function'>":
                    script_env['functions'][key] = value

        except Exception as error:
            print(error)
            raise

        self.scripts[filename] = script_env
        return script_env

def main():
    sys.stdout.write('\nRaftCmdLine - version: %s\n' %  (__version__))

    parser = argparse.ArgumentParser(description='Run RAFT processing from command line')
    parser.add_argument('--db', nargs='?', help='Specify a RAFT database file')
    parser.add_argument('--create', action='store_const', const=True, default=False, help='Create the database (if needed)')
    parser.add_argument('--import', action='store_const', const=True, default=False, help='Import list of files into database')
    parser.add_argument('--parse', action='store_const', const=True, default=False, help='Parse list of files and run processing')
    parser.add_argument('--capture-filter', nargs='*', help='A Python file with a function or single class containing: "capture_filter"')
    parser.add_argument('--process-capture', nargs='*', help='A Python file with a function or single class containing: "process_capture"')
    parser.add_argument('--raft-capture-xml', nargs='*', help='A list of RAFT xml captgure files')
    parser.add_argument('--burp-log', nargs='*', help='A list of Burp log files')
    parser.add_argument('--burp-xml', nargs='*', help='A list of Burp XML files')
    parser.add_argument('--burp-vuln-xml', nargs='*', help='A list of Burp vulnerability report in XML format')
    parser.add_argument('--burp-state', nargs='*', help='A list of Burp saved state files')
    parser.add_argument('--appscan-xml', nargs='*', help='A list of AppScan XML report files')
    parser.add_argument('--webscarab', nargs='*', help='A list of WebScarab locations')
    parser.add_argument('--paros-message', nargs='*', help='A list of Paros message files')

    args = parser.parse_args()

    raftCmdLine = RaftCmdLine()
    raftCmdLine.process_args(args)

if '__main__' == __name__:
    main()
