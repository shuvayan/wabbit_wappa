"""
Wrapper for Vowpal Wabbit executable

TODO: 
-Unit tests.  Reproduce examples from wiki and from
    http://hunch.net/~vw/validate.html
-Documentation.  Use mkdocs and something like picnic to put
    this on PyPI in elegant style.
-Command line generation.  Beginner's mode for common scenarios
    (and a framework to build from).  Make up names for single-char
    args and those missing documentation (like -i and -f) and accept 
    short or long form.
-Performance testing.  How much time is spent in wappa vs. VW?
-Detect VW version in unit tests; for command line generation scenarios,
    unit tests should detect whether it works as expected.
-Scenario assistance; e.g. caching examples for reuse in multi-pass
    (This would make good example code also.)
    -Abstraction for passes (with automatic usage of example cache)
-Example for README: Alternate train and testing to show how regressor converges over time
-Example for README: Active learning interface
-Sklearn compatibility (like vowpal_porpoise)
-Vagrant that builds and installs dependencies (including VW) automatically
    Then run unit tests to verify install
-Use pexpect.which() to find executable automatically
-Handle echo mode introspectively.  Include unit test in which it's switched manually.
-Installable with pip




by Michael J.T. O'Kelly, 2014-2-24
"""

__author__ = "Michael J.T. O'Kelly"
__email__ = 'mokelly@gmail.com'
__version__ = '0.0.1'


import logging
import re

import pexpect


class WabbitInvalidCharacter(ValueError):
    pass


validation_regex = re.compile(r' |:|\|')

def validate_vw_string(s):
    """Throw a WabbitInvalidCharacter exception if the string is
    not a 
    (http://stats.stackexchange.com/questions/28877/finding-the-best-features-in-interaction-models)
    """
    if validation_regex.search(s):
        raise WabbitInvalidCharacter(s)


escape_dict = {' ': r'\_',
               ':': r'\;',
               '|': r'\\'
               }

def escape_vw_character(special_character_re_match):
    special_character = special_character_re_match.group()
    return escape_dict[special_character]


def escape_vw_string(s):
    escaped_s = validation_regex.sub(escape_vw_character, s)
    return escaped_s


class Namespace():
    """Abstraction of Namespace part of VW example lines"""
    def __init__(self,
                 name=None,
                 scale=None,
                 features=None,
                 escape=True,
                 validate=True,
                 cache_string=False):
        """Create a namespace with given (optional) name and importance,
        initialized with any given features (described in add_features()).
        If 'validate', name and features are validated for compatibility
            with VW's reserved characters, throwing a WabbitInvalidCharacter
            exception.
        If 'escape', any invalid characters are replaced with escape characters.
            ('escape' mode supersedes 'vaildate' mode.)
        If 'cache_string', the results of any to_string() call are cached
            permanently, ignoring any further changes to self.
        """
        self.name = name
        self.scale = scale
        self.validate = validate
        self.escape = escape
        self._string = None
        self.features = []
        if name:
            if escape:
                self.name = escape_vw_string(self.name)
            elif validate:
                validate_vw_string(self.name)
        if features:
            self.add_features(features)

    def add_features(self, features):
        """Add features to this namespace.
        features: An iterable of features.  A feature may be either
            1) A VW label (not containing characters from escape_dict.keys(),
                unless 'escape' mode is on)
            2) A tuple (label, value) where value is any float
        """
        for feature in features:
            if isinstance(feature, basestring):
                label = feature
                value = None
            else:
                label, value = feature
            self.add_feature(label, value)

    def add_feature(self, label, value=None):
        """
        label: A VW label (not containing characters from escape_dict.keys(),
            unless 'escape' mode is on)
        value: float giving the weight or magnitude of this feature
        """
        if self.escape:
            label = escape_vw_string(label)
        elif self.validate:
            validate_vw_string(label)
        feature = (label, value)
        self.features.append(feature)

    def to_string(self):
        """Export this namespace to a string suitable for incorporation
        in a VW example line, e.g.
        'MetricFeatures:3.28 height:1.5 length:2.0 '
        """
        if self._string is None:
            tokens = []
            if self.name:
                if self.scale:
                    token = self.name + ':' + str(self.scale)
                else:
                    token = self.name
            else:
                token = ''  # Spacing element to indicate next string is a feature
            tokens.append(token)
            for label, value in self.features:
                if value is None:
                    token = label
                else:
                    token = label + ':' + str(value)
                tokens.append(token)
            tokens.append('')  # Spacing element to separate from next pipe character
            output = ' '.join(tokens)
        else:
            output = self._string
        return output


