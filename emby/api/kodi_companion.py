#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby.api.plugin import Plugin
from emby.api.server import Server

from lib.utils import Url

class KodiCompanion:
    NAMES = ('Emby.Kodi Sync Queue', 'Kodi Sync Queue', 'Kodi companion')

    @staticmethod
    def IsInstalled(embyServer):
        if not embyServer:
            raise ValueError('invalid embyServer')

        # retrieve all plugins
        plugins = Plugin.GetPlugins(embyServer)
        # look for the Kodi Companion plugin
        return any(plugin.name in KodiCompanion.NAMES for plugin in plugins)

    class SyncQueue:
        ENDPOINT_EMBY = 'Emby.Kodi.SyncQueue'
        ENDPOINT_JELLYFIN = 'Jellyfin.Plugin.KodiSyncQueue'
        ENDPOINT_GET_ITEMS = 'GetItems'

        QUERY_GET_ITEMS_LAST_UPDATE = 'LastUpdateDT'
        QUERY_GET_ITEMS_FILTER = 'filter'

        PROPERTY_GET_ITEMS_ADDED = 'ItemsAdded'
        PROPERTY_GET_ITEMS_UPDATED = 'ItemsUpdated'
        PROPERTY_GET_ITEMS_REMOVED = 'ItemsRemoved'
        PROPERTY_GET_ITEMS_USER_DATA_CHANGED = 'UserDataChanged'

        def __init__(self, itemsAdded=[], itemsUpdated=[], itemsRemoved=[], userDataChanged=[]):
            self.itemsAdded = itemsAdded
            self.itemsUpdated = itemsUpdated
            self.itemsRemoved = itemsRemoved
            self.userDataChanged = userDataChanged

        @staticmethod
        def GetItems(embyServer, date, filters=None):
            if not embyServer:
                raise ValueError('invalid embyServer')
            if not date:
                raise ValueError('invalid date')

            # determine the endpoint based on whether we are talking to an Emby or Jellyfin server
            endpoint = KodiCompanion.SyncQueue.ENDPOINT_EMBY
            serverInfo = Server.GetInfo(embyServer.Url())
            if serverInfo and serverInfo.isJellyfinServer():
                endpoint = KodiCompanion.SyncQueue.ENDPOINT_JELLYFIN

            # build the URL to retrieve the items from the sync queue
            url = embyServer.BuildUrl(endpoint)
            url = Url.append(url, embyServer.UserId(), KodiCompanion.SyncQueue.ENDPOINT_GET_ITEMS)
            url = Url.addOptions(url, {
                KodiCompanion.SyncQueue.QUERY_GET_ITEMS_LAST_UPDATE: date,
                KodiCompanion.SyncQueue.QUERY_GET_ITEMS_FILTER: filters
            })

            itemsObj = embyServer.ApiGet(url)
            if not itemsObj:
                return []

            itemsAdded = []
            itemsUpdated = []
            itemsRemoved = []
            userDataChanged = []
            if KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_ADDED in itemsObj:
                itemsAdded = itemsObj[KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_ADDED]
            if KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_UPDATED in itemsObj:
                itemsUpdated = itemsObj[KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_UPDATED]
            if KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_REMOVED in itemsObj:
                itemsRemoved = itemsObj[KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_REMOVED]
            if KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_USER_DATA_CHANGED in itemsObj:
                userDataChanged = itemsObj[KodiCompanion.SyncQueue.PROPERTY_GET_ITEMS_USER_DATA_CHANGED]

            return KodiCompanion.SyncQueue(itemsAdded=itemsAdded, itemsUpdated=itemsUpdated, itemsRemoved=itemsRemoved, userDataChanged=userDataChanged)
