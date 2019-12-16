#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import xbmc
import xbmcmediaimport

from emby.provider_observer import ProviderObserver
from emby.server import Server

from lib.monitor import Monitor
from lib.utils import log, mediaImport2str, mediaProvider2str

class EmbyObserverService(xbmcmediaimport.Observer):
    def __init__(self):
        super(xbmcmediaimport.Observer, self).__init__(self)

        self._monitor = Monitor()
        self._observers = {}

        self._run()

    def _run(self):
        log('Observing Emby servers...')

        while not self._monitor.abortRequested():
            # process all observers
            for observer in self._observers.values():
                observer.Process()

            if self._monitor.waitForAbort(1):
                break

        # stop all observers
        for observer in self._observers.values():
            observer.Stop()

    def _addObserver(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('cannot add invalid media provider')

        # check if we already know about the media provider
        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId in self._observers:
            return

        # create the observer
        self._observers[mediaProviderId] = ProviderObserver()

    def _removeObserver(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('cannot remove invalid media provider')

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        del self._observers[mediaProviderId]

    def _startObserver(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('cannot start invalid media provider')

        # make sure the media provider has been added
        self._addObserver(mediaProvider)

        # start observing the media provider
        self._observers[mediaProvider.getIdentifier()].Start(mediaProvider)

    def _stopObserver(self, mediaProvider):
        if not mediaProvider:
            raise ValueError('cannot stop invalid media provider')

        mediaProviderId = mediaProvider.getIdentifier()
        if mediaProviderId not in self._observers:
            return

        self._observers[mediaProviderId].Stop()

    def _addImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('cannot add invalid media import')

        mediaProvider = mediaImport.getProvider()
        if not mediaProvider:
            raise ValueError('cannot add media import {} with invalid media provider'.format(mediaImport2str(mediaImport)))

        mediaProviderId = mediaProvider.getIdentifier()
        if not mediaProviderId in self._observers:
            return

        self._observers[mediaProviderId].AddImport(mediaImport)

    def _removeImport(self, mediaImport):
        if not mediaImport:
            raise ValueError('cannot remove invalid media import')

        mediaProvider = mediaImport.getProvider()
        if not mediaProvider:
            raise ValueError('cannot remove media import {} with invalid media provider'.format(mediaImport2str(mediaImport)))

        mediaProviderId = mediaProvider.getIdentifier()
        if not mediaProviderId in self._observers:
            return

        self._observers[mediaProviderId].RemoveImport(mediaImport)

    def onProviderAdded(self, mediaProvider):
        self._addObserver(mediaProvider)

    def onProviderUpdated(self, mediaProvider):
        self._addObserver(mediaProvider)

        # make sure the media provider is being observed
        if mediaProvider.isActive():
            self._startObserver(mediaProvider)
        else:
            self._stopObserver(mediaProvider)

    def onProviderRemoved(self, mediaProvider):
        self._removeObserver(mediaProvider)

    def onProviderActivated(self, mediaProvider):
        self._startObserver(mediaProvider)

    def onProviderDeactivated(self, mediaProvider):
        self._stopObserver(mediaProvider)

    def onImportAdded(self, mediaImport):
        self._addImport(mediaImport)

    def onImportUpdated(self, mediaImport):
        self._addImport(mediaImport)

    def onImportRemoved(self, mediaImport):
        self._removeImport(mediaImport)

if __name__ == '__main__':
    # instantiate and start the observer service
    log('Emby Media Import observer started')
    EmbyObserverService()
