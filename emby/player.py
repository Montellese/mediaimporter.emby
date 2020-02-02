#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import threading
import time

import xbmc
import xbmcmediaimport

from emby.api.library import Library
from emby.api.playback import PlaybackCheckin
from emby.constants import *
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

        self._item = self.getPlayingItem()
        if not self._item:
            return

        # check if the item has been imported from a media provider
        mediaProviderId = self._item.getMediaProviderId()
        if not mediaProviderId:
            return

        if not mediaProviderId in self._providers:
            Player.log('currently playing item {} ({}) has been imported from an unknown media provider {}' \
                .format(self._item.getLabel(), self._file, mediaProviderId), xbmc.LOGWARNING)
            return
        self._mediaProvider = self._providers[mediaProviderId]

        videoInfoTag = self.getVideoInfoTag()
        if not videoInfoTag:
            return

        self._itemId = kodi.Api.getEmbyItemIdFromVideoInfoTag(videoInfoTag)
        if not self._itemId:
            return

        settings = self._mediaProvider.prepareSettings()
        if not settings:
            Player.log('failed to load settings for {} ({}) playing from {}' \
                .format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
            self._reset()
            return

        # determine the play method
        if Server.IsDirectStreamUrl(self._mediaProvider, self._file):
            self._playMethod = PLAYING_PLAY_METHOD_DIRECT_STREAM
        else:
            self._playMethod = PLAYING_PLAY_METHOD_DIRECT_PLAY

        # setup and authenticate with the Emby server
        try:
            self._server = Server(self._mediaProvider)
        except:
            pass

        if not self._server or not self._server.Authenticate():
            Player.log('cannot connect to media provider {} to report playback progress of "{}" ({})' \
                .format(mediaProvider2str(self._mediaProvider), self._item.getLabel(), self._file), xbmc.LOGWARNING)
            self._reset()
            return

        # when using DirectStream add any external subtitles
        if self._playMethod == PLAYING_PLAY_METHOD_DIRECT_STREAM and \
           settings.getBool(SETTING_PROVIDER_PLAYBACK_ENABLE_EXTERNAL_SUBTITLES):
            self._addExternalSubtitles()

        # generate a session identifier
        self._playSessionId =  PlaybackCheckin.GenerateSessionId()

        # prepare the data of the API call
        data = self._preparePlayingData(stopped=False)

        # tell the Emby server that a library item is being played
        PlaybackCheckin.StartPlayback(self._server, data)

        self._lastProgressReport = time.time()

        Player.log('playback start for "{}" ({}) on {} reported'.format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    def _reportPlaybackProgress(self, event=PLAYING_PROGRESS_EVENT_TIME_UPDATE):
        if not self.isPlaying():
            self._reset()
        if not self._item:
            return False

        data = self._preparePlayingData(stopped=False, event=event)
        PlaybackCheckin.PlaybackProgress(self._server, data)

        self._lastProgressReport = time.time()

        return True

    def _stopPlayback(self, failed=False):
        if not self.isPlaying():
            self._reset()
        if not self._item:
            return

        data = self._preparePlayingData(stopped=True, failed=failed)
        PlaybackCheckin.StopPlayback(self._server, data)

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

    def _addExternalSubtitles(self):
        if not self._item:
            return

        # get the item's details to look for external subtitles
        itemObj = Library.GetItem(self._server, self._itemId)
        if not itemObj:
            Player.log('cannot retrieve details of "{}" ({}) from media provider {}' \
                .format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
            return

        # extract the media source ID
        if not PROPERTY_ITEM_MEDIA_SOURCES in itemObj or not itemObj[PROPERTY_ITEM_MEDIA_SOURCES]:
            Player.log('cannot add external subtitles for "{}" ({}) from media provider {} ' \
                'because it doesn\'t have a media source' \
                .format(self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)), xbmc.LOGDEBUG)
            return

        mediaSourceId = itemObj.get(PROPERTY_ITEM_MEDIA_SOURCES)[0].get(PROPERTY_ITEM_MEDIA_SOURCES_ID)

        # look for external subtitles
        for stream in itemObj.get(PROPERTY_ITEM_MEDIA_STREAMS):
            if stream.get(PROPERTY_ITEM_MEDIA_STREAM_TYPE) != 'Subtitle' or not stream.get(PROPERTY_ITEM_MEDIA_STREAM_IS_EXTERNAL):
                continue

            # get the index of the subtitle
            index = stream.get(PROPERTY_ITEM_MEDIA_STREAM_INDEX)

            # determine the language and name
            name = stream.get(PROPERTY_ITEM_MEDIA_STREAM_DISPLAY_TITLE) if PROPERTY_ITEM_MEDIA_STREAM_DISPLAY_TITLE in stream else ''
            language = stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE) if PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE in stream else ''

            # determine the stream URL
            if PROPERTY_ITEM_MEDIA_STREAM_DELIVERY_URL in stream and \
                stream.get(PROPERTY_ITEM_MEDIA_STREAM_DELIVERY_URL).upper().startswith('/{}'.format(URL_VIDEOS)):
                url = self._server.BuildStreamDeliveryUrl(stream.get(PROPERTY_ITEM_MEDIA_STREAM_DELIVERY_URL))
            else:
                url = self._server.BuildSubtitleStreamUrl(self._itemId, mediaSourceId, index, stream.get(PROPERTY_ITEM_MEDIA_STREAM_CODEC))

            if not url:
                Player.log('cannot add external subtitle at index {} for "{}" ({}) from media provider {}' \
                .format(index, self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)), xbmc.LOGWARNING)
                continue

            self.addSubtitle(url, name, language, False)  # TODO(Montellese): activate?
            Player.log('external subtitle "{}" [{}] at index {} added for "{}" ({}) from media provider {}' \
                .format(name, language, index, self._item.getLabel(), self._file, mediaProvider2str(self._mediaProvider)))

    @staticmethod
    def log(message, level=xbmc.LOGINFO):
        log('[player] {}'.format(message), level)
