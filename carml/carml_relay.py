from __future__ import print_function

import sys
import datetime
import functools
import random

from twisted.python import usage, log
from twisted.internet import defer, reactor, endpoints
import zope.interface
import humanize
import txtorcon

from carml import util


@defer.inlineCallbacks
def _print_router_info(router, agent=None):
    # loc = yield router.get_location()
    loc = yield router.location
    print("            name: {}".format(router.name))
    print("          hex id: {}".format(router.id_hex))
    print("        location: {}".format(loc.countrycode))
    print("         address: {}:{} (DirPort={})".format(router.ip, router.or_port, router.dir_port))
    diff = datetime.datetime.utcnow() - router.modified
    print("  last published: {} ago".format(humanize.naturaldelta(diff)))
    if agent:
        print(util.colors.italic("Extended information from" + util.colors.green(" onionoo.torproject.org") + ":"))
        details = yield router.get_onionoo_details(agent)
        details.setdefault('dir_address', '<none>')
        details['or_addresses'] = ', '.join(details.get('or_addresses', []))
        print(
            "        platform: {platform}\n"
            "        runnning: {running}\n"
            "     dir_address: {dir_address}\n"
            "    OR addresses: {or_addresses}\n"
            "        location: {city_name}, {region_name}, {country_name}\n"
            "       host name: {host_name}\n"
            "              AS: {as_number} ({as_name})\n"
            "  last restarted: {last_restarted}\n"
            "    last changed: {last_changed_address_or_port}\n"
            "       last seen: {last_seen}\n"
            "   probabilities: guard={guard_probability} middle={middle_probability} exit={exit_probability}\n"
            "".format(**details)
        )


@defer.inlineCallbacks
def router_info(state, arg, tor):
    if len(arg) == 40 and not arg.startswith('$'):
        arg = '${}'.format(arg)

    try:
        relay = state.routers[arg]
    except KeyError:
        candidates = [
            r for r in state.all_routers
            if arg in r.name or arg in r.id_hex
        ]
        if not candidates:
            print("Nothing found ({} routers total)".format(len(state.all_routers)))
        if len(candidates) > 1:
            print("Found multiple routers:")
        for router in candidates:
            yield _print_router_info(router)
            print()
    else:
        yield _print_router_info(relay, agent=tor.web_agent())


def _when_updated(state):
    d = defer.Deferred()

    def _newconsensus(doc):
        # we actually don't care what's *in* the event, we just know
        # that the state has now updated...maybe a .when_updated() in
        # TorState?
        print("Got NEWCONSENSUS at {}".format(datetime.datetime.now()))
        d.callback(None)
        state.protocol.remove_event_listener('NEWCONSENSUS', _newconsensus)
    state.protocol.add_event_listener('NEWCONSENSUS', _newconsensus)
    return d


@defer.inlineCallbacks
def _await_router(state, router_id):
    while True:
        yield _when_updated(state)
        try:
            defer.returnValue(state.routers[router_id])
            return
        except KeyError:
            continue


@defer.inlineCallbacks
def router_await(state, arg):
    if len(arg) == 40 and not arg.startswith('$'):
        arg = '${}'.format(arg)
    if not arg.startswith('$') and len(arg) == 41:
        print("Doesn't appear to be a hex router ID")
        return

    if arg in state.routers:
        print("Router already present:")
        r = state.routers[arg]
    else:
        r = yield _await_router(state, arg)
    yield _print_router_info(r)


def router_list(state):
    for router in state.all_routers:
        print("{}".format(router.id_hex[1:]))


@defer.inlineCallbacks
def run(reactor, cfg, tor, list, info, await):
    state = yield tor.create_state()
    if info:
        yield router_info(state, info, tor)
    elif list:
        yield router_list(state)
    elif await:
        yield router_await(state, await)