class VW():
    """Wrapper for VW executable, handling online input and outputs."""
    def __init__(self, command, raw_output=False):
        """'command' is the full command-line necessary to run VW.  E.g.
        vw --loss_function logistic -p /dev/stdout --quiet
        -p /dev/stdout --quiet is mandatory for compatibility,
        and certain options like 
            --save_resume
        are suggested, while some options make no sense in this context:
            -d
            --passes
        wabbit_wappa.py does not support any mode that turns off piping to
        stdin or stdout

        raw_output: Instead of returning parsed float(s) as output, return
            the string literal.
        """
        self.vw_process = pexpect.spawn(command)
        # TODO: Use spawn(args=args) for more fine-grained control
        self.vw_process.delaybeforesend = 0
        logging.info("Started VW({})".format(command))
        self.output_pipe = None
        self.command = command
        self.namespaces = []
        self._line = None
        self.set_raw_output(raw_output)

    def send_line(self, line):
        """Submit a raw line of text to the VW instance, returning the result.
        """
        self.vw_process.sendline(line)  # Send line, along with newline
        result = self._get_response()
        return result

    def set_raw_output(self, raw_output):
        """Set the value of raw_output, which determines whether VW output
        is parsed into float(s) or returned literally."""
        self.raw_output = raw_output
        return self.raw_output

    def _get_response(self):
        self.vw_process.expect('\r\n')  # Wait until process outputs a complete line
        self.vw_process.expect('\r\n')  # Wait until process outputs a complete line twice
        # Grabbing two lines seems to be necessary because vw_process.getecho() is True
        output = self.vw_process.before
        if self.raw_output:
            result_value = output  # Return the output unchanged
        else:
            result_list = []
            # TODO: Something more robust than whitespace splitting
            #   to handle modes like --audit ?
            for token in output.split():
                try:
                    result = float(token)
                    result_list.append(result)
                except ValueError:
                    # Ignore tokens that can't be made into floats (like tags)
                    logging.debug("Ignoring non-float token {}".format(token))
            if len(result_list) == 1:
                result_value = result_list[0]
            elif len(result_list) > 1:
                result_value = result_list
            else:
                # If no floats were found, return the unparsed output
                # TODO: Should an exception be raised here instead?
                result_value = output
        return result_value

    def send_example(self,
                     *args,
                     **kwargs
                     ):
        line = self.make_line(*args, **kwargs)
        result = self.send_line(line)
        return result

    def make_line(self,
                  response=None,
                  importance=None,
                  base=None,
                  tag=None,
                  features=None,
                  namespaces=None,
                  ):
        if namespaces is not None:
            self.add_namespaces(namespaces)
        if features is not None:
            namespace = Namespace(features=features)
            self.add_namespace(namespace)
        substrings = []
        tokens = []
        if response is not None:
            token = str(response)
            tokens.append(token)
            if importance is not None:  # Check only if response is given
                token = str(importance)
                tokens.append(token)
                if base is not None:  # Check only if importance is given
                    token = str(base)
                    tokens.append(token)
        if tag is not None: 
            token = "'" + str(tag)  # Tags are unambiguous if given a ' prefix
            tokens.append(token)
        else:
            token = ""  # Spacing element to avoid ambiguity in parsing
            tokens.append(token)
        substring = ' '.join(tokens)
        substrings.append(substring)
        if self.namespaces:
            for namespace in self.namespaces:
                substring = namespace.to_string()
                substrings.append(substring)
        else:
            substrings.append('')  # For correct syntax
        line = '|'.join(substrings)
        self._line = line
        self.namespaces = []  # Reset namespaces after their use
        return line

    def add_namespace(self, *args, **kwargs):
        """Accepts two calling patterns:
        add_namespace(namespace): queue a preexisting namespace onto
            this VW instance.
        add_namespace(name, scale, features, ...): Pass all args and kwargs
            to the Namespace constructor to make a new Namespace instance,
            and queue it to this VW instance.

        Returns self (so that this command can be chained).
        """
        if args and isinstance(args[0], Namespace):
            namespace = args[0]
        elif isinstance(kwargs.get('namespace'), Namespace):
            namespace = kwargs.get('namespace')
        else:
            namespace = Namespace(*args, **kwargs)
        self.namespaces.append(namespace)
        return self

    def add_namespaces(self, namespaces):
        """Add these namespaces sequentially.
        Returns self (so that this command can be chained)."""
        for namespace in namespaces:
            self.add_namespace(namespace)
        return self

    def get_prediction(self, tag=None, namespaces=None):
        result = self.send_example(tag=tag, namespaces=namespaces)
        return result

    def save_model(self, model_filename):
        """Pass a "command example" to the VW subprocess requesting
        that the current model be serialized to model_filename immediately."""
        line = "save_{}|".format(model_filename)
        self.vw_process.sendline(line)
        self.vw_process.expect('\r\n')  # Wait until process outputs a complete line
        # Only the echo will be emitted as a result for this command
        result = self.vw_process.before
        return result

    def close(self):
        self.vw_process.close()
        # TODO: Give this a context manager interface

    # TODO: Fancy interface for auditing data?
