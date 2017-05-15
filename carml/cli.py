from __future__ import absolute_import

import sys

from twisted.internet import defer, task
from twisted.internet.endpoints import clientFromString
from twisted.python.failure import Failure

import click
import txtorcon

from . import carml_check_pypi
from . import carml_stream
from . import carml_events
from . import carml_circ
from . import carml_cmd
from . import carml_monitor
from . import carml_newid
from . import carml_pastebin


LOG_LEVELS = ["DEBUG", "INFO", "NOTICE", "WARN", "ERR"]


class Config(object):
    '''
    Passed as the Click object (@pass_obj) to all CLI methods.
    '''


@click.group()
@click.option('--timestamps', '-t', help='Prepend timestamps to each line.', is_flag=True)
@click.option('--no-color', '-n', help='Same as --color=no.', is_flag=True, default=None)
@click.option('--info', '-i', help='Show version of Tor we connect to (on stderr).', is_flag=True)
@click.option('--quiet', '-q', help='Some commands show less information with this option.', is_flag=True)
@click.option('--debug', '-d', help='Debug; print stack traces on error.', is_flag=True)
@click.option(
    '--password', '-p',
    help=('Password to authenticate to Tor with. Using cookie-based authentication'
          'is much easier if you are on the same machine.'),
    default=None,
    required=False,
)
@click.option(
    '--connect', '-c',
    default='tcp:host=127.0.0.1:port=9051',
    help=('Where to connect to Tor. This accepts any Twisted client endpoint '
          'string, or an ip:port pair. Examples: "tcp:localhost:9151" or '
          '"unix:/var/run/tor/control".'),
    metavar='ENDPOINT',
)
@click.option(
    '--color', '-C',
    type=click.Choice(['auto', 'no', 'always']),
    default='auto',
    help='Colourize output using ANSI commands.',
)
@click.pass_context
def carml(ctx, timestamps, no_color, info, quiet, debug, password, connect, color):
    if (color == 'always' and no_color) or \
       (color == 'no' and no_color is True):
        raise click.UsageError(
            "--no-color={} but --color={}".format(no_color, color)
        )

    cfg = Config()
    ctx.obj = cfg

    cfg.timestamps = timestamps
    cfg.no_color = no_color
    cfg.info = info
    cfg.quiet = quiet
    cfg.debug = debug
    cfg.password = password
    cfg.connect = connect
    cfg.color = color


def _run_command(cmd, cfg, *args, **kwargs):

    @defer.inlineCallbacks
    def _startup(reactor):
        ep = clientFromString(reactor, cfg.connect)
        tor = yield txtorcon.connect(reactor, ep)

        if cfg.info:
            info = yield tor.proto.get_info('version', 'status/version/current', 'dormant')
            click.echo(
                'Connected to a Tor version "{version}" (status: '
                '{status/version/current}).\n'.format(**info)
            )
        yield defer.maybeDeferred(
            cmd, reactor, cfg, tor, *args, **kwargs
        )

    from twisted.internet import reactor
    codes = [0]

    def _the_bad_stuff(f):
        print("Error: {}".format(f.value))
        if cfg.debug:
            print(f.getTraceback())
        codes[0] = 1
        return None

    def _go():
        d = _startup(reactor)
        d.addErrback(_the_bad_stuff)
        d.addBoth(lambda _: reactor.stop())

    reactor.callWhenRunning(_go)
    reactor.run()
    sys.exit(codes[0])


@carml.command()
@click.option(
    '--package', '-p',
    help='Name of the package to check (unfortunately, case matters)',
    required=True,
)
@click.option(
    '--revision', '-r',
    help='Specific version to check (default: latest)',
    default=None,
)
@click.pass_obj
def check_pypi(cfg, package, revision):
    """
    Check a PyPI package hash across multiple circuits.
    """
    return _run_command(
        carml_check_pypi.run,
        cfg, package, revision,
    )

@carml.command()
@click.option(
    '--if-unused', '-u',
    help='When deleting, pass the IfUnused flag to Tor.',
    is_flag=True,
)
@click.option(
    '--verbose',
    help='More information per circuit.',
    is_flag=True,
)
@click.option(
    '--list', '-L',
    help='List existing circuits.',
    is_flag=True,
    default=None,
)
@click.option(
    '--build', '-b',
    help=('Build a new circuit, given a comma-separated list of router names or'
          ' IDs. Use "auto" to let Tor select the route.'),
    default=None,
)
@click.option(
    '--delete',
    help='Delete a circuit by its ID.',
    default=None,
    multiple=True,
    type=int,
)
@click.pass_obj
def circ(cfg, if_unused, verbose, list, build, delete):
    """
    Manipulate Tor circuits.
    """
    if len([o for o in [list, build, delete] if o]) != 1:
        raise click.UsageError(
            "Specify just one of --list, --build or --delete"
        )
    return _run_command(
        carml_circ.run,
        cfg, if_unused, verbose, list, build, delete,
    )


