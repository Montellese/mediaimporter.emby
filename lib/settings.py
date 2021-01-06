#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import hashlib
import json

from six import ensure_binary

import xbmcmediaimport  # pylint: disable=import-error

from emby.constants import \
    SETTING_PROVIDER_URL, \
    SETTING_PROVIDER_SYNCHRONIZATION_USE_KODI_COMPANION, \
    SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY, \
    SETTING_IMPORT_VIEWS, \
    SETTING_IMPORT_VIEWS_OPTION_SPECIFIC, \
    SETTING_IMPORT_VIEWS_SPECIFIC, \
    SETTING_IMPORT_IMPORT_COLLECTIONS, \
    SETTING_IMPORT_SYNC_SETTINGS_HASH

class ProviderSettings:
    @staticmethod
    def GetUrl(obj):
        providerSettings = ProviderSettings._getProviderSettings(obj)

        url = providerSettings.getString(SETTING_PROVIDER_URL)
        if not url:
            raise RuntimeError('invalid provider without URL')

        return url

    @staticmethod
    def SetUrl(obj, url):
        if not obj:
            raise ValueError('invalid media provider or media provider settings')
        if not url:
            raise ValueError('invalid url')

        providerSettings = ProviderSettings._getProviderSettings(obj)

        providerSettings.setString(SETTING_PROVIDER_URL, url)

    @staticmethod
    def _getProviderSettings(obj):
        if not obj:
            raise ValueError('invalid media provider or media provider settings')

        if isinstance(obj, xbmcmediaimport.MediaProvider):
            providerSettings = obj.getSettings()
            if not providerSettings:
                raise ValueError('invalid provider without settings')
            return providerSettings

        return obj


class ImportSettings:
    @staticmethod
    def GetLibraryViews(importSettings):
        if not importSettings:
            raise ValueError('invalid importSettings')

        if not importSettings.getString(SETTING_IMPORT_VIEWS) == SETTING_IMPORT_VIEWS_OPTION_SPECIFIC:
            return []

        return importSettings.getStringList(SETTING_IMPORT_VIEWS_SPECIFIC)


class SynchronizationSettings:
    @staticmethod
    def GetHash(importSettings):
        if not importSettings:
            raise ValueError('invalid importSettings')

        return importSettings.getString(SETTING_IMPORT_SYNC_SETTINGS_HASH)

    @staticmethod
    def SaveHash(importSettings, hashHex):
        if not importSettings:
            raise ValueError('invalid importSettings')
        if not hashHex:
            raise ValueError('invalid hashHex')

        importSettings.setString(SETTING_IMPORT_SYNC_SETTINGS_HASH, hashHex)
        importSettings.save()

    @staticmethod
    def CalculateHash(mediaTypes, providerSettings, importSettings, save=True):
        if not mediaTypes:
            raise ValueError('invalid mediaTypes')
        if not providerSettings:
            raise ValueError('invalid providerSettings')
        if not importSettings:
            raise ValueError('invalid importSettings')

        # provider specific settings
        useKodiCompanion = providerSettings.getBool(SETTING_PROVIDER_SYNCHRONIZATION_USE_KODI_COMPANION)
        allowDirectPlay = providerSettings.getBool(SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

        # import specific settings
        libraryViews = ImportSettings.GetLibraryViews(importSettings)

        hashObject = {
            # provider specific settings
            SETTING_PROVIDER_SYNCHRONIZATION_USE_KODI_COMPANION: useKodiCompanion,
            SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY: allowDirectPlay,

            # import specific settings
            SETTING_IMPORT_VIEWS: libraryViews,
        }

        # only consider the import collections setting for movies and collections
        if xbmcmediaimport.MediaTypeMovie in mediaTypes or xbmcmediaimport.MediaTypeVideoCollection in mediaTypes:
            importCollections = importSettings.getBool(SETTING_IMPORT_IMPORT_COLLECTIONS)

            hashObject.update({
                SETTING_IMPORT_IMPORT_COLLECTIONS: importCollections,
            })

        # serialize the object into JSON
        hashString = json.dumps(hashObject)

        # hash the JSON serialized object
        sha1Hash = hashlib.sha1(ensure_binary(hashString))  # nosec
        hashHex = sha1Hash.hexdigest()

        if save:
            SynchronizationSettings.SaveHash(importSettings, hashHex)

        return hashHex

    @staticmethod
    def HaveChanged(mediaTypes, providerSettings, importSettings, save=True):
        if not mediaTypes:
            raise ValueError('invalid mediaTypes')
        if not providerSettings:
            raise ValueError('invalid providerSettings')
        if not importSettings:
            raise ValueError('invalid importSettings')

        oldHash = SynchronizationSettings.GetHash(importSettings)
        newHash = SynchronizationSettings.CalculateHash(mediaTypes, providerSettings, importSettings, save=False)

        if oldHash == newHash:
            return False

        if save:
            SynchronizationSettings.SaveHash(importSettings, newHash)

        return True

    @staticmethod
    def ResetHash(importSettings, save=True):
        if not importSettings:
            raise ValueError('invalid importSettings')

        importSettings.setString(SETTING_IMPORT_SYNC_SETTINGS_HASH, '')
        if save:
            importSettings.save()
