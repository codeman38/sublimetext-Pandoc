# Copyright (c) 2012 Brian Fisher
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import sublime
import sublime_plugin
from collections import OrderedDict
import pprint
import re
import subprocess
import tempfile
import os


class PromptPandocCommand(sublime_plugin.WindowCommand):

    options = []

    def run(self):
        if self.window.active_view():
            self.window.show_quick_panel(
                self.transformations(),
                self.transform)

    def transformations(self):
        '''Generates a ranked list of available transformations.'''
        view = self.window.active_view()

        # hash of transformation ranks
        ranked = {}
        for label, settings in _s('transformations').items():
            for scope in settings['scope'].keys():
                score = view.score_selector(0, scope)
                if not score:
                    continue
                if label not in ranked or ranked[label] < score:
                    ranked[label] = score

        if not len(ranked):
            sublime.error_message(
                'No transformations configured for the syntax '
                + view.settings().get('syntax'))
            return

        # reverse sort
        self.options = list(OrderedDict(sorted(
            ranked.items(), key=lambda t: t[1])).keys())
        self.options.reverse()

        return self.options

    def transform(self, i):
        if i == -1:
            return
        transformation = _s('transformations')[self.options[i]]
        self.window.active_view().run_command('pandoc', {
            'transformation': transformation
        })


class PandocCommand(sublime_plugin.TextCommand):

    def run(self, edit, transformation):
        # string to work with
        region = sublime.Region(0, self.view.size())
        contents = self.view.substr(region)

        pandoc = _find_binary('pandoc', _s('pandoc-path'))
        if pandoc is None:
            return
        cmd = [pandoc]

        # from format
        score = 0
        for scope, c_iformat in transformation['scope'].items():
            c_score = self.view.score_selector(0, scope)
            if c_score <= score:
                continue
            score = c_score
            iformat = c_iformat
        cmd.extend(['-f', iformat])

        # configured parameters
        args = Args(transformation['pandoc-arguments'])

        # output format
        oformat = args.get(short=['t', 'w'], long=['to', 'write'])

        # pandoc doesn't actually take 'pdf' as an output format
        # see https://github.com/jgm/pandoc/issues/571
        if oformat == 'pdf':
            args = args.remove(
                short=['t', 'w'], long=['to', 'write'], values=['pdf'])

        # if write to file, add -o if necessary, set file path to output_path
        if oformat is not None and oformat in _s('pandoc-format-file'):
            output_path = args.get(short=['o'], long=['output'])
            if output_path is None:
                # note the file extension matches the pandoc format name
                output_path = tempfile.NamedTemporaryFile().name
                output_path += "." + oformat
                args.extend(['-o', output_path])

        cmd.extend(args)

        # run pandoc
        process = subprocess.Popen(
            cmd, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        result, error = process.communicate(contents.encode('utf-8'))

        if error:
            sublime.error_message('\n\n'.join([
                'Error when running:',
                ' '.join(cmd),
                error.decode('utf-8').strip()]))
            return
        else:
            print(' '.join(cmd))

        # if write to file, open
        if oformat is not None and oformat in _s('pandoc-format-file'):
            try:
                if sublime.platform() == 'osx':
                    subprocess.call(["open", output_path])
                elif sublime.platform() == 'windows':
                    os.startfile(output_path)
                elif os.name == 'posix':
                    subprocess.call(('xdg-open', output_path))
            except:
                sublime.message_dialog('Wrote to file ' + output_path)

        # write to buffer
        if result:
            if transformation['new-buffer']:
                w = self.view.window()
                w.new_file()
                view = w.active_view()
                region = sublime.Region(0, view.size())
            else:
                view = self.view
            view.replace(edit, region, result.decode('utf8'))
            view.set_syntax_file(transformation['syntax_file'])


def _find_binary(name, default=None):
    if default is not None:
        if os.path.exists(default):
            return default
        msg = 'configured path for {0} {1} not found.'.format(name, default)
        sublime.error_message(msg)
        return None

    for dirname in os.environ['PATH'].split(os.pathsep):
        path = os.path.join(dirname, name)
        if os.path.exists(path):
            return path

    sublime.error_message('Could not find pandoc executable on PATH.')
    return None


def _s(key):
    '''Convenience function for getting the setting dict.'''
    return merge_user_settings()[key]


def merge_user_settings():
    '''Return the default settings merged with the user's settings.'''

    settings = sublime.load_settings('Pandoc.sublime-settings')
    default = settings.get('default', {})
    user = settings.get('user', {})

    if user:

        # merge each transformation
        transformations = default.pop('transformations', {})
        user_transformations = user.get('transformations', {})
        for name, data in user_transformations.items():
            if name in transformations:
                transformations[name].update(data)
            else:
                transformations[name] = data
        default['transformations'] = transformations
        user.pop('transformations', None)

        # merge all other keys
        default.update(user)

    return default


def _c(item):
    '''Pretty prints item to console.'''
    pprint.PrettyPrinter().pprint(item)


class Args(list):
    '''Process Pandoc arguments.

    "short" are of the form "-k val""".
    "long" arguments are of the form "--key=val""".'''

    def get(self, short=None, long=None):
        '''Get the first value for a argument.'''
        value = None
        for arg in self:
            if short is not None:
                if value:
                    return arg
                match = re.search('^-(' + '|'.join(short) + ')$', arg)
                if match:
                    value = True  # grab the next arg
                    continue
            if long is not None:
                match = re.search('^--(' + '|'.join(long) + ')=(.+)$', arg)
                if match:
                    return match.group(2)
        return None

    def remove(self, short=None, long=None, values=None):
        '''Remove all matching arguments.'''
        ret = Args([])
        value = None
        for arg in self:
            if short is not None:
                if value:
                    if values is not None and arg not in values:
                        ret.append(arg)
                    value = None
                    continue
                match = re.search('^-(' + '|'.join(short) + ')$', arg)
                if match:
                    value = True  # grab the next arg
                    continue
            if long is not None:
                match = re.search('^--(' + '|'.join(long) + ')=(.+)$', arg)
                if match:
                    continue
            ret.append(arg)
        return ret
