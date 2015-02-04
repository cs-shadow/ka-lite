from docutils import nodes
from docutils.parsers.rst.directives.images import Image
from docutils.parsers.rst import Directive
import docutils.parsers.rst.directives as directives

import os
import uuid
import json

from exceptions import NotImplementedError
from errors import ActionError
from errors import OptionError

from selenium.webdriver.common.keys import Keys

SCREENSHOT_COMMAND = "python ../kalite/manage.py screenshots"
SCREENSHOT_COMMAND_OPTS = " --no-del -v 0 --from-str '%s' --output-dir %s"
OUTPUT_PATH = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)),"_build","html","_images"))

def setup(app):
    app.add_directive('screenshot', Screenshot)
    app.connect('env-purge-doc', purge_screenshots)
    app.connect('env-updated', process_screenshots)

def purge_screenshots(app, env, docname):
    if not hasattr(env, 'screenshot_all_screenshots'):
        return
    env.screenshot_all_screenshots = [s for s in env.screenshot_all_screenshots
                          if s['docname'] != docname]

def process_screenshots(app, env):
    all_args = map(lambda x: x['from_str_arg'], env.screenshot_all_screenshots)
    os.system(SCREENSHOT_COMMAND + SCREENSHOT_COMMAND_OPTS % (json.dumps(all_args), OUTPUT_PATH))

def _parse_focus(arg_str):
    """ Returns id and annotation after splitting input string.

    First argument should be the id. An optional annotation can follow.
    Everything after an initial space will be considered the annotation.
    """
    split_str = arg_str.split(' ', 1)
    if len(split_str) == 1:
        return {'id': split_str[0], 'annotation': ''}
    else:
        return {'id': split_str[0], 'annotation': split_str[1]}

def _parse_command(command):
    """" Parses a command into action and options.

    Returns a dictionary with following keys:
       selector (string): the selector to identify the element
       action (string): the action type (if it's recognized)
       options (list): a list of options

    Raises an error if action type is not recognized or if options are invalid.
    """
    command_args = command.split()
    if not command_args:
        return None
    else:
        selector = command_args[0]
        action = command_args[1]
        options = command_args[2:]

    if action not in ('click', 'send_keys', 'submit', ''):
        raise ActionError(action)

    # Validate input options for the specified action.
    if action == 'click' or action == 'submit':
        if options:
            raise OptionError("The action '%s' must not contain any arguments whereas supplied arguments: '%s'." % (action, repr(options)))

    return {'selector': selector, 'action': action, 'options': options}

def _parse_login(username, password, submit=""):
    """" Parses a LOGIN command.

    Returns a dictionary with following keys:
       runhandler (string):  "_login_handler".
       args (dict) : A dictionary of arguments with following keys:
         username (string):  the username.
         password (string): password.
         submit (bool): True if login form is to be submitted, false otherwise.
    """
    submit_bool = True if submit == "submit" else False
    args = {'username': username, 'password': password, 'submit': submit_bool}
    return {'runhandler': '_login_handler', 'args': args}

def _parse_nav_steps(arg_str):
    """ Here's how to specify the navigation steps:

        1. selector action [options] ["|" selector action [options]] ...
        2. aliased_action_sequence [options]

        selector will identify the element... for now we'll just implement
            selection by id e.g. "#username-field"
            "NEXT", which just sends a tab keystroke
            "SAME", which just stays focused on the element from the last action
        Where action could be one of "click", "send_keys", or "submit":
            click has no options and just clicks the element
            send_keys sends a sequence of keystrokes specified as a string by options
                (potentially with special characters representing tab, enter, etc.)
            submit submits a form and has no options
        Multiple actions on a page can be specified by putting a | separator,
            and specifying the action using the same syntax.

        aliased_action_sequence is one of a reserved keyword which aliases a common
            sequence of actions as above (or performs special actions unavailable by
            the regular syntax) potentially with options. Available aliases:

            LOGIN username password [submit], which just navigates to the login page
                and inputs the given username and password. Submits the form is submit
                is present, otherwise not.

        Returns a dictionary with:
            runhandler: reference to function invoked in the run method
            args:       a dictionary of arguments passed to the runhandler function
    """
    # The alias with its parse function
    ALIASES = [("LOGIN", _parse_login)]

    # First check if we've been passed an aliased_action_sequence
    words = arg_str.split(' ')
    for e in ALIASES:
        if words[0] == e[0]:
            return e[1](*words[1:])

    commands = arg_str.split('|')
    parsed_commands = reduce(lambda x,y: x+[y] if y else x, map(_parse_command, commands), [])
    runhandler = "_command_handler"
    return { "runhandler":  runhandler,
             "args":        {'commands': parsed_commands}}

