#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
from six import ensure_str
import time

from emby import constants
from emby.request import Request
from emby import server

import lib.semantic_version as semantic_version
from lib.utils import log

class Server:
    class Info:
        EMBY_SERVER = 'Emby Server'
        JELLYFIN_SERVER = 'Jellyfin Server'

        def __init__(self, id, name, version, product=None):
            if not id:
                raise ValueError('invalid id')

            self.id = id
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
               not constants.PROPERTY_SYSTEM_INFO_ID in response or \
               not constants.PROPERTY_SYSTEM_INFO_SERVER_NAME in response or \
               not constants.PROPERTY_SYSTEM_INFO_VERSION in response:
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
