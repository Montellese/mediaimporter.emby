#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import sys
import time
import uuid

from dateutil import parser
from six import iteritems
from six.moves.urllib.parse import parse_qs, unquote, urlparse

import xbmc  # pylint: disable=import-error
import xbmcgui  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error

import emby
from emby.api.embyconnect import EmbyConnect
from emby.api.kodi_companion import KodiCompanion
from emby.api.library import Library
from emby.api.user import User
from emby.api.userdata import UserData
from emby.request import Request
from emby.server import Server

from lib import kodi
from lib.settings import ImportSettings, SynchronizationSettings
from lib.utils import __addon__, localise, log, mediaProvider2str, Url, utc

# list of fields to retrieve
EMBY_ITEM_FIELDS = [
    emby.constants.PROPERTY_ITEM_PREMIERE_DATE,
    emby.constants.PROPERTY_ITEM_PRODUCTION_YEAR,
    emby.constants.PROPERTY_ITEM_PATH,
    emby.constants.PROPERTY_ITEM_SORT_NAME,
    emby.constants.PROPERTY_ITEM_ORIGINAL_TITLE,
    emby.constants.PROPERTY_ITEM_DATE_CREATED,
    emby.constants.PROPERTY_ITEM_COMMUNITY_RATING,
    emby.constants.PROPERTY_ITEM_VOTE_COUNT,
    emby.constants.PROPERTY_ITEM_OFFICIAL_RATING,
    emby.constants.PROPERTY_ITEM_CRITIC_RATING,
    emby.constants.PROPERTY_ITEM_OVERVIEW,
    emby.constants.PROPERTY_ITEM_SHORT_OVERVIEW,
    emby.constants.PROPERTY_ITEM_LOCAL_TRAILER_COUNT,
    emby.constants.PROPERTY_ITEM_REMOTE_TRAILERS,
    emby.constants.PROPERTY_ITEM_TAGLINES,
    emby.constants.PROPERTY_ITEM_GENRES,
    emby.constants.PROPERTY_ITEM_STUDIOS,
    emby.constants.PROPERTY_ITEM_PRODUCTION_LOCATIONS,
    emby.constants.PROPERTY_ITEM_PROVIDER_IDS,
    emby.constants.PROPERTY_ITEM_TAGS,
    emby.constants.PROPERTY_ITEM_PEOPLE,
    emby.constants.PROPERTY_ITEM_ROLE,
    emby.constants.PROPERTY_ITEM_MEDIA_STREAMS,
]

# general constants
ITEM_REQUEST_LIMIT = 100


def mediaTypesFromOptions(options):
    if 'mediatypes' not in options and 'mediatypes[]' not in options:
        return None

    mediaTypes = None
    if 'mediatypes' in options:
        mediaTypes = options['mediatypes']
    elif 'mediatypes[]' in options:
        mediaTypes = options['mediatypes[]']

    return mediaTypes

def getLibraryViews(embyServer, mediaTypes):
    if not embyServer:
        raise ValueError('invalid emby server')
    if not mediaTypes:
        raise ValueError('invalid mediaTypes')

    # check whether to include mixed libraries
    includeMixed = False
    for mediaType in mediaTypes:
        (_, _, mixed, _) = kodi.Api.getEmbyMediaType(mediaType)
        if mixed:
            includeMixed = True
            break

    return Library.GetViews(embyServer, mediaTypes, includeMixed=includeMixed)

def getMatchingLibraryViews(embyServer, mediaTypes, selectedViews):
    libraryViews = getLibraryViews(embyServer, mediaTypes)

    matchingLibraryViews = []
    if not selectedViews:
        matchingLibraryViews = libraryViews
    else:
        matchingLibraryViews = [libraryView for libraryView in libraryViews if libraryView.id in selectedViews]

    return matchingLibraryViews


