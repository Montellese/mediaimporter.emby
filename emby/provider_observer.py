#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
from six import string_types
from six.moves.urllib.parse import urlparse, urlunparse
import websocket

import xbmc  # pylint: disable=import-error
import xbmcgui  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

from emby.api.library import Library
from emby import constants
from emby.server import Server

from lib import kodi
from lib.utils import localise, log, mediaImport2str, mediaProvider2str, Url


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
        self._settings = None
        self._server = None
        self._websocket = None

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
            ProviderObserver.log('media import {} from {} updated'
                                 .format(mediaImport2str(mediaImport), mediaProvider2str(self._mediaProvider)))
        else:
            # otherwise add the import to the list
            self._imports.append(mediaImport)
            ProviderObserver.log('media import {} from {} added'
                                 .format(mediaImport2str(mediaImport), mediaProvider2str(self._mediaProvider)))

    def RemoveImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('invalid mediaImport')

        # look for a matching import
        matchingImportIndices = self._FindImportIndices(mediaImport)
        if not matchingImportIndices:
            return

        # remove the media import from the list
        del self._imports[matchingImportIndices[0]]
        ProviderObserver.log('media import {} from {} removed'
                             .format(mediaImport2str(mediaImport), mediaProvider2str(self._mediaProvider)))

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

        return [i for i, x in enumerate(self._imports)
                if x.getPath() == mediaImport.getPath() and x.getMediaTypes() == mediaImport.getMediaTypes()]

    def _ProcessActions(self):
        for (action, data) in self._actions:
            if action == ProviderObserver.Action.Start:
                self._StartAction(data)
            elif action == ProviderObserver.Action.Stop:
                self._StopAction()
            else:
                ProviderObserver.log('unknown action {} to process'.format(action), xbmc.LOGWARNING)

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
                    ProviderObserver.log('invalid JSON message ({}) from {} received: {}'
                                         .format(len(message), mediaProvider2str(self._mediaProvider), message),
                                         xbmc.LOGWARNING)
                    continue

                self._ProcessMessage(messageObj)

            except websocket.WebSocketTimeoutException:
                break
            except Exception as error:
                ProviderObserver.log('unknown exception when receiving data from {}: {}'
                                     .format(mediaProvider2str(self._mediaProvider), error.args[0]), xbmc.LOGWARNING)
                break

    def _ProcessMessage(self, messageObj):
        if not messageObj:
            return

        if constants.WS_MESSAGE_TYPE not in messageObj:
            ProviderObserver.log('message without "{}" received from {}'
                                 .format(constants.WS_MESSAGE_TYPE, mediaProvider2str(self._mediaProvider)),
                                 xbmc.LOGWARNING)
            return
        if constants.WS_DATA not in messageObj:
            ProviderObserver.log('message without "{}" received from {}'
                                 .format(constants.WS_DATA, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
            return

        messageType = messageObj[constants.WS_MESSAGE_TYPE]
        data = messageObj[constants.WS_DATA]

        if messageType == constants.WS_MESSAGE_TYPE_LIBRARY_CHANGED:
            self._ProcessMessageLibraryChanged(data)
        elif messageType == constants.WS_MESSAGE_TYPE_USER_DATA_CHANGED:
            self._ProcessMessageUserDataChanged(data)
        elif messageType in (constants.WS_MESSAGE_TYPE_SERVER_SHUTTING_DOWN,
                             constants.WS_MESSAGE_TYPE_SERVER_RESTARTING):
            self._ProcessMessageServer(messageType)
        else:
            ProviderObserver.log('ignoring "{}" message from {}'
                                 .format(messageType, mediaProvider2str(self._mediaProvider)), xbmc.LOGDEBUG)

    def _ProcessMessageLibraryChanged(self, data):
        ProviderObserver.log('processing library changed message from {}...'
                             .format(mediaProvider2str(self._mediaProvider)))

        itemsAdded = data[constants.WS_LIBRARY_CHANGED_ITEMS_ADDED]
        itemsUpdated = data[constants.WS_LIBRARY_CHANGED_ITEMS_UPDATED]
        itemsRemoved = data[constants.WS_LIBRARY_CHANGED_ITEMS_REMOVED]

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
            if changesetType in \
               (xbmcmediaimport.MediaImportChangesetTypeAdded, xbmcmediaimport.MediaImportChangesetTypeChanged):
                # get all details for the added / changed item
                item = self._GetItemDetails(itemId)
                if not item:
                    ProviderObserver.log('failed to get details for changed item with id "{}" from {}'
                                         .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                    continue
            else:
                # find the removed item in the list of imported items
                importedItems = xbmcmediaimport.getImportedItemsByProvider(self._mediaProvider)
                matchingItems = [importedItem for importedItem in importedItems
                                 if kodi.Api.getEmbyItemIdFromItem(importedItem) == itemId]
                if not matchingItems:
                    ProviderObserver.log('failed to find removed item with id "{}" from {}'
                                         .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                    continue
                if len(matchingItems) > 1:
                    ProviderObserver.log('multiple imported items for item with id "{}" from {} found '
                                         '=> only removing the first one'
                                         .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)

                item = matchingItems[0]

            if not item:
                ProviderObserver.log('failed to process changed item with id "{}" from {}'
                                     .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                continue

            changedItems.append((changesetType, item, itemId))

        self._ChangeItems(changedItems)

    @staticmethod
    def _ProcessChangedItems(items, changesetType):
        if not isinstance(items, list):
            return []

        return [(changesetType, item) for item in items if isinstance(item, string_types) and item]

    def _ProcessMessageUserDataChanged(self, data):
        ProviderObserver.log('processing userdata changed message from {}...'
                             .format(mediaProvider2str(self._mediaProvider)))

        userDataList = data[constants.WS_USER_DATA_CHANGED_USER_DATA_LIST]

        changedItems = []
        for userDataItem in userDataList:
            if constants.WS_USER_DATA_CHANGED_USER_DATA_ITEM_ID not in userDataItem:
                continue

            itemId = userDataItem[constants.WS_USER_DATA_CHANGED_USER_DATA_ITEM_ID]
            if not itemId or not isinstance(itemId, string_types):
                continue

            item = self._GetItemDetails(itemId)
            if not item:
                ProviderObserver.log('failed to get details for changed item with id "{}" from {}'
                                     .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                continue

            changedItems.append((xbmcmediaimport.MediaImportChangesetTypeChanged, item, itemId))

        self._ChangeItems(changedItems)

    def _ProcessMessageServer(self, messageType):
        if not self._settings.getBool(constants.SETTING_PROVIDER_INTERFACE_SHOW_SERVER_MESSAGES):
            return

        if messageType == constants.WS_MESSAGE_TYPE_SERVER_SHUTTING_DOWN:
            message = 32051
        elif messageType == constants.WS_MESSAGE_TYPE_SERVER_RESTARTING:
            message = 32052
        else:
            return

        xbmcgui.Dialog().notification('Emby Media Importer',
                                      localise(message).format(self._mediaProvider.getFriendlyName()),
                                      self._mediaProvider.getIconUrl())

    def _ChangeItems(self, items):
        # map the changed items to their media import
        changedItemsMap = {}
        for (changesetType, item, itemId) in items:
            if not item:
                continue

            # find a matching import for the changed item
            mediaImport = self._FindImportForItem(item)
            if not mediaImport:
                ProviderObserver.log('failed to determine media import for changed item with id "{}" from {}'
                                     .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                continue

            if mediaImport not in changedItemsMap:
                changedItemsMap[mediaImport] = []

            changedItemsMap[mediaImport].append((changesetType, item))

        # finally pass the changed items grouped by their media import to Kodi
        for (mediaImport, changedItems) in changedItemsMap.items():
            if xbmcmediaimport.changeImportedItems(mediaImport, changedItems):
                ProviderObserver.log('changed {} imported items for media import {} from {}'
                                     .format(len(changedItems), mediaImport2str(mediaImport),
                                             mediaProvider2str(self._mediaProvider)))
            else:
                ProviderObserver.log('failed to change {} imported items for media import {} from {}'
                                     .format(len(changedItems), mediaImport2str(mediaImport),
                                             mediaProvider2str(self._mediaProvider)),
                                     xbmc.LOGWARNING)

    def _GetItemDetails(self, itemId):
        # retrieve all details of the item
        itemObj = Library.GetItem(self._server, itemId)
        if not itemObj:
            ProviderObserver.log('cannot retrieve details of updated item with id "{}" from {}'
                                 .format(itemId, mediaProvider2str(self._mediaProvider)), xbmc.LOGERROR)
            return None

        return kodi.Api.toFileItem(
            self._server, itemObj,
            allowDirectPlay=self._settings.getBool(constants.SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY))

    def _FindImportForItem(self, item):
        videoInfoTag = item.getVideoInfoTag()
        if not videoInfoTag:
            return None

        itemMediaType = videoInfoTag.getMediaType()

        matchingImports = [mediaImport for mediaImport in self._imports
                           if itemMediaType in mediaImport.getMediaTypes()]
        if not matchingImports:
            return None

        return matchingImports[0]

    def _StartAction(self, mediaProvider):
        if not mediaProvider:
            raise RuntimeError('invalid mediaProvider')

        # if we are already connected check if something important changed in the media provider
        if self._connected:
            if kodi.Api.compareMediaProviders(self._mediaProvider, mediaProvider):
                # update the media provider and settings anyway
                self._mediaProvider = mediaProvider
                self._settings = self._mediaProvider.prepareSettings()
                return True

        self._StopAction(restart=True)

        self._mediaProvider = mediaProvider

        self._settings = self._mediaProvider.prepareSettings()
        if not self._settings:
            raise RuntimeError('cannot prepare media provider settings')

        try:
            # create emby server instance
            self._server = Server(self._mediaProvider)

            # authenticate with the Emby server
            authenticated = self._server.Authenticate(force=True)
        except:
            authenticated = False

        if not authenticated:
            ProviderObserver.log('failed to authenticate with {}'.format(mediaProvider2str(self._mediaProvider)),
                                 xbmc.LOGERROR)
            self._Reset()
            return False

        # analyze the media provider's URL
        urlParts = urlparse(self._server.Url())
        # determine the proper scheme (ws:// or wss://) and whether or not to verify the HTTPS certificate
        websocketScheme = 'wss' if urlParts.scheme == 'https' else 'ws'
        # put the urL back together
        url = urlunparse(urlParts._replace(scheme=websocketScheme, path='embywebsocket'))
        url = Url.addOptions(url, {
            constants.URL_QUERY_API_KEY: self._server.AccessToken(),
            constants.URL_QUERY_DEVICE_ID: self._server.DeviceId()
        })

        # create the websocket
        self._websocket = websocket.WebSocket()

        # connect the websocket
        try:
            self._websocket.connect(url)
        except Exception as err:
            ProviderObserver.log('failed to connect to {} using a websocket. {}'.format(url, err), xbmc.LOGERROR)
            self._Reset()
            return False

        # reduce the timeout
        self._websocket.settimeout(1.0)

        ProviderObserver.log('successfully connected to {} to observe media imports'
                             .format(mediaProvider2str(self._mediaProvider)))
        self._connected = True
        return True

    def _StopAction(self, restart=False):
        if not self._connected:
            return

        if not restart:
            ProviderObserver.log('stopped observing media imports from {}'
                                 .format(mediaProvider2str(self._mediaProvider)))

        self._websocket.close()
        self._Reset()

    def _Reset(self):
        self._connected = False
        self._server = None
        self._mediaProvider = None

    @staticmethod
    def log(message, level=xbmc.LOGINFO):
        log('[observer] {}'.format(message), level)
