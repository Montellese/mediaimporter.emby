#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import threading
import time
from uuid import uuid4

import xbmc
import xbmcmediaimport

from emby.constants import EMBY_PROTOCOL, \
    PLAYING_PLAY_METHOD_DIRECT_PLAY, PLAYING_PLAY_METHOD_DIRECT_STREAM, \
    PLAYING_PROGRESS_EVENT_TIME_UPDATE, PLAYING_PROGRESS_EVENT_PAUSE, PLAYING_PROGRESS_EVENT_UNPAUSE
from emby.server import Server

from lib import kodi
from lib.utils import log, mediaProvider2str

class Player(xbmc.Player):
    def __init__(self, progressInterval=None):
        super(xbmc.Player, self).__init__()

        self._lock = threading.Lock()

        self._progressInterval = progressInterval or 10
        self._lastProgressReport = None

        self._providers = {}

        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._server = None
        self._playSessionId = None
        self._paused = False
        self._playMethod = None

    def AddProvider(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            self._providers[mediaProvider.getIdentifier()] = mediaProvider

        Player.log('{} added'.format(mediaProvider2str(mediaProvider)))

    def RemoveProvider(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        with self._lock:
            del self._providers[mediaProvider.getIdentifier()]

        Player.log('{} removed'.format(mediaProvider2str(mediaProvider)))

    def Process(self):
        with self._lock:
            if not self._lastProgressReport:
                return

            # adhere to the configured progress interval
            if (time.time() - self._lastProgressReport) < self._progressInterval:
                return

            self._reportPlaybackProgress()

    def onPlayBackStarted(self):
        with self._lock:
            self._reset()
            try:
                self._file = self.getPlayingFile()
            except RuntimeError:
                pass

    def onAVStarted(self):
        with self._lock:
            self._startPlayback()

    def onPlayBackSeek(self, time, seekOffset):
        with self._lock:
            if self._reportPlaybackProgress():
                Player.log('playback seek for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def onPlayBackSeekChapter(self, chapter):
        with self._lock:
            if not self._item:
                return

            if self._reportPlaybackProgress():
                Player.log('playback seek chapter for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def onPlayBackPaused(self):
        with self._lock:
            self._paused = True
            if self._reportPlaybackProgress():
                Player.log('playback paused for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def onPlayBackResumed(self):
        with self._lock:
            self._paused = False
            if self._reportPlaybackProgress():
                Player.log('playback resumed for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def onPlayBackStopped(self):
        with self._lock:
            self._stopPlayback()

    def onPlayBackEnded(self):
        with self._lock:
            self._stopPlayback()

    def onPlayBackError(self):
        with self._lock:
            self._stopPlayback(failed=True)

    def _reset(self):
        self._file = None
        self._item = None
        self._itemId = None
        self._mediaProvider = None
        self._server = None
        self._playSessionId = None
        self._paused = False
        self._playMethod = None

    def _startPlayback(self):
        if not self._file:
            return

        if not self.isPlayingVideo():
            return

        videoInfoTag = self.getVideoInfoTag()
        if not videoInfoTag:
            return

        self._itemId = videoInfoTag.getUniqueID(EMBY_PROTOCOL)
        if not self._itemId:
            return

        for mediaProvider in self._providers.values():
            importedItems = xbmcmediaimport.getImportedItemsByProvider(mediaProvider)
            matchingItems = [ importedItem for importedItem in importedItems \
                if importedItem.getVideoInfoTag() and importedItem.getVideoInfoTag().getUniqueID(EMBY_PROTOCOL) == self._itemId ]
            if not matchingItems:
                continue

            if len(matchingItems) > 1:
                Player.log('multiple items imported from {} match the imported Emby item {} playing from {}' \
                    .format(mediaProvider2str(mediaProvider), self._itemId, self._file), xbmc.LOGWARNING)

            self._item = matchingItems[0]
            self._mediaProvider = mediaProvider
            break

        if not self._item:
            return

        # generate a session identifier
        self._playSessionId = str(uuid4()).replace("-", "")

        # determine the play method
        if Server.IsDirectStreamUrl(self._mediaProvider, self._file):
            self._playMethod = PLAYING_PLAY_METHOD_DIRECT_STREAM
        else:
            self._playMethod = PLAYING_PLAY_METHOD_DIRECT_PLAY

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=False)

        # tell the Emby server that a library item is being played
        self._server = Server(self._mediaProvider)
        url = self._server.BuildSessionsPlayingUrl()
        self._server.ApiPost(url, data)

        self._lastProgressReport = time.time()

        Player.log('playback start for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def _reportPlaybackProgress(self, event=PLAYING_PROGRESS_EVENT_TIME_UPDATE):
        if not self.isPlaying():
            self._reset()
        if not self._item:
            return False

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=False, event=event)

        # tell the Emby server that a library item is being played
        url = self._server.BuildSessionsPlayingProgressUrl()
        self._server.ApiPost(url, data)

        self._lastProgressReport = time.time()

        return True

    def _stopPlayback(self, failed=False):
        if not self.isPlaying():
            self._reset()
        if not self._item:
            return

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=True, failed=failed)

        # tell the Emby server that a library item is being played
        url = self._server.BuildSessionsPlayingStoppedUrl()
        self._server.ApiPost(url, data)

        Player.log('playback stopped for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

        self._reset()

    def _preparePlayingData(self, stopped=False, event=None, failed=False):
        data = {
            'ItemId': self._itemId,
            'PlaySessionId': self._playSessionId,
            'PlaylistIndex': 0,
            'PlaylistLength': 1,
        }

        if stopped:
            data.update({
                'Failed': failed
            })
        else:
            data.update({
                'QueueableMediaTypes': 'Audio,Video',
                'CanSeek': True,
                'PlayMethod': self._playMethod,
                'IsPaused': self._paused,
            })

            try:
                data.update({
                    'PositionTicks': kodi.Api.secondsToTicks(self.getTime()),
                    'RunTimeTicks': kodi.Api.secondsToTicks(self.getTotalTime()),
                })
            except RuntimeError:
                pass

            if event:
                data.update({
                    'EventName': event
                })

        return data

    @staticmethod
    def log(message, level=xbmc.LOGINFO):
        log('[player] {}'.format(message), level)
