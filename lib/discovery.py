#!/usr/bin/python
# -*- coding: utf-8 -*-/*
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import socket

from six import iteritems

import xbmcmediaimport  # pylint: disable=import-error

import emby
from emby.server import Server

from lib import kodi
from lib.monitor import Monitor
from lib.utils import getIcon, log


class DiscoveryService:
    DiscoveryAddress = '255.255.255.255'
    DiscoveryPort = 7359
    DiscoveryMessage = b'who is EmbyServer?'
    DiscoveryTimeoutS = 1.0

    def __init__(self):
        self._monitor = Monitor()
        self._sock = None
        self._servers = {}

        self._start()

    def _discover(self):
        # broadcast the discovery message
        self._sock.sendto(DiscoveryService.DiscoveryMessage,
                          (DiscoveryService.DiscoveryAddress, DiscoveryService.DiscoveryPort))

        # try to receive an answer
        data = None
        try:
            self._sock.settimeout(DiscoveryService.DiscoveryTimeoutS)
            (data, _) = self._sock.recvfrom(1024)
        except socket.timeout:
            return

        if not data or data == DiscoveryService.DiscoveryMessage:
            return

        server = emby.api.server.Server.Discovery.fromString(data)
        if server is not None:
            self._addServer(server)

    def _addServer(self, server):
        registerServer = False

        # check if the server is already known
        if server.id not in self._servers:
            self._servers[server.id] = server
            registerServer = True
        else:
            # check if the server has already been registered or if some of its properties have changed
            if not self._servers[server.id].registered or self._servers[server.id].name != server.name or \
               self._servers[server.id].address != server.address:
                self._servers[server.id] = server
                registerServer = True
            else:
                # simply update the server's last seen property
                self._servers[server.id].lastseen = server.lastseen

        # if the server doesn't need to be registered there's nothing else to do
        if not registerServer:
            return

        providerId = Server.BuildProviderId(server.id)
        providerIconUrl = getIcon()
        mediaProvider = xbmcmediaimport.MediaProvider(providerId, server.address, server.name, providerIconUrl,
                                                      emby.constants.SUPPORTED_MEDIA_TYPES)

        if xbmcmediaimport.addAndActivateProvider(mediaProvider):
            self._servers[server.id].registered = True
            log('Emby server "{}" ({}) successfully added and activated'.format(server.name, server.id))
        else:
            self._servers[server.id].registered = False
            log('failed to add and/or activate Emby server "{}" ({})'.format(server.name, server.id))

    def _expireServers(self):
        for serverId, server in iteritems(self._servers):
            if not server.isExpired(10):
                continue

            server.registered = False
            xbmcmediaimport.deactivateProvider(serverId)
            log('Emby server "{}" ({}) deactivated due to inactivity'.format(server.name, server.id))

    def _start(self):
        log('Looking for Emby servers...')

        # setup the UDP broadcast socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('0.0.0.0', 0))

        while not self._monitor.abortRequested():
            # try to discover Emby servers
            self._discover()

            # expire Emby servers that haven't responded for a while
            self._expireServers()

            if self._monitor.waitForAbort(1):
                break

        self._sock.close()
