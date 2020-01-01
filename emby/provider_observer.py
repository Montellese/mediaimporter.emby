#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
from six.moves.urllib.parse import urlparse, urlunparse

import xbmc
import xbmcmediaimport

from emby.api import Api
from emby.constants import *
from emby.server import Server

import lib.websocket
from lib.utils import log, mediaImport2str, mediaProvider2str, Url

class ProviderObserver:
    class Action:
        Start = 0
        Stop = 1

    def __init__(self):
        # default values
        self._actions = []
        self._connected = False
        self._imports = []
        self._mediaProvider = None
        self._server = None

        # create the websocket
        self._websocket = lib.websocket.WebSocket()
        self._websocket.settimeout(0.1)

    def __del__(self):
        self._StopAction()

    def AddImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        # if a matching import has been found update it
        if matchingImportIndices:
            self._imports[matchingImportIndices[0]] = mediaImport
            log('media import {} updated'.format(mediaImport2str(mediaImport)))
        else:
            # otherwise add the import to the list
            self._imports.append(mediaImport)
            log('media import {} added'.format(mediaImport2str(mediaImport)))

    def RemoveImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        if not matchingImportIndices:
            return

        # remove the media import from the list
        del self._imports[matchingImportIndices[0]]
        log('media import {} removed'.format(mediaImport2str(mediaImport)))

    def Start(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        self._actions.append((ProviderObserver.Action.Start, mediaProvider))

    def Stop(self):
        self._actions.append((ProviderObserver.Action.Stop, None))

    def Process(self):
        # process any open actions
        self._ProcessActions()
        # process any incoming messages
        self._ProcessMessages()

    def _FindImportIndices(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        return [ i for i, x in enumerate(self._imports) if x.getPath() == mediaImport.getPath() and x.getMediaTypes() == mediaImport.getMediaTypes() ]

    def _ProcessActions(self):
        for (action, data) in self._actions:
            if action == ProviderObserver.Action.Start:
                self._StartAction(data)
            elif action == ProviderObserver.Action.Stop:
                self._StopAction()
            else:
                log('unknown action {} to process'.format(action), xbmc.LOGWARNING)

        self._actions = []

    def _ProcessMessages(self):
        # nothing to do if we are not connected to an Emby server
        if not self._connected:
            return

        while True:
            try:
                message = self._websocket.recv()
                if message is None:
                    break

                messageObj = json.loads(message)
                if not messageObj:
                    log('invalid JSON message ({}) from {} received: {}'.format(len(message), mediaProvider2str(self._mediaProvider), message), xbmc.LOGWARNING)
                    continue

                self._ProcessMessage(messageObj)

            except lib.websocket.WebSocketTimeoutException:
                break
            except Exception as error:
                log('unknown exception when receiving data from {}: {}'.format(mediaProvider2str(self._mediaProvider), error.args[0]), xbmc.LOGWARNING)
                break

    def _ProcessMessage(self, messageObj):
        if not messageObj:
            return

        if not WS_MESSAGE_TYPE in messageObj:
            log('message without "{}" received from {}'.format(WS_MESSAGE_TYPE, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
            return
        if not WS_DATA in messageObj:
            log('message without "{}" received from {}'.format(WS_DATA, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
            return

        messageType = messageObj[WS_MESSAGE_TYPE]
        data = messageObj[WS_DATA]

        if messageType == WS_MESSAGE_TYPE_LIBRARY_CHANGED:
            self._ProcessMessageLibraryChanged(data)
        elif messageType == WS_MESSAGE_TYPE_USER_DATA_CHANGED:
            self._ProcessMessageUserDataChanged(data)
        else:
            log('ignoring "{}" message from {}'.format(messageType, mediaProvider2str(self._mediaProvider)), xbmc.LOGDEBUG)

    def _ProcessMessageLibraryChanged(self, data):
        itemsAdded = data[WS_LIBRARY_CHANGED_ITEMS_ADDED]
        itemsUpdated = data[WS_LIBRARY_CHANGED_ITEMS_UPDATED]
        itemsRemoved = data[WS_LIBRARY_CHANGED_ITEMS_REMOVED]

        changedLibraryItems = []

        # process all newly added items
        changedLibraryItems.extend(
            ProviderObserver._ProcessChangedItems(itemsAdded, xbmcmediaimport.MediaImportChangesetTypeAdded))

        # process all updated items
        changedLibraryItems.extend(
            ProviderObserver._ProcessChangedItems(itemsUpdated, xbmcmediaimport.MediaImportChangesetTypeChanged))

        # process all removed items
        changedLibraryItems.extend(
            ProviderObserver._ProcessChangedItems(itemsRemoved, xbmcmediaimport.MediaImportChangesetTypeRemoved))

        # map the changed items to their media import
        changedItems = []
        for (changesetType, itemId) in changedLibraryItems:
            item = None
            if changesetType == xbmcmediaimport.MediaImportChangesetTypeAdded or \
               changesetType == xbmcmediaimport.MediaImportChangesetTypeChanged:
                # get all details for the added / changed item
                item = self._GetItemDetails(itemId)
                if not item:
                    log('failed to get details for changed item with id "{}"'.format(itemId), xbmc.LOGWARNING)
                    continue
            else:
                # find the removed item in the list of imported items
                importedItems = xbmcmediaimport.getImportedItemsByProvider(self._mediaProvider)
                matchingItems = [ importedItem for importedItem in importedItems if importedItem.getUniqueID(EMBY_PROTOCOL) == itemId ]
                if not matchingItems:
                    log('failed to find removed item with id "{}"'.format(itemId), xbmc.LOGWARNING)
                    continue
                if len(matchingItems) > 1:
                    log('multiple imported items for item with id "{}" found => only removing the first one'.format(itemId), xbmc.LOGWARNING)

                item = matchingItems[0]

            if not item:
                log('failed to process changed item with id "{}"'.format(itemId), xbmc.LOGWARNING)
                continue

            changedItems.append((changesetType, item, itemId))

        self._ChangeItems(changedItems)

    @staticmethod
    def _ProcessChangedItems(items, changesetType):
        if not isinstance(items, list):
            return []

        return [(changesetType, item) for item in items if isinstance(item, basestring) and item]

    def _ProcessMessageUserDataChanged(self, data):
        userDataList = data[WS_USER_DATA_CHANGED_USER_DATA_LIST]

        changedItems = []
        for userDataItem in userDataList:
            if not WS_USER_DATA_CHANGED_USER_DATA_ITEM_ID in userDataItem:
                continue

            itemId = userDataItem[WS_USER_DATA_CHANGED_USER_DATA_ITEM_ID]
            if not itemId or not isinstance(itemId, basestring):
                continue

            item = self._GetItemDetails(itemId)
            if not item:
                log('failed to get details for changed item with id "{}"'.format(itemId), xbmc.LOGWARNING)
                continue

            changedItems.append((xbmcmediaimport.MediaImportChangesetTypeChanged, item, itemId))

        self._ChangeItems(changedItems)

    def _ChangeItems(self, changedItems):
         # map the changed items to their media import
        changedItemsMap = {}
        for (changesetType, item, itemId) in changedItems:
            if not item:
                continue

            # find a matching import for the changed item
            mediaImport = self._FindImportForItem(item)
            if not mediaImport:
                log('failed to determine media import for changed item with id "{}"'.format(itemId), xbmc.LOGWARNING)
                continue

            if mediaImport not in changedItemsMap:
                changedItemsMap[mediaImport] = []

            changedItemsMap[mediaImport].append((changesetType, item))

        # finally pass the changed items grouped by their media import to Kodi
        for (mediaImport, changedItems) in changedItemsMap.items():
            if xbmcmediaimport.changeImportedItems(mediaImport, changedItems):
                log('changed {} imported items for media import {}'.format(len(changedItems), mediaImport2str(mediaImport)))
            else:
                log('failed to change {} imported items for media import {}'.format(len(changedItems), mediaImport2str(mediaImport)), xbmc.LOGWARNING)

    def _GetItemDetails(self, itemId):
        # get the URL to retrieve all details of the item from the Emby server
        getItemUrl = self._server.BuildUserItemUrl(itemId)

        # retrieve all details of the item
        itemObj = self._server.ApiGet(getItemUrl)
        if not itemObj:
            log('cannot retrieve details of updated item with id "{}"'.format(itemId), xbmc.LOGERROR)
            return None

        return Api.toFileItem(self._server, itemObj)

    def _FindImportForItem(self, item):
        videoInfoTag = item.getVideoInfoTag()
        if not videoInfoTag:
            return None

        itemMediaType = videoInfoTag.getMediaType()

        matchingImports = [ mediaImport for mediaImport in self._imports if itemMediaType in mediaImport.getMediaTypes() ]
        if not matchingImports:
            return None

        return matchingImports[0]

    def _StartAction(self, mediaProvider):
        if not mediaProvider:
            raise RuntimeError('invalid mediaProvider')

        # if we are already connected check if something important changed in the media provider
        if self._connected:
            if Api.compareMediaProviders(self._mediaProvider, mediaProvider):
                return True

        self._StopAction(restart=True)

        self._mediaProvider = mediaProvider

        settings = self._mediaProvider.prepareSettings()
        if not settings:
            raise RuntimeError('cannot prepare media provider settings')

        try:
            # create emby server instance
            self._server = Server(self._mediaProvider)

            # authenticate with the Emby server
            authenticated = self._server.Authenticate()
        except:
            authenticated = False

        if not authenticated:
            log('failed to authenticate with {}'.format(mediaProvider2str(self._mediaProvider)), xbmc.LOGERROR)
            self._Reset()
            return False

        # prepare the URL
        urlParts = urlparse(self._mediaProvider.getBasePath())
        url = urlunparse(urlParts._replace(scheme='ws', path='embywebsocket'))
        url = Url.addOptions(url, {
            'api_key': self._server.AccessToken(),
            'deviceId': self._server.DeviceId()
        })

        # connect the websocket
        try:
            self._websocket.connect(url)
        except:
            log('failed to connect to {} using a websocket'.format(url), xbmc.LOGERROR)
            self._Reset()
            return False

        log('successfully connected to {} to observe media imports'.format(mediaProvider2str(self._mediaProvider)))
        self._connected = True
        return True

    def _StopAction(self, restart=False):
        if not self._connected:
            return

        if not restart:
            log('stopped observing media imports from {}'.format(mediaProvider2str(self._mediaProvider)))

        self._websocket.close()
        self._Reset()

    def _Reset(self):
        self._connected = False
        self._server = None
        self._mediaProvider = None
