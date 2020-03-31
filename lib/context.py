#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys

import xbmc
import xbmcmediaimport
from xbmcgui import Dialog

import emby
from emby.api.library import Library
from emby.server import Server
from lib import kodi
from lib.utils import localise, log, mediaProvider2str

class ContextAction:
        Play = 0

def listItem2str(item, itemId):
    return '"{}" ({})'.format(item.getLabel(), itemId)

def play(item, itemId, mediaProvider):
    if item.isFolder():
        log('[context/play] cannot play folder item {}'.format(listItem2str(item, itemId)), xbmc.LOGERROR)
        return

    # create an Emby server instance
    embyServer = Server(mediaProvider)

    # retrieve all details of the item
    itemObj = Library.GetItem(embyServer, itemId)
    if not itemObj:
        log('[context/play] cannot retrieve the details of {} from {}' \
            .format(listItem2str(item, itemId), mediaProvider2str(mediaProvider)), xbmc.LOGERROR)
        return

    # cannot play folders
    if itemObj.get(emby.constants.PROPERTY_ITEM_IS_FOLDER):
        log('[context/play] cannot play folder item {}'.format(listItem2str(item, itemId)), xbmc.LOGERROR)
        return

    playChoices = []
    playChoicesUrl = []

    # determine whether Direct Play is allowed
    mediaProviderSettings = mediaProvider.getSettings()
    allowDirectPlay = mediaProviderSettings.getBool(emby.constants.SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

    # check if the item supports Direct Play and / or Direct Stream
    canDirectPlay = None
    directPlayUrl = None
    if allowDirectPlay:
        (canDirectPlay, directPlayUrl) = kodi.Api.getDirectPlayUrl(embyServer, itemId, itemObj)

        if canDirectPlay and directPlayUrl:
            playChoices.append(localise(32101))
            playChoicesUrl.append(directPlayUrl)

    (canDirectStream, directStreamUrl) = kodi.Api.getDirectStreamUrl(embyServer, itemId, itemObj)
    if canDirectStream:
        playChoices.append(localise(32102))
        playChoicesUrl.append(directStreamUrl)

    # if there are no options something went wrong
    if not playChoices:
        log('[context/play] cannot play {} from {}' \
            .format(listItem2str(item, itemId), mediaProvider2str(mediaProvider)), xbmc.LOGERROR)
        return

    # ask the user how to play
    playChoice = Dialog().contextmenu(playChoices)
    if playChoice < 0 or playChoice >= len(playChoices):
        return

    playUrl = playChoicesUrl[playChoice]

    # play the item
    log('[context/play] playing {} using "{}" ({}) from {}' \
        .format(listItem2str(item, itemId), playChoices[playChoice], playUrl, mediaProvider2str(mediaProvider)))
    # overwrite the dynamic path of the ListItem
    item.setDynamicPath(playUrl)
    xbmc.Player().play(playUrl, item)

def run(action):
    item = sys.listitem
    if not item:
        log('[context] missing ListItem', xbmc.LOGERROR)
        return

    itemId = kodi.Api.getEmbyItemIdFromItem(item)
    if not itemId:
        log('[context] cannot determine the Emby identifier of "{}"' \
            .format(item.getLabel()), xbmc.LOGERROR)
        return

    mediaProviderId = item.getMediaProviderId()
    if not mediaProviderId:
        log('[context] cannot determine the media provider identifier of {}' \
            .format(listItem2str(item, itemId)), xbmc.LOGERROR)
        return

    # get the media provider
    mediaProvider = xbmcmediaimport.getProviderById(mediaProviderId)
    if not mediaProvider:
        log('[context] cannot determine the media provider ({}) of {}' \
            .format(mediaProviderId, listItem2str(item, itemId)), xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('[context] cannot prepare media provider ({}) settings of {}' \
            .format(mediaProvider2str(mediaProvider), listItem2str(item, itemId)), xbmc.LOGERROR)
        return

    if action == ContextAction.Play:
        play(item, itemId, mediaProvider)
    else:
        raise ValueError('unknown action {}'.format(action))
