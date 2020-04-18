#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
import time

import semantic_version
from six import ensure_str

import xbmc  # pylint: disable=import-error

from emby import constants
from emby.request import Request
from emby import server

from lib.utils import log


class Server:
    class Discovery:
        def __init__(self):
            self.id = ''
            self.name = ''
            self.address = ''
            self.registered = False
            self.lastseen = None

        def isExpired(self, timeoutS):
            return self.registered and self.lastseen + timeoutS < time.time()

        @staticmethod
        def fromString(data):
            ServerPropertyId = 'Id'
            ServerPropertyName = 'Name'
            ServerPropertyAddress = 'Address'

            if data is None:
                return None

            data = ensure_str(data)

            obj = json.loads(data)
            if ServerPropertyId not in obj or ServerPropertyName not in obj or ServerPropertyAddress not in obj:
                log('invalid discovery message received: {}'.format(str(data)), xbmc.LOGWARNING)
                return None

            discoveryServer = Server.Discovery()
            discoveryServer.id = obj[ServerPropertyId]
            discoveryServer.name = obj[ServerPropertyName]
            discoveryServer.address = obj[ServerPropertyAddress]
            discoveryServer.registered = False
            discoveryServer.lastseen = time.time()

            if not discoveryServer.id or not discoveryServer.name or not discoveryServer.address:
                return None

            return discoveryServer

    class Info:
        EMBY_SERVER = 'Emby Server'
        JELLYFIN_SERVER = 'Jellyfin Server'

        def __init__(self, identifier, name, version, product=None):
            if not identifier:
                raise ValueError('invalid identifier')

            self.id = identifier
            self.name = name
            self.version = version
            self.product = product or Server.Info.EMBY_SERVER

        def isEmbyServer(self):
            return self.product == Server.Info.EMBY_SERVER

        def isJellyfinServer(self):
            return self.product == Server.Info.JELLYFIN_SERVER

        def isUnknown(self):
            return not self.isEmbyServer() and not self.isJellyfinServer()

        def supportsUserDataUpdates(self):
            # only Emby 4.3+ servers support the UserData update call
            return self.isEmbyServer() and self.version.major >= 4 and self.version.minor >= 3

        @staticmethod
        def fromPublicInfo(response):
            if not response or \
               constants.PROPERTY_SYSTEM_INFO_ID not in response or \
               constants.PROPERTY_SYSTEM_INFO_SERVER_NAME not in response or \
               constants.PROPERTY_SYSTEM_INFO_VERSION not in response:
                return None

            versions = response[constants.PROPERTY_SYSTEM_INFO_VERSION].split('.')
            productName = None
            if constants.PROPERTY_SYSTEM_INFO_PRODUCT_NAME in response:
                productName = response[constants.PROPERTY_SYSTEM_INFO_PRODUCT_NAME]

            return Server.Info(
                response[constants.PROPERTY_SYSTEM_INFO_ID],
                response[constants.PROPERTY_SYSTEM_INFO_SERVER_NAME],
                semantic_version.Version('.'.join(versions[0:3])),
                product=productName)

    @staticmethod
    def GetInfo(baseUrl):
        publicInfoUrl = server.Server.BuildPublicInfoUrl(baseUrl)
        headers = Request.PrepareApiCallHeaders()
        resultObj = Request.GetAsJson(publicInfoUrl, headers=headers)

        return Server.Info.fromPublicInfo(resultObj)