def discoverProviderLocally(handle, options):  # pylint: disable=unused-argument
    baseUrl = xbmcgui.Dialog().input(localise(32050), 'http://')
    if not baseUrl:
        return None

    log('trying to discover an Emby server at {}...'.format(baseUrl))
    try:
        serverInfo = emby.api.server.Server.GetInfo(baseUrl)
        if not serverInfo:
            return None
    except:
        return None

    providerId = Server.BuildProviderId(serverInfo.id)
    providerIconUrl = Server.BuildIconUrl(baseUrl)
    provider = xbmcmediaimport.MediaProvider(providerId, baseUrl, serverInfo.name, providerIconUrl,
                                             emby.constants.SUPPORTED_MEDIA_TYPES)
    provider.setIconUrl(kodi.Api.downloadIcon(provider))

    # store local authentication in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    providerSettings.setString(emby.constants.SETTING_PROVIDER_AUTHENTICATION,
                               emby.constants.SETTING_PROVIDER_AUTHENTICATION_OPTION_LOCAL)
    providerSettings.save()

    log('Local Emby server {} successfully discovered at {}'.format(mediaProvider2str(provider), baseUrl))

    return provider


def linkToEmbyConnect(deviceId):
    dialog = xbmcgui.Dialog()

    pinLogin = EmbyConnect.PinLogin(deviceId=deviceId)
    if not pinLogin.pin:
        dialog.ok(localise(32038), localise(32054))
        log('failed to get PIN to link to Emby Connect', xbmc.LOGWARNING)
        return None

    # show the user the pin
    dialog.ok(localise(32038), localise(32055), '[COLOR FF52B54B]{}[/COLOR]'.format(pinLogin.pin))

    # check the status of the authentication
    while not pinLogin.finished:
        if pinLogin.checkLogin():
            break

        time.sleep(0.25)

    if pinLogin.expired:
        dialog.ok(localise(32038), localise(32056))
        log('linking to Emby Connect has expiried', xbmc.LOGWARNING)
        return None

    authResult = pinLogin.exchange()
    if not authResult:
        log('no valid access token received from the linked Emby Connect account', xbmc.LOGWARNING)
        return None

    return authResult


