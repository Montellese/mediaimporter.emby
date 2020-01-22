#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from datetime import datetime
from dateutil import parser

from emby.api.server import Server

from lib.utils import Url

class UserData:
    @staticmethod
    def PreprocessLastPlayed(lastPlayed):
        lastPlayedDate = None
        if lastPlayed:
            lastPlayedDate = parser.parse(lastPlayed)
        if not lastPlayedDate or lastPlayedDate.year < 1900:
            lastPlayedDate = datetime.now()

        return lastPlayedDate

    @staticmethod
    def Update(embyServer, itemId, updateItemPlayed, updatePlaybackPosition, watched, playcount, lastPlayed, playbackPositionInTicks):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        result = True
        serverInfo = Server.GetInfo(embyServer.Url())
        if serverInfo and serverInfo.supportsUserDataUpdates():
            UserData.UpdateUserData(embyServer, itemId, playcount, watched, lastPlayed, playbackPositionInTicks)
        else:
            if updateItemPlayed:
                if watched:
                    if not UserData.MarkAsWatched(embyServer, itemId, lastPlayed):
                        result = False
                else:
                    if not UserData.MarkAsUnwatched(embyServer, itemId):
                        result = False

            if updatePlaybackPosition:
                if not UserData.UpdateResumePoint(embyServer, itemId, playbackPositionInTicks):
                        result = False

        return result


    @staticmethod
    def MarkAsWatched(embyServer, itemId, lastPlayed):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        lastPlayedDate = UserData.PreprocessLastPlayed(lastPlayed)

        url = embyServer.BuildUserPlayedItemUrl(itemId)
        url = Url.addOptions(url, { 'DatePlayed': lastPlayedDate.strftime('%Y%m%d%H%M%S') })

        if not embyServer.ApiPost(url):
            return False

        return True

    @staticmethod
    def MarkAsUnwatched(embyServer, itemId):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        url = embyServer.BuildUserPlayedItemUrl(itemId)

        embyServer.ApiDelete(url)
        return True

    @staticmethod
    def UpdateResumePoint(embyServer, itemId, positionInTicks):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        url = embyServer.BuildUserPlayingItemUrl(itemId)
        url = Url.addOptions(url, { 'PositionTicks': positionInTicks })

        embyServer.ApiDelete(url)
        return True

    @staticmethod
    def UpdateUserData(embyServer, itemId, playcount, watched, lastPlayed, playbackPositionInTicks):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        lastPlayedDate = UserData.PreprocessLastPlayed(lastPlayed)

        url = embyServer.BuildUserItemUserDataUrl(itemId)
        body = {
            'ItemId': itemId,
            'PlayCount': playcount,
            'Played': watched,
            'LastPlayedDate': lastPlayedDate.strftime('%Y-%m-%dT%H:%M:%S.%f%Z'),
            'PlaybackPositionTicks': playbackPositionInTicks
        }

        embyServer.ApiPost(url, body)
