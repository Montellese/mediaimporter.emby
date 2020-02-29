#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from uuid import uuid4

class PlaybackCheckin:
    @staticmethod
    def GenerateSessionId():
        return str(uuid4()).replace("-", "")

    @staticmethod
    def StartPlayback(embyServer, data):
        if not embyServer:
            raise ValueError('invalid embyServer')

        url = embyServer.BuildSessionsPlayingUrl()
        embyServer.ApiPost(url, json=data)

    @staticmethod
    def PlaybackProgress(embyServer, data):
        if not embyServer:
            raise ValueError('invalid embyServer')

        url = embyServer.BuildSessionsPlayingProgressUrl()
        embyServer.ApiPost(url, json=data)

    @staticmethod
    def StopPlayback(embyServer, data):
        if not embyServer:
            raise ValueError('invalid embyServer')

        url = embyServer.BuildSessionsPlayingStoppedUrl()
        embyServer.ApiPost(url, json=data)