def _parse_user_role(arg_str):
    if arg_str in ["guest", "coach", "admin", "learner"]:
        return arg_str
    else:
        raise NotImplementedError("Unrecognized user-role: %s" % arg_str)

class Screenshot(Image):
    """ Provides directive to include screenshot based on given options.

    Since it inherits from the Image directive, it can take Image options.
    """
    required_arguments = 0
    optional_arguments = 0
    has_content = False

    #########################################################
    # Handlers will be invoked in the run method should     #
    # both return appropriate nodes and spawn a process     #
    # to generate the screenshot (once the script is ready).#
    #########################################################
    def _login_handler(self, username, password, submit):
        from_str_arg = { "users": ["guest"], # This will fail if not guest, because of a redirect
                         "slug": "",
                         "start_url": "/securesync/login",
                         "inputs": [{"#id_username":username},
                                    {"#id_password":password},
                                   ],
                         "pages": [],
                         "notes": [],
                       }
        if submit:
            from_str_arg["inputs"].append({"<submit>":""})
        from_str_arg["inputs"].append({"<slug>":self.filename})
        # Trying to import django.core.management.call_command gets you into some sort of import hell
        # Apparently due to a circular import, according to Ben Bach.
        self.env.screenshot_all_screenshots.append({
            'docname':  self.env.docname,
            'from_str_arg': from_str_arg,
        })
        self.arguments.append(os.path.join("_images", self.filename+".png"))
        (image_node,) = Image.run(self)
        return image_node

    def _command_handler(self, commands):
        if not self.url:
            raise NotImplementedError("Please supply a url using the :url: option")
        from_str_arg = { "users": [self.user_role],
                         "slug": "",
                         "start_url": self.url,
                         "pages": [],
                         "notes": [],
                       }        
        from_str_arg['inputs'] = reduce(lambda x,y: x+y, map(_cmd_to_inputs, commands), [])
        from_str_arg["inputs"].append({"<slug>":self.filename})
        self.env.screenshot_all_screenshots.append({
            'docname':  self.env.docname,
            'from_str_arg': from_str_arg,
        })
        self.arguments.append(os.path.join("_images", self.filename+".png"))
        (image_node,) = Image.run(self)
        return image_node

    # Add options to the image directive.
    option_spec = Image.option_spec.copy()
    option_spec['url'] = directives.unchanged
    option_spec['user-role'] = _parse_user_role
    option_spec['navigation-steps'] = _parse_nav_steps
    option_spec['focus'] = _parse_focus

    def run(self):
        """ Returns list of nodes to appended as screenshot.

        Language xx can be set in conf.py or by:
        make SPHINXOPTS="-D language=xx" html
        Build language can be accessed from the BuildEnvironment.
        """
        # sphinx.environment.BuildEnvironment
        self.env = self.state.document.settings.env
        language = self.env.config.language
        return_nodes = []
        if not hasattr(self.env, 'screenshot_all_screenshots'):
            self.env.screenshot_all_screenshots = []

        if len(self.arguments) == 1:
            (image_node,) = Image.run(self)
            return_nodes.append(image_node)

        if 'focus' in self.options:
            # Again, this has to be handled by the runhandler... so assign it to an instance variable
            pass

        if 'user-role' in self.options:
            self.user_role = self.options['user-role']
        else:
            self.user_role = "guest"

        if 'url' in self.options:
            self.url = self.options['url']

        if 'navigation-steps' in self.options:
            self.filename = uuid.uuid4().__str__()
            runhandler = self.options['navigation-steps']['runhandler']
            args = self.options['navigation-steps']['args']
            return_nodes.append(getattr(self, runhandler)(**args))

        return return_nodes


# Implementation-specific functions for the screenshots management command
def _specialkeys(k):
    if k=="TAB":
        return Keys.TAB
    elif k=="ENTER":
        return Keys.ENTER
    elif k=="BACKSPACE":
        return Keys.BACKSPACE
    else:
        return k

def _cmd_to_inputs(cmd):
    inputs = []
    if cmd['selector'] == 'NEXT':
        sel = ""
        inputs.append({"": Keys.TAB})
    elif cmd['selector'] == 'SAME':
        sel = ""
    else:
        sel = cmd['selector']
    if cmd['action']=='click':
        inputs.append({sel: ""})
    elif cmd['action']=='submit':
        inputs.append({"<submit>": ""})
    elif cmd['action']=='send_keys':
        inputs.append({sel: ' '.join(map(_specialkeys,cmd['options']))})
    return inputs