def linkEmbyConnect(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # get the media provider settings
    providerSettings = mediaProvider.prepareSettings()
    if not providerSettings:
        return

    # make sure we have a valid device ID
    deviceId = providerSettings.getString(emby.constants.SETTING_PROVIDER_DEVICEID)
    if not deviceId:
        deviceId = Request.GenerateDeviceId()
        providerSettings.setString(emby.constants.SETTING_PROVIDER_DEVICEID, deviceId)

    embyConnect = linkToEmbyConnect(deviceId)
    if not embyConnect:
        return

    # make sure the configured Emby server is still accessible
    serverUrl = mediaProvider.getBasePath()
    matchingServer = None
    serverId = Server.GetServerId(mediaProvider.getIdentifier())

    # get all connected servers
    servers = EmbyConnect.GetServers(embyConnect.accessToken, embyConnect.userId)
    if not servers:
        log('no servers available for Emby Connect user id {}'.format(embyConnect.userId), xbmc.LOGWARNING)
        return

    for server in servers:
        if server.systemId == serverId:
            matchingServer = server
            break

    if not matchingServer:
        log('no Emby server matching {} found'.format(serverUrl), xbmc.LOGWARNING)
        xbmcgui.Dialog().ok(localise(32038), localise(32061))
        return

    # change the settings
    providerSettings.setString(emby.constants.SETTING_PROVIDER_EMBY_CONNECT_USER_ID, embyConnect.userId)
    providerSettings.setString(emby.constants.SETTING_PROVIDER_EMBY_CONNECT_ACCESS_KEY, matchingServer.accessKey)

    success = False
    try:
        success = Server(mediaProvider).Authenticate(force=True)
    except:
        pass

    if success:
        xbmcgui.Dialog().ok(localise(32038), localise(32062))
        log('successfully linked to Emby Connect server {} ({}) {}'.format(matchingServer.name, serverId, serverUrl))
    else:
        xbmcgui.Dialog().ok(localise(32038), localise(32061))
        log('failed to link to Emby Connect server {} ({}) {}'.format(matchingServer.name, serverId, serverUrl),
            xbmc.LOGWARNING)


# pylint: disable=too-many-locals, too-many-branches, too-many-return-statements
def discoverProviderWithEmbyConnect(handle, options):  # pylint: disable=unused-argument
    deviceId = Request.GenerateDeviceId()

    embyConnect = linkToEmbyConnect(deviceId)
    if not embyConnect:
        return None

    dialog = xbmcgui.Dialog()

    # get all connected servers
    servers = EmbyConnect.GetServers(embyConnect.accessToken, embyConnect.userId)
    if not servers:
        log('no servers available for Emby Connect user id {}'.format(embyConnect.userId), xbmc.LOGWARNING)
        return None

    if len(servers) == 1:
        server = servers[0]
    else:
        # ask the user which server to use
        serverChoices = [server.name for server in servers]
        serverChoice = dialog.select(localise(32057), serverChoices)
        if serverChoice < 0 or serverChoice >= len(serverChoices):
            return None

        server = server[serverChoice]

    if not server:
        return None

    urls = []
    if server.localUrl:
        # ask the user whether to use a local or remote connection
        isLocal = dialog.yesno(localise(32058), localise(32059).format(server.name))
        if isLocal:
            urls.append(server.localUrl)

    if server.remoteUrl:
        urls.append(server.remoteUrl)

    baseUrl = None
    # find a working connection / base URL
    for url in urls:
        try:
            _ = emby.api.server.Server.GetInfo(url)
        except:
            log('failed to connect to "{}" at {}'.format(server.name, url), xbmc.LOGDEBUG)
            continue

        baseUrl = url
        break

    if not baseUrl:
        dialog.ok(localise(32058), localise(32060).format(server.name))
        log('failed to connect to Emby server "{}" with Emby Connect user ID {}'
            .format(server.name, embyConnect.userId), xbmc.LOGWARNING)
        return None

    providerId = Server.BuildProviderId(server.systemId)
    providerIconUrl = Server.BuildIconUrl(baseUrl)
    provider = xbmcmediaimport.MediaProvider(providerId, baseUrl, server.name, providerIconUrl,
                                             emby.constants.SUPPORTED_MEDIA_TYPES)
    provider.setIconUrl(kodi.Api.downloadIcon(provider))

    # store Emby connect authentication in settings
    providerSettings = provider.prepareSettings()
    if not providerSettings:
        return None

    providerSettings.setString(emby.constants.SETTING_PROVIDER_AUTHENTICATION,
                               emby.constants.SETTING_PROVIDER_AUTHENTICATION_OPTION_EMBY_CONNECT)
    providerSettings.setString(emby.constants.SETTING_PROVIDER_EMBY_CONNECT_USER_ID, embyConnect.userId)
    providerSettings.setString(emby.constants.SETTING_PROVIDER_EMBY_CONNECT_ACCESS_KEY, server.accessKey)
    providerSettings.setString(emby.constants.SETTING_PROVIDER_DEVICEID, deviceId)
    providerSettings.save()

    log('Emby Connect server {} successfully discovered at {}'.format(mediaProvider2str(provider), baseUrl))

    return provider


def testAuthentication(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    log('testing authentication with {}...'.format(mediaProvider2str(mediaProvider)))
    success = False
    try:
        success = Server(mediaProvider).Authenticate(force=True)
    except:
        pass

    title = mediaProvider.getFriendlyName()
    line = 32018
    if success:
        line = 32017
    xbmcgui.Dialog().ok(title, localise(line))


def forceSync(handle, _):
    # ask the user whether he is sure
    force = xbmcgui.Dialog().yesno(localise(32042), localise(32053))
    if not force:
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # reset the synchronization hash setting to force a full synchronization
    SynchronizationSettings.ResetHash(importSettings, save=False)


def settingOptionsFillerUsers(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # get the provider's settings
    settings = mediaProvider.getSettings()

    users = [(__addon__.getLocalizedString(32015), emby.constants.SETTING_PROVIDER_USER_OPTION_MANUAL)]
    publicUsers = User.GetPublicUsers(mediaProvider.getBasePath(),
                                      deviceId=settings.getString(emby.constants.SETTING_PROVIDER_DEVICEID))
    users.extend([(user.name, user.id) for user in publicUsers])

    # pass the list of users back to Kodi
    settings.setStringOptions(emby.constants.SETTING_PROVIDER_USER, users)


def settingOptionsFillerViews(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    try:
        embyServer = Server(mediaProvider)
    except:
        return

    libraryViews = getLibraryViews(embyServer, mediaImport.getMediaTypes())
    views = []
    for libraryView in libraryViews:
        views.append((libraryView.name, libraryView.id))

    # get the import's settings
    settings = mediaImport.getSettings()

    # pass the list of views back to Kodi
    settings.setStringOptions(emby.constants.SETTING_IMPORT_VIEWS_SPECIFIC, views)


# pylint: disable=too-many-locals, too-many-arguments
def importItems(handle, embyServer, url, mediaType, viewId, embyMediaType=None, viewName=None, raw=False,
                allowDirectPlay=True):
    items = []

    viewUrl = url
    viewUrl = Url.addOptions(viewUrl, {emby.constants.URL_QUERY_ITEMS_PARENT_ID: viewId})

    # retrieve all items matching the current media type
    totalCount = 0
    startIndex = 0
    while True:
        if xbmcmediaimport.shouldCancel(handle, startIndex, max(totalCount, 1)):
            return None

        # put together a paged URL
        pagedUrlOptions = {
            emby.constants.URL_QUERY_ITEMS_START_INDEX: startIndex
        }
        pagedUrl = Url.addOptions(viewUrl, pagedUrlOptions)
        resultObj = embyServer.ApiGet(pagedUrl)
        if not resultObj or emby.constants.PROPERTY_ITEM_ITEMS not in resultObj or \
           emby.constants.PROPERTY_ITEM_TOTAL_RECORD_COUNT not in resultObj:
            log('invalid response for items of media type "{}" from {}'.format(mediaType, pagedUrl), xbmc.LOGERROR)
            return None

        # retrieve the total number of items
        totalCount = int(resultObj[emby.constants.PROPERTY_ITEM_TOTAL_RECORD_COUNT])

        # parse all items
        itemsObj = resultObj[emby.constants.PROPERTY_ITEM_ITEMS]
        for itemObj in itemsObj:
            startIndex = startIndex + 1
            if xbmcmediaimport.shouldCancel(handle, startIndex, totalCount):
                return None

            if raw:
                items.append(itemObj)
            else:
                item = kodi.Api.toFileItem(embyServer, itemObj, mediaType, embyMediaType, viewName,
                                           allowDirectPlay=allowDirectPlay)
                if not item:
                    continue

                items.append(item)

        # check if we have retrieved all available items
        if startIndex >= totalCount:
            break

    return items


def discoverProvider(handle, options):
    dialog = xbmcgui.Dialog()

    authenticationChoices = [
        localise(32036),  # local
        localise(32037)   # Emby Connect
    ]
    authenticationChoice = dialog.select(localise(32053), authenticationChoices)

    if authenticationChoice == 0:  # local
        provider = discoverProviderLocally(handle, options)
    elif authenticationChoice == 1:  # Emby Connect
        provider = discoverProviderWithEmbyConnect(handle, options)
    else:
        return

    if not provider:
        return

    xbmcmediaimport.setDiscoveredProvider(handle, True, provider)


def lookupProvider(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    basePath = mediaProvider.getBasePath()

    providerFound = False
    try:
        if emby.api.server.Server.GetInfo(basePath):
            providerFound = True
    except:
        pass

    xbmcmediaimport.setProviderFound(handle, providerFound)


def canImport(handle, options):
    if 'path' not in options:
        log('cannot execute "canimport" without path')
        return

    path = unquote(options['path'][0])

    # try to get the emby server's identifier from the path
    identifier = Server.GetServerId(path)
    if not identifier:
        return

    xbmcmediaimport.setCanImport(handle, True)


def isProviderReady(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # check if authentication works with the current provider settings
    try:
        providerReady = Server(mediaProvider).Authenticate(force=True)
    except:
        providerReady = False

    xbmcmediaimport.setProviderReady(handle, providerReady)


def isImportReady(handle, _):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return
    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    try:
        embyServer = Server(mediaProvider)
    except:
        return

    # check if the chosen library views exist
    selectedViews = ImportSettings.GetLibraryViews(importSettings)
    matchingViews = getMatchingLibraryViews(embyServer, mediaImport.getMediaTypes(), selectedViews)

    xbmcmediaimport.setImportReady(handle, len(matchingViews) > 0)


def loadProviderSettings(handle, _):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    settings = mediaProvider.getSettings()
    if not settings:
        log('cannot retrieve media provider settings', xbmc.LOGERROR)
        return

    # make sure we have a device identifier
    if not settings.getString(emby.constants.SETTING_PROVIDER_DEVICEID):
        settings.setString(emby.constants.SETTING_PROVIDER_DEVICEID, str(uuid.uuid4()))

    settings.registerActionCallback(emby.constants.SETTING_PROVIDER_LINK_EMBY_CONNECT, 'linkembyconnect')
    settings.registerActionCallback(emby.constants.SETTING_PROVIDER_TEST_AUTHENTICATION, 'testauthentication')

    # register a setting options filler for the list of users
    settings.registerOptionsFillerCallback(emby.constants.SETTING_PROVIDER_USER, 'settingoptionsfillerusers')

    settings.setLoaded()


def loadImportSettings(handle, _):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    settings = mediaImport.getSettings()
    if not settings:
        log('cannot retrieve media import settings', xbmc.LOGERROR)
        return

    settings.registerActionCallback(emby.constants.SETTING_IMPORT_FORCE_SYNC, 'forcesync')

    # register a setting options filler for the list of views
    settings.registerOptionsFillerCallback(emby.constants.SETTING_IMPORT_VIEWS_SPECIFIC, 'settingoptionsfillerviews')

    settings.setLoaded()


def canUpdateMetadataOnProvider(handle, options):  # pylint: disable=unused-argument
    xbmcmediaimport.setCanUpdateMetadataOnProvider(True)


def canUpdatePlaycountOnProvider(handle, options):  # pylint: disable=unused-argument
    xbmcmediaimport.setCanUpdatePlaycountOnProvider(True)


def canUpdateLastPlayedOnProvider(handle, options):  # pylint: disable=unused-argument
    xbmcmediaimport.setCanUpdateLastPlayedOnProvider(True)


def canUpdateResumePositionOnProvider(handle, options):  # pylint: disable=unused-argument
    xbmcmediaimport.setCanUpdateResumePositionOnProvider(True)


# noqa pylint: disable=too-many-locals, too-many-statements, too-many-nested-blocks, too-many-branches, too-many-return-statements
def execImport(handle, options):
    if 'path' not in options:
        log('cannot execute "import" without path', xbmc.LOGERROR)
        return

    # parse all necessary options
    mediaTypes = mediaTypesFromOptions(options)
    if not mediaTypes:
        log('cannot execute "import" without media types', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    log('importing {} items from {}...'.format(mediaTypes, mediaProvider2str(mediaProvider)))

    # prepare the media provider settings
    mediaProviderSettings = mediaProvider.prepareSettings()
    if not mediaProviderSettings:
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # create an Emby server instance
    embyServer = Server(mediaProvider)

    # build the base URL to retrieve items
    baseUrl = embyServer.BuildUserUrl(emby.constants.URL_ITEMS)
    baseUrlOptions = {
        emby.constants.URL_QUERY_ITEMS_RECURSIVE: 'true',
        emby.constants.URL_QUERY_ITEMS_FIELDS: ','.join(EMBY_ITEM_FIELDS),
        emby.constants.URL_QUERY_ITEMS_EXCLUDE_LOCATION_TYPES: 'Virtual,Offline',
        emby.constants.URL_QUERY_ITEMS_LIMIT: ITEM_REQUEST_LIMIT
    }
    baseUrl = Url.addOptions(baseUrl, baseUrlOptions)

    # get all (matching) library views
    selectedViews = ImportSettings.GetLibraryViews(importSettings)
    views = getMatchingLibraryViews(embyServer, mediaTypes, selectedViews)
    if not views:
        log('cannot retrieve items without any library views', xbmc.LOGERROR)
        return

    # determine whether Direct Play is allowed
    allowDirectPlay = mediaProviderSettings.getBool(emby.constants.SETTING_PROVIDER_PLAYBACK_ALLOW_DIRECT_PLAY)

    # determine whether to import collections
    importCollections = importSettings.getBool(emby.constants.SETTING_IMPORT_IMPORT_COLLECTIONS)

    # determine the last sync time and whether we should perform a fast sync
    fastSync = False
    syncUrlOptions = {}

    # check if synchronization related settings have changed; if yes we have to perform a full synchronization
    if SynchronizationSettings.HaveChanged(mediaTypes, mediaProviderSettings, importSettings, save=True):
        log('forcing a full synchronization to import {} items from {} because some related settings have changed'
            .format(mediaTypes, mediaProvider2str(mediaProvider)))
    else:
        # check if we
        #   have already performed a (full) synchronization before
        #   should use the Kodi Companion Emby server plugin
        lastSync = mediaImport.getLastSynced()
        if lastSync and \
           mediaProviderSettings.getBool(emby.constants.SETTING_PROVIDER_SYNCHRONIZATION_USE_KODI_COMPANION):
            if KodiCompanion.IsInstalled(embyServer):
                fastSync = True

                # convert the last sync datetime string to ISO 8601
                lastSync = parser.parse(lastSync).astimezone(utc).isoformat(timespec='seconds')

                syncUrlOptions.update({
                    # only set MinDateLastSavedForUser because it already covers DateLastSaved, RatingLastModified
                    # and PlaystateLastModified. Setting both MinDateLastSaved and MinDateLastSavedForUser will
                    # cause issues, see
                    # https://emby.media/community/index.php?/topic/82258-retrieving-changeset-when-client-returns-online-mediaimport/
                    emby.constants.URL_QUERY_ITEMS_MIN_DATE_LAST_SAVED_FOR_USER: lastSync
                })
                log('using fast synchronization to import {} items from {} with Kodi companion plugin'
                    .format(mediaTypes, mediaProvider2str(mediaProvider)), xbmc.LOGDEBUG)

                # retrieving the sync queue from Kodi companion
                syncQueue = KodiCompanion.SyncQueue.GetItems(embyServer, lastSync)
            else:
                log('Kodi companion usage is enabled to import {} items from {} but the server plugin is not installed'
                    .format(mediaTypes, mediaProvider2str(mediaProvider)), xbmc.LOGWARNING)

    # loop over all media types to be imported
    progress = 0
    progressTotal = len(mediaTypes)
    for mediaType in mediaTypes:
        if xbmcmediaimport.shouldCancel(handle, progress, progressTotal):
            return
        progress += 1

        if mediaType == xbmcmediaimport.MediaTypeVideoCollection and not importCollections:
            log('importing {} items from {} is disabled'.format(mediaType, mediaProvider2str(mediaProvider)),
                xbmc.LOGDEBUG)
            continue

        log('importing {} items from {}...'.format(mediaType, mediaProvider2str(mediaProvider)))

        mappedMediaType = kodi.Api.getEmbyMediaType(mediaType)
        if not mappedMediaType:
            log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
            continue
        (_, embyMediaType, _, localizedMediaType) = mappedMediaType

        xbmcmediaimport.setProgressStatus(
            handle, __addon__.getLocalizedString(32001).format(__addon__.getLocalizedString(localizedMediaType)))

        urlOptions = syncUrlOptions.copy()
        urlOptions.update({
            emby.constants.URL_QUERY_ITEMS_INCLUDE_ITEM_TYPES: embyMediaType
        })
        url = Url.addOptions(baseUrl, urlOptions)

        boxsetUrlOptions = {
            emby.constants.URL_QUERY_ITEMS_INCLUDE_ITEM_TYPES: kodi.EMBY_MEDIATYPE_BOXSET
        }
        boxsetUrl = Url.addOptions(baseUrl, boxsetUrlOptions)

        items = []
        boxsets = {}

        # handle library views
        for view in views:
            log('importing {} items from "{}" view from {}...'
                .format(mediaType, view.name, mediaProvider2str(mediaProvider)))
            items.extend(importItems(handle, embyServer, url, mediaType, view.id, embyMediaType=embyMediaType,
                                     viewName=view.name, allowDirectPlay=allowDirectPlay))

            if importCollections and items and mediaType == xbmcmediaimport.MediaTypeMovie:
                # retrieve all BoxSets / collections matching the current media type
                boxsetObjs = importItems(handle, embyServer, boxsetUrl, mediaType, view.id, raw=True,
                                         allowDirectPlay=allowDirectPlay)
                for boxsetObj in boxsetObjs:
                    if emby.constants.PROPERTY_ITEM_ID not in boxsetObj or \
                       emby.constants.PROPERTY_ITEM_NAME not in boxsetObj:
                        continue

                    boxsetId = boxsetObj[emby.constants.PROPERTY_ITEM_ID]
                    boxsetName = boxsetObj[emby.constants.PROPERTY_ITEM_NAME]
                    boxsets[boxsetId] = boxsetName

        # handle BoxSets / collections
        if importCollections and items:
            for (boxsetId, boxsetName) in iteritems(boxsets):
                # get all items belonging to the BoxSet
                boxsetItems = importItems(handle, embyServer, url, mediaType, boxsetId, embyMediaType=embyMediaType,
                                          viewName=boxsetName, allowDirectPlay=allowDirectPlay)
                for boxsetItem in boxsetItems:
                    # find the matching retrieved item
                    for index, item in enumerate(items):
                        if boxsetItem.getPath() == item.getPath():
                            # set the BoxSet / collection
                            kodi.Api.setCollection(item, boxsetName)
                            items[index] = item

        # in a fast sync we need to get the removed items from Kodi companion
        if fastSync:
            if items:
                log('{} changed {} items imported from {}'
                    .format(len(items), mediaType, mediaProvider2str(mediaProvider)))

            # handle removed items through Kodi companion's sync queue
            if syncQueue.itemsRemoved:
                # retrieve all local items matching the current media type from the current import
                localItems = xbmcmediaimport.getImportedItems(handle, mediaType)

                # match the local items against the changed items
                removedItems, = kodi.Api.matchImportedItemIdsToLocalItems(  # noqa: E501 # pylint: disable=unbalanced-tuple-unpacking
                    localItems, syncQueue.itemsRemoved)

                # erase all removed items matching the current media type from the sync queue
                syncQueue.itemsRemoved = \
                    [removedItem for removedItem in syncQueue.itemsRemoved if removedItem in removedItems]

                if removedItems:
                    log('{} previously imported {} items removed from {}'
                        .format(len(removedItems), mediaType, mediaProvider2str(mediaProvider)))
                    xbmcmediaimport.addImportItems(handle, removedItems, mediaType,
                                                   xbmcmediaimport.MediaImportChangesetTypeRemoved)
        else:
            log('{} {} items imported from {}'.format(len(items), mediaType, mediaProvider2str(mediaProvider)))

        # pass the imported items back to Kodi
        if items:
            xbmcmediaimport.addImportItems(handle, items, mediaType)

    xbmcmediaimport.finishImport(handle, fastSync)


# pylint: disable=too-many-locals, too-many-branches, too-many-return-statements
def updateOnProvider(handle, _):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    item = xbmcmediaimport.getUpdatedItem(handle)
    if not item:
        log('cannot retrieve updated item', xbmc.LOGERROR)
        return

    log('updating "{}" ({}) on {}...'.format(item.getLabel(), item.getPath(), mediaProvider2str(mediaProvider)))

    itemVideoInfoTag = item.getVideoInfoTag()
    if not itemVideoInfoTag:
        log('updated item is not a video item', xbmc.LOGERROR)
        return

    # determine the item's identifier
    itemId = kodi.Api.getEmbyItemIdFromVideoInfoTag(itemVideoInfoTag)
    if not itemId:
        log('cannot determine the identifier of the updated item: "{}"'
            .format(itemVideoInfoTag.getPath()), xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # create an Emby server instance
    embyServer = Server(mediaProvider)

    # retrieve all details of the item
    itemObj = Library.GetItem(embyServer, itemId)
    if not itemObj:
        log('cannot retrieve details of updated item with id {}'.format(itemId), xbmc.LOGERROR)
        return

    if emby.constants.PROPERTY_ITEM_USER_DATA not in itemObj:
        log('cannot update item with id {} because it has no userdata'.format(itemId), xbmc.LOGERROR)
        return

    updateItemPlayed = False
    updatePlaybackPosition = False
    # retrieve playback states from the updated item
    playcount = itemVideoInfoTag.getPlayCount()
    watched = playcount > 0
    lastPlayed = itemVideoInfoTag.getLastPlayed()
    # retrieve playback position from the updated item
    playbackPositionInSeconds = max(0.0, float(item.getProperty('resumetime')))
    playbackPositionInTicks = kodi.Api.secondsToTicks(playbackPositionInSeconds)

    userDataObj = itemObj[emby.constants.PROPERTY_ITEM_USER_DATA]

    # check and update playcout if necessary
    if emby.constants.PROPERTY_ITEM_USER_DATA_PLAY_COUNT in userDataObj:
        # retrieve playcount from the original item
        itemPlayed = userDataObj[emby.constants.PROPERTY_ITEM_USER_DATA_PLAY_COUNT] > 0

        if watched != itemPlayed:
            updateItemPlayed = True

    # check and update playback position if necessary
    if emby.constants.PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS in userDataObj:
        # retrieve playback position from the original item
        itemPlaybackPositionInTicks = userDataObj[emby.constants.PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS]

        if playbackPositionInTicks != itemPlaybackPositionInTicks:
            updatePlaybackPosition = True

    # nothing to do if no playback related properties have been changed
    if not updateItemPlayed and not updatePlaybackPosition:
        log('no playback related properties of "{}" ({}) have changed => nothing to update on {}'
            .format(item.getLabel(), item.getPath(), mediaProvider2str(mediaProvider)))
        return

    log('updating playback related properties of "{}" ({}) on {}...'
        .format(item.getLabel(), item.getPath(), mediaProvider2str(mediaProvider)))
    if not UserData.Update(embyServer, itemId, updateItemPlayed, updatePlaybackPosition, watched, playcount,
                           lastPlayed, playbackPositionInTicks):
        log('updating playback related properties of "{}" ({}) on {} failed'
            .format(item.getLabel(), item.getPath(), mediaProvider2str(mediaProvider)), xbmc.LOGERROR)

    xbmcmediaimport.finishUpdateOnProvider(handle)


ACTIONS = {
    # official media import callbacks
    'discoverprovider': discoverProvider,
    'lookupprovider': lookupProvider,
    'canimport': canImport,
    'isproviderready': isProviderReady,
    'isimportready': isImportReady,
    'loadprovidersettings': loadProviderSettings,
    'loadimportsettings': loadImportSettings,
    'canupdatemetadataonprovider': canUpdateMetadataOnProvider,
    'canupdateplaycountonprovider': canUpdatePlaycountOnProvider,
    'canupdatelastplayedonprovider': canUpdateLastPlayedOnProvider,
    'canupdateresumepositiononprovider': canUpdateResumePositionOnProvider,
    'import': execImport,
    'updateonprovider': updateOnProvider,

    # custom setting callbacks
    'linkembyconnect': linkEmbyConnect,
    'testauthentication': testAuthentication,
    'forcesync': forceSync,

    # custom setting options fillers
    'settingoptionsfillerusers': settingOptionsFillerUsers,
    'settingoptionsfillerviews': settingOptionsFillerViews
}


def run(argv):
    path = argv[0]
    handle = int(argv[1])

    options = None
    if len(argv) > 2:
        # get the options but remove the leading ?
        params = argv[2][1:]
        if params:
            options = parse_qs(params)

    log('path = {}, handle = {}, options = {}'.format(path, handle, params), xbmc.LOGDEBUG)

    url = urlparse(path)
    action = url.path
    if action[0] == '/':
        action = action[1:]

    if action not in ACTIONS:
        log('cannot process unknown action: {}'.format(action), xbmc.LOGERROR)
        sys.exit(0)

    actionMethod = ACTIONS[action]
    if not actionMethod:
        log('action not implemented: {}'.format(action), xbmc.LOGWARNING)
        sys.exit(0)

    log('executing action "{}"...'.format(action), xbmc.LOGDEBUG)
    actionMethod(handle, options)