@carml.command()
@click.argument(
    "command_args",
    nargs=-1,
)
@click.pass_obj
def cmd(cfg, command_args):
    """
    Run the rest of the args as a Tor control command. For example
    "GETCONF SocksPort" or "GETINFO net/listeners/socks".
    """
    return _run_command(
        carml_cmd.run,
        cfg, command_args,
    )


@carml.command()
@click.option(
    '--list', '-L',
    help='Show available events.',
    is_flag=True,
)
@click.option(
    '--once',
    help='Output exactly one and quit (same as -n 1 or --count=1).',
    is_flag=True,
)
@click.option(
    '--show-event', '-s',
    help='Prefix each line with the event it is from.',
    is_flag=True,
)
@click.option(
    '--count', '-n',
    help='Output this many events, and quit (default is unlimited).',
    type=int,
)
@click.argument(
    "events",
    nargs=-1,
)
@click.pass_obj
def events(cfg, list, once, show_event, count, events):
    """
    Follow any Tor events, listed as positional arguments.
    """
    if len(events) < 1 and not list:
        raise click.UsageError(
            "Must specify at least one event"
        )
    return _run_command(
        carml_events.run,
        cfg, list, once, show_event, count, events,
    )


@carml.command()
@click.option(
    '--list', '-L',
    help='List existing streams.',
    is_flag=True,
)
@click.option(
    '--follow', '-f',
    help='Follow stream creation.',
    is_flag=True,
)
@click.option(
    '--attach', '-a',
    help='Attach all new streams to a particular circuit-id.',
    type=int,
    default=None,
)
@click.option(
    '--close', '-d',
    help='Delete/close a stream by its ID.',
    type=int,
    default=None,
)
@click.option(
    '--verbose', '-v',
    help='Show more details.',
    is_flag=True,
)
@click.pass_context
def stream(ctx, list, follow, attach, close, verbose):
    """
    Manipulate Tor streams.
    """
    cfg = ctx.obj
    if len([x for x in [list, follow, attach, close] if x]) != 1:
        click.echo(ctx.get_help())
        raise click.UsageError(
            "Must specify one of --list, --follow, --attach or --close"
        )
    return _run_command(
        carml_stream.run,
        cfg, list, follow, attach, close, verbose,
    )


@carml.command()
@click.option(
    '--once', '-o',
    help='Exit after printing the current state.',
    is_flag=True,
)
@click.option(
    '--no-streams', '-s',
    help='Without this, list Tor streams.',
    is_flag=True,
)
@click.option(
    '--no-circuits', '-c',
    help='Without this, list Tor circuits.',
    is_flag=True,
)
@click.option(
    '--no-addr', '-a',
    help='Without this, list address mappings (and expirations, with -f).',
    is_flag=True,
)
@click.option(
    '--no-guards', '-g',
    help='Without this, Information about your current Guards.',
    is_flag=True,
)
@click.option(
    '--verbose', '-v',
    help='Additional information. Circuits: ip, location, asn, country-code.',
    is_flag=True,
)
@click.option(
    '--log-level', '-l',
    default=[],
    type=click.Choice(LOG_LEVELS),
    multiple=True,
)
@click.pass_context
def monitor(ctx, verbose, no_guards, no_addr, no_circuits, no_streams, once, log_level):
    """
    General information about a running Tor; streams, circuits,
    address-maps and event monitoring.
    """
    cfg = ctx.obj
    return _run_command(
        carml_monitor.run,
        cfg, verbose, no_guards, no_addr, no_circuits, no_streams, once, log_level,
    )


@carml.command()
@click.pass_context
def newid(ctx):
    """
    Ask Tor for a new identity via NEWNYM, and listen for the response
    acknowledgement.
    """
    cfg = ctx.obj
    return _run_command(
        carml_newid.run,
        cfg,
    )


@carml.command()
@click.option(
    '--dry-run', '-d',
    help='Test locally; no Tor launch.',
    is_flag=True,
)
@click.option(
    '--once',
    help='Same as --count=1.',
    is_flag=True,
)
@click.option(
    '--file', '-f',
    default=sys.stdin,
    type=click.File('rb'),
    help='Filename to use as input (instead of stdin)',
)
@click.option(
    '--count', '-n',
    default=None,
    help='Number of requests to serve.',
    type=int,
)
@click.option(
    '--keys', '-k',
    default=0,
    help='Number of authentication keys to create.',
    type=int,
)
@click.pass_context
def pastebin(ctx, dry_run, once, file, count, keys):
    """
    Put stdin (or a file) on a fresh hidden-service easily.
    """
    if count is not None and count < 0:
        raise click.UsageError(
            "--count must be positive"
        )
    if once and count is not None:
        raise click.UsageError(
            "Only specify one of --count or --once"
        )

    cfg = ctx.obj
    return _run_command(
        carml_pastebin.run,
        cfg, dry_run, once, file, count, keys,
    )